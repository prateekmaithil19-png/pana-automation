import json
import logging
from datetime import datetime

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from database.db import get_approved_posts, update_post_status

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def _post_to_facebook(caption: str, image_url: str | None):
    page_id = config.META_PAGE_ID
    token = config.META_PAGE_ACCESS_TOKEN
    async with httpx.AsyncClient() as client:
        if image_url:
            resp = await client.post(
                f"https://graph.facebook.com/v21.0/{page_id}/photos",
                params={"access_token": token},
                json={"url": image_url, "caption": caption},
                timeout=30,
            )
        else:
            resp = await client.post(
                f"https://graph.facebook.com/v21.0/{page_id}/feed",
                params={"access_token": token},
                json={"message": caption},
                timeout=30,
            )
        resp.raise_for_status()
        return resp.json()


async def _post_to_instagram(caption: str, image_url: str | None):
    ig_id = config.META_IG_USER_ID
    token = config.META_PAGE_ACCESS_TOKEN
    async with httpx.AsyncClient() as client:
        if image_url:
            # Step 1: create media container
            r1 = await client.post(
                f"https://graph.facebook.com/v21.0/{ig_id}/media",
                params={"access_token": token},
                json={"image_url": image_url, "caption": caption},
                timeout=30,
            )
            r1.raise_for_status()
            creation_id = r1.json()["id"]

            # Step 2: publish
            r2 = await client.post(
                f"https://graph.facebook.com/v21.0/{ig_id}/media_publish",
                params={"access_token": token},
                json={"creation_id": creation_id},
                timeout=30,
            )
            r2.raise_for_status()
        else:
            logger.warning("Instagram requires an image — skipping text-only IG post")


async def _post_to_line_oa(caption: str, image_url: str | None):
    messages: list[dict] = []
    if image_url:
        messages.append(
            {
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url,
            }
        )
    messages.append({"type": "text", "text": caption})

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.line.me/v2/bot/message/broadcast",
            headers={"Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}"},
            json={"messages": messages},
            timeout=30,
        )
        resp.raise_for_status()


async def publish_approved_posts():
    """Check for approved posts whose scheduled_at has passed and publish them."""
    posts = await get_approved_posts()
    now = datetime.utcnow()

    for post in posts:
        try:
            sched = datetime.fromisoformat(post["scheduled_at"])
        except ValueError:
            logger.error("Invalid scheduled_at for post %s", post["id"])
            continue

        if sched > now:
            continue  # not yet time

        platforms = post["platforms"]
        if isinstance(platforms, str):
            platforms = json.loads(platforms)

        caption = post["caption"]
        image_path = post.get("image_path")

        # Convert local image path to public URL if needed
        image_url: str | None = None
        if image_path and image_path.startswith("http"):
            image_url = image_path
        elif image_path:
            image_url = f"{config.APP_BASE_URL.rstrip('/')}/media/{image_path.lstrip('/')}"

        await update_post_status(post["id"], "posting")
        errors = []

        for platform in platforms:
            try:
                if platform == "facebook":
                    await _post_to_facebook(caption, image_url)
                elif platform == "instagram":
                    await _post_to_instagram(caption, image_url)
                elif platform == "line":
                    await _post_to_line_oa(caption, image_url)
                elif platform == "tiktok":
                    logger.warning(
                        "TikTok platform selected but TikTok Content Posting API not yet configured. "
                        "Apply at developers.tiktok.com to enable auto-posting."
                    )
            except Exception as exc:
                logger.exception("Failed to post to %s: %s", platform, exc)
                errors.append(platform)

        final_status = "posted" if not errors else f"partial_error:{','.join(errors)}"
        await update_post_status(post["id"], final_status)
        logger.info("Post %s → %s", post["id"], final_status)


def start_scheduler():
    scheduler.add_job(publish_approved_posts, "interval", minutes=1, id="publish_posts")
    # Refresh upcoming shoot dates daily at 08:00 Bangkok time (UTC+7 = 01:00 UTC)
    scheduler.add_job(
        _refresh_dates,
        "cron",
        hour=1,
        minute=0,
        id="refresh_shoot_dates",
        timezone="UTC",
    )
    scheduler.start()
    logger.info("Scheduler started — posts every minute, dates refreshed daily at 08:00 BKK")


def _refresh_dates():
    import asyncio
    from scheduler.date_fetcher import refresh_upcoming_dates
    asyncio.create_task(refresh_upcoming_dates())


def stop_scheduler():
    scheduler.shutdown(wait=False)

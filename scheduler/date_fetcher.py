"""
Fetches upcoming One Stop Service shoot dates from Pana Studio's Facebook and
Instagram pages, extracts them with an LLM, and writes knowledge/upcoming_dates.md.
Runs once on startup and then daily at 08:00 Bangkok time.
"""

import logging
import os
from datetime import datetime, timezone, timedelta

import httpx

import config
from ai.engine import generate_reply

logger = logging.getLogger(__name__)

_KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), "..", "knowledge")
_DATES_FILE = os.path.join(_KNOWLEDGE_DIR, "upcoming_dates.md")

_BKK = timezone(timedelta(hours=7))  # Asia/Bangkok UTC+7

_FB_POSTS_URL = "https://graph.facebook.com/v19.0/{page_id}/posts"
_IG_MEDIA_URL = "https://graph.facebook.com/v19.0/{ig_user_id}/media"


async def _fetch_facebook_posts() -> list[str]:
    try:
        url = _FB_POSTS_URL.format(page_id=config.META_PAGE_ID)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                params={
                    "fields": "message,created_time",
                    "limit": 15,
                    "access_token": config.META_PAGE_ACCESS_TOKEN,
                },
                timeout=10.0,
            )
            resp.raise_for_status()
        return [
            post.get("message", "")
            for post in resp.json().get("data", [])
            if post.get("message")
        ]
    except Exception as e:
        logger.warning("Facebook posts fetch failed: %s", e)
        return []


async def _fetch_instagram_captions() -> list[str]:
    try:
        url = _IG_MEDIA_URL.format(ig_user_id=config.META_IG_USER_ID)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                params={
                    "fields": "caption,timestamp",
                    "limit": 15,
                    "access_token": config.META_PAGE_ACCESS_TOKEN,
                },
                timeout=10.0,
            )
            resp.raise_for_status()
        return [
            item.get("caption", "")
            for item in resp.json().get("data", [])
            if item.get("caption")
        ]
    except Exception as e:
        logger.warning("Instagram captions fetch failed: %s", e)
        return []


async def _extract_dates_with_llm(posts_text: str, current_month_year: str) -> str:
    prompt = f"""You are reading social media posts from Pana Studio (@pa.na.studio), a Bangkok photography studio.

Current month: {current_month_year}

Posts to analyze:
---
{posts_text}
---

Find any upcoming One Stop Service (แชร์แบรนด์ / multibrand shared shoot) dates.
Rules:
- Only include dates in {current_month_year} or future months (ignore past dates)
- Format each date as: DD Month YYYY
- If none found, reply with exactly the word: NONE

Output only the dates or NONE — no explanation, no extra text."""

    result = await generate_reply(
        prompt,
        [],
        system_prompt="You extract shoot dates from text. Output only what is requested.",
        max_tokens=200,
    )
    return result.strip()


def _write_no_dates(current_month_year: str):
    content = f"""# Upcoming One Stop Service Shoot Dates

Last checked: {datetime.now(_BKK).strftime('%Y-%m-%d %H:%M')} BKK | Month: {current_month_year}

No upcoming shoot dates announced for {current_month_year}.

When a customer asks about One Stop Service availability this month, say:
"ยังไม่มีรอบถ่ายประกาศสำหรับเดือนนี้ค่ะ ขอเช็คกับทีมก่อนนะคะ แล้วจะรีบแจ้งกลับค่ะ"
(English: "We don't have a shoot announced for this month yet — let me check with the team and get back to you.")
"""
    _save(content)


def _write_dates(current_month_year: str, dates_text: str):
    content = f"""# Upcoming One Stop Service Shoot Dates

Last checked: {datetime.now(_BKK).strftime('%Y-%m-%d %H:%M')} BKK | Month: {current_month_year}

## Available shoot dates this month:
{dates_text}

These are for One Stop Service (shared/multibrand shoot only).
For Individual Brand Shoot, dates are arranged directly with the client.
When sharing these with a customer, confirm: "มีรอบถ่ายวันที่ [date] ค่ะ สนใจจองได้เลยนะคะ 😊"
"""
    _save(content)


def _save(content: str):
    os.makedirs(_KNOWLEDGE_DIR, exist_ok=True)
    with open(_DATES_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("Updated %s", _DATES_FILE)


async def refresh_upcoming_dates():
    """Fetch latest posts from Facebook + Instagram and update upcoming_dates.md."""
    now_bkk = datetime.now(_BKK)
    current_month_year = now_bkk.strftime("%B %Y")

    logger.info("Refreshing upcoming shoot dates — checking %s", current_month_year)

    fb_posts = await _fetch_facebook_posts()
    ig_posts = await _fetch_instagram_captions()
    all_posts = fb_posts + ig_posts

    if not all_posts:
        logger.info("No posts fetched — writing no-dates file")
        _write_no_dates(current_month_year)
        return

    posts_text = "\n---\n".join(all_posts[:15])
    extracted = await _extract_dates_with_llm(posts_text, current_month_year)
    logger.info("Date extraction result: %s", extracted)

    if not extracted or extracted.upper() == "NONE":
        _write_no_dates(current_month_year)
    else:
        _write_dates(current_month_year, extracted)

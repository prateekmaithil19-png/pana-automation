import httpx
import config

_LINE_NOTIFY_URL = "https://notify-api.line.me/api/notify"


async def send_line_notify(message: str, image_url: str | None = None):
    """Send a notification to the personal Line Notify channel (prateekm19)."""
    headers = {"Authorization": f"Bearer {config.LINE_NOTIFY_TOKEN}"}
    data: dict = {"message": message}
    if image_url:
        data["imageThumbnail"] = image_url
        data["imageFullsize"] = image_url

    async with httpx.AsyncClient() as client:
        resp = await client.post(_LINE_NOTIFY_URL, headers=headers, data=data, timeout=10)
        resp.raise_for_status()


async def notify_reply_approval(
    approval_id: str,
    platform: str,
    customer_message: str,
    ai_reply: str,
):
    base = config.APP_BASE_URL.rstrip("/")
    approve_url = f"{base}/approve/{approval_id}/action?action=approve"
    edit_url = f"{base}/approve/{approval_id}"

    platform_label = {"facebook": "Facebook", "instagram": "Instagram", "line": "Line OA"}.get(
        platform, platform
    )

    msg = (
        f"\n🔔 [Pana Studio] ลูกค้าถามราคาบน {platform_label}\n\n"
        f"💬 ลูกค้า: {customer_message[:200]}\n\n"
        f"🤖 AI ร่าง: {ai_reply[:200]}\n\n"
        f"✅ อนุมัติ: {approve_url}\n"
        f"✏️ แก้ไข: {edit_url}"
    )
    await send_line_notify(msg)


async def notify_post_approval(
    approval_id: str,
    caption: str,
    platforms: list[str],
    scheduled_at: str,
):
    base = config.APP_BASE_URL.rstrip("/")
    approve_url = f"{base}/approve/{approval_id}/action?action=approve"
    edit_url = f"{base}/approve/{approval_id}"

    platforms_str = ", ".join(platforms)

    msg = (
        f"\n📸 [Pana Studio] โพสต์ใหม่รอการอนุมัติ\n\n"
        f"แพลตฟอร์ม: {platforms_str}\n"
        f"กำหนดโพสต์: {scheduled_at}\n\n"
        f"Caption:\n{caption[:300]}\n\n"
        f"✅ อนุมัติ: {approve_url}\n"
        f"✏️ แก้ไข: {edit_url}"
    )
    await send_line_notify(msg)

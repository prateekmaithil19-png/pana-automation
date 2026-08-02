import secrets
from database.db import save_approval, save_scheduled_post


def _token() -> str:
    return secrets.token_urlsafe(32)


async def create_reply_approval(
    platform: str,
    user_id: str,
    customer_message: str,
    ai_reply: str,
) -> str:
    approval_id = _token()
    await save_approval(
        approval_id,
        {
            "approval_type": "reply",
            "platform": platform,
            "user_id": user_id,
            "customer_message": customer_message,
            "ai_reply": ai_reply,
        },
    )
    return approval_id


async def create_post_approval(
    caption: str,
    platforms: list[str],
    scheduled_at: str,
    image_path: str | None = None,
) -> tuple[str, str]:
    """Returns (approval_id, post_id)."""
    import json

    approval_id = _token()
    post_id = _token()

    await save_approval(
        approval_id,
        {
            "approval_type": "post",
            "platform": json.dumps(platforms),
            "user_id": None,
            "customer_message": None,
            "ai_reply": caption,
        },
    )
    await save_scheduled_post(
        post_id,
        approval_id,
        {
            "caption": caption,
            "image_path": image_path,
            "platforms": platforms,
            "scheduled_at": scheduled_at,
        },
    )
    return approval_id, post_id

import hashlib
import hmac
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

import config
from ai.classifier import is_pricing_request
from ai.engine import generate_reply
from approval.store import create_reply_approval
from database.db import add_message, get_conversation
from notifications.email_notify import send_reply_approval_email
from notifications.line_notify import notify_reply_approval

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_meta_signature(body: bytes, signature_header: str) -> bool:
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        config.META_APP_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature_header)


async def _send_meta_message(platform: str, recipient_id: str, text: str):
    if platform == "instagram":
        url = f"https://graph.facebook.com/v21.0/{config.META_IG_USER_ID}/messages"
    else:
        url = "https://graph.facebook.com/v21.0/me/messages"

    payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            params={"access_token": config.META_PAGE_ACCESS_TOKEN},
            json=payload,
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error("Meta send failed: %s %s", resp.status_code, resp.text)


async def _handle_message(platform: str, sender_id: str, text: str):
    history = await get_conversation(platform, sender_id)
    await add_message(platform, sender_id, "customer", text)

    if is_pricing_request(text):
        # Generate a "collect info" AI reply, hold for human approval
        ai_reply = await generate_reply(text, history)
        approval_id = await create_reply_approval(platform, sender_id, text, ai_reply)
        try:
            await send_reply_approval_email(approval_id, platform, text, ai_reply)
        except Exception:
            logger.exception("Email notification failed")
        try:
            await notify_reply_approval(approval_id, platform, text, ai_reply)
        except Exception:
            logger.exception("Line Notify failed")
    else:
        ai_reply = await generate_reply(text, history)
        await add_message(platform, sender_id, "assistant", ai_reply)
        await _send_meta_message(platform, sender_id, ai_reply)


@router.get("/webhook/meta", response_class=PlainTextResponse)
async def meta_verify(request: Request):
    params = request.query_params
    if params.get("hub.verify_token") == config.META_VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook/meta")
async def meta_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_meta_signature(body, sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    import json
    payload = json.loads(body)
    obj = payload.get("object", "")

    for entry in payload.get("entry", []):
        for msg_event in entry.get("messaging", []):
            sender_id = msg_event.get("sender", {}).get("id")
            message = msg_event.get("message", {})

            # Skip echo (messages sent by the page itself)
            if message.get("is_echo"):
                continue

            text = message.get("text", "").strip()
            if not text or not sender_id:
                continue

            platform = "instagram" if obj == "instagram" else "facebook"
            try:
                await _handle_message(platform, sender_id, text)
            except Exception:
                logger.exception("Error handling %s message from %s", platform, sender_id)

    return {"status": "ok"}

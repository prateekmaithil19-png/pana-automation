import base64
import hashlib
import hmac
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import config
from ai.classifier import is_pricing_request
from ai.engine import generate_reply
from approval.store import create_reply_approval
from database.db import add_message, get_conversation
from notifications.email_notify import send_reply_approval_email
from notifications.line_notify import notify_reply_approval

logger = logging.getLogger(__name__)
router = APIRouter()

_LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
_LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def _verify_line_signature(body: bytes, signature: str) -> bool:
    secret = config.LINE_CHANNEL_SECRET.encode()
    digest = hmac.new(secret, body, hashlib.sha256).digest()
    computed = base64.b64encode(digest).decode()
    return hmac.compare_digest(computed, signature)


async def _line_reply(reply_token: str, text: str):
    async with httpx.AsyncClient() as client:
        await client.post(
            _LINE_REPLY_URL,
            headers={"Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}"},
            json={"replyToken": reply_token, "messages": [{"type": "text", "text": text}]},
            timeout=10,
        )


async def _handle_line_message(user_id: str, text: str, reply_token: str):
    history = await get_conversation("line", user_id)
    await add_message("line", user_id, "customer", text)

    if is_pricing_request(text):
        ai_reply = await generate_reply(text, history)
        approval_id = await create_reply_approval("line", user_id, text, ai_reply)

        # Acknowledge the customer immediately while admin reviews
        ack = "ขอบคุณที่สอบถามนะคะ 🙏 ทางเรากำลังเตรียมข้อมูลให้ รอสักครู่นะคะ"
        await _line_reply(reply_token, ack)

        try:
            await send_reply_approval_email(approval_id, "line", text, ai_reply)
        except Exception:
            logger.exception("Email notification failed")
        try:
            await notify_reply_approval(approval_id, "line", text, ai_reply)
        except Exception:
            logger.exception("Line Notify failed")
    else:
        ai_reply = await generate_reply(text, history)
        await add_message("line", user_id, "assistant", ai_reply)
        await _line_reply(reply_token, ai_reply)


@router.post("/webhook/line")
async def line_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("X-Line-Signature", "")
    if not _verify_line_signature(body, sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    import json
    payload = json.loads(body)

    for event in payload.get("events", []):
        if event.get("type") != "message":
            continue
        msg = event.get("message", {})
        if msg.get("type") != "text":
            continue

        user_id = event.get("source", {}).get("userId")
        text = msg.get("text", "").strip()
        reply_token = event.get("replyToken", "")

        if not user_id or not text:
            continue

        try:
            await _handle_line_message(user_id, text, reply_token)
        except Exception:
            logger.exception("Error handling Line message from %s", user_id)

    return JSONResponse({"status": "ok"})

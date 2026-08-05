import base64
import hashlib
import hmac
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import config
from ai.classifier import is_pricing_request, is_escalation_needed, is_confidentiality_probe, detect_language
from ai.engine import generate_reply, generate_reply_with_image
from ai.prompts import build_system_prompt
from approval.store import create_reply_approval
from database.db import add_message, get_conversation, get_recent_corrections
from memory.customer_context import build_customer_context, update_customer_state
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


async def _build_prompt(user_id: str, lang: str = "th") -> str:
    """Build the system prompt, using detected language to bias example selection."""
    customer_memory = await build_customer_context("line", user_id)
    corrections = await get_recent_corrections()
    return build_system_prompt(customer_memory=customer_memory, corrections=corrections, lang=lang)


async def _download_line_image(message_id: str) -> bytes:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api-data.line.me/v2/bot/message/{message_id}/content",
            headers={"Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.content


async def _handle_line_image(user_id: str, message_id: str, reply_token: str):
    history = await get_conversation("line", user_id)
    system_prompt = await _build_prompt(user_id)

    try:
        image_bytes = await _download_line_image(message_id)
    except Exception:
        logger.exception("Failed to download Line image for user %s", user_id)
        ack = "ขอบคุณที่ส่งรูปมานะคะ 🙏 ขอดูรายละเอียดกับทีมงานก่อนแล้วจะตอบกลับนะคะ"
        await _line_reply(reply_token, ack)
        return

    await add_message("line", user_id, "customer", "[ลูกค้าส่งรูปภาพสินค้า]")

    ai_reply = await generate_reply_with_image(
        image_bytes,
        "[Customer sent a product/reference photo. Describe what you see, connect it to Pana Studio services, and ask one follow-up question.]",
        history,
        system_prompt=system_prompt,
    )

    await add_message("line", user_id, "assistant", ai_reply)
    await _line_reply(reply_token, ai_reply)
    # Refresh history so the image turn (customer + assistant) is included in fact extraction
    updated_history = await get_conversation("line", user_id)
    await update_customer_state("line", user_id, updated_history)


async def _handle_line_message(user_id: str, text: str, reply_token: str):
    history = await get_conversation("line", user_id)
    await add_message("line", user_id, "customer", text)

    # Detect language once — used for prompt bias and fallback message selection
    lang = detect_language(text)
    system_prompt = await _build_prompt(user_id, lang=lang)

    # Confidentiality probe — log silently so Deen can review; agent handles it via prompt
    if is_confidentiality_probe(text):
        logger.warning(
            "[CONFIDENTIALITY PROBE] user=%s message=%r — agent will deflect via prompt",
            user_id, text,
        )

    # Escalation check — alert admin if customer is frustrated or unanswered too long
    if is_escalation_needed(text, history):
        logger.warning("Escalation needed for user %s — message: %s", user_id, text)
        try:
            await send_reply_approval_email(
                "ESCALATION",
                "line",
                text,
                f"[ESCALATION ALERT] Customer {user_id} needs urgent attention.\nMessage: {text}",
            )
        except Exception:
            logger.exception("Escalation email failed")
        try:
            await notify_reply_approval(
                "ESCALATION",
                "line",
                text,
                f"[ด่วน] ลูกค้า {user_id} ต้องการความช่วยเหลือด่วน",
            )
        except Exception:
            logger.exception("Escalation Line Notify failed")

    if is_pricing_request(text, conversation_history=history):
        ai_reply = await generate_reply(text, history, system_prompt=system_prompt)
        approval_id = await create_reply_approval("line", user_id, text, ai_reply)

        # Acknowledge the customer immediately while admin reviews
        ack = (
            "ขอบคุณที่สอบถามนะคะ 🙏 ทางเรากำลังเตรียมข้อมูลให้ รอสักครู่นะคะ"
            if lang == "th"
            else "Thank you for your enquiry! 🙏 We're preparing the details for you — please give us a moment."
        )
        await _line_reply(reply_token, ack)

        # Save the ack so the next turn has full conversation context
        await add_message("line", user_id, "assistant", ack)

        # Refresh history (now includes current customer message + ack) before state update
        updated_history = await get_conversation("line", user_id)
        await update_customer_state("line", user_id, updated_history, force_stage="quote_requested")

        try:
            await send_reply_approval_email(approval_id, "line", text, ai_reply)
        except Exception:
            logger.exception("Email notification failed")
        try:
            await notify_reply_approval(approval_id, "line", text, ai_reply)
        except Exception:
            logger.exception("Line Notify failed")
    else:
        ai_reply = await generate_reply(text, history, system_prompt=system_prompt)
        await add_message("line", user_id, "assistant", ai_reply)
        await _line_reply(reply_token, ai_reply)
        # Refresh history (includes current message pair) before persisting state
        updated_history = await get_conversation("line", user_id)
        await update_customer_state("line", user_id, updated_history)


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
        user_id = event.get("source", {}).get("userId")
        reply_token = event.get("replyToken", "")

        if not user_id:
            continue

        try:
            if msg.get("type") == "text":
                text = msg.get("text", "").strip()
                if text:
                    await _handle_line_message(user_id, text, reply_token)
            elif msg.get("type") == "image":
                message_id = msg.get("id")
                if message_id:
                    await _handle_line_image(user_id, message_id, reply_token)
        except Exception:
            logger.exception("Error handling Line event from %s", user_id)

    return JSONResponse({"status": "ok"})

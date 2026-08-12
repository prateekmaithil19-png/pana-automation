import base64
import hashlib
import hmac
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import config
from ai.classifier import (
    is_pricing_request,
    is_escalation_needed,
    is_confidentiality_probe,
    is_human_handoff_request,
    detect_language,
)
from ai.engine import generate_reply, generate_reply_with_image
from ai.prompts import build_system_prompt
from approval.store import create_reply_approval
from database.db import (
    add_message,
    get_conversation,
    get_recent_corrections,
    get_customer_state,
    set_human_controlled,
    save_admin_contact,
    get_admin_contacts,
)
from memory.customer_context import build_customer_context, update_customer_state
from notifications.email_notify import send_reply_approval_email
from notifications.line_notify import notify_reply_approval
from notifications.line_push import send_line_push

logger = logging.getLogger(__name__)
router = APIRouter()

_LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"

# One-time admin registration phrase. Dean sends this exact message from her own
# personal Line account (after adding the OA as a friend) so the bot can capture
# her userId and push handoff notifications directly to her — no email/Line
# Notify dependency (Line Notify was discontinued by LINE in March 2025; SMTP
# isn't configured). Not something a customer would type by accident.
_ADMIN_REGISTER_PHRASE = "register pana admin"

# Fixed (non-AI-generated) acknowledgment sent the moment a customer asks for a
# human — deliberately not free-generated so it can never claim an action (like
# "I've notified Dean") that didn't actually happen.
_HANDOFF_ACK = {
    "th": "ได้เลยค่ะ ทางทีมได้รับแจ้งแล้วและจะติดต่อกลับไปนะคะ 🙏 หรือติดต่อดีนได้โดยตรงที่ 065-974-5556 ค่ะ",
    "en": "Of course! The team has been notified and will follow up with you shortly 🙏 You can also reach Dean directly at 065-974-5556.",
}


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
    # Infer language from the most recent customer text in history
    recent_text = next(
        (t["content"] for t in reversed(history) if t.get("role") in ("customer", "user")),
        "",
    )
    lang = detect_language(recent_text)
    system_prompt = await _build_prompt(user_id, lang=lang)

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


async def _handle_admin_registration(user_id: str, text: str, reply_token: str) -> bool:
    """If this message is the admin-registration phrase, save the sender as the
    admin contact for handoff notifications and stop further processing.
    Returns True if this message was consumed as a registration (caller should
    not treat it as a customer conversation turn)."""
    if text.strip().lower() != _ADMIN_REGISTER_PHRASE:
        return False

    await save_admin_contact("line", user_id, label="Dean")
    await _line_reply(
        reply_token,
        "✅ Registered as admin — handoff notifications will be sent here from now on.",
    )
    logger.info("Registered admin contact: user_id=%s", user_id)
    return True


async def _notify_admin_handoff(user_id: str, customer_message: str, state: dict | None):
    """Push a message straight to every registered admin's (Dean's, Pat's)
    personal Line account with what the customer asked and whatever context is
    already known about them, so they aren't starting cold."""
    admins = await get_admin_contacts("line")
    if not admins:
        logger.warning(
            "Customer %s requested human handoff but no admin contact is "
            "registered yet — send '%s' from an admin's Line account to fix this.",
            user_id, _ADMIN_REGISTER_PHRASE,
        )
        return

    state = state or {}
    customer_name = state.get("customer_name") or "ไม่ทราบชื่อ"
    shoot_type = state.get("shoot_type") or "-"
    product_type = state.get("product_type") or "-"
    num_looks = state.get("num_looks") or "-"
    preferred_date = state.get("preferred_date") or "-"

    message = (
        f"🙋 ลูกค้าขอคุยกับคุณโดยตรง\n\n"
        f"ข้อความล่าสุด: {customer_message}\n\n"
        f"ชื่อ: {customer_name}\n"
        f"ประเภทงาน: {shoot_type}\n"
        f"สินค้า: {product_type}\n"
        f"จำนวนลุค: {num_looks}\n"
        f"วันที่สนใจ: {preferred_date}\n\n"
        f"บอทจะหยุดตอบลูกค้ารายนี้ชั่วคราวจนกว่าจะมีการติดต่อกลับ"
    )
    for admin in admins:
        try:
            await send_line_push(admin["user_id"], message)
        except Exception:
            logger.exception("Failed to push handoff notification to %s", admin.get("label"))


async def _handle_line_message(user_id: str, text: str, reply_token: str):
    # Check takeover state BEFORE logging this message, so we know whether the
    # AI was already silent for this customer going into this turn.
    state_before = await get_customer_state("line", user_id)
    already_human_controlled = bool(state_before and state_before.get("human_controlled"))

    history = await get_conversation("line", user_id)
    await add_message("line", user_id, "customer", text)

    # Detect language once — used for prompt bias and fallback message selection
    lang = detect_language(text)

    # Explicit request to be connected with a human — stop AI auto-replies for
    # this customer and notify Dean directly, with whatever context is known.
    if is_human_handoff_request(text) and not already_human_controlled:
        await set_human_controlled("line", user_id, True)
        await _notify_admin_handoff(user_id, text, state_before)

        ack = _HANDOFF_ACK.get(lang, _HANDOFF_ACK["th"])
        await _line_reply(reply_token, ack)
        await add_message("line", user_id, "assistant", ack)

        updated_history = await get_conversation("line", user_id)
        await update_customer_state("line", user_id, updated_history, force_stage="human_handling")
        return

    # Already handed off to a human — just log the message, don't auto-reply.
    # The follow-up scheduler will check back in if Dean hasn't replied after
    # 24h, or Dean can resolve it directly via LINE / the admin resolve link.
    if already_human_controlled:
        logger.info(
            "Message from %s logged while human_controlled — no AI reply sent",
            user_id,
        )
        return

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


async def _handle_unsupported_message(user_id: str, msg_type: str, reply_token: str):
    """Send a warm acknowledgment for stickers, audio, video, file, or location messages.

    Stickers are extremely common in Thai chat apps — silently dropping them
    creates a poor experience.  We infer language from history so the reply
    feels natural.
    """
    history = await get_conversation("line", user_id)
    recent_text = next(
        (t["content"] for t in reversed(history) if t.get("role") in ("customer", "user")),
        "",
    )
    lang = detect_language(recent_text)

    if msg_type == "sticker":
        ack = "😊🙏" if lang == "th" else "😊"
    elif msg_type == "location":
        ack = (
            "ขอบคุณที่แชร์ตำแหน่งนะคะ 📍 มีอะไรให้ช่วยเพิ่มเติมได้เลยค่ะ"
            if lang == "th"
            else "Thanks for sharing your location! 📍 Feel free to let us know how we can help."
        )
    else:
        ack = (
            "ขอบคุณที่ส่งข้อมูลมานะคะ 🙏 ทีมงานจะตรวจสอบและติดต่อกลับค่ะ"
            if lang == "th"
            else "Thank you for sending that! 🙏 Our team will review it and get back to you."
        )

    await _line_reply(reply_token, ack)
    logger.info("Acknowledged unsupported message type '%s' for user %s", msg_type, user_id)


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
            msg_type = msg.get("type")
            if msg_type == "text":
                text = msg.get("text", "").strip()
                if text and await _handle_admin_registration(user_id, text, reply_token):
                    continue  # registration message — not a customer conversation turn
                if text:
                    await _handle_line_message(user_id, text, reply_token)
            elif msg_type == "image":
                message_id = msg.get("id")
                if message_id:
                    await _handle_line_image(user_id, message_id, reply_token)
            elif msg_type in ("sticker", "audio", "video", "file", "location"):
                # Acknowledge non-text messages warmly instead of silently dropping them
                await _handle_unsupported_message(user_id, msg_type, reply_token)
        except Exception:
            logger.exception("Error handling Line event from %s", user_id)

    return JSONResponse({"status": "ok"})

"""
Proactive follow-up scheduler for Pana Studio.
Runs every 4 hours. Finds Line customers who showed interest but went quiet
for 48+ hours and sends them a personalized follow-up message via Line push.
Max 2 follow-ups per customer, then stage is set to 'cold'.
"""

import logging

import httpx

import config
from ai.engine import generate_reply
from database.db import get_customers_needing_followup, mark_followup_sent

logger = logging.getLogger(__name__)

_LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

_FOLLOWUP_SYSTEM = """You are a friendly admin assistant for Pana Studio — a commercial photography studio in Bangkok, Thailand.

Write a short follow-up message to a customer who asked about a photoshoot but hasn't replied in a few days.

Rules:
- Write in Thai only. End sentences with "ค่ะ". Use "ทางเรา" as first person.
- 2-3 sentences maximum — brief and warm, not pushy or salesy.
- Reference what the customer was interested in if known.
- Sound like a real human staff member checking in, not a bot.
- No ** markdown. At most 1 emoji.
- Do NOT ask multiple questions at once. One soft question at most."""


async def _generate_followup_message(state: dict) -> str:
    shoot_type = state.get("shoot_type") or "ไม่ระบุ"
    product = state.get("product_type") or "ไม่ระบุ"
    looks = state.get("num_looks") or "ไม่ระบุ"
    preferred_date = state.get("preferred_date") or "ไม่ระบุ"
    follow_up_count = state.get("follow_up_count", 0)

    # Second follow-up is gentler — gives them an easy out
    if follow_up_count >= 1:
        user_prompt = (
            f"Customer interest: {shoot_type}, product: {product}. "
            "This is the second follow-up. Be very brief and give them an easy way to continue "
            "or let us know if they're no longer interested. Keep it friendly, not guilt-tripping."
        )
    else:
        user_prompt = (
            f"Customer was interested in: shoot type = {shoot_type}, "
            f"product = {product}, looks = {looks}, preferred date = {preferred_date}. "
            "Write a warm first follow-up in Thai checking if they still need help with their photoshoot."
        )

    msg = await generate_reply(
        user_prompt,
        [],
        system_prompt=_FOLLOWUP_SYSTEM,
        max_tokens=150,
    )
    return msg.strip()


async def _send_line_push(user_id: str, text: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _LINE_PUSH_URL,
            headers={"Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}"},
            json={"to": user_id, "messages": [{"type": "text", "text": text}]},
            timeout=10,
        )
        resp.raise_for_status()


async def check_and_send_followups():
    """Main entry point — find quiet customers and send personalized follow-ups."""
    try:
        customers = await get_customers_needing_followup()
    except Exception:
        logger.exception("Failed to fetch customers needing follow-up")
        return

    if not customers:
        logger.debug("Follow-up check: no customers need attention")
        return

    logger.info("Follow-up check: %d customer(s) need attention", len(customers))

    for state in customers:
        user_id = state["user_id"]
        current_count = state.get("follow_up_count", 0)
        new_count = current_count + 1
        new_stage = "cold" if new_count >= 2 else state["stage"]

        try:
            message = await _generate_followup_message(state)
            await _send_line_push(user_id, message)
            await mark_followup_sent("line", user_id, new_count, new_stage)
            logger.info(
                "Follow-up #%d sent to %s (stage → %s): %r",
                new_count, user_id, new_stage, message[:60],
            )
        except Exception:
            logger.exception("Failed to send follow-up to %s", user_id)

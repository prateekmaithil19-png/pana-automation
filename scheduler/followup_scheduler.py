"""
Proactive follow-up scheduler for Pana Studio.
Runs every 4 hours. Finds Line customers who showed interest but went quiet
for 48+ hours and sends them a personalized follow-up message via Line push.
Max 2 follow-ups per customer, then stage is set to 'cold'.
"""

import logging

from ai.engine import generate_reply
from database.db import (
    get_customers_needing_followup,
    mark_followup_sent,
    get_human_controlled_idle,
    set_human_controlled,
)
from notifications.line_push import send_line_push

logger = logging.getLogger(__name__)

_RESUME_SYSTEM = """You are a friendly admin assistant for Pana Studio — a commercial photography studio in Bangkok, Thailand.

A customer asked to speak with the studio owner (Dean) directly, and the AI stayed
quiet while Dean was expected to follow up. Dean hasn't replied in over a day, so
you're checking back in on the customer's behalf.

Rules:
- Write in Thai only. End sentences with "ค่ะ". Use "ทางเรา" as first person.
- 2-3 sentences maximum. Warm and apologetic for the wait, not robotic.
- Reference what they were asking about if known.
- Do NOT claim Dean already replied or that anything specific happened — you
  genuinely don't know what, if anything, Dean did outside this chat. Just
  offer to keep helping directly.
- No ** markdown. At most 1 emoji."""

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
            await send_line_push(user_id, message)
            await mark_followup_sent("line", user_id, new_count, new_stage)
            logger.info(
                "Follow-up #%d sent to %s (stage → %s): %r",
                new_count, user_id, new_stage, message[:60],
            )
        except Exception:
            logger.exception("Failed to send follow-up to %s", user_id)


async def _generate_resume_message(state: dict) -> str:
    shoot_type = state.get("shoot_type") or "ไม่ระบุ"
    product = state.get("product_type") or "ไม่ระบุ"
    user_prompt = (
        f"Customer's interest so far: shoot type = {shoot_type}, product = {product}. "
        "They asked to speak with Dean directly and haven't heard back in over a "
        "day. Write a warm, apologetic check-in in Thai offering to keep helping."
    )
    msg = await generate_reply(user_prompt, [], system_prompt=_RESUME_SYSTEM, max_tokens=150)
    return msg.strip()


async def check_and_resume_handoffs():
    """Find customers still marked human_controlled 24h+ after asking for Dean,
    with no resolution — send a check-in and hand control back to the AI."""
    try:
        customers = await get_human_controlled_idle("line", hours=24)
    except Exception:
        logger.exception("Failed to fetch human-controlled idle customers")
        return

    if not customers:
        logger.debug("Handoff resume check: no idle human-controlled customers")
        return

    logger.info("Handoff resume check: %d customer(s) idle 24h+", len(customers))

    for state in customers:
        user_id = state["user_id"]
        try:
            message = await _generate_resume_message(state)
            await send_line_push(user_id, message)
            await set_human_controlled("line", user_id, False)
            logger.info(
                "Resumed AI for %s after 24h+ with no admin follow-up: %r",
                user_id, message[:60],
            )
        except Exception:
            logger.exception("Failed to resume handoff for %s", user_id)

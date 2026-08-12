"""Receives Google Form booking-submission webhooks.

Google Forms has no native webhook — the response Sheet needs a small Apps
Script (onFormSubmit trigger) that POSTs each new response here. See
FORM_APPS_SCRIPT.md for the exact script and setup steps.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import config
from database.db import add_lead, get_admin_contacts
from notifications.line_push import send_line_push

logger = logging.getLogger(__name__)
router = APIRouter()


def _first(answers, *keys) -> str:
    """The Apps Script sends {question_title: answer_text}. Question titles can
    drift slightly (typos, wording tweaks) so match loosely against any of the
    given substrings rather than requiring an exact key."""
    for question, answer in answers.items():
        q = question.lower()
        if any(key in q for key in keys):
            return (answer or "").strip()
    return ""


@router.post("/webhook/form-submit")
async def form_submit(request: Request):
    token = request.query_params.get("token")
    if token != config.SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid token")

    payload = await request.json()
    answers: dict = payload.get("answers", {})
    form_title = payload.get("form_title", "")

    if not answers:
        raise HTTPException(status_code=400, detail="No answers in payload")

    contact_name = _first(answers, "ชื่อผู้ทำการจอง", "ชื่อผู้ติดต่อ", "name")
    phone = _first(answers, "เบอรโทร", "เบอร์โทร", "phone")
    brand = _first(answers, "instagram / line ของแบรนด์", "brand", "แบรนด์")
    product = _first(answers, "ประเภทสินค้า", "type of product")
    quantity = _first(answers, "จำนวนสินค้า", "จำนวน")

    notes_parts = [f"Form: {form_title}"] if form_title else []
    if product:
        notes_parts.append(f"สินค้า: {product}")
    if quantity:
        notes_parts.append(f"จำนวน: {quantity}")
    notes_parts.append(f"เบอร์โทร: {phone}" if phone else "")
    notes = " | ".join(p for p in notes_parts if p)

    lead_id = await add_lead({
        "contact_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "contact_name": contact_name,
        "brand": brand,
        "channel": "Google Form",
        "shoot_date": form_title,
        "notes": notes,
        "status": "new",
    })
    logger.info("Form submission → lead #%d created (%s)", lead_id, contact_name or "no name")

    admins = await get_admin_contacts("line")
    if not admins:
        logger.warning("Form submitted but no admin contacts registered to notify")
    else:
        message = (
            f"📋 มีลูกค้ากรอกฟอร์มจองแล้ว!\n\n"
            f"รอบ: {form_title or '-'}\n"
            f"ชื่อ: {contact_name or '-'}\n"
            f"เบอร์โทร: {phone or '-'}\n"
            f"แบรนด์: {brand or '-'}\n"
            f"สินค้า: {product or '-'}\n"
            f"จำนวน: {quantity or '-'}\n\n"
            f"ดูรายละเอียดเต็มได้ที่ {config.APP_BASE_URL.rstrip('/')}/leads"
        )
        for admin in admins:
            try:
                await send_line_push(admin["user_id"], message)
            except Exception:
                logger.exception("Failed to push form-submission notification to %s", admin.get("label"))

    return JSONResponse({"status": "ok", "lead_id": lead_id})

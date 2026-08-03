"""
Shoot Announcement — send a targeted Line message to warm leads or broadcast
to all Line OA followers about an upcoming One Stop Service shoot.
"""

import logging

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import config
from ai.engine import generate_reply
from database.db import get_customer_state_all

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")

_LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
_LINE_BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"

_ANNOUNCE_SYSTEM = """You are a friendly admin assistant for Pana Studio — a commercial photography studio in Bangkok, Thailand.

Write a short, warm Line message announcing an upcoming One Stop Service photoshoot.

Rules:
- Write in Thai only. End sentences with "ค่ะ". Use "ทางเรา" as first person.
- 3-5 sentences maximum — punchy, exciting, not corporate.
- Include the shoot date, price per look, and highlight the value (model + makeup included).
- End with a soft call to action: invite them to reserve a spot.
- No ** markdown. At most 1-2 emoji. Sound like a real human, not an ad.
- Include studio address at the end: 218 Rhythm Ratchada-Huai Khwang, Room 16, Bangkok"""


async def _generate_announcement(shoot_date: str, price: str, extra_note: str) -> str:
    prompt = (
        f"Write a Line announcement for: shoot date = {shoot_date}, price = {price} THB/look. "
        f"Extra info: {extra_note or 'standard One Stop Service package'}. "
        "Include: model + makeup included, 12-15 photos per look, delivery 5-7 working days."
    )
    return await generate_reply(prompt, [], system_prompt=_ANNOUNCE_SYSTEM, max_tokens=300)


async def _broadcast_line(text: str, image_url: str | None = None):
    messages = []
    if image_url:
        messages.append({
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url,
        })
    messages.append({"type": "text", "text": text})

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _LINE_BROADCAST_URL,
            headers={"Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}"},
            json={"messages": messages},
            timeout=15,
        )
        resp.raise_for_status()


async def _push_line_users(user_ids: list[str], text: str, image_url: str | None = None):
    messages = []
    if image_url:
        messages.append({
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url,
        })
    messages.append({"type": "text", "text": text})

    async with httpx.AsyncClient() as client:
        for uid in user_ids:
            try:
                await client.post(
                    _LINE_PUSH_URL,
                    headers={"Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}"},
                    json={"to": uid, "messages": messages},
                    timeout=10,
                )
            except Exception:
                logger.warning("Push failed for user %s", uid)


@router.get("/announce", response_class=HTMLResponse)
async def announce_page(request: Request):
    return templates.TemplateResponse("announce.html", {"request": request})


@router.post("/announce/preview", response_class=HTMLResponse)
async def announce_preview(
    request: Request,
    shoot_date: str = Form(...),
    price: str = Form("2190"),
    extra_note: str = Form(""),
    image_url: str = Form(""),
    target: str = Form("broadcast"),
):
    message = await _generate_announcement(shoot_date, price, extra_note)
    return templates.TemplateResponse("announce.html", {
        "request": request,
        "preview_message": message,
        "shoot_date": shoot_date,
        "price": price,
        "extra_note": extra_note,
        "image_url": image_url,
        "target": target,
    })


@router.post("/announce/send", response_class=HTMLResponse)
async def announce_send(
    request: Request,
    shoot_date: str = Form(...),
    price: str = Form("2190"),
    extra_note: str = Form(""),
    image_url: str = Form(""),
    target: str = Form("broadcast"),
    final_message: str = Form(...),
):
    clean_image = image_url.strip() or None
    sent_count = 0
    error_msg = ""

    try:
        if target == "broadcast":
            await _broadcast_line(final_message, clean_image)
            sent_count = -1  # broadcast — unknown count
        else:
            # Push to warm leads (stage not 'booked' or 'new')
            leads = await get_customer_state_all(platform="line", stages=["service_inquiry", "shoot_type_known", "collecting", "cold", "quote_requested"])
            user_ids = [r["user_id"] for r in leads]
            if user_ids:
                await _push_line_users(user_ids, final_message, clean_image)
            sent_count = len(user_ids)
    except Exception as exc:
        logger.exception("Announcement send failed")
        error_msg = str(exc)

    return templates.TemplateResponse("announce.html", {
        "request": request,
        "sent": True,
        "sent_count": sent_count,
        "error_msg": error_msg,
    })

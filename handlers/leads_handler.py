from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ai.engine import generate_reply
from database.db import add_lead, delete_lead, get_leads, update_lead, update_lead_status
from skills import build_lead_prompt

router = APIRouter(prefix="/leads")
templates = Jinja2Templates(directory="templates")

STATUSES = ["all", "new", "follow_up", "in_progress", "paid", "rejected", "no_response"]


@router.get("", response_class=HTMLResponse)
async def leads_list(request: Request, status: str = "all"):
    leads = await get_leads(status if status != "all" else None)
    counts = {}
    for s in STATUSES[1:]:
        counts[s] = len(await get_leads(s))
    counts["all"] = sum(counts.values())
    return templates.TemplateResponse(
        "leads.html",
        {"request": request, "leads": leads, "active_status": status, "counts": counts},
    )


@router.post("/add", response_class=RedirectResponse)
async def lead_add(
    contact_date: str = Form(""),
    contact_name: str = Form(""),
    brand: str = Form(""),
    channel: str = Form(""),
    shoot_date: str = Form(""),
    notes: str = Form(""),
    email: str = Form(""),
    status: str = Form("new"),
):
    await add_lead(
        dict(contact_date=contact_date, contact_name=contact_name, brand=brand,
             channel=channel, shoot_date=shoot_date, notes=notes, email=email, status=status)
    )
    return RedirectResponse("/leads", status_code=303)


@router.post("/{lead_id}/status")
async def lead_update_status(lead_id: int, status: str = Form(...)):
    await update_lead_status(lead_id, status)
    return JSONResponse({"ok": True})


@router.post("/{lead_id}/delete", response_class=RedirectResponse)
async def lead_delete(lead_id: int):
    await delete_lead(lead_id)
    return RedirectResponse("/leads", status_code=303)


@router.post("/{lead_id}/generate-followup")
async def lead_generate_followup(lead_id: int, request: Request):
    leads = await get_leads()
    lead = next((l for l in leads if l["id"] == lead_id), None)
    if not lead:
        return JSONResponse({"error": "Lead not found"}, status_code=404)

    brief = f"""Contact: {lead['contact_name'] or 'Unknown'}
Brand: {lead['brand'] or 'Unknown brand'}
Channel: {lead['channel']}
Notes: {lead['notes'] or 'No additional notes'}
Shoot date: {lead['shoot_date'] or 'Not set'}
Status: {lead['status']}"""

    system = build_lead_prompt(brief)
    message = (
        "Write a personalized follow-up message for this lead. "
        "They already had initial contact — this is a follow-up, not first outreach. "
        "Keep it warm, short, and end with a clear next step."
        if lead["status"] == "follow_up"
        else "Write a personalized outreach DM for this lead."
    )
    draft = await generate_reply(message, [], system_prompt=system, max_tokens=300)
    return JSONResponse({"draft": draft})

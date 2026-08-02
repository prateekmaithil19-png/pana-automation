import json

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import config
from database.db import get_approval, update_approval, update_post_status

router = APIRouter()
templates = Jinja2Templates(directory="templates")


async def _send_meta_reply(platform: str, user_id: str, text: str):
    if platform == "instagram":
        url = f"https://graph.facebook.com/v21.0/{config.META_IG_USER_ID}/messages"
    else:
        url = "https://graph.facebook.com/v21.0/me/messages"

    payload = {"recipient": {"id": user_id}, "message": {"text": text}}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            params={"access_token": config.META_PAGE_ACCESS_TOKEN},
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()


async def _send_line_push(user_id: str, text: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}"},
            json={"to": user_id, "messages": [{"type": "text", "text": text}]},
            timeout=10,
        )
        resp.raise_for_status()


async def _deliver_reply(approval: dict, final_text: str):
    platform = approval.get("platform", "")
    user_id = approval.get("user_id", "")
    if platform == "line":
        await _send_line_push(user_id, final_text)
    else:
        await _send_meta_reply(platform, user_id, final_text)


@router.get("/approve/{approval_id}", response_class=HTMLResponse)
async def approval_page(request: Request, approval_id: str):
    approval = await get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval["status"] != "pending":
        return HTMLResponse(
            f"<h2>Already {approval['status']}</h2><p>This approval was already handled.</p>"
        )
    return templates.TemplateResponse(
        "approve.html",
        {"request": request, "approval": approval, "approval_id": approval_id},
    )


@router.get("/approve/{approval_id}/action")
async def quick_action(approval_id: str, action: str):
    approval = await get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval["status"] != "pending":
        return HTMLResponse(f"<p>Already {approval['status']}.</p>")

    if action == "approve":
        final = approval["ai_reply"]
        await update_approval(approval_id, "approved", final)
        if approval["approval_type"] == "reply":
            await _deliver_reply(approval, final)
        elif approval["approval_type"] == "post":
            # Mark the linked post as approved so the scheduler picks it up
            pass
        return HTMLResponse("<h2>✅ อนุมัติแล้ว</h2><p>ส่งข้อความให้ลูกค้าเรียบร้อยค่ะ</p>")

    elif action == "reject":
        await update_approval(approval_id, "rejected")
        return HTMLResponse("<h2>❌ ยกเลิกแล้ว</h2><p>ข้อความถูกยกเลิกค่ะ</p>")

    raise HTTPException(status_code=400, detail="Invalid action")


@router.post("/approve/{approval_id}/submit")
async def submit_edit(approval_id: str, edited_reply: str = Form(...)):
    approval = await get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval["status"] != "pending":
        return HTMLResponse(f"<p>Already {approval['status']}.</p>")

    await update_approval(approval_id, "edited", edited_reply)
    if approval["approval_type"] == "reply":
        await _deliver_reply(approval, edited_reply)
    return HTMLResponse("<h2>✅ ส่งข้อความแล้ว</h2><p>ข้อความที่แก้ไขถูกส่งให้ลูกค้าเรียบร้อยค่ะ</p>")

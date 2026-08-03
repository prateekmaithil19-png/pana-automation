"""
Skills API — Lead Manager, Sales Manager, Marketing Manager, Competitor Analyst.
All endpoints generate AI drafts for human review. Nothing is sent automatically.
"""

import os
import tempfile

from fastapi import APIRouter, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ai.engine import generate_reply
from skills import (
    build_competitor_prompt,
    build_expense_prompt,
    build_lead_prompt,
    build_marketing_prompt,
    build_sales_prompt,
)
from skills.expense_parser import parse_expense_file, format_for_ai

router = APIRouter(prefix="/skills")
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def skills_dashboard(request: Request):
    return templates.TemplateResponse("skills.html", {"request": request, "result": None})


@router.post("/lead", response_class=HTMLResponse)
async def skill_lead(request: Request, business_info: str = Form(...)):
    system = build_lead_prompt(business_info)
    draft = await generate_reply(
        "เขียน DM outreach สำหรับธุรกิจนี้",
        [],
        system_prompt=system,
        max_tokens=400,
    )
    return templates.TemplateResponse(
        "skills.html",
        {
            "request": request,
            "result": draft,
            "result_title": "📨 ร่าง DM สำหรับ Lead",
            "active_skill": "lead",
            "input_value": business_info,
        },
    )


@router.post("/sales", response_class=HTMLResponse)
async def skill_sales(request: Request, conversation: str = Form(...)):
    system = build_sales_prompt()
    draft = await generate_reply(
        conversation,
        [],
        system_prompt=system,
        max_tokens=400,
    )
    return templates.TemplateResponse(
        "skills.html",
        {
            "request": request,
            "result": draft,
            "result_title": "💼 คำแนะนำจาก Sales Manager",
            "active_skill": "sales",
            "input_value": conversation,
        },
    )


@router.post("/marketing", response_class=HTMLResponse)
async def skill_marketing(request: Request, brief: str = Form(...)):
    system = build_marketing_prompt()
    draft = await generate_reply(
        brief,
        [],
        system_prompt=system,
        max_tokens=800,
    )
    return templates.TemplateResponse(
        "skills.html",
        {
            "request": request,
            "result": draft,
            "result_title": "📣 Marketing Plan จาก AI",
            "active_skill": "marketing",
            "input_value": brief,
        },
    )


@router.post("/competitor", response_class=HTMLResponse)
async def skill_competitor(request: Request, competitor_info: str = Form(...)):
    system = build_competitor_prompt()
    draft = await generate_reply(
        competitor_info,
        [],
        system_prompt=system,
        max_tokens=1000,
    )
    return templates.TemplateResponse(
        "skills.html",
        {
            "request": request,
            "result": draft,
            "result_title": "🔍 Competitor Analysis",
            "active_skill": "competitor",
            "input_value": competitor_info,
        },
    )


@router.post("/expense", response_class=HTMLResponse)
async def skill_expense(
    request: Request,
    expense_file: UploadFile = File(None),
    expense_data: str = Form(""),
):
    system = build_expense_prompt()
    analysis_input = expense_data.strip()
    parse_error = None

    # If a file was uploaded, parse it; otherwise use the pasted text
    if expense_file and expense_file.filename:
        try:
            contents = await expense_file.read()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                tmp.write(contents)
                tmp_path = tmp.name
            parsed = parse_expense_file(tmp_path)
            os.unlink(tmp_path)
            analysis_input = format_for_ai(parsed)
        except Exception as exc:
            parse_error = f"Could not read file: {exc}. Please paste the data manually below."

    if not analysis_input:
        return templates.TemplateResponse(
            "skills.html",
            {
                "request": request,
                "result": parse_error or "Please upload an Excel file or paste expense data.",
                "result_title": "⚠️ No Data",
                "active_skill": "expense",
                "input_value": "",
            },
        )

    draft = await generate_reply(
        analysis_input,
        [],
        system_prompt=system,
        max_tokens=1500,
    )
    return templates.TemplateResponse(
        "skills.html",
        {
            "request": request,
            "result": draft,
            "result_title": "💰 Expense Analysis — Pana Studio",
            "active_skill": "expense",
            "input_value": expense_data,
            "parse_error": parse_error,
        },
    )

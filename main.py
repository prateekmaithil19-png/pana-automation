import logging
import os
import uuid
from contextlib import asynccontextmanager

import aiofiles
from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from approval.router import router as approval_router
from database.db import init_db, get_upcoming_posts, get_next_suggested_slot
from handlers.leads_handler import router as leads_router
from handlers.line_handler import router as line_router
from handlers.meta_handler import router as meta_router
from handlers.skills_handler import router as skills_router
from scheduler.post_scheduler import start_scheduler, stop_scheduler
from scheduler.date_fetcher import refresh_upcoming_dates
from approval.store import create_post_approval
from notifications.email_notify import send_post_approval_email
from notifications.line_notify import notify_post_approval
from ai.engine import generate_reply
from skills import build_marketing_prompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler()
    try:
        await refresh_upcoming_dates()
    except Exception:
        logger.warning("Startup date refresh failed — will retry at 08:00 BKK daily")
    yield
    stop_scheduler()


app = FastAPI(title="Pana Studio Automation", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

app.include_router(meta_router)
app.include_router(line_router)
app.include_router(approval_router)
app.include_router(skills_router)
app.include_router(leads_router)

# Serve uploaded media files publicly (needed for Instagram image URLs)
app.mount("/media", StaticFiles(directory=UPLOAD_DIR), name="media")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})


@app.get("/post", response_class=HTMLResponse)
async def post_form(request: Request):
    next_slot = await get_next_suggested_slot()
    return templates.TemplateResponse("post_form.html", {"request": request, "next_slot": next_slot})


@app.post("/post", response_class=HTMLResponse)
async def submit_post(
    request: Request,
    caption: str = Form(...),
    platforms: list[str] = Form(...),
    scheduled_at: str = Form(...),
    image_url: str = Form(""),
    image_file: UploadFile | None = File(None),
):
    final_image_path: str | None = None

    # Prefer uploaded file over URL
    if image_file and image_file.filename:
        ext = os.path.splitext(image_file.filename)[1]
        filename = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(UPLOAD_DIR, filename)
        async with aiofiles.open(save_path, "wb") as f:
            content = await image_file.read()
            await f.write(content)
        final_image_path = filename  # relative name; scheduler prepends APP_BASE_URL/media/
    elif image_url.strip():
        final_image_path = image_url.strip()

    approval_id, post_id = await create_post_approval(
        caption=caption,
        platforms=platforms,
        scheduled_at=scheduled_at,
        image_path=final_image_path,
    )

    public_image_url: str | None = None
    if final_image_path and not final_image_path.startswith("http"):
        import config
        public_image_url = f"{config.APP_BASE_URL.rstrip('/')}/media/{final_image_path}"
    elif final_image_path:
        public_image_url = final_image_path

    try:
        await send_post_approval_email(approval_id, caption, platforms, scheduled_at, public_image_url)
    except Exception:
        logger.exception("Email notification failed")
    try:
        await notify_post_approval(approval_id, caption, platforms, scheduled_at)
    except Exception:
        logger.exception("Line Notify failed")

    next_slot = await get_next_suggested_slot()
    return templates.TemplateResponse(
        "post_form.html",
        {
            "request": request,
            "success": True,
            "approval_id": approval_id,
            "next_slot": next_slot,
        },
    )


@app.post("/post/generate-caption")
async def generate_caption(brief: str = Form(...), platform_hint: str = Form("")):
    """AI-powered caption generator using Marketing Manager skill."""
    task = f"""Generate a social media caption for: {brief}
Platform: {platform_hint or 'Instagram/Facebook'}
Requirements: match Pana Studio's post style — engaging, clean, minimal emojis, Thai or English based on brief language.
Return ONLY the caption text + hashtags. No explanations."""
    system = build_marketing_prompt()
    caption = await generate_reply(task, [], system_prompt=system, max_tokens=400)
    return JSONResponse({"caption": caption})


@app.get("/calendar", response_class=HTMLResponse)
async def calendar_view(request: Request):
    posts = await get_upcoming_posts()
    return templates.TemplateResponse("calendar.html", {"request": request, "posts": posts})


@app.get("/health")
async def health():
    return {"status": "ok"}

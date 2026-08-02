import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config


def _send_email_sync(subject: str, html_body: str, to: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.SMTP_USER
    msg["To"] = to
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        smtp.sendmail(config.SMTP_USER, to, msg.as_string())


async def send_email(subject: str, html_body: str, to: str | None = None):
    recipient = to or config.NOTIFY_EMAIL
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_email_sync, subject, html_body, recipient)


async def send_reply_approval_email(
    approval_id: str,
    platform: str,
    customer_message: str,
    ai_reply: str,
):
    base = config.APP_BASE_URL.rstrip("/")
    approve_url = f"{base}/approve/{approval_id}/action?action=approve"
    edit_url = f"{base}/approve/{approval_id}"
    reject_url = f"{base}/approve/{approval_id}/action?action=reject"

    platform_label = {"facebook": "Facebook", "instagram": "Instagram", "line": "Line OA"}.get(
        platform, platform
    )

    html = f"""
<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;max-width:600px;margin:auto;padding:20px;">
  <h2 style="color:#333;">🔔 Pana Studio — ลูกค้าถามราคา ({platform_label})</h2>

  <div style="background:#f5f5f5;border-left:4px solid #888;padding:12px;margin:16px 0;">
    <strong>ข้อความลูกค้า:</strong><br>
    <p style="margin:8px 0;">{customer_message}</p>
  </div>

  <div style="background:#e8f4e8;border-left:4px solid #4CAF50;padding:12px;margin:16px 0;">
    <strong>AI ร่างตอบ:</strong><br>
    <p style="margin:8px 0;">{ai_reply}</p>
  </div>

  <div style="margin:24px 0;">
    <a href="{approve_url}"
       style="background:#4CAF50;color:white;padding:12px 24px;text-decoration:none;border-radius:4px;margin-right:8px;">
      ✅ อนุมัติ &amp; ส่ง
    </a>
    <a href="{edit_url}"
       style="background:#2196F3;color:white;padding:12px 24px;text-decoration:none;border-radius:4px;margin-right:8px;">
      ✏️ แก้ไขก่อนส่ง
    </a>
    <a href="{reject_url}"
       style="background:#f44336;color:white;padding:12px 24px;text-decoration:none;border-radius:4px;">
      ❌ ยกเลิก
    </a>
  </div>

  <p style="color:#999;font-size:12px;">Approval ID: {approval_id}</p>
</body>
</html>"""

    await send_email(
        subject=f"[Pana Studio] ลูกค้าถามราคาบน {platform_label} — รอการอนุมัติ",
        html_body=html,
    )


async def send_post_approval_email(
    approval_id: str,
    caption: str,
    platforms: list[str],
    scheduled_at: str,
    image_url: str | None = None,
):
    base = config.APP_BASE_URL.rstrip("/")
    approve_url = f"{base}/approve/{approval_id}/action?action=approve"
    edit_url = f"{base}/approve/{approval_id}"
    reject_url = f"{base}/approve/{approval_id}/action?action=reject"

    platforms_str = ", ".join(platforms)
    image_html = f'<img src="{image_url}" style="max-width:100%;margin:12px 0;">' if image_url else ""

    html = f"""
<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;max-width:600px;margin:auto;padding:20px;">
  <h2 style="color:#333;">📸 Pana Studio — โพสต์ใหม่รอการอนุมัติ</h2>

  <p><strong>แพลตฟอร์ม:</strong> {platforms_str}</p>
  <p><strong>กำหนดโพสต์:</strong> {scheduled_at}</p>

  {image_html}

  <div style="background:#f5f5f5;border-left:4px solid #888;padding:12px;margin:16px 0;">
    <strong>Caption:</strong><br>
    <p style="margin:8px 0;white-space:pre-wrap;">{caption}</p>
  </div>

  <div style="margin:24px 0;">
    <a href="{approve_url}"
       style="background:#4CAF50;color:white;padding:12px 24px;text-decoration:none;border-radius:4px;margin-right:8px;">
      ✅ อนุมัติ
    </a>
    <a href="{edit_url}"
       style="background:#2196F3;color:white;padding:12px 24px;text-decoration:none;border-radius:4px;margin-right:8px;">
      ✏️ แก้ไข
    </a>
    <a href="{reject_url}"
       style="background:#f44336;color:white;padding:12px 24px;text-decoration:none;border-radius:4px;">
      ❌ ยกเลิก
    </a>
  </div>

  <p style="color:#999;font-size:12px;">Approval ID: {approval_id}</p>
</body>
</html>"""

    await send_email(
        subject=f"[Pana Studio] โพสต์ใหม่รอการอนุมัติ ({platforms_str})",
        html_body=html,
    )

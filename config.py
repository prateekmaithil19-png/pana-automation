from dotenv import load_dotenv
import os

load_dotenv()

# Claude AI
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# Meta
META_APP_ID = os.environ["META_APP_ID"]
META_APP_SECRET = os.environ["META_APP_SECRET"]
META_VERIFY_TOKEN = os.environ["META_VERIFY_TOKEN"]
META_PAGE_ACCESS_TOKEN = os.environ["META_PAGE_ACCESS_TOKEN"]
META_PAGE_ID = os.environ["META_PAGE_ID"]
META_IG_USER_ID = os.environ["META_IG_USER_ID"]

# Line OA
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]

# Line Notify (personal)
LINE_NOTIFY_TOKEN = os.environ["LINE_NOTIFY_TOKEN"]

# Email
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
NOTIFY_EMAIL = os.environ["NOTIFY_EMAIL"]

# App
APP_BASE_URL = os.environ["APP_BASE_URL"]
SECRET_KEY = os.environ["SECRET_KEY"]
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./pana.db")

from dotenv import load_dotenv
import os

load_dotenv()

# LLM Configs
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
PATEWAY_API_KEY = os.getenv("PATEWAY_API_KEY", "")
PATEWAY_BASE_URL = os.getenv("PATEWAY_BASE_URL", "https://api.pateway.ai/v1")
PATEWAY_MODEL = os.getenv("PATEWAY_MODEL", "gpt-5.5")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
KIMCHI_API_KEY = os.getenv("KIMCHI_API_KEY", "")
KIMCHI_BASE_URL = os.getenv("KIMCHI_BASE_URL", "https://api.kimchi.dev/v1")
KIMCHI_MODEL = os.getenv("KIMCHI_MODEL", "kimchi-large")
LLM_PROVIDERS = os.getenv("LLM_PROVIDERS", "gemini,pateway,openai,claude,kimchi")

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

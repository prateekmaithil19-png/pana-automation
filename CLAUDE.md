# Pana Studio Automation — Project Context

## What this project is

A business automation system for **Pana Studio** — a commercial photography studio in Bangkok, Thailand.
Owner: Prateek (goes by Deen). Instagram: @pa.na.studio. Line OA: @147xhyzb.

The system does three things:
1. **AI auto-reply** on Line OA — answers customer questions, defers custom quote requests to admin
2. **Human approval flow** — admin approves AI replies and social posts before anything is sent
3. **Social media scheduler** — posts to Facebook, Instagram, Line OA on a schedule (every 1-2 days)

Live URL: `https://pana-studio-bot.onrender.com`
GitHub: `https://github.com/prateekmaithil19-png/pana-automation`

---

## Tech stack

- **FastAPI** (Python) — webhook server + admin UI
- **SQLite + aiosqlite** — conversations, approvals, scheduled posts
- **APScheduler** — runs every minute to publish approved posts
- **Jinja2** — server-side HTML templates
- **Render.com** free tier — hosting (kept awake by SleepNoMore pinging `/health` every 8 min)

### Multi-LLM fallback chain
Order: `gemini → pateway → openai → claude → kimchi` (configured via `LLM_PROVIDERS` env var)

- **Gemini** (`gemini-flash-latest`) — primary, 20 req/day free tier
- **Pateway** (`gpt-5.5`) — second, OpenAI-compatible at `https://api.pateway.ai/v1`
- **OpenAI** (`gpt-4o-mini`) — third
- **Claude** (`claude-3-5-sonnet-20241022`) — fourth
- **Kimchi** (`kimchi-large`) — backup/last resort, OpenAI-compatible at `https://api.kimchi.dev/v1`

---

## Project structure

```
main.py                  # FastAPI app, routes: /post, /post/generate-caption, /calendar
config.py                # All env vars (LLM keys, Meta, Line, SMTP, app config)
requirements.txt

ai/
  engine.py              # Multi-LLM fallback: generate_reply(), _call_gemini/pateway/openai/claude
  classifier.py          # is_pricing_request() — only triggers for explicit quote requests
  prompts.py             # build_system_prompt(customer_memory) — reads from knowledge/

knowledge/
  faq.md                 # Full FAQ: pricing, delivery times, look rules, add-ons, policies
  chat_examples.json     # 45+ real customer conversations used as style examples
  business_profile.md    # Studio identity, brand voice, services, address

skills/
  __init__.py            # Exports all 4 skill prompt builders
  lead_manager.py        # build_lead_prompt() — personalized outreach DMs
  sales_manager.py       # build_sales_prompt() — closing, objection handling
  marketing_manager.py   # build_marketing_prompt() — captions, hashtags, ad copy
  competitor_analyst.py  # build_competitor_prompt() — competitor analysis

memory/
  customer_context.py    # build_customer_context() — reads last 10 msgs, avoids repeating questions

handlers/
  line_handler.py        # Line webhook — receives messages, calls AI, sends to approval
  meta_handler.py        # Facebook/Instagram webhook
  skills_handler.py      # /skills UI — Lead, Sales, Marketing, Competitor pages

approval/
  router.py              # /approve/{id} GET (show), POST (approve/reject/edit)
  store.py               # create_post_approval(), create_reply_approval()

notifications/
  email_notify.py        # send_post_approval_email() — Gmail SMTP
  line_notify.py         # notify_post_approval() — Line Notify

scheduler/
  post_scheduler.py      # publish_approved_posts() runs every min
                         # _post_to_facebook(), _post_to_instagram(), _post_to_line_oa()
                         # TikTok stub (logs warning — API not yet configured)

database/
  db.py                  # init_db(), add_message(), get_conversation(), save_approval(),
                         # get_approval(), update_approval(), save_scheduled_post(),
                         # update_post_status(), get_upcoming_posts(), get_next_suggested_slot(),
                         # get_approved_posts()

templates/
  base.html              # Nav: Home / โพสต์ใหม่ / Calendar / Skills
  home.html
  post_form.html         # AI caption generator + auto-suggested next slot + post submission
  calendar.html          # Content calendar — upcoming posts queue with status badges
  approve.html           # Admin approval page
  skills.html            # 4 AI skill forms
```

---

## Key behaviors

### Line OA auto-reply flow
1. Customer sends message → `line_handler.py`
2. `build_customer_context()` reads last 10 messages (so AI doesn't repeat questions)
3. `is_pricing_request()` checks if it's an explicit quote request
4. If **yes** → trigger admin approval flow (email + Line Notify)
5. If **no** → `generate_reply()` with full system prompt → send directly
6. Message saved to `conversations` table

### Smart classifier (`ai/classifier.py`)
- Only triggers approval for explicit quote requests: "ใบเสนอราคา", "send me a quote", "total cost", etc.
- `_NOT_PRICE_PATTERNS` prevents false triggers for "how much duration", "how many photos", etc.
- General FAQ questions (delivery time, prices listed in FAQ) → AI answers directly

### System prompt rules (`ai/prompts.py`)
- **Language rule**: full English if customer writes English, full Thai if Thai — never mix
- **Answer Directly list**: 18+ facts AI must answer without deferring (delivery time=5-7 days, photos per look=12-15, etc.)
- **TYPE 1** (standard prices) → answer directly
- **TYPE 2** (custom project quote) → gather requirements first, then defer to admin

### Social media posting flow
1. Admin goes to `/post` → uploads image + brief
2. AI generates caption (Marketing Manager skill) via `/post/generate-caption`
3. `get_next_suggested_slot()` auto-fills scheduled time (last post + 1.5 days)
4. Submit → creates approval record → email + Line Notify sent to admin
5. Admin approves at `/approve/{id}`
6. Scheduler publishes at `scheduled_at` via Graph API (FB/IG) or Line broadcast

---

## Environment variables (all required)

```
# LLM
GEMINI_API_KEY
OPENAI_API_KEY
PATEWAY_API_KEY
PATEWAY_BASE_URL=https://api.pateway.ai/v1
ANTHROPIC_API_KEY
KIMCHI_API_KEY
KIMCHI_BASE_URL=https://api.kimchi.dev/v1
KIMCHI_MODEL=kimchi-large
LLM_PROVIDERS=gemini,pateway,openai,claude,kimchi

# Meta (Facebook + Instagram)
META_APP_ID=28212985095056808
META_APP_SECRET=d532b491298a9f54345ac1d079ea1948
META_VERIFY_TOKEN=pana_studio_webhook_secret_2025
META_PAGE_ACCESS_TOKEN=         # 60-day token, renew every 2 months
META_PAGE_ID=130079090192180
META_IG_USER_ID=17841461516085598

# Line
LINE_CHANNEL_ACCESS_TOKEN=      # From Line Developers console
LINE_CHANNEL_SECRET=
LINE_NOTIFY_TOKEN=              # Not yet set up

# Email
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=prateekmaithil19@gmail.com
SMTP_PASSWORD=                  # Gmail App Password — not yet set up
NOTIFY_EMAIL=prateekmaithil19@gmail.com

# App
APP_BASE_URL=https://pana-studio-bot.onrender.com
SECRET_KEY=pana2025studioautomationsecretkey
DATABASE_URL=sqlite+aiosqlite:///./pana.db
```

---

## Known limitations / pending setup

- **META_PAGE_ACCESS_TOKEN** expires every 60 days — must be manually renewed via Graph API token exchange
- **LINE_NOTIFY_TOKEN** — not yet configured (notifications fall back to email only)
- **SMTP_PASSWORD** — Gmail App Password not yet set up (email notifications not working)
- **TikTok** — platform checkbox exists in UI, scheduler has stub, but TikTok Content Posting API not applied for yet (`developers.tiktok.com`)
- **Meta Business Verification** — pending (needed for full Instagram Graph API access)
- **Image generation** — NOT implemented. User uploads real studio photos. AI only generates captions.
- **Website knowledge** — `panastudio.in` content not yet scraped (site timed out). Update `knowledge/` manually when available.

---

## Business context

- **One Stop Service**: 2,190–2,600 THB/look — multiple brands share studio + model cost
- **Individual Brand Shoot**: starts 23,000 THB/half-day — full team, custom creative
- **Delivery**: 5-7 working days after shoot, Google Drive link (6-month expiry)
- **Returns**: 3-5 working days via Flash Express or Grab
- **Studio address**: 218 Rhythm Ratchada-Huai Khwang, Room 16, Bangkok 10310
- **Contact**: Deen 065-974-5556
- **Accepted shoots**: fashion, lingerie, swimwear, supplements, wedding, outdoor/beach
- **Hair & makeup**: included in team
- **Model selection**: admin sends list, client chooses

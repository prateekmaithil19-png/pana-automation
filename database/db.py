import aiosqlite
import os

DB_PATH = "pana.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pending_approvals (
                id TEXT PRIMARY KEY,
                approval_type TEXT NOT NULL,
                platform TEXT,
                user_id TEXT,
                customer_message TEXT,
                ai_reply TEXT,
                status TEXT DEFAULT 'pending',
                final_reply TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME
            );

            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id TEXT PRIMARY KEY,
                approval_id TEXT,
                caption TEXT NOT NULL,
                image_path TEXT,
                platforms TEXT NOT NULL,
                scheduled_at DATETIME NOT NULL,
                status TEXT DEFAULT 'pending_approval',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_date TEXT,
                contact_name TEXT,
                brand TEXT,
                channel TEXT,
                shoot_date TEXT,
                notes TEXT,
                email TEXT,
                status TEXT DEFAULT 'new',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS customer_state (
                platform TEXT NOT NULL,
                user_id TEXT NOT NULL,
                stage TEXT DEFAULT 'new',
                shoot_type TEXT,
                num_looks TEXT,
                product_type TEXT,
                preferred_date TEXT,
                customer_name TEXT,
                follow_up_count INTEGER DEFAULT 0,
                last_message_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_follow_up_at DATETIME,
                PRIMARY KEY (platform, user_id)
            );

            CREATE TABLE IF NOT EXISTS correction_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_message TEXT NOT NULL,
                ai_reply TEXT NOT NULL,
                corrected_reply TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.commit()
    await _migrate_existing_tables()
    await _seed_leads()


async def _migrate_existing_tables():
    """Add new columns to existing tables without data loss."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("PRAGMA table_info(customer_state)") as cur:
            existing_cols = {row[1] async for row in cur}
        if "customer_name" not in existing_cols:
            await db.execute("ALTER TABLE customer_state ADD COLUMN customer_name TEXT")
            await db.commit()


async def add_message(platform: str, user_id: str, role: str, message: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO conversations (platform, user_id, role, message) VALUES (?,?,?,?)",
            (platform, user_id, role, message),
        )
        await db.commit()


async def get_conversation(platform: str, user_id: str, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT role, message FROM conversations
               WHERE platform=? AND user_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (platform, user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [{"role": r["role"], "content": r["message"]} for r in reversed(rows)]


async def get_customer_state(platform: str, user_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM customer_state WHERE platform=? AND user_id=?",
            (platform, user_id),
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


_ALLOWED_STATE_COLS = {"stage", "shoot_type", "num_looks", "product_type", "preferred_date", "customer_name", "follow_up_count"}


async def upsert_customer_state(platform: str, user_id: str, **fields):
    """Create or update a customer's state. Only whitelisted columns are written."""
    safe = {k: v for k, v in fields.items() if k in _ALLOWED_STATE_COLS}
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO customer_state (platform, user_id, last_message_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(platform, user_id) DO UPDATE SET
               last_message_at = CURRENT_TIMESTAMP""",
            (platform, user_id),
        )
        for col, val in safe.items():
            await db.execute(
                f"UPDATE customer_state SET {col}=? WHERE platform=? AND user_id=?",
                (val, platform, user_id),
            )
        await db.commit()


async def mark_followup_sent(platform: str, user_id: str, new_count: int, new_stage: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE customer_state
               SET follow_up_count=?, stage=?, last_follow_up_at=CURRENT_TIMESTAMP
               WHERE platform=? AND user_id=?""",
            (new_count, new_stage, platform, user_id),
        )
        await db.commit()


async def save_correction_example(customer_message: str, ai_reply: str, corrected_reply: str):
    """Save a case where Deen edited the AI reply — used to improve future responses."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO correction_examples (customer_message, ai_reply, corrected_reply) VALUES (?,?,?)",
            (customer_message, ai_reply, corrected_reply),
        )
        await db.commit()


async def get_recent_corrections(limit: int = 5) -> list[dict]:
    """Return the most recent corrections for inclusion in the system prompt."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT customer_message, ai_reply, corrected_reply FROM correction_examples ORDER BY id DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_customers_needing_followup() -> list[dict]:
    """Return Line customers who went quiet 48+ hours ago and still need follow-up."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM customer_state
               WHERE platform = 'line'
               AND stage IN ('service_inquiry', 'shoot_type_known', 'collecting')
               AND follow_up_count < 2
               AND last_message_at < datetime('now', '-48 hours')
               AND (last_follow_up_at IS NULL
                    OR last_follow_up_at < datetime('now', '-72 hours'))
               ORDER BY last_message_at ASC""",
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def save_approval(approval_id: str, data: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO pending_approvals
               (id, approval_type, platform, user_id, customer_message, ai_reply)
               VALUES (?,?,?,?,?,?)""",
            (
                approval_id,
                data["approval_type"],
                data.get("platform"),
                data.get("user_id"),
                data.get("customer_message"),
                data.get("ai_reply"),
            ),
        )
        await db.commit()


async def get_approval(approval_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM pending_approvals WHERE id=?", (approval_id,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def update_approval(approval_id: str, status: str, final_reply: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE pending_approvals
               SET status=?, final_reply=?, resolved_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (status, final_reply, approval_id),
        )
        await db.commit()


async def save_scheduled_post(post_id: str, approval_id: str, data: dict):
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO scheduled_posts
               (id, approval_id, caption, image_path, platforms, scheduled_at)
               VALUES (?,?,?,?,?,?)""",
            (
                post_id,
                approval_id,
                data["caption"],
                data.get("image_path"),
                json.dumps(data["platforms"]),
                data["scheduled_at"],
            ),
        )
        await db.commit()


async def update_post_status(post_id: str, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE scheduled_posts SET status=? WHERE id=?", (status, post_id)
        )
        await db.commit()


async def get_upcoming_posts() -> list[dict]:
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM scheduled_posts
               WHERE status IN ('pending_approval','approved')
               ORDER BY scheduled_at ASC"""
        ) as cur:
            rows = await cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["platforms"] = json.loads(d["platforms"])
        result.append(d)
    return result


async def get_next_suggested_slot(gap_days: float = 1.5) -> str:
    """Return ISO datetime string for the next suggested post slot."""
    from datetime import datetime, timedelta
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT MAX(scheduled_at) FROM scheduled_posts
               WHERE status NOT IN ('rejected')"""
        ) as cur:
            row = await cur.fetchone()
    last = row[0] if row and row[0] else None
    if last:
        try:
            base = datetime.fromisoformat(last)
        except ValueError:
            base = datetime.utcnow()
    else:
        base = datetime.utcnow()
    next_slot = base + timedelta(days=gap_days)
    # Round to nearest hour for cleaner UX
    next_slot = next_slot.replace(minute=0, second=0, microsecond=0)
    return next_slot.strftime("%Y-%m-%dT%H:%M")


async def get_approved_posts() -> list[dict]:
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM scheduled_posts WHERE status='approved'"
        ) as cur:
            rows = await cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["platforms"] = json.loads(d["platforms"])
        result.append(d)
    return result


# ── Leads CRM ────────────────────────────────────────────────────────────────

async def get_leads(status: str | None = None) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status and status != "all":
            async with db.execute(
                "SELECT * FROM leads WHERE status=? ORDER BY contact_date DESC, id DESC",
                (status,),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                "SELECT * FROM leads ORDER BY contact_date DESC, id DESC"
            ) as cur:
                rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def add_lead(data: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO leads (contact_date, contact_name, brand, channel, shoot_date, notes, email, status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                data.get("contact_date", ""),
                data.get("contact_name", ""),
                data.get("brand", ""),
                data.get("channel", ""),
                data.get("shoot_date", ""),
                data.get("notes", ""),
                data.get("email", ""),
                data.get("status", "new"),
            ),
        )
        await db.commit()
        return cur.lastrowid


async def update_lead_status(lead_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE leads SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, lead_id),
        )
        await db.commit()


async def update_lead(lead_id: int, data: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE leads SET contact_date=?, contact_name=?, brand=?, channel=?,
               shoot_date=?, notes=?, email=?, status=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (
                data.get("contact_date", ""),
                data.get("contact_name", ""),
                data.get("brand", ""),
                data.get("channel", ""),
                data.get("shoot_date", ""),
                data.get("notes", ""),
                data.get("email", ""),
                data.get("status", "new"),
                lead_id,
            ),
        )
        await db.commit()


async def delete_lead(lead_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM leads WHERE id=?", (lead_id,))
        await db.commit()


async def _seed_leads():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM leads") as cur:
            count = (await cur.fetchone())[0]
    if count >= 76:
        return
    seed = [
        ("2024-09-21","Ploy","No Brand","Line OA","November 2","Whey Protein / 2 models","","paid"),
        ("2024-09-21","Earn","","Line OA","","","","new"),
        ("2024-09-21","F","","Line OA","","","","new"),
        ("2024-09-21","Jusmin","Sandei Studio","Line OA","","Cloths","","new"),
        ("2024-09-22","Tina","Navara Jewelry","Line OA","November","","","new"),
        ("2024-09-23","Saipahn","Pattama","Line OA","","Cloths","","new"),
        ("2024-09-29","F","","Line OA","","","","new"),
        ("2024-09-30","Art","","Line OA","","Photographer","","new"),
        ("2024-10-01","Ruji","","Line OA","","","","new"),
        ("2024-10-02","Houze","","Line OA","","Photographer","","new"),
        ("2024-10-02","Auiiaui","","Line OA","","","","new"),
        ("2024-10-02","BossAK","","Line OA","","","","new"),
        ("2024-10-02","Janet","","Line OA","","Shoes","","no_response"),
        ("2024-10-02","Kikie","","Line OA","29/10","Body Oil","","new"),
        ("2024-10-03","Auey","","Line OA","","","","new"),
        ("2024-10-03","Farida","Urbana Studios","Line OA","","Offer Olena","","rejected"),
        ("2024-10-03","","Cocomill.brand","Instagram","","New Collection Mid Oct / Shoot mom and kid","","paid"),
        ("2024-10-04","Fah","Sky Handbag","Instagram","","Thai Model only","","paid"),
        ("2024-10-04","","ภูมิใจ","Instagram","","Negotiate","","follow_up"),
        ("2024-10-04","Eveandboy","Eveandboy","Email","","Company Profile","marketing@eveandboy.com","in_progress"),
        ("2024-10-04","Jaruwan","Chobdress","Line OA","","New brand / shirts","","new"),
        ("2024-10-04","Yo","Palilyn Jewelry","Line OA","","Earring","","new"),
        ("2024-10-04","Chompu","","Line OA","","Offer Olena 3 looks","","follow_up"),
        ("2024-10-04","Khong Kwan","","Line OA","","No answer keep following","","rejected"),
        ("2024-10-04","","Welry Accessories","Instagram","","1 look 2 jewelry offer","","follow_up"),
        ("2024-10-04","","Jubilee Diamond","Email","","Company Profile","contact@jubileediamond.co.th","in_progress"),
        ("2024-10-04","Juv","","Line OA","","","","new"),
        ("2024-10-04","Fon","Regenelle","Line OA","","2-3 looks","","new"),
        ("2024-10-04","","Bewish Anana","Instagram","","1 look","","new"),
        ("2024-10-16","Namwan","","Line OA","29/10","Dress","","in_progress"),
        ("2024-10-17","Bo Chi Chi","","Line OA","29/10","","","follow_up"),
        ("2024-10-17","Khun Jub","","Line OA","29/10","","","follow_up"),
        ("2024-10-17","Thidaphon","","Line OA","29/10","2 looks","","follow_up"),
        ("2024-10-17","Stamping","","Line OA","29/10","","","follow_up"),
        ("2024-10-17","Mookmik","","Line OA","29/10","","","in_progress"),
        ("2024-10-18","Shatamp","","Line OA","","Thai Model only","","new"),
        ("2024-10-18","M","","Line OA","29/10","","","follow_up"),
        ("2024-10-18","NamFah","Blanc du Nil","Line OA","29/10","1 look","","paid"),
        ("2024-10-18","Rabbit","","Line OA","29/10","4 Bags","","in_progress"),
        ("2024-10-18","Mai","","Line OA","29/10","Street Shoot","","new"),
        ("2024-10-18","Bumbim","","Line OA","29/10","170 cm height concern","","new"),
        ("2024-10-18","Parwenapat","","Line OA","29/10","","","follow_up"),
        ("2024-10-19","Nice","","Line OA","29/10","","","follow_up"),
        ("2024-10-18","กานต์","Wanderlust Stylish","Instagram","30/10","Sent Email","karnkanyapak.work@gmail.com","follow_up"),
        ("2024-10-18","Fon","Jin.BKK","Instagram","29/10","","","paid"),
        ("2024-10-19","Auri","Maison de Auri","Instagram","29/10","","","paid"),
        # Brand outreach targets (from Brand Data spreadsheet)
        ("","","Varenna Studio","Instagram","","Bag | @varenna.studio","","new"),
        ("","","FFfinder","Instagram","","@fffinderco","","new"),
        ("","","Kasina","Instagram","","@kasina.official___ | Dene","","new"),
        ("","","Rock Chang Tshirt Brand","Instagram","","@rockchangth","","new"),
        ("","","LABELIZED","Instagram","","@shoplabelized","","new"),
        ("","","Oh Honey Honey","Instagram","","Swimwear | @ohhoneyhoney.official","","new"),
        ("","","KADE.BKK","Instagram","","@kade.bkk","","new"),
        ("","","SANDAA EST2016","Instagram","","Swimwear | @sandaa_official","","new"),
        ("","","Hit-chip Shoes","Instagram","","@hit.chip","","new"),
        ("","","Alice Gems","Instagram","","Accessories | @alicegems_official","","new"),
        ("","","Overnaked","Instagram","","Body Oil | @overnaked.official","","new"),
        ("","","MIRAH","Instagram","","@mirahofficial_th","","new"),
        ("","","Feline Agency","Instagram","","@felineagency","","new"),
        ("","","Whiteline Official","Instagram","","Dene | @whiteline_dress","","new"),
        ("","","SUAVE LUXE","Instagram","","Night Dress | @suave.luxe","","new"),
        ("","","felt.bkk","Instagram","","@felt.bkk","","new"),
        ("","","Plant B","Instagram","","Whey Protein | @plantbhealth","","new"),
        ("","","bubuBee-story","Instagram","","Dene | @bububeestory","","new"),
        ("","","VINTAGE FLAMINGO","Instagram","","Swimwear | @vintage_flamingo","","new"),
        ("","","Daisy by Daisy","Instagram","","@daisybydaisy.brand","","new"),
        ("","","ROMP","Instagram","","@romp.co","","new"),
        ("","","Fullada","Instagram","","Swimwear | @fullanda_swimwear","","new"),
        ("","","PASTELS MOTEL","Instagram","","@pastelsmotel","","new"),
        ("","","VATANA","Instagram","","Street Shoot | @vatana_official","","new"),
        ("","","Sierabysera","Instagram","","@sierabysera","","new"),
        ("","","THREEP","Instagram","","@threep.co","","new"),
        ("","","Trikul","Instagram","","@trikul.official","","new"),
        ("","","WEEKEND WARDROBE","Instagram","","@weekendwardrobe.rb","","new"),
        ("","","Embroiderer","Instagram","","Bag | @embroidererbangkok","","new"),
        ("","","KLOVES","Instagram","","Jewelry | @kloves_jewelry","","new"),
    ]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            """INSERT INTO leads (contact_date, contact_name, brand, channel, shoot_date, notes, email, status)
               VALUES (?,?,?,?,?,?,?,?)""",
            seed,
        )
        await db.commit()

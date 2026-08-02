import aiosqlite
import os

DB_PATH = "pana.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,          -- 'facebook', 'instagram', 'line'
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,              -- 'customer' | 'assistant'
                message TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pending_approvals (
                id TEXT PRIMARY KEY,             -- secure token
                approval_type TEXT NOT NULL,     -- 'reply' | 'post'
                platform TEXT,
                user_id TEXT,
                customer_message TEXT,
                ai_reply TEXT,
                status TEXT DEFAULT 'pending',   -- 'pending' | 'approved' | 'rejected' | 'edited'
                final_reply TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME
            );

            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id TEXT PRIMARY KEY,
                approval_id TEXT,
                caption TEXT NOT NULL,
                image_path TEXT,
                platforms TEXT NOT NULL,         -- JSON list: ["facebook","instagram","line"]
                scheduled_at DATETIME NOT NULL,
                status TEXT DEFAULT 'pending_approval',  -- 'pending_approval' | 'approved' | 'posted' | 'rejected'
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
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

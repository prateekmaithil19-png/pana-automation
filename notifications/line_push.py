"""Shared Line push-message helper.

Previously duplicated as a local `_send_line_push` in handlers/line_handler.py,
approval/router.py, and scheduler/followup_scheduler.py — consolidated here
since a fourth call site (handlers/form_handler.py) made the duplication worth
fixing.
"""

import httpx

import config

_LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


async def send_line_push(user_id: str, text: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _LINE_PUSH_URL,
            headers={"Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}"},
            json={"to": user_id, "messages": [{"type": "text", "text": text}]},
            timeout=10,
        )
        resp.raise_for_status()

"""
Customer Memory Module
Builds a context summary from a customer's conversation history so the AI
remembers what was discussed and doesn't ask the same questions twice.
"""

from database.db import get_conversation


async def build_customer_context(platform: str, user_id: str) -> str:
    """
    Reads the customer's conversation history and returns a memory summary
    that gets prepended to the system prompt so the AI has context.
    """
    history = await get_conversation(platform, user_id)
    if not history:
        return ""

    # Extract key facts mentioned by the customer
    customer_messages = [
        turn["content"]
        for turn in history
        if turn.get("role") in ("customer", "user")
    ]

    if not customer_messages:
        return ""

    # Build a concise summary of what we already know
    conversation_text = "\n".join(
        f"- {msg}" for msg in customer_messages[-10:]  # last 10 customer messages
    )

    return f"""
## What this customer has already told us (conversation memory)
Do NOT ask for information they already provided. Use this context to give smarter replies.

{conversation_text}

Based on the above, you already know their product type, requirements, and preferences.
Reference this when replying — do not ask the same questions again.
"""

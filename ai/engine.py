import anthropic
import config
from ai.prompts import build_system_prompt

_client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)


async def generate_reply(
    customer_message: str,
    conversation_history: list[dict],
    system_prompt: str | None = None,
    max_tokens: int = 512,
) -> str:
    if system_prompt is None:
        system_prompt = build_system_prompt()

    messages = []
    for turn in conversation_history:
        role = "user" if turn["role"] == "customer" else "assistant"
        messages.append({"role": role, "content": turn["content"]})
    messages.append({"role": "user", "content": customer_message})

    response = await _client.messages.create(
        model="claude-sonnet-5",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text.strip()

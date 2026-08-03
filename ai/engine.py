import logging
import re
import httpx

from google import genai
from google.genai import types
import config
from ai.prompts import build_system_prompt

logger = logging.getLogger(__name__)

_THINKING_RE = re.compile(
    r"(\*\*Drafting Options.*?\*\*|"
    r"\*\*Internal Monologue.*?\*\*|"
    r"Draft \d+:.*?(?=Draft \d+:|$)|"
    r"\(Internal Monologue.*?\))",
    re.DOTALL | re.IGNORECASE,
)


def _clean_reply(text: str) -> str:
    cleaned = _THINKING_RE.sub("", text)
    return cleaned.strip()


def _format_openai_messages(customer_message: str, conversation_history: list[dict], system_prompt: str) -> list[dict]:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for turn in conversation_history:
        role = "user" if turn.get("role") in ("customer", "user") else "assistant"
        messages.append({"role": role, "content": turn.get("content", "")})
    messages.append({"role": "user", "content": customer_message})
    return messages


def _format_claude_messages(customer_message: str, conversation_history: list[dict]) -> list[dict]:
    messages = []
    for turn in conversation_history:
        role = "user" if turn.get("role") in ("customer", "user") else "assistant"
        content = turn.get("content", "")
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += f"\n{content}"
        else:
            messages.append({"role": role, "content": content})

    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += f"\n{customer_message}"
    else:
        messages.append({"role": "user", "content": customer_message})
    return messages


async def _call_gemini(
    customer_message: str,
    conversation_history: list[dict],
    system_prompt: str,
    max_tokens: int,
) -> str:
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is missing or empty")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    contents = []
    for turn in conversation_history:
        role = "user" if turn.get("role") in ("customer", "user") else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=turn.get("content", ""))]))
    contents.append(types.Content(role="user", parts=[types.Part(text=customer_message)]))

    safety = [
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
        ),
    ]

    response = await client.aio.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
            safety_settings=safety,
        ),
    )
    return response.text or ""


async def _call_pateway(
    customer_message: str,
    conversation_history: list[dict],
    system_prompt: str,
    max_tokens: int,
) -> str:
    if not config.PATEWAY_API_KEY:
        raise ValueError("PATEWAY_API_KEY is missing or empty")

    base_url = config.PATEWAY_BASE_URL.rstrip("/")
    url = f"{base_url}/chat/completions"
    messages = _format_openai_messages(customer_message, conversation_history, system_prompt)

    payload = {
        "model": config.PATEWAY_MODEL,
        "messages": messages,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {config.PATEWAY_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""


async def _call_openai(
    customer_message: str,
    conversation_history: list[dict],
    system_prompt: str,
    max_tokens: int,
) -> str:
    if not config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is missing or empty")

    url = "https://api.openai.com/v1/chat/completions"
    messages = _format_openai_messages(customer_message, conversation_history, system_prompt)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.OPENAI_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""


async def _call_claude(
    customer_message: str,
    conversation_history: list[dict],
    system_prompt: str,
    max_tokens: int,
) -> str:
    if not config.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is missing or empty")

    url = "https://api.anthropic.com/v1/messages"
    messages = _format_claude_messages(customer_message, conversation_history)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={
                "x-api-key": config.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": config.ANTHROPIC_MODEL,
                "system": system_prompt,
                "messages": messages,
                "max_tokens": max_tokens,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("content", [{}])[0].get("text", "") or ""


async def generate_reply(
    customer_message: str,
    conversation_history: list[dict],
    system_prompt: str | None = None,
    max_tokens: int = 800,
) -> str:
    if system_prompt is None:
        system_prompt = build_system_prompt()

    providers = [p.strip().lower() for p in config.LLM_PROVIDERS.split(",") if p.strip()]

    provider_map = {
        "gemini": _call_gemini,
        "pateway": _call_pateway,
        "openai": _call_openai,
        "claude": _call_claude,
    }

    for provider in providers:
        fn = provider_map.get(provider)
        if not fn:
            continue
        try:
            logger.info("Attempting LLM generation with provider: %s", provider)
            raw_reply = await fn(customer_message, conversation_history, system_prompt, max_tokens)
            if raw_reply and raw_reply.strip():
                return _clean_reply(raw_reply)
        except Exception as e:
            logger.warning("LLM provider '%s' failed: %s", provider, e)

    logger.error("All configured LLM providers failed or returned empty response.")
    return "ขอบคุณที่สอบถามนะคะ 🙏 ทางเราจะติดต่อกลับเร็วๆ นี้ค่ะ"

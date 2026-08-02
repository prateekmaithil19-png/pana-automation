import re

from google import genai
from google.genai import types
import config
from ai.prompts import build_system_prompt

_client = genai.Client(api_key=config.GEMINI_API_KEY)
_MODEL = "gemini-flash-latest"

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


async def generate_reply(
    customer_message: str,
    conversation_history: list[dict],
    system_prompt: str | None = None,
    max_tokens: int = 512,
) -> str:
    if system_prompt is None:
        system_prompt = build_system_prompt()

    contents = []
    for turn in conversation_history:
        role = "user" if turn["role"] == "customer" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=turn["content"])]))
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

    response = await _client.aio.models.generate_content(
        model=_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
            safety_settings=safety,
        ),
    )

    text = response.text
    if not text:
        return "ขอบคุณที่สอบถามนะคะ 🙏 ทางเราจะติดต่อกลับเร็วๆ นี้ค่ะ"
    return _clean_reply(text)

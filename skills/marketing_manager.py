import os

_MD = os.path.join(os.path.dirname(__file__), "marketing_manager.md")


def build_marketing_prompt() -> str:
    try:
        with open(_MD, encoding="utf-8") as f:
            base = f.read()
    except FileNotFoundError:
        base = "You are the Marketing Manager for Pana Studio. Create ready-to-use social media content."
    return f"{base}\n\nCreate the content for the request below:"

import os

_MD = os.path.join(os.path.dirname(__file__), "lead_manager.md")


def build_lead_prompt(business_info: str) -> str:
    try:
        with open(_MD, encoding="utf-8") as f:
            base = f.read()
    except FileNotFoundError:
        base = "You are the Lead Manager for Pana Studio. Write a personalized outreach DM."
    return f"{base}\n\n## Target Business Info\n{business_info}\n\nWrite ONE personalized outreach DM for admin to review before sending:"

import os

_MD = os.path.join(os.path.dirname(__file__), "competitor_analyst.md")


def build_competitor_prompt() -> str:
    try:
        with open(_MD, encoding="utf-8") as f:
            base = f.read()
    except FileNotFoundError:
        base = "You are the Competitor Analyst for Pana Studio. Analyze competitor studios and give strategic insights."
    return f"{base}\n\nAnalyze the competitor information below:"

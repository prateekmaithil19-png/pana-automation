import os

_MD = os.path.join(os.path.dirname(__file__), "sales_manager.md")


def build_sales_prompt() -> str:
    try:
        with open(_MD, encoding="utf-8") as f:
            base = f.read()
    except FileNotFoundError:
        base = "You are the Sales Manager for Pana Studio. Help close the booking."
    return f"{base}\n\nRead the customer conversation below and write the ideal next reply to move toward a booking:"

import re

# Thai and English keywords that indicate a pricing/quotation request
_PRICE_KEYWORDS = [
    # Thai
    "ราคา", "เท่าไหร่", "เท่าไร", "ค่าใช้จ่าย", "ค่าบริการ", "แพ็กเกจ",
    "โปรโมชั่น", "โปร", "งบประมาณ", "งบ", "ใบเสนอราคา", "ราคาเท่า",
    "คิดเท่าไหร่", "คิดราคา", "จ่ายเท่าไหร่",
    # English
    "price", "pricing", "cost", "how much", "budget", "quote",
    "quotation", "package", "promotion", "rate", "fee", "charge",
]

_PRICE_RE = re.compile(
    "|".join(re.escape(k) for k in _PRICE_KEYWORDS),
    re.IGNORECASE,
)


def is_pricing_request(message: str) -> bool:
    return bool(_PRICE_RE.search(message))


def detect_language(message: str) -> str:
    thai_chars = sum(1 for c in message if "฀" <= c <= "๿")
    return "th" if thai_chars > 0 else "en"

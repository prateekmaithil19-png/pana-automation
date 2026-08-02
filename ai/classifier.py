import re

# Only trigger admin approval for custom project quotes — NOT for standard FAQ prices
_QUOTE_KEYWORDS = [
    # Thai — explicit custom quotation requests
    "ใบเสนอราคา", "เสนอราคา", "คิดราคา", "ราคางาน", "ค่าถ่ายทั้งหมด",
    "ราคาทั้งหมด", "จ่ายทั้งหมด", "งบทั้งหมด", "ราคาแพ็กเกจ",
    "ราคาเท่าไหร่สำหรับ", "คิดเท่าไหร่สำหรับ", "ค่าใช้จ่ายทั้งหมด",
    # English — explicit custom quotation requests
    "quotation", "send me a quote", "prepare a quote", "send quote",
    "how much for the shoot", "how much for my", "how much would it cost",
    "total price", "total cost", "how much to book", "overall price",
    "full package price", "price for my project",
]

# Phrases that look like price questions but are actually about features/specs
_NOT_PRICE_PATTERNS = re.compile(
    r"how (much|long|many) (time|duration|days|weeks|hours|percent|advance|pieces|looks|clips|photos|images|pictures)|"
    r"how long (is|are|does|will)|"
    r"how many (days|weeks|photos|images|clips|looks|pieces)",
    re.IGNORECASE,
)

_QUOTE_RE = re.compile(
    "|".join(re.escape(k) for k in _QUOTE_KEYWORDS),
    re.IGNORECASE,
)


def is_pricing_request(message: str) -> bool:
    # First exclude questions about duration/count that aren't pricing
    if _NOT_PRICE_PATTERNS.search(message):
        return False
    return bool(_QUOTE_RE.search(message))


def detect_language(message: str) -> str:
    thai_chars = sum(1 for c in message if "฀" <= c <= "๿")
    return "th" if thai_chars > 0 else "en"

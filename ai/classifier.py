import re

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

# Signals in conversation history that indicate a custom project (not standard FAQ)
_CUSTOM_PROJECT_SIGNALS = re.compile(
    r"moodboard|reference|concept|theme|individual brand|แบรนด์เดี่ยว|เฉพาะแบรนด์|"
    r"outdoor|beach|location|full.?day|half.?day|งบประมาณ|งบ|custom|bespoke",
    re.IGNORECASE,
)

# Vague price question that only becomes a quote request with custom project context
_VAGUE_PRICE_RE = re.compile(
    r"ราคา|เท่าไหร่|cost|price|how much|budget|งบ",
    re.IGNORECASE,
)

# Escalation signals — frustrated customer or no response
_ESCALATION_PATTERNS = re.compile(
    r"ทำไมไม่ตอบ|ตอบช้า|รอนานมาก|ไม่มีคนตอบ|ติดต่อไม่ได้|"
    r"no one is reply|nobody reply|why no response|not responding|still waiting|"
    r"เสียเวลา|ไม่พอใจ|แย่มาก|บริการแย่|"
    r"urgent|urgently|asap|ด่วน|ด่วนมาก",
    re.IGNORECASE,
)

# Explicit requests to be connected with a human/Dean — distinct from general
# "are you a bot?" curiosity (that's _CONFIDENTIALITY_PROBE_PATTERNS below, which
# doesn't need a full handoff, just an honest answer). This is a customer
# actively asking to be routed to a person, so it should stop AI auto-replies
# for that conversation until admin (or the follow-up timeout) resumes it.
_HUMAN_HANDOFF_PATTERNS = re.compile(
    r"talk to (a )?(human|person|dean|admin|someone|real person|staff)|"
    r"speak (to|with) (a )?(human|person|dean|admin|someone|real person|staff)|"
    r"connect me (with|to) (dean|admin|a human|someone|your team)|"
    r"can i (talk|speak) to dean|"
    r"i want to (talk|speak|connect) (to|with) (a )?human|"
    r"ขอคุยกับ(ดีน|แอดมิน|คนจริง|คนจริงๆ|มนุษย์|ทีมงาน)|"
    r"อยากคุยกับ(ดีน|แอดมิน|คนจริง|คนจริงๆ|มนุษย์|ทีมงาน)|"
    r"ติดต่อ(ดีน|แอดมิน)โดยตรง|"
    r"ขอเบอร์(ดีน|แอดมิน)|ต่อสาย(ดีน|แอดมิน)",
    re.IGNORECASE,
)


def is_pricing_request(message: str, conversation_history: list[dict] | None = None) -> bool:
    if _NOT_PRICE_PATTERNS.search(message):
        return False
    if _QUOTE_RE.search(message):
        return True
    # Vague price question + custom project context in history = treat as quote request
    if conversation_history and _VAGUE_PRICE_RE.search(message):
        recent_customer_text = " ".join(
            t.get("content", "")
            for t in conversation_history[-6:]
            if t.get("role") in ("customer", "user")
        )
        if _CUSTOM_PROJECT_SIGNALS.search(recent_customer_text):
            return True
    return False


def is_escalation_needed(message: str, conversation_history: list[dict] | None = None) -> bool:
    if _ESCALATION_PATTERNS.search(message):
        return True
    # 3+ consecutive unanswered customer messages = needs attention
    if conversation_history and len(conversation_history) >= 3:
        last_roles = [t.get("role") for t in conversation_history[-4:]]
        streak = 0
        for role in reversed(last_roles):
            if role in ("customer", "user"):
                streak += 1
            else:
                break
        if streak >= 3:
            return True
    return False


def is_human_handoff_request(message: str) -> bool:
    """True if the customer is explicitly asking to be connected with a human/Dean."""
    return bool(_HUMAN_HANDOFF_PATTERNS.search(message))


_CONFIDENTIALITY_PROBE_PATTERNS = re.compile(
    # Internal cost probing (English)
    r"pay (the )?model|pay (the )?photographer|pay (the )?studio|"
    r"how much (do you|does it) cost you|your cost|your expense|your margin|profit margin|"
    r"profit (per|on|from)|markup|cost per look|internal (cost|price|rate)|"
    r"how much (do you|you) make|your revenue|your income|annual (revenue|income)|"
    r"monthly (revenue|income|profit)|"
    # Financial health probing (English)
    r"profitable|making (money|profit|loss)|losing money|financial(ly)?|"
    r"how much (is the|does the) business|business (performance|health)|"
    # Other clients probing (English)
    r"who else (is|are) (shooting|booking|coming)|other (brand|client|customer)s?|"
    r"how many (brand|client|customer)s? (per|a|each) (day|month|session|shoot)|"
    r"who (else )?shoot(s|ing)? (with|together|same day)|"
    # Tech/system probing (English)
    r"are you (an? )?(ai|bot|robot|automated|chatbot|gpt|chatgpt|claude|gemini)|"
    r"(using|use) (ai|chatgpt|gpt|claude|gemini|openai)|"
    r"is this (automated|a bot|ai)|"
    r"who (is |are )?(really |actually )?respond(ing)?|"
    r"(real|human|actual) (person|human|staff|admin)|"
    # Vendor probing (English)
    r"which studio (do you|you) (rent|use)|studio (rate|cost|price) for you|"
    r"photographer (name|who|rate|fee)|who (is|are) (your|the) photographer|"
    # Thai language probing
    r"จ่าย(ค่า)?(นางแบบ|ช่างภาพ|สตูดิโอ)|"
    r"ต้นทุน|กำไร(เท่าไหร่|ต่อ|กี่)|ขาดทุน|รายได้|รายรับ|"
    r"แบรนด์อื่น|ลูกค้าคนอื่น|ใครถ่ายด้วย|มีกี่แบรนด์|"
    r"เป็น\s*(AI|บอท|ระบบอัตโนมัติ|โปรแกรม)|ใช้\s*AI|"
    r"คุยกับ(คน|มนุษย์)จริงๆ|มีคนจริงๆ|ระบบอัตโนมัติ",
    re.IGNORECASE,
)


def is_confidentiality_probe(message: str) -> bool:
    """Detects if a customer message is probing for internal/confidential business info."""
    return bool(_CONFIDENTIALITY_PROBE_PATTERNS.search(message))


def detect_language(message: str) -> str:
    """Detect whether a message is primarily Thai or English.

    Defaults to 'th' for empty/ambiguous messages — this is a Thai business
    and the majority of customers write Thai. Only switches to 'en' when the
    message actually contains real English content — a message with no Thai
    AND no meaningful Latin-alphabet content (a number, an emoji, ".", a
    single stray character) previously fell through to 'en' purely because
    the Thai ratio was 0, which would incorrectly flip a Thai conversation to
    English mid-chat. Now that case stays 'th' instead.
    """
    if not message or not message.strip():
        return "th"
    # Thai Unicode block: U+0E00–U+0E7F
    thai_chars = sum(1 for c in message if "฀" <= c <= "๿")
    if thai_chars > 0:
        ratio = thai_chars / len(message)
        if ratio > 0.15:
            return "th"
    # No (or too little) Thai — only call it English if there's real Latin
    # alphabetic content to back that up, not just digits/punctuation/emoji.
    latin_letters = sum(1 for c in message if c.isascii() and c.isalpha())
    return "en" if latin_letters >= 2 else "th"

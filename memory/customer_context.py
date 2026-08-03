import re
from database.db import get_conversation

_SHOOT_TYPE_MULTIBRAND = re.compile(
    r"one stop|multibrand|multi.?brand|แชร์แบรนด์|one-stop|sharing|"
    r"หลายแบรนด์|ร่วมกัน|ราคาถูก|ประหยัด",
    re.IGNORECASE,
)
_SHOOT_TYPE_INDIVIDUAL = re.compile(
    r"individual|เดี่ยว|เฉพาะแบรนด์|custom|exclusive|แบรนด์เดียว|"
    r"moodboard|concept|half.?day|full.?day|23,000|19,500",
    re.IGNORECASE,
)
_LOOK_COUNT = re.compile(r"(\d+)\s*(ลุค|look|looks)", re.IGNORECASE)
_PRODUCT_TYPE = re.compile(
    r"(เสื้อผ้า|fashion|clothes|clothing|dress|กระเป๋า|bag|shoes|รองเท้า|"
    r"ลิป|lip|เครื่องสำอาง|makeup|สกินแคร์|skincare|ครีม|อาหารเสริม|supplement|"
    r"ว่ายน้ำ|swimwear|lingerie|ชุดชั้นใน|jewelry|เครื่องประดับ|accessories)",
    re.IGNORECASE,
)
_DATE_PATTERN = re.compile(
    r"\d{1,2}[/\-\.]\d{1,2}(?:[/\-\.]\d{2,4})?|"
    r"วันที่\s*\d+\s*\w+|"
    r"(มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|"
    r"กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม)|"
    r"(january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s*\d{0,4}",
    re.IGNORECASE,
)


async def build_customer_context(platform: str, user_id: str) -> str:
    history = await get_conversation(platform, user_id)
    if not history:
        return ""

    customer_messages = [
        t["content"] for t in history if t.get("role") in ("customer", "user")
    ]
    if not customer_messages:
        return ""

    combined = " ".join(customer_messages[-10:])
    facts = []

    # Shoot type
    if _SHOOT_TYPE_MULTIBRAND.search(combined):
        facts.append("shoot_type = One Stop Service (multibrand/shared)")
    elif _SHOOT_TYPE_INDIVIDUAL.search(combined):
        facts.append("shoot_type = Individual Brand Shoot (custom/exclusive)")

    # Number of looks
    look_match = _LOOK_COUNT.search(combined)
    if look_match:
        facts.append(f"num_looks = {look_match.group(1)}")

    # Product types mentioned
    product_matches = list({m.group(0).lower() for m in _PRODUCT_TYPE.finditer(combined)})
    if product_matches:
        facts.append(f"product_type = {', '.join(product_matches[:3])}")

    # Dates mentioned
    date_matches = _DATE_PATTERN.findall(combined)
    flat_dates = [d if isinstance(d, str) else next((x for x in d if x), "") for d in date_matches]
    flat_dates = [d for d in flat_dates if d]
    if flat_dates:
        facts.append(f"dates_mentioned = {', '.join(flat_dates[:3])}")

    if not facts:
        # No structured facts found — pass recent raw messages as fallback
        recent_raw = "\n".join(f"- {m}" for m in customer_messages[-5:])
        return f"""
## Customer conversation memory
{recent_raw}

Do NOT ask for information already mentioned above.
"""

    facts_text = "\n".join(f"- {f}" for f in facts)
    return f"""
## What we already know about this customer
{facts_text}

Do NOT re-ask for any information listed above. Reference these facts in your reply.
"""

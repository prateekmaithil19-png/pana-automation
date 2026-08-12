import re
from database.db import get_conversation, get_customer_state, upsert_customer_state

# Name extraction — Thai: "ชื่อ X" / "เรียก X" | English: "I'm X", "my name is X", "call me X"
_NAME_PATTERNS = [
    re.compile(r"ชื่อ\s*([ก-๙a-zA-Z]{2,20})", re.IGNORECASE),
    re.compile(r"เรียก\s*([ก-๙a-zA-Z]{2,20})\s*(?:ได้|นะ|ว่า|เลย)", re.IGNORECASE),
    re.compile(r"(?:I'm|I am|my name is|this is|call me|name(?:'s| is))\s+([A-Z][a-z]{1,19})", re.IGNORECASE),
]
# Thai sentence-ending particles that may get attached to a captured name
_THAI_PARTICLES = re.compile(r"(?:นะคะ|นะครับ|ค่ะ|คะ|ครับ|นะ|ค่)$")

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
# Fallback for branded/novel product names the keyword whitelist above won't catch
# (e.g. "My product is Face Glow" — "Face Glow" isn't a generic category word).
# Only used when _PRODUCT_TYPE finds nothing, so it doesn't override a clean category match.
_PRODUCT_DECLARATION = re.compile(
    r"(?:(?:my|our)\s+product\s+is|product\s+(?:name\s+)?is|"
    r"สินค้าคือ|สินค้าของ(?:เรา|ผม|ฉัน)คือ|แบรนด์คือ|ชื่อแบรนด์คือ)"
    r"\s+([A-Za-zก-๙][\w ก-๙]{1,30}?)(?:[.,!?\n]|$)",
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

_STAGE_GUIDANCE = {
    "new": "New customer. Greet warmly and find out what they need.",
    "service_inquiry": "Customer is exploring services. Find out: are they interested in One Stop Service (multibrand) or Individual Brand Shoot?",
    "shoot_type_known": "Shoot type is known (see below). Collect what's still missing — see checklist below.",
    "collecting": "Requirements being gathered. See the checklist below — ONLY ask about fields marked ❌. Do NOT re-ask anything marked ✅.",
    "quote_requested": "This customer's quote has already been sent to admin. If they ask for an update, say the team is preparing it.",
    "cold": "Customer was previously unresponsive to follow-ups. Re-engage warmly but do not push.",
    "booked": "Customer has confirmed a booking. Focus on pre-shoot preparation and logistics.",
}

# Fields required before a quote can be prepared, in priority order
_REQUIRED_FIELDS = [
    ("shoot_type", "Shoot type (One Stop Service or Individual Brand Shoot)"),
    ("product_type", "Product type"),
    ("num_looks", "Number of looks"),
    ("preferred_date", "Preferred date / timing"),
]


def _extract_facts(messages: list[str]) -> dict:
    combined = " ".join(messages[-10:])
    facts = {}

    # Name — scan all messages individually to catch introductions
    for msg in messages[-10:]:
        for pattern in _NAME_PATTERNS:
            m = pattern.search(msg)
            if m:
                name = _THAI_PARTICLES.sub("", m.group(1)).strip()
                if len(name) >= 2:
                    facts["customer_name"] = name
                    break
        if "customer_name" in facts:
            break

    if _SHOOT_TYPE_MULTIBRAND.search(combined):
        facts["shoot_type"] = "One Stop Service (multibrand/shared)"
    elif _SHOOT_TYPE_INDIVIDUAL.search(combined):
        facts["shoot_type"] = "Individual Brand Shoot (custom/exclusive)"

    look_match = _LOOK_COUNT.search(combined)
    if look_match:
        facts["num_looks"] = look_match.group(1)

    product_matches = list({m.group(0).lower() for m in _PRODUCT_TYPE.finditer(combined)})
    if product_matches:
        facts["product_type"] = ", ".join(product_matches[:3])
    else:
        decl_match = _PRODUCT_DECLARATION.search(combined)
        if decl_match:
            facts["product_type"] = decl_match.group(1).strip()

    date_matches = _DATE_PATTERN.findall(combined)
    flat = [d if isinstance(d, str) else next((x for x in d if x), "") for d in date_matches]
    flat = [d for d in flat if d]
    if flat:
        facts["preferred_date"] = ", ".join(flat[:3])

    return facts


def _determine_stage(persisted_stage: str, facts: dict, num_customer_turns: int) -> str:
    # Never downgrade terminal stages
    if persisted_stage in ("quote_requested", "cold", "booked"):
        return persisted_stage

    if num_customer_turns == 0:
        return "new"

    shoot_type = facts.get("shoot_type")
    detail_count = sum(1 for k in ("num_looks", "product_type", "preferred_date") if facts.get(k))

    if shoot_type and detail_count >= 1:
        return "collecting"
    if shoot_type:
        return "shoot_type_known"
    return "service_inquiry"


async def update_customer_state(
    platform: str,
    user_id: str,
    history: list[dict],
    force_stage: str | None = None,
):
    """Extract facts from history and persist to customer_state table."""
    customer_messages = [t["content"] for t in history if t.get("role") in ("customer", "user")]
    facts = _extract_facts(customer_messages) if customer_messages else {}

    current = await get_customer_state(platform, user_id)
    persisted_stage = current.get("stage", "new") if current else "new"

    stage = force_stage if force_stage else _determine_stage(persisted_stage, facts, len(customer_messages))

    update_fields: dict = {"stage": stage, "follow_up_count": 0}
    for key in ("shoot_type", "num_looks", "product_type", "preferred_date", "customer_name"):
        if facts.get(key):
            update_fields[key] = facts[key]

    await upsert_customer_state(platform, user_id, **update_fields)


async def build_customer_context(platform: str, user_id: str) -> str:
    """Build the context block injected into the system prompt."""
    history = await get_conversation(platform, user_id)
    state = await get_customer_state(platform, user_id)

    customer_messages = [t["content"] for t in history if t.get("role") in ("customer", "user")]
    fresh_facts = _extract_facts(customer_messages) if customer_messages else {}

    # Merge: DB state is the source of truth; fresh extraction adds anything new
    merged: dict = {}
    if state:
        for k in ("shoot_type", "num_looks", "product_type", "preferred_date", "customer_name"):
            if state.get(k):
                merged[k] = state[k]
    for k, v in fresh_facts.items():
        if v:
            merged[k] = v  # fresh message wins if it adds new info

    stage = state.get("stage", "new") if state else "new"

    if not merged and not history:
        return ""

    lines = []

    # Name instruction — at the very top so agent sees it first
    customer_name = merged.pop("customer_name", None)
    if customer_name:
        lines.append(f"## Customer Name: {customer_name}")
        lines.append(f"Address this customer as {customer_name} occasionally (not every message — once or twice naturally).")
        lines.append("")

    # Stage header — tells the agent exactly where it is in the funnel
    lines.append(f"## Conversation Stage: {stage.upper()}")
    guidance = _STAGE_GUIDANCE.get(stage, "")
    if guidance:
        lines.append(f"Agent guidance: {guidance}")

    # Build an explicit checklist so the AI knows exactly what's done and what's next
    if stage in ("shoot_type_known", "collecting", "service_inquiry") or merged:
        lines.append("")
        lines.append("## Requirements checklist")
        missing: list[str] = []
        for key, label in _REQUIRED_FIELDS:
            value = merged.get(key)
            if value:
                lines.append(f"- ✅ {label}: {value}")
            else:
                lines.append(f"- ❌ {label}: not yet collected")
                missing.append(label)

        if missing:
            # Tell the AI which single field to ask about next (highest priority missing)
            lines.append("")
            lines.append(f"→ Ask about next (ONE question only): **{missing[0]}**")
        else:
            lines.append("")
            lines.append("→ All requirements collected. You may offer to prepare a quotation.")

    elif customer_messages:
        lines.append("")
        lines.append("## Recent customer messages (for context)")
        for m in customer_messages[-5:]:
            lines.append(f"- {m}")

    return "\n".join(lines)

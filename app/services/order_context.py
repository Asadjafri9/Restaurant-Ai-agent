"""Extract and track name, address, and items from voice/text order messages."""

import re

from app.services.voice_text import ADDRESS_MARKERS, normalize_transcript, normalize_user_text, is_thank_you_message

NAME_PATTERNS = (
    re.compile(r"mera naam\s+([a-zA-Z]+)\s+hai", re.I),
    re.compile(r"mera name\s+([a-zA-Z]+)\s+hai", re.I),
    re.compile(r"naam\s+([a-zA-Z]+)\s+hai", re.I),
    re.compile(r"my name is\s+([a-zA-Z]+)", re.I),
    re.compile(r"name is\s+([a-zA-Z]+)", re.I),
    re.compile(r"i am\s+([a-zA-Z]+)", re.I),
    re.compile(r"main\s+([a-zA-Z]+)\s+hoon", re.I),
)

ADDRESS_PATTERNS = (
    re.compile(r"(block\s+[a-z0-9]+(?:\s+[a-z0-9]+)?)", re.I),
    re.compile(r"address\s+(?:hai|is)\s+(.+)", re.I),
    re.compile(r"(?:mera|my)\s+address\s+(?:hai|is)\s+(.+)", re.I),
    re.compile(r"(phase\s+\d+(?:\s+\w+)?)", re.I),
    re.compile(r"(sector\s+[a-z0-9-]+)", re.I),
    re.compile(r"(house\s+(?:no\s*)?[a-z0-9-]+)", re.I),
)

DONE_ADDING_PHRASES = (
    "nahi bas",
    "bas itna",
    "itna hi",
    "bus itna",
    "nothing else",
    "no more",
    "bas yehi",
    "nahi aur",
    "that's all",
    "that is all",
    "sirf itna",
    "itna hi kardo",
    "itna hi kar do",
    "bas itna hi",
    "nahi bas itna",
    "nahi karna",
    "nahi order karna",
    "nahi chahiye",
    "kuch aur nahi",
    "kuch or nahi",
    "aur nahi",
    "bas hai",
    "nahi aur kuch",
)

MORE_ITEMS_ASK_MARKERS = (
    "kuch aur",
    "kuch or",
    "aur order",
    "or order",
    "anything else",
    "more order",
    "aur kuch",
    "kya order",
    "order karna chahte",
    "order karna hai",
    "kuch order",
)

# Whisper often mishears Pakistani names — apply only when no explicit name pattern matched
_NAME_TRANSCRIPT_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bkareer\b", re.I), "Askari"),
    (re.compile(r"\bkarir\b", re.I), "Askari"),
    (re.compile(r"\baskari\b", re.I), "Askari"),
]

_ORDER_WORDS = frozenset(
    {
        "kfc",
        "kabab",
        "kababjees",
        "menu",
        "order",
        "cola",
        "zinger",
        "burger",
        "nahi",
        "yes",
        "han",
        "haan",
        "kardo",
        "chahiye",
        "confirm",
        "address",
        "naam",
        "name",
        "block",
    }
)

_ITEM_TOKEN_ALIASES = {
    "chkn": "chicken",
    "chiken": "chicken",
    "chk": "chicken",
    "briyani": "biryani",
    "biriyani": "biryani",
    "beriyani": "biryani",
}


def _normalize_item_tokens(name: str) -> str:
    words = normalize_user_text(name).split()
    return " ".join(_ITEM_TOKEN_ALIASES.get(w, w) for w in words)


def match_catalog_item(name: str, catalog: list[dict]) -> dict | None:
    """Fuzzy menu match — handles voice typos like chkn briyani → Chicken Biryani."""
    needle = _normalize_item_tokens(name)
    if not needle or not catalog:
        return None
    by_name = {i["name"].lower(): i for i in catalog}
    if needle in by_name:
        return by_name[needle]
    for key, item in by_name.items():
        norm_key = _normalize_item_tokens(key)
        if needle in norm_key or norm_key in needle:
            return item
    needle_tokens = set(needle.split())
    best: dict | None = None
    best_score = 0
    for key, item in by_name.items():
        key_tokens = set(_normalize_item_tokens(key).split())
        if not key_tokens:
            continue
        overlap = len(needle_tokens & key_tokens)
        min_len = min(len(needle_tokens), len(key_tokens))
        if overlap > 0 and overlap >= max(1, min_len - 1) and overlap > best_score:
            best_score = overlap
            best = item
    return best


def fix_name_transcript(text: str) -> str:
    t = text
    for pattern, repl in _NAME_TRANSCRIPT_FIXES:
        t = pattern.sub(repl, t)
    return t


def _title_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z\s'-]", "", name.strip())
    if not cleaned:
        return name.strip()
    return cleaned.title()


def extract_customer_name(text: str) -> str | None:
    """Explicit name phrases win over single-word guesses."""
    if is_thank_you_message(text):
        return None
    text = fix_name_transcript(text)
    for pattern in NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            return _title_name(match.group(1))
    normalized = normalize_user_text(text)
    words = [w for w in normalized.split() if w not in ("bhai", "ji", "jani")]
    if not words or len(words) > 3:
        return None
    if any(w in normalized for w in _ORDER_WORDS):
        return None
    if any(m in normalized for m in ADDRESS_MARKERS):
        return None
    return _title_name(words[0].upper() if len(words[0]) <= 3 else words[0].capitalize())


def _clean_address(addr: str) -> str:
    addr = addr.strip()
    addr = re.sub(r"\s+address\s*$", "", addr, flags=re.I).strip()
    if addr.lower().startswith("block"):
        return addr.title()
    return addr


def extract_address(text: str) -> str | None:
    text = normalize_transcript(text)
    for pattern in ADDRESS_PATTERNS:
        match = pattern.search(text)
        if match:
            addr = _clean_address(match.group(1))
            if len(addr) >= 3:
                return addr
    normalized = normalize_user_text(text)
    block = re.search(r"block\s+[a-z0-9]+", normalized)
    if block:
        return block.group(0).title()
    if any(m in normalized for m in ADDRESS_MARKERS):
        for marker in ("block", "phase", "sector", "house"):
            if marker in normalized:
                idx = normalized.find(marker)
                snippet = normalized[idx : idx + 40].strip()
                return _clean_address(snippet)
    return None


def extract_order_items(text: str, catalog: list[dict]) -> list[dict]:
    text = normalize_transcript(text)
    normalized = normalize_user_text(text)
    if not normalized or not catalog:
        return []
    found: list[dict] = []
    seen: set[str] = set()
    for cat in catalog:
        name = normalize_user_text(cat.get("name", ""))
        if not name:
            continue
        matched = name in normalized
        if not matched:
            tokens = [t for t in name.split() if len(t) > 2]
            matched = len(tokens) >= 2 and all(t in normalized for t in tokens)
        if not matched:
            matched = match_catalog_item(text, [cat]) is not None
        if matched:
            key = cat["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(
                {
                    "item": cat["name"],
                    "quantity": _extract_quantity(text, name),
                    "menu_item_id": cat.get("tenant_item_id"),
                    "unit_price": cat.get("price"),
                }
            )
    return found


def _extract_quantity(text: str, item_name: str) -> int:
    normalized = normalize_user_text(text)
    patterns = (
        rf"(\d+)\s+{re.escape(item_name)}",
        rf"{re.escape(item_name)}\s+x\s*(\d+)",
        r"\b(ek|aik|one)\b",
        r"\b(do|two|2)\b",
        r"\b(teen|three|3)\b",
    )
    for pat in patterns[:2]:
        m = re.search(pat, normalized)
        if m:
            return max(1, int(m.group(1)))
    if re.search(r"\b(ek|aik|one)\b", normalized):
        return 1
    if re.search(r"\b(do|two)\b", normalized):
        return 2
    return 1


def is_done_adding_items(text: str) -> bool:
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    return any(p in normalized for p in DONE_ADDING_PHRASES)


def bot_asked_for_more_items(last_bot_text: str) -> bool:
    lower = (last_bot_text or "").lower()
    return any(m in lower for m in MORE_ITEMS_ASK_MARKERS)


def is_declining_more_items(text: str, last_bot_text: str) -> bool:
    """Customer said no to adding more — not cancelling the whole order."""
    if not bot_asked_for_more_items(last_bot_text):
        return False
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    if is_done_adding_items(text):
        return True
    decline_starts = ("nahi", "na", "no", "nope", "bas")
    return normalized in decline_starts or normalized.split()[0] in decline_starts


def merge_pending_items(existing: list[dict], new_items: list[dict]) -> list[dict]:
    by_name = {i["item"].lower(): dict(i) for i in existing}
    for item in new_items:
        key = item["item"].lower()
        if key in by_name:
            by_name[key]["quantity"] = int(by_name[key].get("quantity", 1)) + int(item.get("quantity", 1))
            if item.get("menu_item_id"):
                by_name[key]["menu_item_id"] = item["menu_item_id"]
            if item.get("unit_price") is not None:
                by_name[key]["unit_price"] = item["unit_price"]
        else:
            by_name[key] = {
                "item": item["item"],
                "quantity": int(item.get("quantity", 1)),
                **({"menu_item_id": item["menu_item_id"]} if item.get("menu_item_id") else {}),
                **({"unit_price": item["unit_price"]} if item.get("unit_price") is not None else {}),
            }
    return list(by_name.values())


def pending_order_complete(session) -> bool:
    return bool(
        session.pending_items
        and session.pending_customer_name
        and session.pending_address
    )


def order_from_session(session) -> dict | None:
    if not pending_order_complete(session):
        return None
    return {
        "restaurant": session.active_tenant_slug or "",
        "customer_name": session.pending_customer_name,
        "address": session.pending_address,
        "items": list(session.pending_items),
    }


def format_order_summary(session, catalog: list[dict], lang: str) -> str:
    by_name = {c["name"].lower(): c for c in catalog}
    lines = []
    total = 0.0
    for pi in session.pending_items:
        cat = by_name.get(pi["item"].lower(), {})
        price = float(cat.get("price", 0))
        qty = int(pi.get("quantity", 1))
        line = price * qty
        total += line
        lines.append(f"{qty}x {pi['item']} — Rs {line:.0f}")
    items_text = "\n".join(lines)
    if lang == "roman_ur":
        return (
            f"Order summary:\n{items_text}\n"
            f"Naam: {session.pending_customer_name}\n"
            f"Address: {session.pending_address}\n"
            f"Total: Rs {total:.0f}\n\n"
            f"YES ya han kardo likhein confirm karne ke liye."
        )
    return (
        f"Order summary:\n{items_text}\n"
        f"Name: {session.pending_customer_name}\n"
        f"Address: {session.pending_address}\n"
        f"Total: Rs {total:.0f}\n\n"
        f"Reply YES or say han kardo to confirm."
    )


def update_pending_from_message(session, user_message: str, catalog: list[dict]) -> None:
    user_message = fix_name_transcript(user_message)
    name = extract_customer_name(user_message)
    if name:
        session.pending_customer_name = name
    address = extract_address(user_message)
    if address:
        session.pending_address = address
    new_items = extract_order_items(user_message, catalog)
    if new_items:
        session.pending_items = merge_pending_items(session.pending_items, new_items)


def clear_pending_order(session) -> None:
    session.pending_customer_name = None
    session.pending_address = None
    session.pending_items = []

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

ORDER_CORRECTION_MARKERS = (
    "wrong order",
    "order wrong",
    "galat order",
    "order galat",
    "wrong items",
    "galat hai",
    "sahi nahi",
    "not correct",
    "incorrect order",
    "you gave wrong",
    "order is wrong",
    "order s wrong",
    "mistake in order",
    "order mistake",
    "galat dia",
    "galat diya",
    "theek nahi",
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
    "fiz": "fizz",
}


def _normalize_item_tokens(name: str) -> str:
    words = normalize_user_text(name).split()
    return " ".join(_ITEM_TOKEN_ALIASES.get(w, w) for w in words)


_ITEM_SIZE_TOKENS = frozenset({"1", "2", "3", "4", "5", "6", "7", "8", "9", "pc", "pcs", "l", "half", "large"})
_GENERIC_FOOD_TOKENS = frozenset({"chicken", "burger", "piece", "hot", "beef", "roll", "fries", "kabab", "seekh"})


def _meaningful_tokens(text: str) -> set[str]:
    words = _normalize_item_tokens(text).split()
    return {w for w in words if w not in _ITEM_SIZE_TOKENS and len(w) > 2 and not w.isdigit()}


def _tokens_as_words(tokens: set[str], text: str) -> bool:
    return bool(tokens) and all(re.search(rf"\b{re.escape(t)}\b", text) for t in tokens)


def match_catalog_item(name: str, catalog: list[dict]) -> dict | None:
    """Fuzzy menu match — handles voice typos like chkn briyani → Chicken Biryani."""
    needle = _normalize_item_tokens(name)
    if not needle or not catalog:
        return None
    needle_tokens = _meaningful_tokens(needle)
    if not needle_tokens:
        return None
    by_name = {i["name"].lower(): i for i in catalog}
    if needle in by_name:
        return by_name[needle]
    for key, item in by_name.items():
        base = _catalog_base_name(item["name"])
        if base and re.search(rf"\b{re.escape(base)}\b", needle):
            return item
    best: dict | None = None
    best_score = 0
    for key, item in by_name.items():
        key_tokens = _meaningful_tokens(_catalog_base_name(item["name"]) or key)
        if not key_tokens:
            continue
        if key_tokens <= needle_tokens:
            return item
        overlap = len(needle_tokens & key_tokens)
        min_len = min(len(needle_tokens), len(key_tokens))
        if len(key_tokens) >= 2 and overlap < len(key_tokens):
            lone = len(needle_tokens) == 1 and overlap == 1
            token = next(iter(needle_tokens & key_tokens), "")
            if not (lone and token and token not in _GENERIC_FOOD_TOKENS):
                continue
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


def _catalog_base_name(name: str) -> str:
    """Strip size/count suffixes — 'Hot Wings (6 pcs)' → 'hot wings'."""
    stripped = re.sub(r"\([^)]*\)", "", name).strip()
    base = normalize_user_text(stripped)
    base = re.sub(r"\s+\d+\s*(pcs|pc|l)\b", "", base)
    return re.sub(r"\s+", " ", base).strip()


def _item_mentioned_in_text(normalized: str, cat_name: str, raw_text: str) -> bool:
    name = normalize_user_text(cat_name)
    base = _catalog_base_name(cat_name)
    if base and re.search(rf"\b{re.escape(base)}\b", normalized):
        return True
    if name != base and re.search(rf"\b{re.escape(name)}\b", normalized):
        return True
    base_tokens = _meaningful_tokens(base or name)
    if len(base_tokens) >= 2 and _tokens_as_words(base_tokens, normalized):
        return True
    if len(base_tokens) == 1 and _tokens_as_words(base_tokens, normalized):
        return True
    return match_catalog_item(raw_text, [{"name": cat_name}]) is not None


def is_order_correction_message(text: str) -> bool:
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    return any(m in normalized for m in ORDER_CORRECTION_MARKERS)


def _strip_correction_preamble(text: str) -> str:
    normalized = normalize_user_text(text)
    for marker in sorted(ORDER_CORRECTION_MARKERS, key=len, reverse=True):
        if marker in normalized:
            idx = normalized.find(marker)
            tail = text[idx + len(marker) :].strip(" .,;:-")
            if tail:
                return tail
    return text


def _split_order_segments(text: str) -> list[str]:
    """Split a multi-item order into per-item phrases (comma / and / aur)."""
    cleaned = _strip_correction_preamble(text)
    normalized = normalize_user_text(cleaned)
    if not normalized:
        return []
    parts = re.split(r"\s*,\s*|\s+and\s+|\s+aur\s+", normalized)
    return [p.strip() for p in parts if p.strip()]


def _best_segment_for_item(text: str, cat_name: str, segments: list[str]) -> str | None:
    raw = normalize_transcript(text)
    for seg in segments:
        seg_norm = normalize_user_text(seg)
        if _item_mentioned_in_text(seg_norm, cat_name, seg):
            return seg
    if not segments:
        whole = normalize_user_text(text)
        if _item_mentioned_in_text(whole, cat_name, raw):
            return text
    return None


def _quantity_from_segment(segment: str, base: str) -> int:
    seg = normalize_user_text(segment)
    patterns: list[str | None] = [
        rf"(\d+)\s+{re.escape(base)}",
        rf"(\d+)\s+{re.escape(base.split()[0])}" if base.split() else None,
        rf"{re.escape(base)}\s+x\s*(\d+)",
        r"^(\d+)\s+",
    ]
    for pat in patterns:
        if not pat:
            continue
        m = re.search(pat, seg)
        if m:
            return max(1, int(m.group(1)))
    if re.search(r"\b(teen|three|3)\b", seg):
        return 3
    if re.search(r"\b(do|two)\b", seg):
        return 2
    if re.search(r"\b(ek|aik|one)\b", seg):
        return 1
    return 1


def extract_order_items(text: str, catalog: list[dict]) -> list[dict]:
    text = normalize_transcript(text)
    normalized = normalize_user_text(text)
    if not normalized or not catalog:
        return []
    segments = _split_order_segments(text)
    found: list[dict] = []
    seen: set[str] = set()
    # Sort longest names first so "chicken piece" wins over bare "chicken".
    sorted_catalog = sorted(catalog, key=lambda c: len(c.get("name", "")), reverse=True)
    for cat in sorted_catalog:
        cat_name = cat.get("name", "")
        if not cat_name:
            continue
        segment = _best_segment_for_item(text, cat_name, segments)
        if not segment:
            continue
        key = cat_name.lower()
        if key in seen:
            continue
        seen.add(key)
        base = _catalog_base_name(cat_name)
        found.append(
            {
                "item": cat_name,
                "quantity": _extract_quantity(segment, base or normalize_user_text(cat_name)),
                "menu_item_id": cat.get("tenant_item_id"),
                "unit_price": cat.get("price"),
            }
        )
    return found


def _extract_quantity(text: str, item_name: str) -> int:
    return _quantity_from_segment(text, _catalog_base_name(item_name) or normalize_user_text(item_name))


def format_pending_items_list(items: list[dict]) -> str:
    if not items:
        return ""
    return "\n".join(f"{int(i.get('quantity', 1))}x {i.get('item', '')}" for i in items)


def pending_items_changed(before: list[dict], after: list[dict]) -> bool:
    def sig(items: list[dict]) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in items:
            key = (i.get("item") or "").lower()
            out[key] = out.get(key, 0) + int(i.get("quantity", 1))
        return out

    return sig(before) != sig(after)


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


def update_pending_from_message(session, user_message: str, catalog: list[dict], *, replace: bool = False) -> None:
    user_message = fix_name_transcript(user_message)
    name = extract_customer_name(user_message)
    if name:
        session.pending_customer_name = name
    address = extract_address(user_message)
    if address:
        session.pending_address = address
    new_items = extract_order_items(user_message, catalog)
    if new_items:
        if replace or is_order_correction_message(user_message):
            session.pending_items = new_items
        else:
            session.pending_items = merge_pending_items(session.pending_items, new_items)


def clear_pending_order(session) -> None:
    session.pending_customer_name = None
    session.pending_address = None
    session.pending_items = []


def detect_remove_intent(text: str, catalog: list[dict]) -> str | None:
    """Return the catalog item name the customer wants to remove, or None."""
    from app.services.voice_text import REMOVE_CUES, has_remove_cue, normalize_user_text

    if not text or not catalog:
        return None
    if not has_remove_cue(text):
        return None
    cleaned = text
    for cue in sorted(REMOVE_CUES, key=len, reverse=True):
        cleaned = re.sub(rf"\b{re.escape(cue)}\b", " ", cleaned, flags=re.I)
    cleaned = normalize_user_text(cleaned).strip()
    for filler in ("bhai", "ji", "please", "plz", "jani", "sir", "madam"):
        cleaned = re.sub(rf"\b{re.escape(filler)}\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    for item in catalog:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        if name.lower() in cleaned:
            return name
    sorted_catalog = sorted(catalog, key=lambda c: len(c.get("name", "")), reverse=True)
    for item in sorted_catalog:
        name = (item.get("name") or "").strip().lower()
        if not name:
            continue
        for token in name.split():
            if len(token) >= 4 and token in cleaned:
                return item["name"]
    best = match_catalog_item(cleaned, catalog)
    if best:
        return best["name"]
    return None


_QTY_PATTERNS = (
    re.compile(r"\b(\d+)\s+([a-zA-Z][a-zA-Z\s'-]{2,})", re.I),
    re.compile(r"([a-zA-Z][a-zA-Z\s'-]{2,})\s+(\d+)\s*(?:chahiye|order|kardo|kar do|karo|do)?", re.I),
)


def detect_set_qty_intent(text: str, catalog: list[dict]) -> tuple[str, int] | None:
    """Return (item_name, new_quantity) for a 'make that N' or 'N items' style intent.

    Conservative: only fires when the customer references a number AND a known menu item.
    Returns None otherwise.
    """
    from app.services.voice_text import normalize_user_text

    if not text or not catalog:
        return None
    lower = text.lower()
    nums = re.findall(r"\b\d+\b", lower)
    if not nums:
        return None
    qty = max(1, int(nums[0]))
    for item in catalog:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        if name.lower() in lower:
            return name, qty
    sorted_catalog = sorted(catalog, key=lambda c: len(c.get("name", "")), reverse=True)
    for item in sorted_catalog:
        name = (item.get("name") or "").strip().lower()
        if not name:
            continue
        for token in name.split():
            if len(token) < 4:
                continue
            if re.search(rf"\b\d+\b[^\d]{{0,8}}\b{re.escape(token)}\b", lower) or re.search(
                rf"\b{re.escape(token)}\b[^\d]{{0,8}}\b\d+\b", lower
            ):
                return item["name"], qty
    cleaned = normalize_user_text(text)
    nums2 = re.findall(r"\b\d+\b", cleaned)
    if not nums2:
        return None
    qty = max(1, int(nums2[0]))
    for item in sorted_catalog:
        name = (item.get("name") or "").strip().lower()
        if not name:
            continue
        for token in name.split():
            if len(token) < 4:
                continue
            if token in cleaned:
                return item["name"], qty
    return None


def apply_pending_edit(session, *, remove: str | None = None, set_qty: tuple[str, int] | None = None) -> None:
    """Mutate session.pending_items: remove a named item or set a new quantity for one item."""
    if remove:
        key = remove.lower()
        session.pending_items = [
            i for i in session.pending_items
            if (i.get("item") or "").lower() != key
        ]
    if set_qty:
        name, qty = set_qty
        key = name.lower()
        for i in session.pending_items:
            if (i.get("item") or "").lower() == key:
                i["quantity"] = max(1, int(qty))
                return
        # Not in cart yet — caller will need to add it
        session.pending_items.append({"item": name, "quantity": max(1, int(qty))})

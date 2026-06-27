"""Normalize voice transcripts and detect Roman Urdu ordering intents."""

import logging
import re

logger = logging.getLogger(__name__)

_NON_LATIN_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u0900-\u097F\u0980-\u09FF]")

# Common Whisper mis-hearings for Pakistani food orders (Roman Urdu + brand names)
_TRANSCRIPT_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bk\s*f\s*c\b", re.I), "kfc"),
    (re.compile(r"\bk\.?\s*f\.?\s*c\.?\b", re.I), "kfc"),
    (re.compile(r"\bkay\s+eff\s+see\b", re.I), "kfc"),
    (re.compile(r"\bkabab\s*jees?\b", re.I), "kababjees"),
    (re.compile(r"\bkabab\s*ji+\b", re.I), "kababjees"),
    (re.compile(r"\bkabab\s*jes+\b", re.I), "kababjees"),
    (re.compile(r"\bkabab\s*jee\b", re.I), "kababjees"),
    (re.compile(r"\bcola\s*next\b", re.I), "cola next"),
    (re.compile(r"\bcolla\s*next\b", re.I), "cola next"),
    (re.compile(r"\bkola\s*next\b", re.I), "cola next"),
    (re.compile(r"\bfiz+\s*up\s*next\b", re.I), "fizz up next"),
    (re.compile(r"\bfizz\s*up\b", re.I), "fizz up next"),
    (re.compile(r"\bblog\b", re.I), "block"),
    (re.compile(r"\bchkn\b", re.I), "chicken"),
    (re.compile(r"\bchiken\b", re.I), "chicken"),
    (re.compile(r"\bbriyani\b", re.I), "biryani"),
    (re.compile(r"\bbiriyani\b", re.I), "biryani"),
    (re.compile(r"\bbirayani\b", re.I), "biryani"),
    (re.compile(r"\bhun\b", re.I), "han"),
    (re.compile(r"\bhawn\b", re.I), "haan"),
    (re.compile(r"\bاوڈر\b", re.I), "order"),
    (re.compile(r"\bسے\b", re.I), " se "),
]

WHISPER_ORDER_PROMPT = (
    "Roman Urdu and English WhatsApp food order. Latin letters ONLY, no Urdu script. "
    "Restaurants: KFC, Kababjees. Items: Zinger, Chicken Biryani, Cola Next, fries, burger. "
    "Addresses like Block C5. Names like Askari. Confirmations: han kardo, haan kar do, yes, ji haan."
)

MENU_PHRASES = (
    "menu",
    "show menu",
    "see menu",
    "full menu",
    "menu dikhao",
    "menu dikhayo",
    "menu dikha do",
    "menu batao",
    "menu bataiye",
    "menu bata do",
    "menu dekhna",
    "menu list",
    "menu send karo",
    "menu bhejo",
    "menu bhejdo",
    "menu bhej do",
    "menu bhi bhejdo",
    "menu bhi bhej do",
    "menu bhi bhejo",
    "pura menu bhejo",
    "full menu bhejo",
    "kya kya hai",
    "kya milta hai",
    "kya hai menu",
    "menu kya hai",
    "items list",
    "sara menu",
    "pura menu",
    "what's on the menu",
    "whats on the menu",
)

SPEECH_FILLERS = frozenset(
    {"jani", "janii", "yar", "yara", "bhai", "bhay", "please", "plz", "ek", "aik", "one", "ji"}
)

ADDRESS_MARKERS = (
    "block",
    "street",
    "phase",
    "sector",
    "house",
    "flat",
    "road",
    "lahore",
    "karachi",
    "islamabad",
    "rawalpindi",
    "c1",
    "c2",
    "c3",
    "c4",
    "c5",
    "c6",
    "gulshan",
    "dha",
    "bahria",
)

URDU_YES_MARKERS = ("ہاں", "हाँ", "हां", "جی ہاں", "جی ہاں")


def has_non_latin_script(text: str) -> bool:
    return bool(_NON_LATIN_RE.search(text))


def normalize_transcript(text: str) -> str:
    t = text.strip()
    for pattern, repl in _TRANSCRIPT_REPLACEMENTS:
        t = pattern.sub(repl, t)
    return re.sub(r"\s+", " ", t).strip()


def normalize_confirm_transcript(text: str) -> str:
    """Fix common Whisper mis-hearings on short YES / han kardo voice notes."""
    return normalize_transcript(text)


def normalize_user_text(text: str) -> str:
    """Lowercase, strip punctuation — voice transcripts often include '.' or '!'"""
    cleaned = text.strip().lower()
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def strip_speech_fillers(text: str) -> str:
    words = normalize_user_text(text).split()
    return " ".join(w for w in words if w not in SPEECH_FILLERS)


async def ensure_latin_transcript(text: str) -> str:
    """Normalize transcript without an extra LLM call (saves Groq rate limit)."""
    text = normalize_transcript(text)
    if not text:
        return text
    if not has_non_latin_script(text):
        return text

    # Mixed Urdu/Latin voice — Latin tokens (kfc, block c5, cola) still parse correctly.
    # Avoid a second LLM chat call per voice note; order_context handles the rest.
    logger.info("Mixed-script voice kept as-is after normalize (%d chars)", len(text))
    return text


THANK_YOU_WORDS = frozenset(
    {
        "shukriya",
        "shukria",
        "thanks",
        "thank",
        "thx",
        "ty",
        "dhanyavad",
        "dhanyavaad",
        "meherbani",
        "jazakallah",
        "jazakallahu",
        "allah",
    }
)

THANK_YOU_PHRASES = (
    "thank you",
    "thanks a lot",
    "thank u",
    "bahut shukriya",
    "bohat shukriya",
    "shukriya bhai",
    "shukriya jani",
    "thanks bhai",
    "thank you so much",
    "thanks so much",
)

# Urdu-script thanks (Whisper often outputs these for voice notes)
URDU_THANK_MARKERS = ("شکریہ", "شكر", "بہت شکریہ", "جزاک", "جزاک اللہ", "الحمدلله")


def is_thank_you_message(text: str) -> bool:
    """Courtesy / gratitude — not a name, address, or order detail."""
    if not text or not text.strip():
        return False
    if any(marker in text for marker in URDU_THANK_MARKERS):
        return True
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    if any(p in normalized for p in THANK_YOU_PHRASES):
        return True
    words = normalized.split()
    if len(words) <= 5 and all(w in THANK_YOU_WORDS or w in ("bhai", "ji", "jani", "yar") for w in words):
        return True
    if len(words) <= 3 and any(w in THANK_YOU_WORDS for w in words):
        return True
    if normalized in THANK_YOU_WORDS:
        return True
    # Fuzzy: shukreeya, shukria, etc.
    return bool(re.search(r"\bshukr", normalized, re.I))


def is_menu_request(text: str) -> bool:
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    if any(phrase in normalized for phrase in MENU_PHRASES):
        return True
    if "menu" in normalized and any(
        w in normalized for w in ("bhej", "dikha", "dekha", "send", "show", "bata", "list")
    ):
        return True
    return False


def is_mid_order_detail_reply(text: str) -> bool:
    """Address, name, or short reply while order is in progress — not a menu/restaurant pick."""
    if is_thank_you_message(text):
        return False
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    if is_menu_request(text):
        return False
    if any(m in normalized for m in ADDRESS_MARKERS):
        return True
    words = normalized.split()
    if len(words) <= 5 and not any(w in normalized for w in ("kfc", "kabab", "kababjees", "kentucky")):
        return True
    return False


def restaurant_named_in_text(text: str, slug: str, restaurants: list[dict] | None = None) -> bool:
    """True when the customer explicitly names this restaurant in the message."""
    normalized = normalize_user_text(text)
    if not normalized:
        return False
    compact = re.sub(r"\s+", "", normalized)
    if slug.replace("_", "") in compact:
        return True
    if restaurants:
        for r in restaurants:
            if r["slug"] == slug and r["name"].lower() in normalized:
                return True
    if slug == "kababjees" and re.search(r"kabab\s*jee?s?", normalized):
        return True
    if slug == "kfc" and ("kfc" in normalized or "kentucky" in normalized):
        return True
    return False


def should_show_restaurant_menu(
    text: str,
    slug: str,
    session,
    catalog_items: list[dict],
) -> bool:
    """Only dump full menu on explicit restaurant pick/switch — not mid-order."""
    # "kababjees ka menu dikhao" — always show that restaurant's menu.
    if is_menu_request(text) and restaurant_named_in_text(text, slug):
        return True
    if is_menu_request(text):
        return False
    if message_mentions_items(text, catalog_items):
        return False
    if (
        session.active_tenant_slug == slug
        and session.state in ("ordering", "confirming")
        and is_mid_order_detail_reply(text)
    ):
        return False
    has_progress = bool(
        session.pending_items or session.pending_customer_name or session.pending_address
    )
    if (
        session.active_tenant_slug == slug
        and session.state in ("ordering", "confirming")
        and has_progress
    ):
        return False
    if session.active_tenant_slug and session.active_tenant_slug != slug:
        return True
    if not session.active_tenant_slug:
        return True
    # Same restaurant, no order in progress yet — show menu (first pick / re-pick)
    if session.active_tenant_slug == slug:
        return True
    return False


def message_mentions_items(text: str, items: list[dict]) -> bool:
    normalized = normalize_user_text(text)
    if not normalized or not items:
        return False
    # Strip restaurant names so "kababjees" does not match "Beef Kabab Roll".
    scrubbed = normalized
    for token in ("kababjees", "kabab jee", "kabab jees", "kfc", "kentucky"):
        scrubbed = scrubbed.replace(token, " ")
    scrubbed = re.sub(r"kabab\s*jee?s?", " ", scrubbed)
    scrubbed = re.sub(r"\s+", " ", scrubbed).strip()
    if not scrubbed:
        return False
    for item in items:
        name = normalize_user_text(item.get("name", ""))
        if not name:
            continue
        if name in scrubbed:
            return True
        tokens = name.split()
        if len(tokens) >= 2 and all(t in scrubbed for t in tokens):
            return True
    return False


def resolve_restaurant_slug(text: str, restaurants: list[dict]) -> str | None:
    """Detect KFC / Kababjees from Roman Urdu or English voice/text."""
    raw = normalize_user_text(text)
    stripped = strip_speech_fillers(text)
    for candidate in (raw, stripped, normalize_transcript(text).lower()):
        if not candidate:
            continue
        candidate = re.sub(r"kabab\s*jee?s?", "kababjees", candidate)
        for r in sorted(restaurants, key=lambda x: len(x["slug"]), reverse=True):
            slug = r["slug"]
            name = r["name"].lower()
            if slug in candidate or name in candidate:
                return slug
        if "kababjees" in candidate or "kababjee" in candidate or "kabab" in candidate:
            return "kababjees"
        if "kfc" in candidate or "kentucky" in candidate:
            return "kfc"
    return None


QUESTION_STARTS = (
    "how", "what", "which", "why", "when", "where", "do you",
    "can you", "is it", "are ", "could you", "kya", "kab",
    "kahan", "kahaan", "kaun", "kon", "kitna", "kitne", "kaisa",
    "kaisi", "kaisay", "kab tak", "kab aayega", "kab aayegi",
    "kitne ka", "kitna hai", "kya hai", "kya milega", "kya hai aap",
    "kya aata", "available", "deliver", "delivery",
)


def is_question_message(text: str) -> bool:
    """True if the message looks like the customer is asking a question rather than placing an order."""
    if not text:
        return False
    if "?" in text:
        return True
    lower = text.lower().strip()
    if not lower:
        return False
    for start in QUESTION_STARTS:
        if lower == start or lower.startswith(start + " "):
            return True
    return False


MODIFIER_CUES = (
    " no ", " no.", " no,", "no mayo", "no cheese", "no onion", "no onions",
    "no pyaaz", "no pyaz", "no salt", "no sugar", "no oil", "no spice",
    "without", " extra ", " extra.", " extra,", " extra-", "thoda sa",
    "less ", " kam ", " zyada", " zayada", " spicy", " teekha", " tikha",
    " masala", " well done", " medium", " large", " small", " thoda",
    " thori", " bin ", " baghair", "with extra", " elaichi", " achari",
)


def has_modifier_cue(text: str) -> bool:
    """True if the text carries a modifier cue (no X, extra Y, etc.). Conservative — caller
    should AND this with other evidence (e.g. a menu item is mentioned) to avoid false positives
    on short unrelated words like 'no' in 'no thanks'."""
    if not text:
        return False
    lower = (" " + text.lower().strip() + " ").replace("?", " ").replace(".", " ")
    return any(cue in lower for cue in MODIFIER_CUES)


REMOVE_CUES = (
    "remove", "hatao", "hata do", "hata dein", "hata de", "cancel",
    "delete", "nikalo", "nikal do", "nikal dein", "hatana", "nikalna",
    "wo nahi", "wo hatao", "na chahiye", "mat dena", "mat do",
    "nai chahiye", "nahi chahiye", "nai rakhna", "nai rakhna hai",
    "wo nai chahiye", "wo nai", "wo cancel", "off karo", "off kardo",
)


def has_remove_cue(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    return any(cue in lower for cue in REMOVE_CUES)

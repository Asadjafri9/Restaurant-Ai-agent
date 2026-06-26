"""Language detection and bilingual message templates for the order agent."""

import re

Language = str  # "en" | "roman_ur"

ROMAN_URDU_MARKERS = frozenset(
    {
        "hai",
        "hain",
        "ho",
        "mujhe",
        "mujhay",
        "chahiye",
        "chahye",
        "kitne",
        "kitna",
        "kya",
        "kia",
        "acha",
        "theek",
        "bhai",
        "janab",
        "salam",
        "aoa",
        "assalamualaikum",
        "jani",
        "janii",
        "ek",
        "aik",
        "kardo",
        "dena",
        "dedo",
        "order",
        "khana",
        "address",
        "naam",
        "name",
        "yeh",
        "ye",
        "wo",
        "aur",
        "bhi",
        "se",
        "ka",
        "ki",
        "ke",
        "ko",
        "mein",
        "main",
        "par",
        "pe",
        "ap",
        "aap",
        "apka",
        "aapka",
        "shukriya",
        "meherbani",
        "batao",
        "bataiye",
        "dijiye",
        "lijiye",
    }
)

_MESSAGES: dict[str, dict[str, str]] = {
    "greeting": {
        "en": (
            "Hello! Welcome to our food ordering service.\n\n"
            "We have {restaurants}. Which restaurant would you like to order from?"
        ),
        "roman_ur": (
            "Assalam o alaikum! Khana order karne ke liye khush amdeed.\n\n"
            "Hamare paas {restaurants} hain. Aap kis restaurant se order karna chahte hain?"
        ),
    },
    "no_restaurants": {
        "en": "Hello! No restaurants are available right now. Please try again shortly.",
        "roman_ur": "Assalam o alaikum! Abhi koi restaurant available nahi. Thori der baad try karein.",
    },
    "menu_empty": {
        "en": "Sorry, the {name} menu is empty right now. Please try again later or pick another restaurant.",
        "roman_ur": "Maaf kijiye, {name} ka menu abhi khali hai. Baad mein try karein ya doosra restaurant chunein.",
    },
    "menu_intro_switch": {
        "en": "Sure, switching to {name}!",
        "roman_ur": "Theek hai, {name} par switch kar rahe hain!",
    },
    "menu_intro_pick": {
        "en": "Great choice — {name}!",
        "roman_ur": "Behtareen choice — {name}!",
    },
    "menu_ask": {
        "en": "What would you like to order?",
        "roman_ur": "Aap kya order karna chahte hain?",
    },
    "menu_full_header": {
        "en": "{name}'s full menu:",
        "roman_ur": "{name} ka poora menu:",
    },
    "menu_item_added": {
        "en": "Got it — added to your order: {items}.",
        "roman_ur": "Theek hai — aapka order note kar liya: {items}.",
    },
    "menu_ask_more": {
        "en": "Here is the full menu. Would you like to order anything else?",
        "roman_ur": "Yeh poora menu hai. Kuch aur order karna chahte hain?",
    },
    "order_confirmed": {
        "en": (
            "Order confirmed! Total: Rs {total:.0f}\n"
            "Order ID: #{order_id}\n"
            "Estimated delivery: 45-60 minutes.\n\n"
            "Reply 'new order' to order again."
        ),
        "roman_ur": (
            "Order confirm ho gaya! Total: Rs {total:.0f}\n"
            "Order ID: #{order_id}\n"
            "Delivery: 45-60 minute.\n\n"
            "Dobara order ke liye 'new order' likhein."
        ),
    },
    "persist_fail": {
        "en": (
            "Sorry, I could not place your order — some items may be unavailable. "
            "Please check the menu and try again."
        ),
        "roman_ur": (
            "Maaf kijiye, order place nahi ho saka — kuch items available nahi hain. "
            "Menu dekhein aur dobara try karein."
        ),
    },
    "persist_error": {
        "en": "Sorry, there was a problem placing your order. Please try again in a moment.",
        "roman_ur": "Maaf kijiye, order place karne mein masla hua. Thori der baad dobara try karein.",
    },
    "confirm_fail": {
        "en": "Sorry, I couldn't confirm your order. Please send your items, name, and address again.",
        "roman_ur": "Maaf kijiye, order confirm nahi ho saka. Items, naam aur address dobara bhejein.",
    },
    "voice_fail": {
        "en": "Sorry, I couldn't understand the voice note. Please type your order or try again.",
        "roman_ur": "Maaf kijiye, voice note samajh nahi aayi. Type karke order bhejein ya dobara try karein.",
    },
    "unsupported_media": {
        "en": "Please send a text message or voice note to place your order.",
        "roman_ur": "Order ke liye text message ya voice note bhejein.",
    },
    "voice_ack": {
        "en": "Got your voice message, one moment...",
        "roman_ur": "Voice message mil gayi, ek minute...",
    },
    "fallback": {
        "en": "Sorry, I am unable to respond right now.\nPlease try again later.",
        "roman_ur": "Maaf kijiye, abhi jawab nahi de sakta.\nThori der baad try karein.",
    },
    "rate_limit": {
        "en": "I'm a bit busy right now (too many requests). Please wait 10 seconds and try again.",
        "roman_ur": "Abhi thora load zyada hai. 10 second ruk kar dobara message bhejein.",
    },
    "ask_name": {
        "en": "What name should we put on the order?",
        "roman_ur": "Order par kis naam se likhein? Apna naam bata dein.",
    },
    "ask_address": {
        "en": "What's your delivery address?",
        "roman_ur": "Delivery address bata dein (e.g. Block C5).",
    },
    "thank_you_closing": {
        "en": (
            "You're very welcome — glad we could help!\n"
            "Enjoy your meal. See you again soon!\n\n"
            "Reply 'new order' anytime you'd like to order again."
        ),
        "roman_ur": (
            "Aap ka shukriya! Khushi hui aap ki madad kar ke.\n"
            "Mazay se khayein — phir milenge!\n\n"
            "Dobara order ke liye 'new order' likhein."
        ),
    },
    "thank_you_ack": {
        "en": "You're welcome! Let me know if you need anything else.",
        "roman_ur": "Khushi hui! Agar aur kuch chahiye ho to bata dein.",
    },
}


def detect_language(text: str) -> Language:
    """Heuristic: Roman Urdu if enough Urdu-ish tokens in Latin script."""
    if not text or not text.strip():
        return "en"
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not words:
        return "en"
    hits = sum(1 for w in words if w in ROMAN_URDU_MARKERS)
    if hits >= 2:
        return "roman_ur"
    if hits == 1 and len(words) <= 5:
        return "roman_ur"
    return "en"


def msg(key: str, lang: Language, **kwargs: object) -> str:
    templates = _MESSAGES[key]
    template = templates.get(lang) or templates["en"]
    return template.format(**kwargs)

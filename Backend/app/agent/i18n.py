"""
Languages the agent can speak, and the few fixed lines it says without the LLM.
"""
from app.config import get_settings

settings = get_settings()

LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "ml": "Malayalam",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}

SUPPORTED_LANGUAGES = [
    code.strip() for code in settings.supported_languages.split(",") if code.strip()
] or ["en"]

_PHRASES = {
    "escalate": {
        "en": "I'm connecting you to a human agent now. Please hold.",
        "hi": "मैं आपको अभी हमारे एक प्रतिनिधि से जोड़ रहा हूँ। कृपया प्रतीक्षा करें।",
        "ta": "உங்களை இப்போது எங்கள் பிரதிநிதியுடன் இணைக்கிறேன். தயவுசெய்து காத்திருக்கவும்.",
    },
    "fallback": {
        "en": "Sorry, I didn't catch that. Could you say it again?",
        "hi": "माफ़ कीजिए, मैं समझ नहीं पाया। क्या आप दोबारा कह सकते हैं?",
        "ta": "மன்னிக்கவும், எனக்குப் புரியவில்லை. மீண்டும் சொல்ல முடியுமா?",
    },
    "human_joined": {
        "en": "A human agent has joined the call.",
        "hi": "हमारे प्रतिनिधि अब कॉल पर हैं।",
        "ta": "எங்கள் பிரதிநிதி இப்போது அழைப்பில் இணைந்துள்ளார்.",
    },
    "human_left": {
        "en": "You are back with the virtual assistant. How else can I help?",
        "hi": "आप फिर से वर्चुअल सहायक के साथ हैं। मैं और क्या मदद कर सकता हूँ?",
        "ta": "நீங்கள் மீண்டும் மெய்நிகர் உதவியாளருடன் இருக்கிறீர்கள். வேறு என்ன உதவி வேண்டும்?",
    },
}


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


def phrase(key: str, language: str) -> str:
    lines = _PHRASES[key]
    return lines.get(language, lines["en"])

from __future__ import annotations

DEFAULT_RESPONSE_LANGUAGE = "english"

_LANGUAGE_ALIASES = {
    "en": "english",
    "eng": "english",
    "english": "english",
    "us english": "english",
    "uk english": "english",
    "vi": "vietnamese",
    "vie": "vietnamese",
    "vietnamese": "vietnamese",
    "tiếng việt": "vietnamese",
    "tieng viet": "vietnamese",
    "es": "spanish",
    "spa": "spanish",
    "spanish": "spanish",
    "español": "spanish",
    "fr": "french",
    "fre": "french",
    "fra": "french",
    "french": "french",
    "français": "french",
    "de": "german",
    "ger": "german",
    "deu": "german",
    "german": "german",
    "deutsch": "german",
    "pt": "portuguese",
    "por": "portuguese",
    "portuguese": "portuguese",
    "pt-br": "portuguese",
    "it": "italian",
    "ita": "italian",
    "italian": "italian",
    "ja": "japanese",
    "jpn": "japanese",
    "japanese": "japanese",
    "日本語": "japanese",
    "ko": "korean",
    "kor": "korean",
    "korean": "korean",
    "한국어": "korean",
    "zh": "chinese",
    "zho": "chinese",
    "chi": "chinese",
    "chinese": "chinese",
    "中文": "chinese",
    "简体中文": "chinese",
    "traditional chinese": "chinese",
    "ru": "russian",
    "rus": "russian",
    "russian": "russian",
    "th": "thai",
    "tha": "thai",
    "thai": "thai",
    "id": "indonesian",
    "ind": "indonesian",
    "indonesian": "indonesian",
}

_LANGUAGE_DISPLAY_NAMES = {
    "english": "English",
    "vietnamese": "Vietnamese",
    "spanish": "Spanish",
    "french": "French",
    "german": "German",
    "portuguese": "Portuguese",
    "italian": "Italian",
    "japanese": "Japanese",
    "korean": "Korean",
    "chinese": "Chinese",
    "russian": "Russian",
    "thai": "Thai",
    "indonesian": "Indonesian",
}


def normalize_language_name(value: object) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return DEFAULT_RESPONSE_LANGUAGE
    return _LANGUAGE_ALIASES.get(raw, raw if raw.isascii() else DEFAULT_RESPONSE_LANGUAGE)


def get_language_display_name(value: object) -> str:
    normalized = normalize_language_name(value)
    return _LANGUAGE_DISPLAY_NAMES.get(normalized, normalized.title() if normalized else "English")


def build_response_language_instruction(response_language: object, *, explicit: bool = False) -> str:
    _ = response_language, explicit
    return (
        "Language policy: normalize non-English user input into clear English for internal reasoning, "
        "and write the user-facing answer strictly in English. "
        "Do not switch to another language except for short source quotes, code, or proper nouns."
    )

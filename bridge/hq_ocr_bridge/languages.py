from __future__ import annotations

SUPPORTED_LANGUAGE_CODES = frozenset(
    {
        "en",
        "pt-BR",
        "es",
        "fr",
        "de",
        "it",
        "ja",
        "ko",
        "zh-CN",
        "zh-TW",
        "ru",
        "nl",
        "pl",
        "tr",
    }
)

_LANGUAGE_ALIASES = {
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "pt": "pt-BR",
    "pt-br": "pt-BR",
    "es": "es",
    "es-es": "es",
    "fr": "fr",
    "fr-fr": "fr",
    "de": "de",
    "de-de": "de",
    "it": "it",
    "it-it": "it",
    "ja": "ja",
    "ja-jp": "ja",
    "ko": "ko",
    "ko-kr": "ko",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "zh-sg": "zh-CN",
    "zh-tw": "zh-TW",
    "zh-hant": "zh-TW",
    "zh-hk": "zh-TW",
    "ru": "ru",
    "ru-ru": "ru",
    "nl": "nl",
    "nl-nl": "nl",
    "pl": "pl",
    "pl-pl": "pl",
    "tr": "tr",
    "tr-tr": "tr",
}


def normalize_language_code(value: object) -> str:
    requested = str(value).strip()
    if not requested:
        raise ValueError("language code must not be empty")

    normalized = _LANGUAGE_ALIASES.get(requested.lower())
    if normalized is None:
        raise ValueError(f"unsupported language code: {requested}")
    return normalized


def language_base(value: object) -> str:
    return normalize_language_code(value).split("-", 1)[0].lower()

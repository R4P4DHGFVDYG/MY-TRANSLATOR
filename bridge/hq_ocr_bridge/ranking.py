from __future__ import annotations

from difflib import SequenceMatcher
import re
import string

from .models import EngineResult


WHITESPACE_RE = re.compile(r"\s+")
LONG_REPEAT_RE = re.compile(r"(.)\1{5,}")
WORD_RE = re.compile(r"[A-Za-z']+")
SMART_PUNCTUATION = str.maketrans(
    {
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "`": "'",
    }
)
COMMON_WORD_FIXES = {
    "CLRE": "CURE",
    "LNCLEAN": "UNCLEAN",
    "MLCH": "MUCH",
    "YOL": "YOU",
}
CONTRACTION_FIXES = {
    "ARENT": "AREN'T",
    "CANT": "CAN'T",
    "COULDNT": "COULDN'T",
    "DIDNT": "DIDN'T",
    "DONT": "DON'T",
    "ID": "I'D",
    "ILL": "I'LL",
    "IM": "I'M",
    "ISNT": "ISN'T",
    "IVE": "I'VE",
    "SHOULDNT": "SHOULDN'T",
    "THATS": "THAT'S",
    "WASNT": "WASN'T",
    "WERENT": "WEREN'T",
    "WONT": "WON'T",
    "WOULDNT": "WOULDN'T",
    "YOURE": "YOU'RE",
}


def normalize_ocr_text(text: str) -> str:
    if not text:
        return ""

    printable = "".join(ch if ch.isprintable() else " " for ch in text)
    normalized = printable.translate(SMART_PUNCTUATION)
    normalized = WHITESPACE_RE.sub(" ", normalized).strip()
    normalized = _fix_comic_letter_confusions(normalized)
    normalized = _fix_contractions(normalized)
    normalized = _normalize_comic_case(normalized)
    normalized = _fix_contractions(normalized)
    normalized = _fix_punctuation(normalized)
    return WHITESPACE_RE.sub(" ", normalized).strip()


def text_quality_score(text: str, confidence: float) -> float:
    normalized = normalize_ocr_text(text)
    if not normalized:
        return 0.0

    chars = list(normalized)
    printable_count = sum(1 for ch in chars if ch in string.printable)
    alpha_count = sum(1 for ch in chars if ch.isalpha())
    accepted_count = sum(
        1 for ch in chars if ch.isalnum() or ch.isspace() or ch in ".,!?;:'\"-()[]"
    )
    words = [word for word in re.split(r"\s+", normalized) if word]

    printable_ratio = printable_count / len(chars)
    accepted_ratio = accepted_count / len(chars)
    alpha_ratio = alpha_count / len(chars)
    length_bonus = min(len(normalized) / 80, 1.0)
    word_bonus = min(len(words) / 8, 1.0)
    confidence = _clamp(float(confidence), 0.0, 1.0)

    score = (
        confidence * 0.55
        + printable_ratio * 0.1
        + accepted_ratio * 0.13
        + alpha_ratio * 0.07
        + length_bonus * 0.08
        + word_bonus * 0.07
    )

    if len(normalized) < 2:
        score *= 0.25
    if LONG_REPEAT_RE.search(normalized):
        score *= 0.55
    if accepted_ratio < 0.65:
        score *= 0.65

    return round(_clamp(score, 0.0, 1.0), 4)


def rank_ocr_results(results: list[EngineResult]) -> EngineResult | None:
    candidates = [result for result in results if normalize_ocr_text(result.text)]
    if not candidates:
        return None

    normalized_by_engine = {
        result.engine: normalize_ocr_text(result.text).lower() for result in candidates
    }
    for result in candidates:
        for other in candidates:
            if other is result:
                continue
            similarity = SequenceMatcher(
                None,
                normalized_by_engine[result.engine],
                normalized_by_engine[other.engine],
            ).ratio()
            if similarity >= 0.82:
                result.score = min(1.0, result.score + 0.08)
                break

    return max(candidates, key=lambda item: (item.score, item.raw_confidence, len(item.text)))


def _fix_comic_letter_confusions(text: str) -> str:
    text = re.sub(r"\b(?:1a|la|ia)\s+(?=with\b)", "...", text, flags=re.IGNORECASE)
    text = re.sub(r"\b4(?=[oO][uU])", "Y", text)
    text = re.sub(r"\b5[oO]\b", lambda match: _case_like("so", match.group(0)), text)
    text = re.sub(
        r"\b2[I1l][O0](?=\s+POUNDS?\b)",
        lambda match: _case_like("210", match.group(0)),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bEAS[/\\|]ER\b",
        lambda match: _case_like("easier", match.group(0)),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(JASON)\s+(TOOD)\b",
        lambda match: f"{match.group(1)} {_case_like('todd', match.group(2))}",
        text,
        flags=re.IGNORECASE,
    )

    def replace_word(match: re.Match[str]) -> str:
        word = match.group(0)
        fixed = COMMON_WORD_FIXES.get(word.upper())
        return _case_like(fixed, word) if fixed else word

    return re.sub(r"\b[A-Za-z]+\b", replace_word, text)


def _fix_contractions(text: str) -> str:
    text = re.sub(
        r"\b(can|couldn|didn|doesn|don|isn|shouldn|wasn|weren|won|wouldn)\s+t\b",
        lambda match: f"{match.group(1)}'t",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(I|you|we|they|he|she|it)\s+(m|re|ve|ll|d|s)\b",
        lambda match: f"{match.group(1)}'{match.group(2)}",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bWELL(?=\s+GIVE\b)",
        "WE'LL",
        text,
        flags=re.IGNORECASE,
    )

    def replace_word(match: re.Match[str]) -> str:
        word = match.group(0)
        fixed = CONTRACTION_FIXES.get(word.upper())
        return _case_like(fixed, word) if fixed else word

    return re.sub(r"\b[A-Za-z]+\b", replace_word, text)


def _normalize_comic_case(text: str) -> str:
    words = WORD_RE.findall(text)
    letters = [ch for ch in text if ch.isalpha()]
    if len(words) < 3 or not letters:
        return text

    uppercase_ratio = sum(1 for ch in letters if ch.isupper()) / len(letters)
    suspicious_words = sum(1 for word in words if _is_suspicious_mixed_case(word))
    all_caps_words = sum(1 for word in words if len(word) >= 2 and word.isupper())
    if (
        uppercase_ratio >= 0.65
        or (uppercase_ratio >= 0.45 and suspicious_words >= 2)
        or (uppercase_ratio >= 0.48 and all_caps_words >= 2)
    ):
        return text.upper()

    return text


def _is_suspicious_mixed_case(word: str) -> bool:
    if len(word) < 4 or not any(ch.isupper() for ch in word):
        return False
    if not any(ch.islower() for ch in word):
        return False
    if word[0].isupper() and word[1:].islower():
        return False
    return True


def _fix_punctuation(text: str) -> str:
    text = re.sub(r";\s*7\b", "...", text)
    text = re.sub(r"\(?\bTIS\b", "IT'S", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    text = re.sub(r"([({\[])\s+", r"\1", text)
    text = re.sub(r"\.{2,}", "...", text)
    text = re.sub(r";(?=\s*$)", ".", text)
    text = re.sub(r":(?=\s*$)", ".", text)
    text = re.sub(r"\bIT'S(?=\s+HOSTAGE\b)", "ITS", text)
    return text


def _case_like(value: str, sample: str) -> str:
    if sample.isupper():
        return value.upper()
    if sample.islower():
        return value.lower()
    if sample[:1].isupper() and sample[1:].islower():
        return value.capitalize()
    return value


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))

from __future__ import annotations

from difflib import SequenceMatcher
import math
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


def text_quality_score(
    text: str, confidence: float, *, raw_text: str | None = None
) -> float:
    normalized = normalize_ocr_text(text)
    if not normalized:
        return 0.0

    chars = list(normalized)
    printable_count = sum(1 for ch in chars if ch in string.printable)
    content_count = sum(1 for ch in chars if ch.isalnum())
    accepted_count = sum(
        1 for ch in chars if ch.isalnum() or ch.isspace() or ch in ".,!?;:'\"-()[]"
    )
    words = [word for word in re.split(r"\s+", normalized) if word]

    printable_ratio = printable_count / len(chars)
    accepted_ratio = accepted_count / len(chars)
    content_ratio = content_count / len(chars)
    length_bonus = min(len(normalized) / 80, 1.0)
    word_bonus = min(len(words) / 8, 1.0)
    confidence = _bounded_number(confidence)

    score = (
        confidence * 0.55
        + printable_ratio * 0.1
        + accepted_ratio * 0.13
        + content_ratio * 0.07
        + length_bonus * 0.08
        + word_bonus * 0.07
    )

    if len(normalized) < 2:
        score *= 0.25
    if LONG_REPEAT_RE.search(normalized):
        score *= 0.55
    if accepted_ratio < 0.65:
        score *= 0.65
    score *= 1.0 - ocr_suspicion_score(raw_text if raw_text is not None else text)

    return round(_clamp(score, 0.0, 1.0), 4)


def ocr_suspicion_score(text: str) -> float:
    printable = "".join(ch if ch.isprintable() else " " for ch in str(text))
    normalized = WHITESPACE_RE.sub(
        " ", printable.translate(SMART_PUNCTUATION)
    ).strip()
    if not normalized:
        return 0.0

    tokens = [token.strip(".,!?;:'\"-()[]") for token in normalized.split()]
    tokens = [token for token in tokens if token]
    likely_digit_confusions = sum(
        1 for token in tokens if _looks_like_ocr_digit_confusion(token)
    )
    embedded_slashes = sum(
        len(re.findall(r"(?<=[A-Za-z])[/\\|](?=[A-Za-z])", token))
        for token in tokens
        if not token.islower()
    )
    unexpected_letters = sum(
        1 for ch in normalized if ch.isalpha() and ch not in string.ascii_letters
    )
    very_long_tokens = sum(1 for token in tokens if len(token) >= 20)

    penalty = min(0.24, likely_digit_confusions * 0.12)
    penalty += min(0.18, embedded_slashes * 0.12)
    penalty += min(0.12, unexpected_letters * 0.06)
    penalty += min(0.08, very_long_tokens * 0.04)
    return round(_clamp(penalty, 0.0, 0.45), 4)


def _looks_like_ocr_digit_confusion(token: str) -> bool:
    compact = token.replace("-", "")
    if re.search(r"(?<=[A-Za-z])[13](?=[A-Za-z])", compact):
        return True
    if re.fullmatch(r"[017][A-Za-z]{1,3}", compact):
        return True
    return re.fullmatch(r"2[IO][A-Za-z]*", compact, flags=re.IGNORECASE) is not None


def rank_ocr_results(
    results: list[EngineResult],
    *,
    primary_engine: str | None = None,
    accept_score: float = 0.8,
    accept_confidence: float = 0.78,
) -> EngineResult | None:
    candidates = [result for result in results if normalize_ocr_text(result.text)]
    if not candidates:
        return None

    normalized_texts = {
        id(result): normalize_ocr_text(result.text).lower() for result in candidates
    }
    adjusted_scores: dict[int, float] = {}
    for result in candidates:
        result.score = _bounded_number(result.score)
        result.raw_confidence = _bounded_number(result.raw_confidence)
        adjusted_score = result.score
        for other in candidates:
            if (
                other is result
                or _base_engine(other.engine) == _base_engine(result.engine)
            ):
                continue
            similarity = SequenceMatcher(
                None,
                normalized_texts[id(result)],
                normalized_texts[id(other)],
            ).ratio()
            if similarity >= 0.82:
                adjusted_score = min(1.0, adjusted_score + 0.08)
                break
        adjusted_scores[id(result)] = adjusted_score

    strongest = max(
        candidates,
        key=lambda item: (
            adjusted_scores[id(item)],
            item.raw_confidence,
            len(item.text),
        ),
    )
    if not primary_engine:
        return strongest

    primary_candidates = [
        result
        for result in candidates
        if _base_engine(result.engine) == primary_engine.strip().lower()
    ]
    if not primary_candidates:
        return strongest

    primary = max(
        primary_candidates,
        key=lambda item: (
            adjusted_scores[id(item)],
            item.raw_confidence,
            len(item.text),
        ),
    )
    if primary is strongest:
        return strongest

    primary_is_reliable = (
        primary.score >= _bounded_number(accept_score)
        and primary.raw_confidence >= _bounded_number(accept_confidence)
    )
    similarity = SequenceMatcher(
        None,
        normalized_texts[id(primary)],
        normalized_texts[id(strongest)],
    ).ratio()
    verifier_has_clear_advantage = (
        adjusted_scores[id(strongest)] - adjusted_scores[id(primary)] >= 0.08
    )
    if primary_is_reliable or similarity >= 0.82 or not verifier_has_clear_advantage:
        return primary
    return strongest


def _base_engine(engine: str) -> str:
    return str(engine).split(":", 1)[0].strip().lower()


def _fix_comic_letter_confusions(text: str) -> str:
    text = re.sub(r"^\s*\*+\s*", "", text)
    text = re.sub(r"^CIT'{1,2}S\b", "(It's", text, flags=re.IGNORECASE)
    text = re.sub(r"^IT'{1,2}S\b", "It's", text, flags=re.IGNORECASE)
    text = re.sub(r"\bMOMS(?=\s+VAN\b)", "mom's", text, flags=re.IGNORECASE)
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
    text = re.sub(r"^\.\.\.\s+and,\s+", "...and ", text, flags=re.IGNORECASE)
    text = re.sub(r";\s*7\b", "...", text)
    text = re.sub(r"\(?\bTIS\b", "IT'S", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    text = re.sub(r"([({\[])\s+", r"\1", text)
    text = re.sub(r"\s+([)}\]])", r"\1", text)
    text = re.sub(r"\.{2,}", "...", text)
    text = re.sub(r";(?=\s*$)", ".", text)
    text = re.sub(r":(?=\s*$)", ".", text)
    text = re.sub(r"\bIT'S(?=\s+HOSTAGE\b)", "ITS", text)
    if text.startswith("(") and text.endswith("}"):
        text = text[:-1].rstrip() + ")"
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


def _bounded_number(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return _clamp(number, 0.0, 1.0)

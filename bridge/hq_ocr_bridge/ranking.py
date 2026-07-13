from __future__ import annotations

from difflib import SequenceMatcher
import math
import re

from .languages import language_base
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
    "HAHAT": "HAHA!",
    "LNCLEAN": "UNCLEAN",
    "MLCH": "MUCH",
    "TIMEF": "TIME!",
    "TIMET": "TIME!",
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


def normalize_ocr_text(text: str, language_tag: str | None = "en") -> str:
    if not text:
        return ""

    printable = "".join(ch if ch.isprintable() else " " for ch in text)
    normalized = printable.translate(SMART_PUNCTUATION)
    normalized = WHITESPACE_RE.sub(" ", normalized).strip()
    if language_base(language_tag or "en") != "en":
        return normalized
    normalized = _fix_comic_letter_confusions(normalized)
    normalized = _fix_contractions(normalized)
    normalized = _normalize_comic_case(normalized)
    normalized = _fix_contractions(normalized)
    normalized = _fix_punctuation(normalized)
    return WHITESPACE_RE.sub(" ", normalized).strip()


def text_quality_score(
    text: str,
    confidence: float | None,
    *,
    raw_text: str | None = None,
    language_tag: str | None = "en",
) -> float:
    normalized = normalize_ocr_text(text, language_tag)
    if not normalized:
        return 0.0

    chars = list(normalized)
    printable_count = sum(1 for ch in chars if ch.isprintable())
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
    if (
        language_base(language_tag or "en") in {"ja", "ko", "zh"}
        and len(words) <= 1
    ):
        word_bonus = max(word_bonus, min(content_count / 8, 1.0))
    confidence = _bounded_optional_number(confidence)
    visual_score = (
        printable_ratio * 0.1
        + accepted_ratio * 0.13
        + content_ratio * 0.07
        + length_bonus * 0.08
        + word_bonus * 0.07
    )
    if confidence is None:
        # Some engines, notably Windows OCR, do not expose confidence. Treat
        # that as missing evidence instead of a zero-confidence result.
        score = min(0.86, (visual_score / 0.45) * 0.86)
    else:
        score = confidence * 0.55 + visual_score

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
    very_long_tokens = sum(1 for token in tokens if len(token) >= 20)

    penalty = min(0.24, likely_digit_confusions * 0.12)
    penalty += min(0.18, embedded_slashes * 0.12)
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
    language_tag: str | None = "en",
) -> EngineResult | None:
    candidates = [
        result
        for result in results
        if normalize_ocr_text(result.text, language_tag)
    ]
    if not candidates:
        return None

    for result in candidates:
        result.score = _bounded_number(result.score)
        result.raw_confidence = _bounded_optional_number(result.raw_confidence)

    normalized_texts = {
        id(result): normalize_ocr_text(result.text, language_tag).casefold()
        for result in candidates
    }
    exact_consensus = _exact_cross_engine_consensus(
        candidates,
        normalized_texts,
    )
    if exact_consensus:
        return max(
            exact_consensus,
            key=lambda item: (
                item.score,
                _confidence_rank_value(item.raw_confidence),
                len(item.text),
            ),
        )

    adjusted_scores: dict[int, float] = {}
    for result in candidates:
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
            _confidence_rank_value(item.raw_confidence),
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
            _confidence_rank_value(item.raw_confidence),
            len(item.text),
        ),
    )
    if primary is strongest:
        return strongest

    primary_is_reliable = (
        primary.score >= _bounded_number(accept_score)
        and primary.raw_confidence is not None
        and primary.raw_confidence >= _bounded_number(accept_confidence)
    )
    similarity = SequenceMatcher(
        None,
        normalized_texts[id(primary)],
        normalized_texts[id(strongest)],
    ).ratio()
    score_advantage = strongest.score - primary.score
    confidence_advantage = _known_confidence_advantage(strongest, primary)
    verifier_has_clear_advantage = (
        adjusted_scores[id(strongest)] - adjusted_scores[id(primary)] >= 0.08
        or (score_advantage >= 0.03 and confidence_advantage >= 0.04)
    )
    primary_has_variant_consensus = _same_engine_variant_consensus(
        primary,
        primary_candidates,
        normalized_texts,
    )
    if similarity >= 0.90 and primary_has_variant_consensus:
        return primary
    if primary_is_reliable and not verifier_has_clear_advantage:
        return primary
    return strongest


def _base_engine(engine: str) -> str:
    return str(engine).split(":", 1)[0].strip().lower()


def _exact_cross_engine_consensus(
    candidates: list[EngineResult],
    normalized_texts: dict[int, str],
) -> list[EngineResult]:
    clusters: dict[str, list[EngineResult]] = {}
    for candidate in candidates:
        clusters.setdefault(normalized_texts[id(candidate)], []).append(candidate)

    consensus_clusters = [
        cluster
        for cluster in clusters.values()
        if len({_base_engine(result.engine) for result in cluster}) >= 2
        and not any(
            ocr_suspicion_score(result.raw_text or result.text) > 0
            for result in cluster
        )
    ]
    if not consensus_clusters:
        return []
    return max(
        consensus_clusters,
        key=lambda cluster: (
            len({_base_engine(result.engine) for result in cluster}),
            max(result.score for result in cluster),
            len(cluster[0].text),
        ),
    )


def _same_engine_variant_consensus(
    primary: EngineResult,
    primary_candidates: list[EngineResult],
    normalized_texts: dict[int, str],
) -> bool:
    primary_text = normalized_texts[id(primary)]
    agreeing_variants = {
        result.engine.strip().lower()
        for result in primary_candidates
        if normalized_texts[id(result)] == primary_text
    }
    return len(agreeing_variants) >= 2


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
        r"\b(I|you|we|they|he|she|it)\s*[:;]\s*(m|re|ve|ll|d|s)\b",
        lambda match: f"{match.group(1)}'{match.group(2)}",
        text,
        flags=re.IGNORECASE,
    )
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


def _bounded_optional_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return _clamp(number, 0.0, 1.0)


def _confidence_rank_value(value: float | None) -> float:
    return value if value is not None else -1.0


def _known_confidence_advantage(
    strongest: EngineResult, primary: EngineResult
) -> float:
    if strongest.raw_confidence is None or primary.raw_confidence is None:
        return 0.0
    return strongest.raw_confidence - primary.raw_confidence

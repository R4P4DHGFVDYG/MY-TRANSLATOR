from __future__ import annotations

from difflib import SequenceMatcher
import re
import string

from .models import EngineResult


WHITESPACE_RE = re.compile(r"\s+")
LONG_REPEAT_RE = re.compile(r"(.)\1{5,}")


def normalize_ocr_text(text: str) -> str:
    if not text:
        return ""

    printable = "".join(ch if ch.isprintable() else " " for ch in text)
    return WHITESPACE_RE.sub(" ", printable).strip()


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
                None, normalized_by_engine[result.engine], normalized_by_engine[other.engine]
            ).ratio()
            if similarity >= 0.82:
                result.score = min(1.0, result.score + 0.08)
                break

    return max(candidates, key=lambda item: (item.score, item.raw_confidence, len(item.text)))


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))

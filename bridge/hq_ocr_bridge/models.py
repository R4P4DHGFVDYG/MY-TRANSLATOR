from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass
class EngineResult:
    engine: str
    text: str
    score: float
    raw_confidence: float = 0.0
    warning: str | None = None
    raw_text: str | None = None

    def to_dict(self) -> dict:
        score = _finite_float(self.score)
        raw_confidence = _finite_float(self.raw_confidence)
        data = {
            "engine": self.engine,
            "text": self.text,
            "score": round(score, 4),
        }
        if raw_confidence:
            data["rawConfidence"] = round(raw_confidence, 4)
        if self.warning:
            data["warning"] = self.warning
        if self.raw_text and self.raw_text != self.text:
            data["rawText"] = self.raw_text

        return data


def _finite_float(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0

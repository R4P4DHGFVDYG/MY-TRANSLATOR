from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EngineResult:
    engine: str
    text: str
    score: float
    raw_confidence: float = 0.0
    warning: str | None = None
    raw_text: str | None = None

    def to_dict(self) -> dict:
        data = {
            "engine": self.engine,
            "text": self.text,
            "score": round(float(self.score), 4),
        }
        if self.raw_confidence:
            data["rawConfidence"] = round(float(self.raw_confidence), 4)
        if self.warning:
            data["warning"] = self.warning
        if self.raw_text and self.raw_text != self.text:
            data["rawText"] = self.raw_text

        return data

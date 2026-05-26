from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EngineResult:
    engine: str
    text: str
    score: float
    raw_confidence: float = 0.0
    warning: str | None = None

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

        return data

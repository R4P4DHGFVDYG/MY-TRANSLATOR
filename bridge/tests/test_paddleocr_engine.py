from __future__ import annotations

from PIL import Image

from hq_ocr_bridge.config import BridgeConfig
from hq_ocr_bridge.models import EngineResult
from hq_ocr_bridge.ocr import DEFAULT_ENGINES, OcrService


def test_default_engines_prefer_paddleocr_then_easyocr():
    assert DEFAULT_ENGINES == ["paddleocr", "easyocr"]


def test_paddleocr_engine_can_be_requested(monkeypatch):
    service = OcrService(BridgeConfig())

    def fake_paddleocr(image):
        return EngineResult("paddleocr", "HELLO WORLD", 0.9, 0.9)

    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["paddleocr"],
    )

    assert warnings == []
    assert best is not None
    assert best.text == "HELLO WORLD"
    assert [result.engine for result in results] == ["paddleocr:standard"]

from __future__ import annotations

import threading

from hq_ocr_bridge.config import BridgeConfig
from hq_ocr_bridge.ocr import OcrService


def test_ocr_warmup_runs_requested_engines_in_parallel(monkeypatch):
    service = OcrService(BridgeConfig(ocr_max_parallel_engines=3))
    barrier = threading.Barrier(3)
    calls: list[str] = []
    calls_lock = threading.Lock()

    def fake_warmup(engine: str) -> None:
        with calls_lock:
            calls.append(engine)
        barrier.wait(timeout=2)

    monkeypatch.setattr(service, "_warm_up_engine", fake_warmup)

    warnings = service.warm_up(["tesseract", "windowsocr", "paddleocr"])

    assert warnings == []
    assert set(calls) == {"tesseract", "windowsocr", "paddleocr"}
    assert set(service.health_checks()["settings"]["lastWarmupMs"]) == set(calls)


def test_ocr_warmup_reports_failures_without_stopping_other_engines(monkeypatch):
    service = OcrService(BridgeConfig(ocr_max_parallel_engines=3))
    calls: list[str] = []

    def fake_warmup(engine: str) -> None:
        calls.append(engine)
        if engine == "paddleocr":
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(service, "_warm_up_engine", fake_warmup)

    warnings = service.warm_up(["tesseract", "paddleocr", "unknown"])

    assert set(calls) == {"tesseract", "paddleocr"}
    assert warnings == [
        "paddleocr warmup failed: model unavailable",
        "unknown warmup failed: unsupported OCR engine",
    ]

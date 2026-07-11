from __future__ import annotations

import time

from PIL import Image
import pytest

from hq_ocr_bridge.config import BridgeConfig
from hq_ocr_bridge.models import EngineResult
from hq_ocr_bridge.ocr import (
    DEFAULT_ENGINES,
    OcrCancelledError,
    OcrCapacityError,
    OcrService,
)


def test_default_engine_uses_the_low_latency_paddle_path():
    assert DEFAULT_ENGINES == ["paddleocr"]


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


def test_ocr_max_variants_limits_easyocr_work(monkeypatch):
    service = OcrService(
        BridgeConfig(
            allowed_ocr_engines=("paddleocr", "easyocr", "tesseract"),
            ocr_max_variants=1,
        )
    )

    def fake_easyocr(image):
        return EngineResult("easyocr", "HELLO WORLD", 0.9, 0.9)

    monkeypatch.setattr(service, "_run_easyocr", fake_easyocr)

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["easyocr"],
    )

    assert warnings == []
    assert best is not None
    assert [result.engine for result in results] == ["easyocr:standard"]


def test_ocr_cache_skips_unchanged_pixels(monkeypatch):
    service = OcrService(BridgeConfig())
    calls = 0

    def fake_paddleocr(image):
        nonlocal calls
        calls += 1
        return EngineResult("paddleocr", "HELLO WORLD", 0.9, 0.9)

    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)
    image = Image.new("RGB", (120, 40), "white")

    first = service.detect_text_with_metadata(image, ["paddleocr"])
    second = service.detect_text_with_metadata(image.copy(), ["paddleocr"])

    assert calls == 1
    assert first[3] == {"cacheHit": False}
    assert second[3] == {"cacheHit": True}
    assert second[0] is not first[0]


def test_ocr_cancellation_discards_work_before_another_variant(monkeypatch):
    service = OcrService(
        BridgeConfig(
            allowed_ocr_engines=("paddleocr", "easyocr", "tesseract"),
            ocr_max_variants=3,
        )
    )
    cancelled = False
    calls = 0

    def fake_easyocr(image):
        nonlocal cancelled, calls
        calls += 1
        cancelled = True
        return EngineResult("easyocr", "OLD TEXT", 0.9, 0.9)

    monkeypatch.setattr(service, "_run_easyocr", fake_easyocr)

    image = Image.new("RGB", (120, 40), "white")
    with pytest.raises(OcrCancelledError, match="superseded"):
        service.detect_text_with_metadata(
            image,
            ["easyocr"],
            cancel_check=lambda: cancelled,
        )

    assert calls == 1


def test_completed_single_variant_is_cached_even_if_response_is_cancelled(monkeypatch):
    service = OcrService(BridgeConfig())
    cancelled = False
    calls = 0

    def fake_paddleocr(image):
        nonlocal cancelled, calls
        calls += 1
        cancelled = True
        return EngineResult("paddleocr", "LATEST TEXT", 0.9, 0.9)

    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)
    image = Image.new("RGB", (120, 40), "white")

    with pytest.raises(OcrCancelledError, match="superseded"):
        service.detect_text_with_metadata(
            image,
            ["paddleocr"],
            cancel_check=lambda: cancelled,
        )

    _best, _results, _warnings, metadata = service.detect_text_with_metadata(
        image, ["paddleocr"]
    )

    assert calls == 1
    assert metadata == {"cacheHit": True}


def test_ocr_engine_timeout_returns_warning(monkeypatch):
    service = OcrService(BridgeConfig(ocr_engine_timeout_seconds=0.01))

    def slow_paddleocr(image):
        time.sleep(0.1)
        return EngineResult("paddleocr", "HELLO WORLD", 0.9, 0.9)

    monkeypatch.setattr(service, "_run_paddleocr", slow_paddleocr)

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["paddleocr"],
    )

    assert best is None
    assert results[0].engine == "paddleocr:standard"
    assert "timed out" in warnings[0]


def test_ocr_rejects_requests_when_its_bounded_capacity_is_exhausted():
    service = OcrService(
        BridgeConfig(
            ocr_max_concurrent_requests=1,
            ocr_queue_timeout_seconds=0,
        )
    )
    assert service._request_slots.acquire(blocking=False)

    try:
        with pytest.raises(OcrCapacityError, match="busy"):
            service.detect_text(Image.new("RGB", (120, 40), "white"), ["paddleocr"])
    finally:
        service._request_slots.release()

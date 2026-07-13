from __future__ import annotations

import time

import threading

from PIL import Image
import pytest

from hq_ocr_bridge.config import BridgeConfig
from hq_ocr_bridge.models import EngineResult
from hq_ocr_bridge.ocr import (
    DEFAULT_ENGINES,
    OcrCancelledError,
    OcrCapacityError,
    OcrService,
    _filtered_tesseract_words,
    _ordered_paddleocr_fragments,
)


def test_default_engine_uses_windows_tesseract():
    assert DEFAULT_ENGINES == ["tesseract"]


def test_windows_ocr_engine_can_be_requested(monkeypatch):
    service = OcrService(BridgeConfig(ocr_max_variants=1))
    monkeypatch.setattr(
        service,
        "_run_windowsocr",
        lambda _image, _language=None: EngineResult(
            "windowsocr", "HELLO WINDOWS", 0.0, 0.0
        ),
    )

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["windowsocr"],
    )

    assert warnings == []
    assert best is not None
    assert best.text == "HELLO WINDOWS"
    assert [result.engine for result in results] == ["windowsocr:binary"]


def test_windows_ocr_compares_binary_and_standard_without_fake_confidence(
    monkeypatch,
):
    service = OcrService(BridgeConfig(ocr_max_variants=2))
    seen_modes: list[str] = []

    class FakeAdapter:
        def recognize(self, image, language_tag=None):
            seen_modes.append(image.mode)
            assert language_tag == "pt-BR"
            return "TEXTO"

    monkeypatch.setattr(service, "_get_windowsocr_adapter", lambda: FakeAdapter())

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["windowsocr"],
        language_tag="pt-BR",
    )

    assert warnings == []
    assert best is not None
    assert best.text == "TEXTO"
    assert seen_modes == ["L", "RGB"]
    assert [result.engine for result in results] == [
        "windowsocr:binary",
        "windowsocr:standard",
    ]
    assert all(result.raw_confidence is None for result in results)
    assert all(result.to_dict()["confidenceKnown"] is False for result in results)


def test_windows_ocr_cache_is_scoped_by_source_language(monkeypatch):
    service = OcrService(BridgeConfig(ocr_max_variants=1))
    languages: list[str | None] = []

    def fake_windowsocr(_image, language_tag=None):
        languages.append(language_tag)
        return EngineResult("windowsocr", str(language_tag), 0.0, 0.0)

    monkeypatch.setattr(service, "_run_windowsocr", fake_windowsocr)
    image = Image.new("RGB", (120, 40), "white")

    service.detect_text(image, ["windowsocr"], language_tag="en")
    service.detect_text(image.copy(), ["windowsocr"], language_tag="pt-BR")

    assert languages == ["en", "pt-BR"]


def test_automatic_chain_continues_when_windows_ocr_is_unavailable(monkeypatch):
    service = OcrService(
        BridgeConfig(ocr_parallel_engines=False, ocr_max_variants=1)
    )
    paddle_calls = 0

    monkeypatch.setattr(
        service,
        "_run_tesseract",
        lambda _image: EngineResult("tesseract", "H3LL0", 0.4, 0.4),
    )

    def unavailable_windowsocr(_image, _language=None):
        raise RuntimeError("Windows OCR support is not installed")

    def fake_paddleocr(_image):
        nonlocal paddle_calls
        paddle_calls += 1
        return EngineResult("paddleocr", "HELLO", 0.95, 0.95)

    monkeypatch.setattr(service, "_run_windowsocr", unavailable_windowsocr)
    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract", "windowsocr", "paddleocr"],
        language_tag="en",
    )

    assert best is not None
    assert best.text == "HELLO"
    assert paddle_calls == 1
    assert "windowsocr failed" in warnings[0]
    assert [result.engine for result in results] == [
        "tesseract:standard",
        "windowsocr:binary",
        "paddleocr:standard",
    ]


def test_automatic_profile_runs_fast_engines_in_parallel_and_skips_paddle_on_consensus(
    monkeypatch,
):
    service = OcrService(
        BridgeConfig(ocr_max_variants=1, ocr_max_parallel_engines=2)
    )
    rendezvous = threading.Barrier(2)
    paddle_calls = 0

    def fake_tesseract(_image):
        rendezvous.wait(timeout=1)
        return EngineResult("tesseract", "HELLO WORLD", 0.95, 0.95)

    def fake_windowsocr(_image, _language=None):
        rendezvous.wait(timeout=1)
        return EngineResult("windowsocr", "HELLO WORLD", 0.0, None)

    def fake_paddleocr(_image):
        nonlocal paddle_calls
        paddle_calls += 1
        return EngineResult("paddleocr", "SHOULD NOT RUN", 0.99, 0.99)

    monkeypatch.setattr(service, "_run_tesseract", fake_tesseract)
    monkeypatch.setattr(service, "_run_windowsocr", fake_windowsocr)
    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract", "windowsocr", "paddleocr"],
        language_tag="en",
    )

    assert warnings == []
    assert best is not None
    assert best.text == "HELLO WORLD"
    assert paddle_calls == 0
    assert {_result.engine.split(":", 1)[0] for _result in results} == {
        "tesseract",
        "windowsocr",
    }


def test_automatic_profile_stops_after_first_variant_when_fast_engines_agree(
    monkeypatch,
):
    service = OcrService(
        BridgeConfig(ocr_max_variants=2, ocr_max_parallel_engines=2)
    )
    calls = {"tesseract": 0, "windowsocr": 0, "paddleocr": 0}

    def fake_tesseract(_image):
        calls["tesseract"] += 1
        return EngineResult("tesseract", "HELLO WORLD", 0.91, 0.91)

    def fake_windowsocr(_image, _language=None):
        calls["windowsocr"] += 1
        return EngineResult("windowsocr", "HELLO WORLD", 0.0, None)

    def fake_paddleocr(_image):
        calls["paddleocr"] += 1
        return EngineResult("paddleocr", "SHOULD NOT RUN", 0.99, 0.99)

    monkeypatch.setattr(service, "_run_tesseract", fake_tesseract)
    monkeypatch.setattr(service, "_run_windowsocr", fake_windowsocr)
    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract", "windowsocr", "paddleocr"],
    )

    assert warnings == []
    assert best is not None
    assert best.text == "HELLO WORLD"
    assert calls == {"tesseract": 1, "windowsocr": 1, "paddleocr": 0}
    assert len(results) == 2


def test_automatic_profile_accepts_safe_punctuation_only_consensus(monkeypatch):
    service = OcrService(BridgeConfig(ocr_max_variants=2))
    calls = {"tesseract": 0, "windowsocr": 0, "paddleocr": 0}

    def fake_tesseract(_image):
        calls["tesseract"] += 1
        return EngineResult("tesseract", "Hello, brave world!", 0.95, 0.95)

    def fake_windowsocr(_image, _language=None):
        calls["windowsocr"] += 1
        return EngineResult("windowsocr", "Hello brave world", 0.0, None)

    def fake_paddleocr(_image):
        calls["paddleocr"] += 1
        return EngineResult("paddleocr", "SHOULD NOT RUN", 0.99, 0.99)

    monkeypatch.setattr(service, "_run_tesseract", fake_tesseract)
    monkeypatch.setattr(service, "_run_windowsocr", fake_windowsocr)
    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract", "windowsocr", "paddleocr"],
    )

    assert warnings == []
    assert best is not None
    assert best.text == "Hello, brave world!"
    assert calls == {"tesseract": 1, "windowsocr": 1, "paddleocr": 0}
    assert len(results) == 2


def test_automatic_profile_accepts_one_safe_letter_difference_in_long_text(
    monkeypatch,
):
    service = OcrService(BridgeConfig(ocr_max_variants=2))
    calls = {"tesseract": 0, "windowsocr": 0, "paddleocr": 0}

    def fake_tesseract(_image):
        calls["tesseract"] += 1
        return EngineResult(
            "tesseract",
            "Follow your brother through the dark forest",
            0.94,
            0.94,
        )

    def fake_windowsocr(_image, _language=None):
        calls["windowsocr"] += 1
        return EngineResult(
            "windowsocr",
            "Follow your brotner through the dark forest",
            0.0,
            None,
        )

    def fake_paddleocr(_image):
        calls["paddleocr"] += 1
        return EngineResult("paddleocr", "SHOULD NOT RUN", 0.99, 0.99)

    monkeypatch.setattr(service, "_run_tesseract", fake_tesseract)
    monkeypatch.setattr(service, "_run_windowsocr", fake_windowsocr)
    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, _results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract", "windowsocr", "paddleocr"],
    )

    assert warnings == []
    assert best is not None
    assert best.text == "Follow your brother through the dark forest"
    assert calls == {"tesseract": 1, "windowsocr": 1, "paddleocr": 0}


def test_automatic_profile_sends_digit_letter_disagreement_to_paddle(monkeypatch):
    service = OcrService(BridgeConfig(ocr_max_variants=1))
    paddle_calls = 0
    expected = "Follow your brother through the dark forest"

    monkeypatch.setattr(
        service,
        "_run_tesseract",
        lambda _image: EngineResult("tesseract", expected, 0.94, 0.94),
    )
    monkeypatch.setattr(
        service,
        "_run_windowsocr",
        lambda _image, _language=None: EngineResult(
            "windowsocr",
            "Follow your br0ther through the dark forest",
            0.0,
            None,
        ),
    )

    def fake_paddleocr(_image):
        nonlocal paddle_calls
        paddle_calls += 1
        return EngineResult("paddleocr", expected, 0.98, 0.98)

    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, _results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract", "windowsocr", "paddleocr"],
    )

    assert warnings == []
    assert paddle_calls == 1
    assert best is not None
    assert best.text == expected


def test_automatic_profile_sends_short_one_letter_disagreement_to_paddle(
    monkeypatch,
):
    service = OcrService(BridgeConfig(ocr_max_variants=1))
    paddle_calls = 0

    monkeypatch.setattr(
        service,
        "_run_tesseract",
        lambda _image: EngineResult("tesseract", "Take it", 0.95, 0.95),
    )
    monkeypatch.setattr(
        service,
        "_run_windowsocr",
        lambda _image, _language=None: EngineResult(
            "windowsocr", "Make it", 0.0, None
        ),
    )

    def fake_paddleocr(_image):
        nonlocal paddle_calls
        paddle_calls += 1
        return EngineResult("paddleocr", "Take it", 0.98, 0.98)

    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, _results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract", "windowsocr", "paddleocr"],
    )

    assert warnings == []
    assert paddle_calls == 1
    assert best is not None
    assert best.text == "Take it"


def test_automatic_profile_uses_paddle_when_fast_engines_disagree(monkeypatch):
    service = OcrService(BridgeConfig(ocr_max_variants=1))
    paddle_calls = 0

    monkeypatch.setattr(
        service,
        "_run_tesseract",
        lambda _image: EngineResult("tesseract", "HELLO W0RLD", 0.8, 0.8),
    )
    monkeypatch.setattr(
        service,
        "_run_windowsocr",
        lambda _image, _language=None: EngineResult(
            "windowsocr", "HELLO WORLD", 0.0, None
        ),
    )

    def fake_paddleocr(_image):
        nonlocal paddle_calls
        paddle_calls += 1
        return EngineResult("paddleocr", "HELLO WORLD", 0.96, 0.96)

    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract", "windowsocr", "paddleocr"],
    )

    assert warnings == []
    assert paddle_calls == 1
    assert best is not None
    assert best.text == "HELLO WORLD"
    assert any(result.engine.startswith("paddleocr:") for result in results)


def test_automatic_profile_verifies_suspicious_fast_consensus_with_paddle(
    monkeypatch,
):
    service = OcrService(BridgeConfig(ocr_max_variants=1))
    paddle_calls = 0

    monkeypatch.setattr(
        service,
        "_run_tesseract",
        lambda _image: EngineResult("tesseract", "H3LLO", 0.91, 0.91),
    )
    monkeypatch.setattr(
        service,
        "_run_windowsocr",
        lambda _image, _language=None: EngineResult(
            "windowsocr", "H3LLO", 0.0, None
        ),
    )

    def fake_paddleocr(_image):
        nonlocal paddle_calls
        paddle_calls += 1
        return EngineResult("paddleocr", "HELLO", 0.97, 0.97)

    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, _results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract", "windowsocr", "paddleocr"],
    )

    assert warnings == []
    assert paddle_calls == 1
    assert best is not None
    assert best.text == "HELLO"


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


def test_tesseract_filters_large_portrait_artifacts_and_detached_noise():
    data = {
        "text": ["(3)", "put", "honey", "CO", "honey?"],
        "conf": [26, 96, 94, 43, 95],
        "left": [76, 336, 464, 44, 336],
        "width": [125, 88, 152, 196, 184],
        "height": [124, 48, 48, 52, 48],
        "block_num": [1, 1, 1, 1, 1],
        "par_num": [1, 1, 1, 1, 1],
        "line_num": [2, 2, 2, 3, 3],
        "word_num": [1, 2, 3, 1, 2],
    }

    assert _filtered_tesseract_words(data) == [
        ("put", 96.0),
        ("honey", 94.0),
        ("honey?", 95.0),
    ]


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


def test_low_quality_result_tries_a_second_preprocess_variant(monkeypatch):
    service = OcrService(BridgeConfig(ocr_max_variants=2))
    calls: list[str] = []

    def fake_easyocr(image):
        calls.append(image.mode)
        if image.mode == "RGB":
            return EngineResult("easyocr", "H3LL0", 0.4, 0.4)
        return EngineResult("easyocr", "HELLO", 0.95, 0.95)

    monkeypatch.setattr(service, "_run_easyocr", fake_easyocr)

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["easyocr"],
    )

    assert warnings == []
    assert calls == ["RGB", "L"]
    assert [result.engine for result in results] == [
        "easyocr:standard",
        "easyocr:contrast",
    ]
    assert best is not None
    assert best.text == "HELLO"


def test_adaptive_engine_chain_skips_fallback_for_reliable_primary(monkeypatch):
    service = OcrService(BridgeConfig(ocr_parallel_engines=False))
    paddle_calls = 0

    monkeypatch.setattr(
        service,
        "_run_tesseract",
        lambda _image: EngineResult("tesseract", "CLEAR SUBTITLE", 0.95, 0.95),
    )

    def fake_paddleocr(_image):
        nonlocal paddle_calls
        paddle_calls += 1
        return EngineResult("paddleocr", "UNNECESSARY", 0.99, 0.99)

    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract", "paddleocr"],
    )

    assert warnings == []
    assert best is not None
    assert best.text == "CLEAR SUBTITLE"
    assert paddle_calls == 0
    assert [result.engine for result in results] == [
        "tesseract:standard",
        "tesseract:pixel",
    ]


def test_adaptive_engine_chain_uses_fallback_when_tesseract_variants_disagree(
    monkeypatch,
):
    service = OcrService(BridgeConfig(ocr_parallel_engines=False))
    tesseract_calls = 0
    paddle_calls = 0

    def fake_tesseract(_image):
        nonlocal tesseract_calls
        tesseract_calls += 1
        text = "S50 WHAT" if tesseract_calls == 1 else "SO WHAT"
        return EngineResult("tesseract", text, 0.95, 0.95)

    def fake_paddleocr(_image):
        nonlocal paddle_calls
        paddle_calls += 1
        return EngineResult("paddleocr", "SO WHAT", 0.94, 0.96)

    monkeypatch.setattr(service, "_run_tesseract", fake_tesseract)
    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract", "paddleocr"],
    )

    assert warnings == []
    assert best is not None
    assert best.text == "SO WHAT"
    assert paddle_calls == 1
    assert [result.engine for result in results] == [
        "tesseract:standard",
        "tesseract:pixel",
        "paddleocr:standard",
    ]


def test_tesseract_tries_binary_when_first_two_variants_disagree(monkeypatch):
    service = OcrService(BridgeConfig(ocr_max_variants=3))
    calls = 0

    def fake_tesseract(_image):
        nonlocal calls
        calls += 1
        texts = ["S50 WHAT", "SO WHAT", "SO WHAT"]
        return EngineResult("tesseract", texts[calls - 1], 0.95, 0.95)

    monkeypatch.setattr(service, "_run_tesseract", fake_tesseract)

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract"],
    )

    assert warnings == []
    assert best is not None
    assert calls == 3
    assert [result.engine for result in results] == [
        "tesseract:standard",
        "tesseract:pixel",
        "tesseract:binary",
    ]


def test_empty_second_tesseract_variant_allows_paddle_fallback(monkeypatch):
    service = OcrService(BridgeConfig(ocr_parallel_engines=False))
    tesseract_calls = 0
    paddle_calls = 0

    def fake_tesseract(_image):
        nonlocal tesseract_calls
        tesseract_calls += 1
        text = "CLEAR SUBTITLE" if tesseract_calls == 1 else ""
        confidence = 0.95 if text else 0.0
        return EngineResult("tesseract", text, confidence, confidence)

    def fake_paddleocr(_image):
        nonlocal paddle_calls
        paddle_calls += 1
        return EngineResult("paddleocr", "CLEAR SUBTITLE", 0.95, 0.95)

    monkeypatch.setattr(service, "_run_tesseract", fake_tesseract)
    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, _results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract", "paddleocr"],
    )

    assert warnings == []
    assert best is not None
    assert best.text == "CLEAR SUBTITLE"
    assert paddle_calls == 1


def test_adaptive_engine_chain_uses_fallback_for_uncertain_primary(monkeypatch):
    service = OcrService(
        BridgeConfig(ocr_parallel_engines=False, ocr_max_variants=1)
    )
    paddle_calls = 0

    monkeypatch.setattr(
        service,
        "_run_tesseract",
        lambda _image: EngineResult("tesseract", "H3LL0", 0.4, 0.4),
    )

    def fake_paddleocr(_image):
        nonlocal paddle_calls
        paddle_calls += 1
        return EngineResult("paddleocr", "HELLO", 0.95, 0.95)

    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract", "paddleocr"],
    )

    assert warnings == []
    assert best is not None
    assert best.text == "HELLO"
    assert paddle_calls == 1
    assert [result.engine for result in results] == [
        "tesseract:standard",
        "paddleocr:standard",
    ]


def test_single_variant_override_accepts_reliable_tesseract(monkeypatch):
    service = OcrService(
        BridgeConfig(ocr_parallel_engines=False, ocr_max_variants=1)
    )
    paddle_calls = 0

    monkeypatch.setattr(
        service,
        "_run_tesseract",
        lambda _image: EngineResult("tesseract", "CLEAR SUBTITLE", 0.95, 0.95),
    )

    def fake_paddleocr(_image):
        nonlocal paddle_calls
        paddle_calls += 1
        return EngineResult("paddleocr", "UNNECESSARY", 0.99, 0.99)

    monkeypatch.setattr(service, "_run_paddleocr", fake_paddleocr)

    best, results, warnings = service.detect_text(
        Image.new("RGB", (120, 40), "white"),
        ["tesseract", "paddleocr"],
    )

    assert warnings == []
    assert best is not None
    assert best.text == "CLEAR SUBTITLE"
    assert paddle_calls == 0
    assert [result.engine for result in results] == ["tesseract:standard"]


def test_easyocr_uses_accuracy_focused_decoder_without_png_reencoding(monkeypatch):
    service = OcrService(BridgeConfig())
    captured: dict = {}

    class FakeReader:
        def readtext(self, image, **kwargs):
            captured["image"] = image
            captured.update(kwargs)
            return [([0, 0, 1, 1], "HELLO", 0.9)]

    monkeypatch.setattr(service, "_get_easyocr_reader", lambda: FakeReader())

    result = service._run_easyocr(Image.new("RGB", (80, 30), "white"))

    assert result.text == "HELLO"
    assert captured["image"].shape == (30, 80, 3)
    assert captured["decoder"] == "beamsearch"
    assert captured["beamWidth"] == 5
    assert captured["mag_ratio"] == 1.5


def test_paddleocr_orders_fragments_by_visual_lines(monkeypatch):
    service = OcrService(BridgeConfig())

    class FakeReader:
        def predict(self, _image):
            return [
                {
                    "res": {
                        "rec_texts": ["SECOND", "FIRST", "FOURTH", "THIRD", ""],
                        "rec_scores": [0.8, 0.9, 0.6, 0.7, 0.99],
                        "rec_boxes": [
                            [110, 10, 200, 40],
                            [10, 12, 100, 42],
                            [110, 60, 200, 90],
                            [10, 62, 100, 92],
                            [0, 0, 5, 5],
                        ],
                    }
                }
            ]

    monkeypatch.setattr(service, "_get_paddleocr_reader", lambda: FakeReader())

    result = service._run_paddleocr(Image.new("RGB", (240, 120), "white"))

    assert result.text == "FIRST SECOND THIRD FOURTH"
    assert result.raw_confidence == pytest.approx(0.75)


@pytest.mark.parametrize("artifact", ["LE", "#"])
def test_paddleocr_filters_small_low_confidence_leading_artifact(artifact):
    payload = {
        "rec_texts": [artifact, "HELLO", "WORLD"],
        "rec_scores": [0.42, 0.96, 0.94],
        "rec_boxes": [
            [8, 18, 27, 34],
            [36, 10, 118, 42],
            [126, 10, 214, 42],
        ],
    }

    assert _ordered_paddleocr_fragments(payload) == [
        ("HELLO", 0.96),
        ("WORLD", 0.94),
    ]


def test_paddleocr_preserves_normal_sized_initial_word_with_low_confidence():
    payload = {
        "rec_texts": ["WELCOME", "HOME"],
        "rec_scores": [0.62, 0.95],
        "rec_boxes": [
            [8, 10, 126, 42],
            [134, 10, 210, 42],
        ],
    }

    assert _ordered_paddleocr_fragments(payload) == [
        ("WELCOME", 0.62),
        ("HOME", 0.95),
    ]


def test_paddleocr_preserves_confident_small_initial_fragment():
    payload = {
        "rec_texts": ["LE", "HELLO", "WORLD"],
        "rec_scores": [0.91, 0.96, 0.94],
        "rec_boxes": [
            [8, 18, 27, 34],
            [36, 10, 118, 42],
            [126, 10, 214, 42],
        ],
    }

    assert _ordered_paddleocr_fragments(payload) == [
        ("LE", 0.91),
        ("HELLO", 0.96),
        ("WORLD", 0.94),
    ]


@pytest.mark.parametrize("punctuation", ["(", '"', "...", "*"])
def test_paddleocr_preserves_small_leading_punctuation(punctuation):
    payload = {
        "rec_texts": [punctuation, "HELLO"],
        "rec_scores": [0.42, 0.96],
        "rec_boxes": [
            [8, 18, 20, 34],
            [28, 10, 110, 42],
        ],
    }

    assert _ordered_paddleocr_fragments(payload) == [
        (punctuation, 0.42),
        ("HELLO", 0.96),
    ]


def test_tesseract_uses_sparse_text_fallback_only_for_uncertain_primary(monkeypatch):
    service = OcrService(BridgeConfig())
    calls: list[int] = []

    monkeypatch.setattr(service, "_ensure_tesseract_available", lambda: None)

    def fake_pass(_image, psm):
        calls.append(psm)
        if psm == 6:
            return EngineResult("tesseract", "H3LL0", 0.4, 0.4)
        return EngineResult("tesseract", "HELLO", 0.95, 0.95)

    monkeypatch.setattr(service, "_run_tesseract_psm", fake_pass)

    result = service._run_tesseract(Image.new("RGB", (120, 40), "white"))

    assert calls == [6, 11]
    assert result.text == "HELLO"


def test_tesseract_skips_sparse_fallback_for_strong_primary(monkeypatch):
    service = OcrService(BridgeConfig())
    calls: list[int] = []

    monkeypatch.setattr(service, "_ensure_tesseract_available", lambda: None)

    def fake_pass(_image, psm):
        calls.append(psm)
        return EngineResult("tesseract", "CLEAR SUBTITLE", 0.96, 0.96)

    monkeypatch.setattr(service, "_run_tesseract_psm", fake_pass)

    service._run_tesseract(Image.new("RGB", (120, 40), "white"))

    assert calls == [6]


def test_tesseract_does_not_repeat_empty_page_with_image_to_string(monkeypatch):
    service = OcrService(BridgeConfig())
    image_to_string_calls = 0

    class FakePytesseract:
        @staticmethod
        def image_to_data(*_args, **_kwargs):
            return {
                "text": [],
                "conf": [],
                "left": [],
                "width": [],
                "height": [],
            }

        @staticmethod
        def image_to_string(*_args, **_kwargs):
            nonlocal image_to_string_calls
            image_to_string_calls += 1
            return ""

    import pytesseract

    monkeypatch.setattr(pytesseract, "image_to_data", FakePytesseract.image_to_data)
    monkeypatch.setattr(
        pytesseract, "image_to_string", FakePytesseract.image_to_string
    )

    result = service._run_tesseract_psm(
        Image.new("RGB", (120, 40), "white"),
        6,
    )

    assert result.text == ""
    assert image_to_string_calls == 0


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

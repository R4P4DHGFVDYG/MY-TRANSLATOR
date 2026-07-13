from __future__ import annotations

import pytest

from hq_ocr_bridge.config import BridgeConfig


def test_performance_env_vars_are_loaded(monkeypatch):
    monkeypatch.setenv("HQ_OCR_REQUEST_TIMEOUT_SECONDS", "4.5")
    monkeypatch.setenv("HQ_OCR_DEFAULT_ENGINES", "paddleocr")
    monkeypatch.setenv("HQ_OCR_FORCE_ENGINES", "true")
    monkeypatch.setenv("HQ_OCR_ENGINE_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("HQ_OCR_PARALLEL_ENGINES", "1")
    monkeypatch.setenv("HQ_OCR_MAX_VARIANTS", "1")
    monkeypatch.setenv("HQ_OCR_ACCEPT_SCORE", "0.75")
    monkeypatch.setenv("HQ_OCR_ACCEPT_CONFIDENCE", "0.7")
    monkeypatch.setenv("HQ_OCR_WARMUP_ON_START", "yes")
    monkeypatch.setenv(
        "HQ_OCR_WARMUP_ENGINES", "windowsocr,tesseract,paddleocr"
    )
    monkeypatch.setenv("HQ_OCR_EASYOCR_GPU", "on")
    monkeypatch.setenv("HQ_OCR_WINDOWS_LANG", "pt-BR")

    config = BridgeConfig.from_env()

    assert config.request_timeout_seconds == 4.5
    assert config.default_ocr_engines == ("paddleocr",)
    assert config.force_ocr_engines is True
    assert config.ocr_engine_timeout_seconds == 3
    assert config.ocr_parallel_engines is True
    assert config.ocr_max_variants == 1
    assert config.ocr_accept_score == 0.75
    assert config.ocr_accept_confidence == 0.7
    assert config.ocr_warmup_on_start is True
    assert config.ocr_warmup_engines == (
        "windowsocr",
        "tesseract",
        "paddleocr",
    )
    assert config.paddleocr_max_pixels == 1_500_000
    assert config.easyocr_gpu is True
    assert config.windows_ocr_lang == "pt-BR"


def test_config_exposes_safety_limits_and_tesseract_default(
    monkeypatch,
):
    monkeypatch.setenv("HQ_OCR_MAX_REQUEST_BYTES", "2048")
    monkeypatch.setenv("HQ_OCR_MAX_IMAGE_BYTES", "1024")
    monkeypatch.setenv("HQ_OCR_MAX_CONCURRENT_REQUESTS", "2")
    monkeypatch.setenv("HQ_OCR_CORS_ALLOWED_ORIGINS", "chrome-extension://trusted")

    config = BridgeConfig.from_env()

    assert config.max_request_bytes == 2048
    assert config.max_image_bytes == 1024
    assert config.ocr_max_concurrent_requests == 2
    assert config.cors_allowed_origins == ("chrome-extension://trusted",)
    assert config.paddleocr_detection_model == "PP-OCRv5_mobile_det"
    assert config.paddleocr_recognition_model == "en_PP-OCRv5_mobile_rec"
    assert config.default_ocr_engines == ("tesseract",)
    assert config.allowed_ocr_engines == (
        "windowsocr",
        "paddleocr",
        "easyocr",
        "tesseract",
    )
    assert config.windows_ocr_lang == "en-US"
    assert config.ocr_max_variants == 2
    assert config.ocr_accept_score == 0.8
    assert config.ocr_accept_confidence == 0.78
    assert config.ocr_warmup_on_start is True
    assert config.ocr_warmup_engines == (
        "tesseract",
        "windowsocr",
        "paddleocr",
    )


def test_config_requires_both_named_paddle_models_and_explicit_cors_origins():
    with pytest.raises(ValueError, match="must be set together"):
        BridgeConfig(
            paddleocr_detection_model="det",
            paddleocr_recognition_model=None,
        )
    with pytest.raises(ValueError, match="explicit origins"):
        BridgeConfig(cors_allowed_origins=("*",))
    with pytest.raises(ValueError, match="paddleocr_max_pixels"):
        BridgeConfig(paddleocr_max_pixels=0)
    with pytest.raises(ValueError, match="ocr_accept_score"):
        BridgeConfig(ocr_accept_score=1.1)
    with pytest.raises(ValueError, match="ocr_accept_confidence"):
        BridgeConfig(ocr_accept_confidence=-0.1)
    with pytest.raises(ValueError, match="windows_ocr_lang"):
        BridgeConfig(windows_ocr_lang=" ")
    with pytest.raises(ValueError, match="ocr_warmup_engines"):
        BridgeConfig(ocr_warmup_engines=("imaginary",))


def test_warmup_engines_are_limited_to_allowed_engines():
    config = BridgeConfig(
        allowed_ocr_engines=("tesseract", "paddleocr"),
        ocr_warmup_engines=("windowsocr", "tesseract", "paddleocr"),
    )

    assert config.ocr_warmup_engines == ("tesseract", "paddleocr")


def test_config_reserves_request_space_for_base64_and_json_envelope():
    with pytest.raises(ValueError, match="Base64-encoded"):
        BridgeConfig(max_request_bytes=2_048, max_image_bytes=1_536)

    config = BridgeConfig(max_request_bytes=2_048, max_image_bytes=1_024)
    assert config.max_image_bytes == 1_024

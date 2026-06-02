from __future__ import annotations

from dataclasses import dataclass
import os


def _bool_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_from_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def _csv_from_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default

    items = tuple(item.strip().lower() for item in value.split(",") if item.strip())
    return items or default


@dataclass(frozen=True)
class BridgeConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    libretranslate_url: str = "http://127.0.0.1:5000"
    translation_providers: tuple[str, ...] = ("deepl", "google")
    google_translate_url: str = "https://translate.googleapis.com/translate_a/single"
    deepl_api_url: str = "https://api-free.deepl.com/v2/translate"
    deepl_auth_key: str | None = None
    request_timeout_seconds: float = 15.0
    easyocr_lang: str = "en"
    easyocr_model_dir: str | None = None
    allow_easyocr_download: bool = False
    paddleocr_lang: str = "en"
    paddleocr_ocr_version: str = "PP-OCRv5"
    paddleocr_detection_model: str = "PP-OCRv5_mobile_det"
    paddleocr_recognition_model: str = "en_PP-OCRv5_mobile_rec"
    paddleocr_cache_dir: str = ".paddlex-cache"
    paddleocr_model_source: str = "bos"
    paddleocr_enable_mkldnn: bool = False
    paddleocr_max_pixels: int = 700_000
    tesseract_lang: str = "eng"
    save_debug_captures: bool = False
    debug_capture_dir: str = "debug-captures"

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        return cls(
            host=os.getenv("HQ_OCR_BRIDGE_HOST", cls.host),
            port=_int_from_env("HQ_OCR_BRIDGE_PORT", cls.port),
            libretranslate_url=os.getenv(
                "HQ_OCR_LIBRETRANSLATE_URL", cls.libretranslate_url
            ).rstrip("/"),
            translation_providers=_csv_from_env(
                "HQ_OCR_TRANSLATION_PROVIDERS", cls.translation_providers
            ),
            google_translate_url=os.getenv(
                "HQ_OCR_GOOGLE_TRANSLATE_URL", cls.google_translate_url
            ),
            deepl_api_url=os.getenv("HQ_OCR_DEEPL_API_URL", cls.deepl_api_url),
            deepl_auth_key=os.getenv("HQ_OCR_DEEPL_AUTH_KEY") or None,
            easyocr_lang=os.getenv("HQ_OCR_EASYOCR_LANG", cls.easyocr_lang),
            easyocr_model_dir=os.getenv("HQ_OCR_EASYOCR_MODEL_DIR") or None,
            allow_easyocr_download=_bool_from_env(
                "HQ_OCR_ALLOW_EASYOCR_DOWNLOAD", cls.allow_easyocr_download
            ),
            paddleocr_lang=os.getenv("HQ_OCR_PADDLEOCR_LANG", cls.paddleocr_lang),
            paddleocr_ocr_version=os.getenv(
                "HQ_OCR_PADDLEOCR_VERSION", cls.paddleocr_ocr_version
            ),
            paddleocr_detection_model=os.getenv(
                "HQ_OCR_PADDLEOCR_DETECTION_MODEL", cls.paddleocr_detection_model
            ),
            paddleocr_recognition_model=os.getenv(
                "HQ_OCR_PADDLEOCR_RECOGNITION_MODEL",
                cls.paddleocr_recognition_model,
            ),
            paddleocr_cache_dir=os.getenv(
                "HQ_OCR_PADDLEOCR_CACHE_DIR", cls.paddleocr_cache_dir
            ),
            paddleocr_model_source=os.getenv(
                "HQ_OCR_PADDLEOCR_MODEL_SOURCE", cls.paddleocr_model_source
            ),
            paddleocr_enable_mkldnn=_bool_from_env(
                "HQ_OCR_PADDLEOCR_ENABLE_MKLDNN", cls.paddleocr_enable_mkldnn
            ),
            paddleocr_max_pixels=_int_from_env(
                "HQ_OCR_PADDLEOCR_MAX_PIXELS", cls.paddleocr_max_pixels
            ),
            tesseract_lang=os.getenv("HQ_OCR_TESSERACT_LANG", cls.tesseract_lang),
            save_debug_captures=_bool_from_env(
                "HQ_OCR_SAVE_DEBUG_CAPTURES", cls.save_debug_captures
            ),
            debug_capture_dir=os.getenv(
                "HQ_OCR_DEBUG_CAPTURE_DIR", cls.debug_capture_dir
            ),
        )

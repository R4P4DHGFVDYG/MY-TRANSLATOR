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


@dataclass(frozen=True)
class BridgeConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    libretranslate_url: str = "http://127.0.0.1:5000"
    request_timeout_seconds: float = 15.0
    easyocr_lang: str = "en"
    easyocr_model_dir: str | None = None
    allow_easyocr_download: bool = False
    tesseract_lang: str = "eng"

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        return cls(
            host=os.getenv("HQ_OCR_BRIDGE_HOST", cls.host),
            port=_int_from_env("HQ_OCR_BRIDGE_PORT", cls.port),
            libretranslate_url=os.getenv(
                "HQ_OCR_LIBRETRANSLATE_URL", cls.libretranslate_url
            ).rstrip("/"),
            easyocr_lang=os.getenv("HQ_OCR_EASYOCR_LANG", cls.easyocr_lang),
            easyocr_model_dir=os.getenv("HQ_OCR_EASYOCR_MODEL_DIR") or None,
            allow_easyocr_download=_bool_from_env(
                "HQ_OCR_ALLOW_EASYOCR_DOWNLOAD", cls.allow_easyocr_download
            ),
            tesseract_lang=os.getenv("HQ_OCR_TESSERACT_LANG", cls.tesseract_lang),
        )

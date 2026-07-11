from __future__ import annotations

from dataclasses import dataclass
import math
import os


_DATA_URL_PREFIX_BYTES = len("data:image/png;base64,")
_REQUEST_ENVELOPE_BYTES = 512


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


def _float_from_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        parsed = float(value)
    except ValueError:
        return default

    return parsed if math.isfinite(parsed) else default


def _csv_from_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default

    items = tuple(item.strip().lower() for item in value.split(",") if item.strip())
    return items or default


def _optional_string_from_env(name: str, default: str | None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default

    normalized = value.strip()
    return normalized or None


def _origins_from_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default

    return tuple(item.strip() for item in value.split(",") if item.strip())


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
    translation_cache_capacity: int = 128
    translation_cache_ttl_seconds: float = 900.0
    default_ocr_engines: tuple[str, ...] = ("paddleocr",)
    allowed_ocr_engines: tuple[str, ...] = ("paddleocr", "tesseract")
    max_ocr_engines: int = 3
    force_ocr_engines: bool = False
    ocr_engine_timeout_seconds: float = 0.0
    ocr_parallel_engines: bool = False
    ocr_max_parallel_engines: int = 3
    ocr_max_concurrent_requests: int = 1
    ocr_max_concurrent_engine_calls: int = 3
    ocr_queue_timeout_seconds: float = 10.0
    ocr_max_variants: int = 1
    ocr_cache_capacity: int = 128
    ocr_cache_ttl_seconds: float = 600.0
    ocr_warmup_on_start: bool = True
    easyocr_lang: str = "en"
    easyocr_model_dir: str | None = None
    allow_easyocr_download: bool = False
    easyocr_gpu: bool = False
    paddleocr_lang: str = "en"
    paddleocr_ocr_version: str = "PP-OCRv5"
    paddleocr_detection_model: str | None = "PP-OCRv5_mobile_det"
    paddleocr_recognition_model: str | None = "en_PP-OCRv5_mobile_rec"
    paddleocr_cache_dir: str = ".paddlex-cache"
    paddleocr_model_source: str = "bos"
    paddleocr_enable_mkldnn: bool = False
    paddleocr_max_pixels: int = 500_000
    tesseract_lang: str = "eng"
    max_request_bytes: int = 17 * 1024 * 1024
    max_image_bytes: int = 12 * 1024 * 1024
    max_image_pixels: int = 24_000_000
    max_crop_pixels: int = 12_000_000
    cors_allowed_origins: tuple[str, ...] = ()
    save_debug_captures: bool = False
    allow_request_debug_captures: bool = False
    debug_capture_dir: str = "debug-captures"
    log_performance: bool = True

    def __post_init__(self) -> None:
        allowed_engines = _unique_lower(self.allowed_ocr_engines)
        if not allowed_engines:
            raise ValueError("allowed_ocr_engines must not be empty")
        unknown_allowed = set(allowed_engines) - {"easyocr", "paddleocr", "tesseract"}
        if unknown_allowed:
            raise ValueError(
                "allowed_ocr_engines contains unsupported engines: "
                + ", ".join(sorted(unknown_allowed))
            )

        default_engines = _unique_lower(self.default_ocr_engines)
        if not default_engines:
            raise ValueError("default_ocr_engines must not be empty")
        unsupported_defaults = set(default_engines) - set(allowed_engines)
        if unsupported_defaults:
            raise ValueError(
                "default_ocr_engines must be included in allowed_ocr_engines"
            )

        if not self.paddleocr_lang.strip():
            raise ValueError("paddleocr_lang must not be empty")
        if not self.paddleocr_ocr_version.strip():
            raise ValueError("paddleocr_ocr_version must not be empty")

        detection_model = _normalized_optional(self.paddleocr_detection_model)
        recognition_model = _normalized_optional(self.paddleocr_recognition_model)
        if bool(detection_model) != bool(recognition_model):
            raise ValueError(
                "paddleocr_detection_model and paddleocr_recognition_model must be set together"
            )

        origins = tuple(dict.fromkeys(origin.strip() for origin in self.cors_allowed_origins if origin.strip()))
        if "*" in origins:
            raise ValueError("cors_allowed_origins must list explicit origins, not '*'")

        _require_range("port", self.port, minimum=1, maximum=65535)
        _require_positive("request_timeout_seconds", self.request_timeout_seconds)
        _require_positive_integer(
            "translation_cache_capacity", self.translation_cache_capacity
        )
        _require_positive(
            "translation_cache_ttl_seconds", self.translation_cache_ttl_seconds
        )
        _require_positive_integer("max_ocr_engines", self.max_ocr_engines)
        _require_non_negative("ocr_engine_timeout_seconds", self.ocr_engine_timeout_seconds)
        _require_positive_integer(
            "ocr_max_parallel_engines", self.ocr_max_parallel_engines
        )
        _require_positive_integer(
            "ocr_max_concurrent_requests", self.ocr_max_concurrent_requests
        )
        _require_positive_integer(
            "ocr_max_concurrent_engine_calls", self.ocr_max_concurrent_engine_calls
        )
        _require_non_negative("ocr_queue_timeout_seconds", self.ocr_queue_timeout_seconds)
        _require_non_negative_integer("ocr_max_variants", self.ocr_max_variants)
        _require_positive_integer("ocr_cache_capacity", self.ocr_cache_capacity)
        _require_positive("ocr_cache_ttl_seconds", self.ocr_cache_ttl_seconds)
        _require_positive_integer("paddleocr_max_pixels", self.paddleocr_max_pixels)
        _require_positive_integer("max_request_bytes", self.max_request_bytes)
        _require_positive_integer("max_image_bytes", self.max_image_bytes)
        _require_positive_integer("max_image_pixels", self.max_image_pixels)
        _require_positive_integer("max_crop_pixels", self.max_crop_pixels)
        required_request_bytes = _minimum_request_bytes_for_image(
            self.max_image_bytes
        )
        if self.max_request_bytes < required_request_bytes:
            raise ValueError(
                "max_request_bytes must allow the Base64-encoded max_image_bytes "
                "payload"
            )

        object.__setattr__(self, "allowed_ocr_engines", allowed_engines)
        object.__setattr__(self, "default_ocr_engines", default_engines)
        object.__setattr__(self, "paddleocr_detection_model", detection_model)
        object.__setattr__(self, "paddleocr_recognition_model", recognition_model)
        object.__setattr__(self, "cors_allowed_origins", origins)

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
            request_timeout_seconds=_float_from_env(
                "HQ_OCR_REQUEST_TIMEOUT_SECONDS", cls.request_timeout_seconds
            ),
            translation_cache_capacity=_int_from_env(
                "HQ_OCR_TRANSLATION_CACHE_CAPACITY",
                cls.translation_cache_capacity,
            ),
            translation_cache_ttl_seconds=_float_from_env(
                "HQ_OCR_TRANSLATION_CACHE_TTL_SECONDS",
                cls.translation_cache_ttl_seconds,
            ),
            default_ocr_engines=_csv_from_env(
                "HQ_OCR_DEFAULT_ENGINES", cls.default_ocr_engines
            ),
            allowed_ocr_engines=_csv_from_env(
                "HQ_OCR_ALLOWED_ENGINES", cls.allowed_ocr_engines
            ),
            max_ocr_engines=_int_from_env(
                "HQ_OCR_MAX_ENGINES", cls.max_ocr_engines
            ),
            force_ocr_engines=_bool_from_env(
                "HQ_OCR_FORCE_ENGINES", cls.force_ocr_engines
            ),
            ocr_engine_timeout_seconds=_float_from_env(
                "HQ_OCR_ENGINE_TIMEOUT_SECONDS", cls.ocr_engine_timeout_seconds
            ),
            ocr_parallel_engines=_bool_from_env(
                "HQ_OCR_PARALLEL_ENGINES", cls.ocr_parallel_engines
            ),
            ocr_max_parallel_engines=_int_from_env(
                "HQ_OCR_MAX_PARALLEL_ENGINES", cls.ocr_max_parallel_engines
            ),
            ocr_max_concurrent_requests=_int_from_env(
                "HQ_OCR_MAX_CONCURRENT_REQUESTS",
                cls.ocr_max_concurrent_requests,
            ),
            ocr_max_concurrent_engine_calls=_int_from_env(
                "HQ_OCR_MAX_CONCURRENT_ENGINE_CALLS",
                cls.ocr_max_concurrent_engine_calls,
            ),
            ocr_queue_timeout_seconds=_float_from_env(
                "HQ_OCR_QUEUE_TIMEOUT_SECONDS", cls.ocr_queue_timeout_seconds
            ),
            ocr_max_variants=_int_from_env(
                "HQ_OCR_MAX_VARIANTS", cls.ocr_max_variants
            ),
            ocr_cache_capacity=_int_from_env(
                "HQ_OCR_CACHE_CAPACITY", cls.ocr_cache_capacity
            ),
            ocr_cache_ttl_seconds=_float_from_env(
                "HQ_OCR_CACHE_TTL_SECONDS", cls.ocr_cache_ttl_seconds
            ),
            ocr_warmup_on_start=_bool_from_env(
                "HQ_OCR_WARMUP_ON_START", cls.ocr_warmup_on_start
            ),
            easyocr_lang=os.getenv("HQ_OCR_EASYOCR_LANG", cls.easyocr_lang),
            easyocr_model_dir=os.getenv("HQ_OCR_EASYOCR_MODEL_DIR") or None,
            allow_easyocr_download=_bool_from_env(
                "HQ_OCR_ALLOW_EASYOCR_DOWNLOAD", cls.allow_easyocr_download
            ),
            easyocr_gpu=_bool_from_env("HQ_OCR_EASYOCR_GPU", cls.easyocr_gpu),
            paddleocr_lang=os.getenv("HQ_OCR_PADDLEOCR_LANG", cls.paddleocr_lang),
            paddleocr_ocr_version=os.getenv(
                "HQ_OCR_PADDLEOCR_VERSION", cls.paddleocr_ocr_version
            ),
            paddleocr_detection_model=_optional_string_from_env(
                "HQ_OCR_PADDLEOCR_DETECTION_MODEL", cls.paddleocr_detection_model
            ),
            paddleocr_recognition_model=_optional_string_from_env(
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
            max_request_bytes=_int_from_env(
                "HQ_OCR_MAX_REQUEST_BYTES", cls.max_request_bytes
            ),
            max_image_bytes=_int_from_env(
                "HQ_OCR_MAX_IMAGE_BYTES", cls.max_image_bytes
            ),
            max_image_pixels=_int_from_env(
                "HQ_OCR_MAX_IMAGE_PIXELS", cls.max_image_pixels
            ),
            max_crop_pixels=_int_from_env(
                "HQ_OCR_MAX_CROP_PIXELS", cls.max_crop_pixels
            ),
            cors_allowed_origins=_origins_from_env(
                "HQ_OCR_CORS_ALLOWED_ORIGINS", cls.cors_allowed_origins
            ),
            save_debug_captures=_bool_from_env(
                "HQ_OCR_SAVE_DEBUG_CAPTURES", cls.save_debug_captures
            ),
            allow_request_debug_captures=_bool_from_env(
                "HQ_OCR_ALLOW_REQUEST_DEBUG_CAPTURES",
                cls.allow_request_debug_captures,
            ),
            debug_capture_dir=os.getenv(
                "HQ_OCR_DEBUG_CAPTURE_DIR", cls.debug_capture_dir
            ),
            log_performance=_bool_from_env(
                "HQ_OCR_LOG_PERFORMANCE", cls.log_performance
            ),
        )


def _unique_lower(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        name = str(value).strip().lower()
        if name and name not in normalized:
            normalized.append(name)
    return tuple(normalized)


def _normalized_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _minimum_request_bytes_for_image(image_bytes: int) -> int:
    base64_bytes = ((image_bytes + 2) // 3) * 4
    return base64_bytes + _DATA_URL_PREFIX_BYTES + _REQUEST_ENVELOPE_BYTES


def _require_positive(name: str, value: int | float) -> None:
    _require_finite(name, value)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


def _require_non_negative(name: str, value: int | float) -> None:
    _require_finite(name, value)
    if value < 0:
        raise ValueError(f"{name} must not be negative")


def _require_positive_integer(name: str, value: int) -> None:
    _require_integer(name, value)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


def _require_non_negative_integer(name: str, value: int) -> None:
    _require_integer(name, value)
    if value < 0:
        raise ValueError(f"{name} must not be negative")


def _require_range(name: str, value: int, minimum: int, maximum: int) -> None:
    _require_integer(name, value)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


def _require_finite(name: str, value: int | float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def _require_integer(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")

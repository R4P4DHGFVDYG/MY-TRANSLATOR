from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
import hashlib
from io import BytesIO
import importlib.util
import math
import os
import threading
import time
from typing import Any, Callable

from PIL import Image

from .cache import TTLCache
from .config import BridgeConfig
from .image_utils import preprocess_variants_for_ocr
from .models import EngineResult
from .ranking import normalize_ocr_text, rank_ocr_results, text_quality_score


DEFAULT_ENGINES = ["paddleocr"]
SUPPORTED_ENGINES = frozenset({"easyocr", "paddleocr", "tesseract"})


class OcrCapacityError(RuntimeError):
    """Raised when all bounded OCR request slots are occupied."""


class OcrCancelledError(RuntimeError):
    """Raised when a newer capture supersedes the current OCR request."""


class OcrService:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self._easyocr_reader: Any | None = None
        self._paddleocr_reader: Any | None = None
        self._easyocr_lock = threading.Lock()
        self._paddleocr_lock = threading.Lock()
        self._request_slots = threading.BoundedSemaphore(
            config.ocr_max_concurrent_requests
        )
        self._engine_slots = threading.BoundedSemaphore(
            config.ocr_max_concurrent_engine_calls
        )
        self._engine_executor = ThreadPoolExecutor(
            max_workers=config.ocr_max_concurrent_engine_calls,
            thread_name_prefix="ocr-engine",
        )
        self._parallel_executor = ThreadPoolExecutor(
            max_workers=config.ocr_max_parallel_engines,
            thread_name_prefix="ocr-parallel",
        )
        self._cache = TTLCache(
            capacity=config.ocr_cache_capacity,
            ttl_seconds=config.ocr_cache_ttl_seconds,
        )

    def health_checks(self) -> dict[str, Any]:
        return {
            "settings": {
                "defaultEngines": list(self.config.default_ocr_engines),
                "forceEngines": self.config.force_ocr_engines,
                "engineTimeoutSeconds": self.config.ocr_engine_timeout_seconds,
                "timeoutMode": "response deadline; timed-out workers stay bounded",
                "parallelEngines": self.config.ocr_parallel_engines,
                "maxParallelEngines": self.config.ocr_max_parallel_engines,
                "maxConcurrentRequests": self.config.ocr_max_concurrent_requests,
                "maxConcurrentEngineCalls": self.config.ocr_max_concurrent_engine_calls,
                "queueTimeoutSeconds": self.config.ocr_queue_timeout_seconds,
                "maxVariants": self.config.ocr_max_variants,
                "cacheCapacity": self.config.ocr_cache_capacity,
                "cacheTtlSeconds": self.config.ocr_cache_ttl_seconds,
                "warmupOnStart": self.config.ocr_warmup_on_start,
                "allowedEngines": list(self.config.allowed_ocr_engines),
            },
            "easyocr": self._easyocr_health(),
            "paddleocr": self._paddleocr_health(),
            "tesseract": self._tesseract_health(),
        }

    def warm_up(self, engines: list[str] | tuple[str, ...] | None = None) -> list[str]:
        warnings: list[str] = []
        requested = engines or self.config.default_ocr_engines

        for engine in requested:
            normalized_engine = str(engine).strip().lower()
            try:
                if normalized_engine == "easyocr":
                    self._get_easyocr_reader()
                elif normalized_engine == "paddleocr":
                    self._get_paddleocr_reader()
                elif normalized_engine == "tesseract":
                    self._ensure_tesseract_available()
            except Exception as exc:
                warnings.append(f"{normalized_engine} warmup failed: {exc}")

        return warnings

    def detect_text(
        self, image: Image.Image, engines: list[str] | None = None
    ) -> tuple[EngineResult | None, list[EngineResult], list[str]]:
        best, results, warnings, _metadata = self.detect_text_with_metadata(
            image,
            engines,
        )
        return best, results, warnings

    def detect_text_with_metadata(
        self,
        image: Image.Image,
        engines: list[str] | None = None,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[EngineResult | None, list[EngineResult], list[str], dict[str, bool]]:
        requested = engines if engines is not None else list(self.config.default_ocr_engines)
        results: list[EngineResult] = []
        warnings: list[str] = []
        normalized_engines = self._normalize_requested_engines(
            requested, results, warnings
        )
        if not normalized_engines:
            return None, results, warnings, {"cacheHit": False}

        _raise_if_cancelled(cancel_check)
        cache_key = (tuple(normalized_engines), _image_fingerprint(image))
        cached = self._cache.get(cache_key)
        if _is_cached_detection(cached):
            best, cached_results, cached_warnings = _copy_detection(cached)
            return best, cached_results, cached_warnings, {"cacheHit": True}

        if not self._acquire_request_slot(cancel_check):
            raise OcrCapacityError("OCR service is busy; try again shortly")

        try:
            # Another request may have populated the cache while this request was
            # waiting for the single inference slot.
            cached = self._cache.get(cache_key)
            if _is_cached_detection(cached):
                best, cached_results, cached_warnings = _copy_detection(cached)
                return best, cached_results, cached_warnings, {"cacheHit": True}

            _raise_if_cancelled(cancel_check)

            variant_limit = (
                1
                if all(engine == "paddleocr" for engine in normalized_engines)
                else self.config.ocr_max_variants
            )
            variants = preprocess_variants_for_ocr(
                image,
                max_variants=variant_limit,
            )
            engine_tasks = [
                (
                    engine,
                    _paddleocr_variants(variants)
                    if engine == "paddleocr"
                    else variants,
                )
                for engine in normalized_engines
            ]

            if self.config.ocr_parallel_engines and len(engine_tasks) > 1:
                parallel_results, parallel_warnings = self._detect_engines_parallel(
                    engine_tasks,
                    cancel_check,
                )
                results.extend(parallel_results)
                warnings.extend(parallel_warnings)
            else:
                for normalized_engine, engine_variants in engine_tasks:
                    engine_results, engine_warnings = self._detect_engine_variants(
                        normalized_engine,
                        engine_variants,
                        cancel_check,
                    )
                    results.extend(engine_results)
                    warnings.extend(engine_warnings)

            best = rank_ocr_results(results)
            cached_detection = _copy_detection((best, results, warnings))
            self._cache.set(cache_key, cached_detection)
            _raise_if_cancelled(cancel_check)
            return best, results, warnings, {"cacheHit": False}
        finally:
            self._request_slots.release()

    def _acquire_request_slot(
        self, cancel_check: Callable[[], bool] | None = None
    ) -> bool:
        timeout = self.config.ocr_queue_timeout_seconds
        if timeout <= 0:
            _raise_if_cancelled(cancel_check)
            return self._request_slots.acquire(blocking=False)

        deadline = time.monotonic() + timeout
        while True:
            _raise_if_cancelled(cancel_check)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if self._request_slots.acquire(timeout=min(0.05, remaining)):
                return True

    def _normalize_requested_engines(
        self,
        requested: list[str] | tuple[str, ...],
        results: list[EngineResult],
        warnings: list[str],
    ) -> list[str]:
        normalized_engines: list[str] = []
        for engine in requested:
            normalized_engine = str(engine).strip().lower()
            if normalized_engine not in SUPPORTED_ENGINES:
                message = f"unknown OCR engine: {engine}"
                warnings.append(message)
                results.append(
                    EngineResult(normalized_engine or "unknown", "", 0.0, 0.0, message)
                )
                continue
            if normalized_engine not in self.config.allowed_ocr_engines:
                message = f"OCR engine is disabled: {normalized_engine}"
                warnings.append(message)
                results.append(
                    EngineResult(normalized_engine, "", 0.0, 0.0, message)
                )
                continue
            if normalized_engine in normalized_engines:
                continue
            if len(normalized_engines) >= self.config.max_ocr_engines:
                message = "too many OCR engines were requested"
                warnings.append(message)
                break
            normalized_engines.append(normalized_engine)

        return normalized_engines

    def _detect_engines_parallel(
        self,
        engine_tasks: list[tuple[str, list[tuple[str, Image.Image]]]],
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[list[EngineResult], list[str]]:
        results: list[EngineResult] = []
        warnings: list[str] = []
        futures = [
            (
                normalized_engine,
                self._parallel_executor.submit(
                    self._detect_engine_variants,
                    normalized_engine,
                    engine_variants,
                    cancel_check,
                ),
            )
            for normalized_engine, engine_variants in engine_tasks
        ]

        for normalized_engine, future in futures:
            _raise_if_cancelled(cancel_check)
            try:
                engine_results, engine_warnings = future.result()
            except Exception as exc:
                message = f"{normalized_engine} failed: {exc}"
                warnings.append(message)
                results.append(EngineResult(normalized_engine, "", 0.0, 0.0, message))
                continue

            results.extend(engine_results)
            warnings.extend(engine_warnings)

        return results, warnings

    def _detect_engine_variants(
        self,
        normalized_engine: str,
        engine_variants: list[tuple[str, Image.Image]],
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[list[EngineResult], list[str]]:
        results: list[EngineResult] = []
        warnings: list[str] = []

        for variant_name, prepared in engine_variants:
            _raise_if_cancelled(cancel_check)
            try:
                result = self._run_engine_with_timeout(normalized_engine, prepared)
            except TimeoutError:
                message = (
                    f"{normalized_engine} timed out on {variant_name} after "
                    f"{self.config.ocr_engine_timeout_seconds:g}s"
                )
                warnings.append(message)
                results.append(
                    EngineResult(
                        f"{normalized_engine}:{variant_name}",
                        "",
                        0.0,
                        0.0,
                        message,
                    )
                )
                # A timed-out worker may still be running. Do not queue more
                # variants behind it; the shared worker pool remains bounded.
                break
            except Exception as exc:
                message = f"{normalized_engine} failed on {variant_name}: {exc}"
                warnings.append(message)
                results.append(
                    EngineResult(
                        f"{normalized_engine}:{variant_name}",
                        "",
                        0.0,
                        0.0,
                        message,
                    )
                )
                if _is_engine_setup_failure(exc) or isinstance(exc, OcrCapacityError):
                    break
                continue

            result.engine = f"{normalized_engine}:{variant_name}"
            result.raw_text = result.text
            result.text = normalize_ocr_text(result.text)
            result.score = text_quality_score(result.text, result.raw_confidence)
            results.append(result)

        return results, warnings

    def _run_engine_with_timeout(
        self, normalized_engine: str, image: Image.Image
    ) -> EngineResult:
        timeout = self.config.ocr_engine_timeout_seconds
        if not self._acquire_engine_slot(timeout):
            raise OcrCapacityError("OCR engine capacity is busy")
        if timeout <= 0:
            try:
                return self._run_engine(normalized_engine, image)
            finally:
                self._engine_slots.release()

        try:
            future = self._engine_executor.submit(
                self._run_engine,
                normalized_engine,
                image,
            )
        except Exception:
            self._engine_slots.release()
            raise
        future.add_done_callback(lambda _future: self._engine_slots.release())
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            raise

    def _acquire_engine_slot(self, timeout: float) -> bool:
        if timeout <= 0:
            return self._engine_slots.acquire(blocking=False)
        return self._engine_slots.acquire(timeout=timeout)

    def _run_engine(self, normalized_engine: str, image: Image.Image) -> EngineResult:
        if normalized_engine == "easyocr":
            return self._run_easyocr(image)
        if normalized_engine == "paddleocr":
            return self._run_paddleocr(image)
        return self._run_tesseract(image)

    def _run_easyocr(self, image: Image.Image) -> EngineResult:
        reader = self._get_easyocr_reader()

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        with self._easyocr_lock:
            detections = reader.readtext(
                buffer.getvalue(),
                detail=1,
                paragraph=False,
            )

        fragments: list[str] = []
        confidences: list[float] = []
        for detection in detections:
            if len(detection) < 3:
                continue
            text = str(detection[1]).strip()
            if text:
                fragments.append(text)
            confidence = _finite_float(detection[2])
            if confidence is not None:
                confidences.append(confidence)

        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return EngineResult("easyocr", " ".join(fragments), confidence, confidence)

    def _get_easyocr_reader(self) -> Any:
        if self._easyocr_reader is not None:
            return self._easyocr_reader

        if importlib.util.find_spec("easyocr") is None:
            raise RuntimeError("easyocr package is not installed")

        import easyocr

        with self._easyocr_lock:
            if self._easyocr_reader is None:
                kwargs: dict[str, Any] = {
                    "gpu": self.config.easyocr_gpu,
                    "download_enabled": self.config.allow_easyocr_download,
                }
                if self.config.easyocr_model_dir:
                    kwargs["model_storage_directory"] = self.config.easyocr_model_dir
                self._easyocr_reader = easyocr.Reader(
                    [self.config.easyocr_lang], **kwargs
                )

        return self._easyocr_reader

    def _run_paddleocr(self, image: Image.Image) -> EngineResult:
        import numpy as np

        image = _limit_image_pixels(image, self.config.paddleocr_max_pixels)
        reader = self._get_paddleocr_reader()

        with self._paddleocr_lock:
            detections = reader.predict(np.asarray(image.convert("RGB")))
        fragments: list[str] = []
        confidences: list[float] = []
        for detection in detections:
            payload = _paddleocr_payload(detection)
            recognized_texts = (
                str(item).strip() for item in payload.get("rec_texts", [])
            )
            fragments.extend(text for text in recognized_texts if text)
            for confidence in payload.get("rec_scores", []):
                parsed_confidence = _finite_float(confidence)
                if parsed_confidence is not None:
                    confidences.append(parsed_confidence)

        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return EngineResult("paddleocr", " ".join(fragments), confidence, confidence)

    def _get_paddleocr_reader(self) -> Any:
        if self._paddleocr_reader is not None:
            return self._paddleocr_reader

        if importlib.util.find_spec("paddleocr") is None:
            raise RuntimeError("paddleocr package is not installed")

        self._configure_paddleocr_environment()

        from paddleocr import PaddleOCR

        with self._paddleocr_lock:
            if self._paddleocr_reader is None:
                kwargs: dict[str, Any] = dict(
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                )
                if self.config.paddleocr_detection_model:
                    kwargs["text_detection_model_name"] = (
                        self.config.paddleocr_detection_model
                    )
                    kwargs["text_recognition_model_name"] = (
                        self.config.paddleocr_recognition_model
                    )
                else:
                    kwargs["lang"] = self.config.paddleocr_lang
                    kwargs["ocr_version"] = self.config.paddleocr_ocr_version

                self._paddleocr_reader = PaddleOCR(**kwargs)

        return self._paddleocr_reader

    def _configure_paddleocr_environment(self) -> None:
        os.environ["PADDLE_PDX_CACHE_HOME"] = os.path.abspath(
            self.config.paddleocr_cache_dir
        )
        os.environ["PADDLE_PDX_MODEL_SOURCE"] = self.config.paddleocr_model_source
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        os.environ["PADDLEOCR_DISABLE_AUTO_LOGGING_CONFIG"] = "1"
        os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = (
            "True" if self.config.paddleocr_enable_mkldnn else "False"
        )

    def _run_tesseract(self, image: Image.Image) -> EngineResult:
        self._ensure_tesseract_available()

        import pytesseract
        from pytesseract import Output

        data = pytesseract.image_to_data(
            image,
            lang=self.config.tesseract_lang,
            config="--psm 6",
            output_type=Output.DICT,
        )
        words: list[str] = []
        confidences: list[float] = []
        for text, confidence in zip(data.get("text", []), data.get("conf", [])):
            clean = str(text).strip()
            if not clean:
                continue
            conf_value = _finite_float(confidence)
            if conf_value is not None and conf_value >= 0:
                words.append(clean)
                confidences.append(conf_value / 100)

        if words:
            confidence = sum(confidences) / len(confidences) if confidences else 0.0
            return EngineResult("tesseract", " ".join(words), confidence, confidence)

        fallback = pytesseract.image_to_string(
            image,
            lang=self.config.tesseract_lang,
            config="--psm 6",
        )
        return EngineResult("tesseract", fallback, 0.35, 0.35)

    def _ensure_tesseract_available(self) -> None:
        if importlib.util.find_spec("pytesseract") is None:
            raise RuntimeError("pytesseract package is not installed")

    def _easyocr_health(self) -> dict[str, Any]:
        installed = importlib.util.find_spec("easyocr") is not None
        model_dir = self.config.easyocr_model_dir
        return {
            "installed": installed,
            "language": self.config.easyocr_lang,
            "modelDirectory": model_dir,
            "modelDirectoryExists": bool(model_dir and os.path.isdir(model_dir)),
            "downloadEnabled": self.config.allow_easyocr_download,
            "gpu": self.config.easyocr_gpu,
            "loaded": self._easyocr_reader is not None,
        }

    def _paddleocr_health(self) -> dict[str, Any]:
        installed = importlib.util.find_spec("paddleocr") is not None
        cache_dir = os.path.abspath(self.config.paddleocr_cache_dir)
        return {
            "installed": installed,
            "language": self.config.paddleocr_lang,
            "version": self.config.paddleocr_ocr_version,
            "detectionModel": self.config.paddleocr_detection_model,
            "recognitionModel": self.config.paddleocr_recognition_model,
            "modelMode": (
                "named"
                if self.config.paddleocr_detection_model
                else "language-and-version"
            ),
            "cacheDirectory": cache_dir,
            "cacheDirectoryExists": os.path.isdir(cache_dir),
            "mkldnnEnabled": self.config.paddleocr_enable_mkldnn,
            "maxPixels": self.config.paddleocr_max_pixels,
            "loaded": self._paddleocr_reader is not None,
        }

    def _tesseract_health(self) -> dict[str, Any]:
        if importlib.util.find_spec("pytesseract") is None:
            return {"installed": False, "language": self.config.tesseract_lang}

        try:
            import pytesseract

            version = str(pytesseract.get_tesseract_version())
            return {
                "installed": True,
                "language": self.config.tesseract_lang,
                "version": version,
            }
        except Exception as exc:
            return {
                "installed": False,
                "language": self.config.tesseract_lang,
                "error": str(exc),
            }


def _raise_if_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise OcrCancelledError("OCR request was superseded by a newer capture")


def _image_fingerprint(image: Image.Image) -> tuple[int, int, str, str]:
    digest = hashlib.blake2b(image.tobytes(), digest_size=16).hexdigest()
    return image.width, image.height, image.mode, digest


def _is_cached_detection(value: object) -> bool:
    return isinstance(value, tuple) and len(value) == 3


def _copy_detection(
    detection: tuple[EngineResult | None, list[EngineResult], list[str]],
) -> tuple[EngineResult | None, list[EngineResult], list[str]]:
    best, results, warnings = detection
    return (
        replace(best) if best is not None else None,
        [replace(result) for result in results],
        list(warnings),
    )


def _is_engine_setup_failure(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "not installed" in message
        or "not in your path" in message
        or "package is not installed" in message
        or "no module named" in message
    )


def _paddleocr_variants(
    variants: list[tuple[str, Image.Image]]
) -> list[tuple[str, Image.Image]]:
    for variant in variants:
        if variant[0] == "standard":
            return [variant]
    return variants[:1]


def _limit_image_pixels(image: Image.Image, max_pixels: int) -> Image.Image:
    if max_pixels <= 0:
        return image

    pixels = image.width * image.height
    if pixels <= max_pixels:
        return image

    scale = math.sqrt(max_pixels / pixels)
    width = max(1, int(image.width * scale))
    height = max(1, int(image.height * scale))
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    return image.resize((width, height), resampling)


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _paddleocr_payload(result: Any) -> dict[str, Any]:
    data = getattr(result, "json", None)
    if callable(data):
        data = data()
    if isinstance(data, dict):
        payload = data.get("res", data)
        if isinstance(payload, dict):
            return payload
    if isinstance(result, dict):
        payload = result.get("res", result)
        if isinstance(payload, dict):
            return payload
    return {}

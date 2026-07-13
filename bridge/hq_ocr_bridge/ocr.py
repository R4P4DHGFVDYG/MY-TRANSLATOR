from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from dataclasses import replace
from difflib import SequenceMatcher
import hashlib
import importlib.util
import math
import os
import shutil
import threading
import time
from typing import Any, Callable

from PIL import Image

from .cache import TTLCache
from .config import BridgeConfig
from .image_utils import preprocess_variants_for_ocr
from .models import EngineResult
from .ranking import (
    normalize_ocr_text,
    ocr_suspicion_score,
    rank_ocr_results,
    text_quality_score,
)
from .text_region import isolate_text_region
from .windows_ocr import WindowsOcrAdapter, windows_ocr_health


DEFAULT_ENGINES = ["tesseract"]
AUTOMATIC_PROFILE_ENGINES = ("tesseract", "windowsocr", "paddleocr")
AUTOMATIC_FAST_ENGINES = ("tesseract", "windowsocr")
OCR_PREPROCESSING_STANDARD = "standard"
OCR_PREPROCESSING_PIXEL_ART = "pixel-art"
SUPPORTED_OCR_PREPROCESSING_PROFILES = frozenset(
    {"auto", OCR_PREPROCESSING_STANDARD, OCR_PREPROCESSING_PIXEL_ART}
)
AUTOMATIC_NEAR_CONSENSUS_MIN_LENGTH = 20
AUTOMATIC_NEAR_CONSENSUS_SIMILARITY = 0.96
AUTOMATIC_NEAR_CONSENSUS_WINDOWS_SCORE = 0.60
SUPPORTED_ENGINES = frozenset(
    {"windowsocr", "easyocr", "paddleocr", "tesseract"}
)


class OcrCapacityError(RuntimeError):
    """Raised when all bounded OCR request slots are occupied."""


class OcrCancelledError(RuntimeError):
    """Raised when a newer capture supersedes the current OCR request."""


class OcrService:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self._easyocr_reader: Any | None = None
        self._paddleocr_reader: Any | None = None
        self._windowsocr_adapter: WindowsOcrAdapter | None = None
        self._easyocr_lock = threading.Lock()
        self._paddleocr_lock = threading.Lock()
        self._windowsocr_lock = threading.Lock()
        self._warmup_timings_lock = threading.Lock()
        self._warmup_timings: dict[str, float] = {}
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
        with self._warmup_timings_lock:
            warmup_timings = dict(self._warmup_timings)
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
                "acceptScore": self.config.ocr_accept_score,
                "acceptConfidence": self.config.ocr_accept_confidence,
                "cacheCapacity": self.config.ocr_cache_capacity,
                "cacheTtlSeconds": self.config.ocr_cache_ttl_seconds,
                "warmupOnStart": self.config.ocr_warmup_on_start,
                "warmupEngines": list(self.config.ocr_warmup_engines),
                "lastWarmupMs": warmup_timings,
                "allowedEngines": list(self.config.allowed_ocr_engines),
            },
            "easyocr": self._easyocr_health(),
            "paddleocr": self._paddleocr_health(),
            "windowsocr": self._windowsocr_health(),
            "tesseract": self._tesseract_health(),
        }

    def warm_up(self, engines: list[str] | tuple[str, ...] | None = None) -> list[str]:
        requested = engines or self.config.ocr_warmup_engines
        normalized_engines = list(
            dict.fromkeys(
                str(engine).strip().lower()
                for engine in requested
                if str(engine).strip()
            )
        )
        failures: dict[str, str] = {}
        supported_engines = [
            engine for engine in normalized_engines if engine in SUPPORTED_ENGINES
        ]
        for engine in normalized_engines:
            if engine not in SUPPORTED_ENGINES:
                failures[engine] = "unsupported OCR engine"

        if supported_engines:
            worker_count = min(
                len(supported_engines),
                self.config.ocr_max_parallel_engines,
            )
            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="ocr-warmup-engine",
            ) as executor:
                futures = {
                    executor.submit(self._warm_up_engine_with_timing, engine): engine
                    for engine in supported_engines
                }
                for future in as_completed(futures):
                    engine = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        failures[engine] = str(exc)

        return [
            f"{engine} warmup failed: {failures[engine]}"
            for engine in normalized_engines
            if engine in failures
        ]

    def _warm_up_engine_with_timing(self, engine: str) -> None:
        started_at = time.perf_counter()
        try:
            self._warm_up_engine(engine)
        finally:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            with self._warmup_timings_lock:
                self._warmup_timings[engine] = elapsed_ms

    def _warm_up_engine(self, engine: str) -> None:
        if engine == "windowsocr":
            self._get_windowsocr_adapter().warm_up()
        elif engine == "easyocr":
            self._get_easyocr_reader()
        elif engine == "paddleocr":
            self._get_paddleocr_reader()
        elif engine == "tesseract":
            self._ensure_tesseract_available()
            self._run_tesseract_psm(Image.new("L", (96, 32), 255), 7)

    def detect_text(
        self,
        image: Image.Image,
        engines: list[str] | None = None,
        *,
        language_tag: str | None = None,
        preprocessing_profile: str = OCR_PREPROCESSING_STANDARD,
    ) -> tuple[EngineResult | None, list[EngineResult], list[str]]:
        best, results, warnings, _metadata = self.detect_text_with_metadata(
            image,
            engines,
            language_tag=language_tag,
            preprocessing_profile=preprocessing_profile,
        )
        return best, results, warnings

    def detect_text_with_metadata(
        self,
        image: Image.Image,
        engines: list[str] | None = None,
        *,
        cancel_check: Callable[[], bool] | None = None,
        language_tag: str | None = None,
        preprocessing_profile: str = OCR_PREPROCESSING_STANDARD,
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
        normalized_language = str(language_tag or "").strip().lower()
        normalized_preprocessing = _normalize_preprocessing_profile(
            preprocessing_profile
        )
        force_pixel_art = normalized_preprocessing == OCR_PREPROCESSING_PIXEL_ART
        cache_key = (
            tuple(normalized_engines),
            normalized_language,
            normalized_preprocessing,
            _image_fingerprint(image),
        )
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

            recognition_image = isolate_text_region(image)

            if tuple(normalized_engines) == AUTOMATIC_PROFILE_ENGINES:
                automatic_results, automatic_warnings = (
                    self._detect_automatic_profile(
                        recognition_image,
                        cancel_check,
                        language_tag,
                        force_pixel_art=force_pixel_art,
                    )
                )
                results.extend(automatic_results)
                warnings.extend(automatic_warnings)
            else:
                engine_tasks = [
                    (
                        engine,
                        preprocess_variants_for_ocr(
                            recognition_image,
                            max_variants=self.config.ocr_max_variants,
                            engine=engine,
                            force_pixel_art=force_pixel_art,
                        ),
                    )
                    for engine in normalized_engines
                ]

                self._detect_configured_engines(
                    engine_tasks,
                    results,
                    warnings,
                    cancel_check,
                    language_tag,
                )

            best = rank_ocr_results(
                results,
                primary_engine=(
                    normalized_engines[0] if len(normalized_engines) > 1 else None
                ),
                accept_score=self.config.ocr_accept_score,
                accept_confidence=self.config.ocr_accept_confidence,
                language_tag=language_tag,
            )
            cached_detection = _copy_detection((best, results, warnings))
            self._cache.set(cache_key, cached_detection)
            _raise_if_cancelled(cancel_check)
            return best, results, warnings, {"cacheHit": False}
        finally:
            self._request_slots.release()

    def _detect_configured_engines(
        self,
        engine_tasks: list[tuple[str, list[tuple[str, Image.Image]]]],
        results: list[EngineResult],
        warnings: list[str],
        cancel_check: Callable[[], bool] | None,
        language_tag: str | None,
    ) -> None:
        if self.config.ocr_parallel_engines and len(engine_tasks) > 1:
            parallel_results, parallel_warnings = self._detect_engines_parallel(
                engine_tasks,
                cancel_check,
                language_tag,
            )
            results.extend(parallel_results)
            warnings.extend(parallel_warnings)
            return

        for normalized_engine, engine_variants in engine_tasks:
            engine_results, engine_warnings = self._detect_engine_variants(
                normalized_engine,
                engine_variants,
                cancel_check,
                language_tag,
            )
            results.extend(engine_results)
            warnings.extend(engine_warnings)
            if self._engine_results_are_conclusive(
                normalized_engine,
                engine_results,
                available_variants=len(engine_variants),
                language_tag=language_tag,
            ):
                break

    def _detect_automatic_profile(
        self,
        image: Image.Image,
        cancel_check: Callable[[], bool] | None,
        language_tag: str | None,
        *,
        force_pixel_art: bool = False,
    ) -> tuple[list[EngineResult], list[str]]:
        fast_variants = {
            engine: preprocess_variants_for_ocr(
                image,
                max_variants=self.config.ocr_max_variants,
                engine=engine,
                force_pixel_art=force_pixel_art,
            )
            for engine in AUTOMATIC_FAST_ENGINES
        }
        results: list[EngineResult] = []
        warnings: list[str] = []
        stopped_engines: set[str] = set()
        rounds = max(
            (len(variants) for variants in fast_variants.values()),
            default=0,
        )

        for variant_index in range(rounds):
            round_tasks = [
                (engine, [variants[variant_index]])
                for engine, variants in fast_variants.items()
                if engine not in stopped_engines and variant_index < len(variants)
            ]
            if not round_tasks:
                break

            round_results, round_warnings = self._detect_engines_parallel(
                round_tasks,
                cancel_check,
                language_tag,
            )
            results.extend(round_results)
            warnings.extend(round_warnings)
            stopped_engines.update(
                engine
                for engine, _variants in round_tasks
                if _automatic_engine_has_terminal_failure(engine, round_results)
            )
            _raise_if_cancelled(cancel_check)

            if self._automatic_fast_result_is_conclusive(results, language_tag):
                return results, warnings

        paddle_variants = preprocess_variants_for_ocr(
            image,
            max_variants=self.config.ocr_max_variants,
            engine="paddleocr",
            force_pixel_art=force_pixel_art,
        )
        paddle_results, paddle_warnings = self._detect_engine_variants(
            "paddleocr",
            paddle_variants,
            cancel_check,
            language_tag,
        )
        results.extend(paddle_results)
        warnings.extend(paddle_warnings)
        return results, warnings

    def _automatic_fast_result_is_conclusive(
        self,
        results: list[EngineResult],
        language_tag: str | None = "en",
    ) -> bool:
        clusters: dict[str, list[EngineResult]] = {}
        for result in results:
            base_engine = _base_engine(result.engine)
            normalized = normalize_ocr_text(result.text, language_tag).casefold()
            if base_engine in AUTOMATIC_FAST_ENGINES and normalized:
                clusters.setdefault(normalized, []).append(result)

        consensus = [
            cluster
            for cluster in clusters.values()
            if {_base_engine(result.engine) for result in cluster}
            >= set(AUTOMATIC_FAST_ENGINES)
        ]
        for cluster in consensus:
            consensus_text = normalize_ocr_text(cluster[0].text, language_tag)
            if len(consensus_text) < 2 or not any(
                ch.isalnum() for ch in consensus_text
            ):
                continue
            if not any(
                ocr_suspicion_score(result.raw_text or result.text) > 0
                for result in cluster
            ):
                return True

        tesseract_results = [
            result
            for result in results
            if _base_engine(result.engine) == "tesseract"
            and normalize_ocr_text(result.text, language_tag)
        ]
        windows_results = [
            result
            for result in results
            if _base_engine(result.engine) == "windowsocr"
            and normalize_ocr_text(result.text, language_tag)
        ]
        return any(
            self._automatic_fast_pair_is_conclusive(
                tesseract,
                windows,
                language_tag,
            )
            for tesseract in tesseract_results
            for windows in windows_results
        )

    def _automatic_fast_pair_is_conclusive(
        self,
        tesseract: EngineResult,
        windows: EngineResult,
        language_tag: str | None = "en",
    ) -> bool:
        if (
            not self._is_reliable_result(tesseract)
            or windows.score < AUTOMATIC_NEAR_CONSENSUS_WINDOWS_SCORE
        ):
            return False
        if any(
            ocr_suspicion_score(result.raw_text or result.text) > 0
            for result in (tesseract, windows)
        ):
            return False

        tesseract_text = _automatic_consensus_key(tesseract.text, language_tag)
        windows_text = _automatic_consensus_key(windows.text, language_tag)
        if not tesseract_text or not windows_text:
            return False
        if tesseract_text == windows_text:
            return len(tesseract_text) >= 4
        if min(len(tesseract_text), len(windows_text)) < (
            AUTOMATIC_NEAR_CONSENSUS_MIN_LENGTH
        ):
            return False
        if len(tesseract_text.split()) != len(windows_text.split()):
            return False
        if abs(len(tesseract_text) - len(windows_text)) > 1:
            return False

        similarity = SequenceMatcher(
            None,
            tesseract_text,
            windows_text,
        ).ratio()
        return (
            similarity >= AUTOMATIC_NEAR_CONSENSUS_SIMILARITY
            and _has_single_safe_consensus_edit(tesseract_text, windows_text)
        )

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
        language_tag: str | None = None,
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
                    language_tag,
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
        language_tag: str | None = None,
    ) -> tuple[list[EngineResult], list[str]]:
        results: list[EngineResult] = []
        warnings: list[str] = []
        minimum_attempts = (
            min(2, len(engine_variants))
            if normalized_engine == "tesseract"
            else 1
        )
        attempted = 0

        for variant_name, prepared in engine_variants:
            _raise_if_cancelled(cancel_check)
            attempted += 1
            try:
                result = self._run_engine_with_timeout(
                    normalized_engine,
                    prepared,
                    language_tag,
                )
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
            result.text = normalize_ocr_text(result.text, language_tag)
            result.score = text_quality_score(
                result.text,
                result.raw_confidence,
                raw_text=result.raw_text,
                language_tag=language_tag,
            )
            results.append(result)
            if (
                normalized_engine != "windowsocr"
                and attempted >= minimum_attempts
                and self._is_reliable_result(result)
            ):
                if normalized_engine != "tesseract" or len(engine_variants) == 1:
                    break
                texts = [
                    normalize_ocr_text(candidate.text, language_tag).casefold()
                    for candidate in results
                    if normalize_ocr_text(candidate.text, language_tag)
                ]
                if len(texts) >= 2 and len(set(texts)) == 1:
                    break
            _raise_if_cancelled(cancel_check)

        return results, warnings

    def _is_reliable_result(self, result: EngineResult | None) -> bool:
        if not result or result.score < self.config.ocr_accept_score:
            return False
        if result.raw_confidence is None:
            return result.score >= max(self.config.ocr_accept_score, 0.86)
        return result.raw_confidence >= self.config.ocr_accept_confidence

    def _engine_results_are_conclusive(
        self,
        engine: str,
        results: list[EngineResult],
        *,
        available_variants: int,
        language_tag: str | None = "en",
    ) -> bool:
        best = rank_ocr_results(results, language_tag=language_tag)
        if not self._is_reliable_result(best):
            return False
        if engine != "tesseract":
            return True

        required = min(2, available_variants)
        texts = [
            normalize_ocr_text(result.text, language_tag).casefold()
            for result in results
            if normalize_ocr_text(result.text, language_tag)
        ]
        return len(texts) >= required and len(set(texts)) == 1

    def _run_engine_with_timeout(
        self,
        normalized_engine: str,
        image: Image.Image,
        language_tag: str | None = None,
    ) -> EngineResult:
        timeout = self.config.ocr_engine_timeout_seconds
        if not self._acquire_engine_slot(timeout):
            raise OcrCapacityError("OCR engine capacity is busy")
        if timeout <= 0:
            try:
                return self._run_engine(normalized_engine, image, language_tag)
            finally:
                self._engine_slots.release()

        try:
            future = self._engine_executor.submit(
                self._run_engine,
                normalized_engine,
                image,
                language_tag,
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

    def _run_engine(
        self,
        normalized_engine: str,
        image: Image.Image,
        language_tag: str | None = None,
    ) -> EngineResult:
        if normalized_engine == "windowsocr":
            return self._run_windowsocr(image, language_tag)
        if normalized_engine == "easyocr":
            return self._run_easyocr(image)
        if normalized_engine == "paddleocr":
            return self._run_paddleocr(image)
        return self._run_tesseract(image)

    def _run_windowsocr(
        self,
        image: Image.Image,
        language_tag: str | None = None,
    ) -> EngineResult:
        text = self._get_windowsocr_adapter().recognize(image, language_tag)
        return EngineResult("windowsocr", text, 0.0, None)

    def _get_windowsocr_adapter(self) -> WindowsOcrAdapter:
        if self._windowsocr_adapter is None:
            with self._windowsocr_lock:
                if self._windowsocr_adapter is None:
                    self._windowsocr_adapter = WindowsOcrAdapter(
                        self.config.windows_ocr_lang
                    )
        return self._windowsocr_adapter

    def _run_easyocr(self, image: Image.Image) -> EngineResult:
        import numpy as np

        reader = self._get_easyocr_reader()

        with self._easyocr_lock:
            detections = reader.readtext(
                np.asarray(image.convert("RGB")),
                detail=1,
                paragraph=False,
                decoder="beamsearch",
                beamWidth=5,
                contrast_ths=0.05,
                adjust_contrast=0.7,
                mag_ratio=1.5,
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
            for text, confidence in _ordered_paddleocr_fragments(payload):
                fragments.append(text)
                if confidence is not None:
                    confidences.append(confidence)

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

        primary = self._run_tesseract_psm(image, 6)
        primary.score = text_quality_score(
            normalize_ocr_text(primary.text),
            primary.raw_confidence,
            raw_text=primary.text,
        )
        if self._is_reliable_result(primary):
            return primary

        sparse = self._run_tesseract_psm(image, 11)
        sparse.score = text_quality_score(
            normalize_ocr_text(sparse.text),
            sparse.raw_confidence,
            raw_text=sparse.text,
        )
        best = rank_ocr_results([primary, sparse])
        return best or primary

    def _run_tesseract_psm(self, image: Image.Image, psm: int) -> EngineResult:
        import pytesseract
        from pytesseract import Output

        tesseract_config = (
            f"--oem 1 --psm {psm} -c preserve_interword_spaces=1"
        )

        data = pytesseract.image_to_data(
            image,
            lang=self.config.tesseract_lang,
            config=tesseract_config,
            output_type=Output.DICT,
        )
        recognized = _filtered_tesseract_words(data)
        words = [text for text, _confidence in recognized]
        confidences = [confidence / 100 for _text, confidence in recognized]

        if words:
            confidence = sum(confidences) / len(confidences) if confidences else 0.0
            return EngineResult("tesseract", " ".join(words), confidence, confidence)

        raw_words = [str(value).strip() for value in data.get("text", [])]
        if not any(raw_words):
            return EngineResult("tesseract", "", 0.0, 0.0)

        fallback = pytesseract.image_to_string(
            image,
            lang=self.config.tesseract_lang,
            config=tesseract_config,
        )
        return EngineResult("tesseract", fallback, 0.35, 0.35)

    def _ensure_tesseract_available(self) -> None:
        if importlib.util.find_spec("pytesseract") is None:
            raise RuntimeError("pytesseract package is not installed")

        import pytesseract

        configured = pytesseract.pytesseract.tesseract_cmd
        if shutil.which(configured):
            return

        if os.name == "nt":
            candidates = (
                os.path.join(
                    os.environ.get("ProgramFiles", r"C:\Program Files"),
                    "Tesseract-OCR",
                    "tesseract.exe",
                ),
                os.path.join(
                    os.environ.get("LOCALAPPDATA", ""),
                    "Programs",
                    "Tesseract-OCR",
                    "tesseract.exe",
                ),
            )
            for candidate in candidates:
                if candidate and os.path.isfile(candidate):
                    pytesseract.pytesseract.tesseract_cmd = candidate
                    return

        raise RuntimeError("tesseract executable is not installed or not on PATH")

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

    def _windowsocr_health(self) -> dict[str, Any]:
        return windows_ocr_health(self.config.windows_ocr_lang)

    def _tesseract_health(self) -> dict[str, Any]:
        if importlib.util.find_spec("pytesseract") is None:
            return {"installed": False, "language": self.config.tesseract_lang}

        try:
            import pytesseract

            self._ensure_tesseract_available()
            version = str(pytesseract.get_tesseract_version())
            return {
                "installed": True,
                "language": self.config.tesseract_lang,
                "version": version,
                "executable": pytesseract.pytesseract.tesseract_cmd,
            }
        except Exception as exc:
            return {
                "installed": False,
                "language": self.config.tesseract_lang,
                "error": str(exc),
            }


def _base_engine(engine: str) -> str:
    return str(engine).split(":", 1)[0].strip().lower()


def _normalize_preprocessing_profile(profile: str) -> str:
    normalized = str(profile).strip().lower()
    if normalized not in SUPPORTED_OCR_PREPROCESSING_PROFILES:
        raise ValueError(f"unsupported OCR preprocessing profile: {profile}")
    return OCR_PREPROCESSING_STANDARD if normalized == "auto" else normalized


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
        or "worker crashed" in message
    )


def _automatic_engine_has_terminal_failure(
    engine: str, results: list[EngineResult]
) -> bool:
    for result in results:
        if _base_engine(result.engine) != engine or not result.warning:
            continue
        warning = result.warning.lower()
        if "timed out on" in warning or _is_engine_setup_failure(
            RuntimeError(warning)
        ):
            return True
    return False


def _automatic_consensus_key(
    text: str, language_tag: str | None = "en"
) -> str:
    normalized = normalize_ocr_text(text, language_tag).casefold()
    characters = [
        character
        for character in normalized
        if character.isalnum() or character.isspace()
    ]
    return " ".join("".join(characters).split())


def _has_single_safe_consensus_edit(left: str, right: str) -> bool:
    changed_characters = ""
    edit_cost = 0
    matcher = SequenceMatcher(
        None,
        left,
        right,
    )
    for operation, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        edit_cost += max(left_end - left_start, right_end - right_start)
        changed_characters += left[left_start:left_end] + right[right_start:right_end]
        if edit_cost > 1:
            return False

    return (
        edit_cost == 1
        and bool(changed_characters)
        and all(character.isalpha() for character in changed_characters)
    )


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


def _ordered_paddleocr_fragments(
    payload: dict[str, Any],
) -> list[tuple[str, float | None]]:
    texts = list(payload.get("rec_texts", []))
    scores = list(payload.get("rec_scores", []))
    boxes = list(payload.get("rec_boxes", []))
    polygons = list(payload.get("rec_polys", []))
    entries: list[dict[str, Any]] = []

    for index, value in enumerate(texts):
        text = str(value).strip()
        if not text:
            continue
        confidence = _finite_float(scores[index]) if index < len(scores) else None
        geometry = None
        if index < len(boxes):
            geometry = _paddle_bounds(boxes[index])
        if geometry is None and index < len(polygons):
            geometry = _paddle_bounds(polygons[index])
        entries.append(
            {
                "text": text,
                "confidence": confidence,
                "geometry": geometry,
                "index": index,
            }
        )

    if entries and all(entry["geometry"] is not None for entry in entries):
        entries = _filtered_paddle_entries(entries)
        entries = _sort_paddle_entries(entries)
    return [(entry["text"], entry["confidence"]) for entry in entries]


def _paddle_bounds(value: Any) -> tuple[float, float, float, float] | None:
    try:
        coordinates = list(value)
    except TypeError:
        return None

    if len(coordinates) >= 4 and all(
        _finite_float(coordinate) is not None for coordinate in coordinates[:4]
    ):
        left, top, right, bottom = (
            float(coordinate) for coordinate in coordinates[:4]
        )
    else:
        points: list[tuple[float, float]] = []
        for point in coordinates:
            try:
                point_values = list(point)
            except TypeError:
                continue
            if len(point_values) < 2:
                continue
            x = _finite_float(point_values[0])
            y = _finite_float(point_values[1])
            if x is not None and y is not None:
                points.append((x, y))
        if not points:
            return None
        left = min(point[0] for point in points)
        top = min(point[1] for point in points)
        right = max(point[0] for point in points)
        bottom = max(point[1] for point in points)

    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _sort_paddle_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines: list[list[dict[str, Any]]] = []
    ordered_by_height = sorted(
        entries,
        key=lambda entry: (
            (entry["geometry"][1] + entry["geometry"][3]) / 2,
            entry["geometry"][0],
        ),
    )

    for entry in ordered_by_height:
        top = entry["geometry"][1]
        bottom = entry["geometry"][3]
        center = (top + bottom) / 2
        height = bottom - top
        matching_line = None
        matching_distance = math.inf
        for line in lines:
            centers = [
                (item["geometry"][1] + item["geometry"][3]) / 2
                for item in line
            ]
            line_center = sum(centers) / len(centers)
            line_height = max(
                item["geometry"][3] - item["geometry"][1] for item in line
            )
            distance = abs(center - line_center)
            if (
                distance <= max(height, line_height) * 0.6
                and distance < matching_distance
            ):
                matching_line = line
                matching_distance = distance
        if matching_line is None:
            lines.append([entry])
        else:
            matching_line.append(entry)

    lines.sort(
        key=lambda line: sum(
            (item["geometry"][1] + item["geometry"][3]) / 2 for item in line
        )
        / len(line)
    )
    ordered: list[dict[str, Any]] = []
    for line in lines:
        line.sort(key=lambda entry: (entry["geometry"][0], entry["index"]))
        ordered.extend(line)
    return ordered


def _filtered_paddle_entries(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reliable = [
        entry
        for entry in entries
        if entry["confidence"] is not None and entry["confidence"] >= 0.70
    ]
    if not reliable:
        return entries

    reliable_heights = sorted(
        entry["geometry"][3] - entry["geometry"][1]
        for entry in reliable
    )
    median_height = reliable_heights[len(reliable_heights) // 2]
    filtered: list[dict[str, Any]] = []
    for entry in entries:
        confidence = entry["confidence"]
        left, top, right, bottom = entry["geometry"]
        height = bottom - top
        center = (top + bottom) / 2
        same_line_reliable = [
            candidate
            for candidate in reliable
            if abs(
                center
                - (candidate["geometry"][1] + candidate["geometry"][3]) / 2
            )
            <= max(height, candidate["geometry"][3] - candidate["geometry"][1])
            * 0.65
        ]
        is_small_leading_artifact = bool(
            confidence is not None
            and confidence < 0.65
            and height < median_height * 0.75
            and same_line_reliable
            and right <= min(candidate["geometry"][0] for candidate in same_line_reliable)
            and _looks_like_paddle_leading_artifact(entry["text"])
        )
        if not is_small_leading_artifact:
            filtered.append(entry)
    return filtered


def _looks_like_paddle_leading_artifact(text: str) -> bool:
    normalized = str(text).strip()
    return normalized == "#" or any(character.isalnum() for character in normalized)


def _filtered_tesseract_words(data: dict[str, Any]) -> list[tuple[str, float]]:
    texts = list(data.get("text", []))
    entries: list[dict[str, Any]] = []
    for index, value in enumerate(texts):
        text = str(value).strip()
        confidence = _tesseract_value(data, "conf", index)
        height = _tesseract_value(data, "height", index)
        left = _tesseract_value(data, "left", index)
        width = _tesseract_value(data, "width", index)
        if not text or confidence is None or confidence < 0:
            continue
        if height is None or height <= 0 or left is None or width is None:
            continue
        entries.append(
            {
                "text": text,
                "confidence": confidence,
                "height": height,
                "left": left,
                "right": left + max(0, width),
                "line": (
                    _tesseract_integer(data, "block_num", index),
                    _tesseract_integer(data, "par_num", index),
                    _tesseract_integer(data, "line_num", index),
                ),
                "word": _tesseract_integer(data, "word_num", index),
                "index": index,
            }
        )

    if not entries:
        return []

    reliable_heights = sorted(
        entry["height"] for entry in entries if entry["confidence"] >= 50
    )
    heights = reliable_heights or sorted(entry["height"] for entry in entries)
    median_height = heights[len(heights) // 2]
    entries = [
        entry for entry in entries if entry["height"] <= median_height * 1.8
    ]

    lines: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for entry in entries:
        lines.setdefault(entry["line"], []).append(entry)

    filtered: list[dict[str, Any]] = []
    for line_entries in lines.values():
        reliable = [entry for entry in line_entries if entry["confidence"] >= 50]
        if not reliable:
            continue
        first_reliable_left = min(entry["left"] for entry in reliable)
        for entry in line_entries:
            is_detached_low_confidence = (
                entry["confidence"] < 50
                and entry["right"] < first_reliable_left - median_height * 1.5
            )
            if not is_detached_low_confidence:
                filtered.append(entry)

    filtered.sort(key=lambda entry: (entry["line"], entry["word"], entry["index"]))
    return [
        (entry["text"], entry["confidence"])
        for entry in filtered
    ]


def _tesseract_value(
    data: dict[str, Any], key: str, index: int
) -> float | None:
    values = data.get(key, [])
    try:
        return _finite_float(values[index])
    except (IndexError, KeyError, TypeError):
        return None


def _tesseract_integer(data: dict[str, Any], key: str, index: int) -> int:
    value = _tesseract_value(data, key, index)
    return int(value) if value is not None else 0

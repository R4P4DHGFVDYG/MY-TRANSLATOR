from __future__ import annotations

from collections import OrderedDict
import json
import threading
from time import perf_counter
from typing import Any

from flask import Flask, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from .config import BridgeConfig
from .debug_capture import DebugCapture, debug_capture_requested
from .image_utils import (
    ImagePayloadTooLarge,
    crop_visible_selection,
    image_from_data_url,
)
from .libretranslate import LibreTranslateClient, TranslationResult
from .ocr import (
    OCR_PREPROCESSING_AUTO,
    SUPPORTED_OCR_PREPROCESSING_PROFILES,
    OcrCancelledError,
    OcrCapacityError,
    OcrService,
)
from .translation_text import prepare_text_for_translation


def create_app(
    config: BridgeConfig | None = None,
    ocr_service: OcrService | None = None,
    translator: LibreTranslateClient | None = None,
) -> Flask:
    bridge_config = config or BridgeConfig.from_env()
    ocr = ocr_service or OcrService(bridge_config)
    translator_client = translator or LibreTranslateClient(bridge_config)
    latest_requests = LatestRequestRegistry()
    warmup_complete = threading.Event()
    warmup_warnings: list[str] = []

    if bridge_config.ocr_warmup_on_start and ocr_service is None:
        _start_ocr_warmup(ocr, bridge_config, warmup_complete, warmup_warnings)
    else:
        warmup_complete.set()

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = bridge_config.max_request_bytes

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(_error: RequestEntityTooLarge):
        return _error_response("request body exceeds the allowed size", 413)

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin")
        if origin and origin in bridge_config.cors_allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers.add("Vary", "Origin")
        return response

    @app.get("/health")
    def health():
        translation_health = translator_client.health()
        return jsonify(
            {
                "bridge": {"ok": True},
                "translation": translation_health,
                "libretranslate": translation_health.get("libretranslate", {}),
                "ocr": ocr.health_checks(),
                "warmup": {
                    "enabled": bridge_config.ocr_warmup_on_start,
                    "complete": warmup_complete.is_set(),
                    "warnings": list(warmup_warnings),
                },
                "debug": {
                    "saveCaptures": bridge_config.save_debug_captures,
                    "requestCapturesAllowed": bridge_config.allow_request_debug_captures,
                },
            }
        )

    @app.get("/ready")
    def ready():
        payload = {
            "ready": warmup_complete.is_set(),
            "warnings": list(warmup_warnings),
        }
        return jsonify(payload), 200 if payload["ready"] else 503

    @app.post("/v1/translate-selection")
    def translate_selection():
        started_at = perf_counter()
        timings: dict[str, float] = {}
        parse_started_at = perf_counter()
        payload = request.get_json(silent=True)
        timings["requestParseMs"] = _elapsed_ms(parse_started_at)
        if not isinstance(payload, dict):
            return _error_response("request body must be JSON", 400)

        try:
            ticket = latest_requests.begin(payload)
        except ValueError as exc:
            return _error_response(str(exc), 400)
        if not ticket.is_current():
            return _superseded_response(
                ticket, started_at, timings, bridge_config
            )

        try:
            decode_started_at = perf_counter()
            image = image_from_data_url(
                payload.get("imageDataUrl"),
                max_image_bytes=bridge_config.max_image_bytes,
                max_image_pixels=bridge_config.max_image_pixels,
            )
            timings["imageDecodeMs"] = _elapsed_ms(decode_started_at)

            crop_started_at = perf_counter()
            crop, crop_meta = crop_visible_selection(
                image,
                _dict_field(payload, "selection"),
                _dict_field(payload, "viewport"),
                max_crop_pixels=bridge_config.max_crop_pixels,
            )
            timings["cropMs"] = _elapsed_ms(crop_started_at)
        except ImagePayloadTooLarge as exc:
            return _error_response(str(exc), 413)
        except ValueError as exc:
            return _error_response(str(exc), 400)

        if not ticket.is_current():
            return _superseded_response(
                ticket, started_at, timings, bridge_config
            )

        try:
            engines = _requested_ocr_engines(payload, bridge_config)
            preprocessing_profile = _requested_ocr_preprocessing_profile(payload)
        except ValueError as exc:
            return _error_response(str(exc), 400)

        source = _language_code(payload.get("source") or "en")
        target = _language_code(payload.get("target") or "pt-BR")

        debug_capture: DebugCapture | None = None
        debug_warning = ""
        if debug_capture_requested(bridge_config, payload):
            debug_started_at = perf_counter()
            try:
                debug_capture = DebugCapture(bridge_config, payload, crop, crop_meta)
            except Exception:
                debug_capture = None
                debug_warning = "debug capture could not be saved"
            timings["debugCaptureMs"] = _elapsed_ms(debug_started_at)

        ocr_started_at = perf_counter()
        try:
            best, engine_results, warnings, ocr_metadata = _detect_text(
                ocr,
                crop,
                engines,
                ticket,
                source,
                preprocessing_profile,
            )
        except OcrCancelledError:
            timings["ocrMs"] = _elapsed_ms(ocr_started_at)
            return _superseded_response(
                ticket, started_at, timings, bridge_config
            )
        except OcrCapacityError as exc:
            response = {"error": str(exc), "warnings": [debug_warning] if debug_warning else []}
            timings["ocrMs"] = _elapsed_ms(ocr_started_at)
            _attach_performance(
                response,
                ticket,
                started_at,
                timings,
                bridge_config,
                {"ocr": False, "translation": False},
            )
            _save_debug_response(debug_capture, response, 503)
            return jsonify(response), 503
        timings["ocrMs"] = _elapsed_ms(ocr_started_at)
        cache_status = {
            "ocr": ocr_metadata.get("cacheHit") is True,
            "translation": False,
        }
        if debug_warning:
            warnings = [*warnings, debug_warning]
        response_base: dict[str, Any] = {
            "sourceText": best.text if best else "",
            "translatedText": "",
            "engineResults": [result.to_dict() for result in engine_results],
            "warnings": warnings,
            "crop": crop_meta,
        }
        if debug_capture:
            response_base["debugCapture"] = debug_capture.to_dict()

        if best is None or not best.text:
            response_base["warnings"] = [*warnings, "No OCR text detected"]
            _attach_performance(
                response_base,
                ticket,
                started_at,
                timings,
                bridge_config,
                cache_status,
            )
            _save_debug_response(debug_capture, response_base)
            return jsonify(response_base)

        if not ticket.is_current():
            return _superseded_response(
                ticket, started_at, timings, bridge_config
            )

        translation_started_at = perf_counter()
        try:
            translation_source_text = prepare_text_for_translation(best.text)
            translation = _translate(
                translator_client,
                translation_source_text,
                source=source,
                target=target,
            )
            timings["translationMs"] = _elapsed_ms(translation_started_at)
            cache_status["translation"] = translation.provider == "cache"
            if not ticket.is_current():
                return _superseded_response(
                    ticket, started_at, timings, bridge_config
                )
            response_base["translatedText"] = translation.text
            if translation_source_text != best.text:
                response_base["translationSourceText"] = translation_source_text
            if translation.provider:
                response_base["translationProvider"] = translation.provider
            if translation.warnings:
                response_base["warnings"] = [
                    *response_base["warnings"],
                    "translation fallback: " + "; ".join(translation.warnings),
                ]
        except RuntimeError as exc:
            timings["translationMs"] = _elapsed_ms(translation_started_at)
            if not ticket.is_current():
                return _superseded_response(
                    ticket, started_at, timings, bridge_config
                )
            response_base["error"] = str(exc)
            _attach_performance(
                response_base,
                ticket,
                started_at,
                timings,
                bridge_config,
                cache_status,
            )
            _save_debug_response(debug_capture, response_base, 502)
            return jsonify(response_base), 502

        _attach_performance(
            response_base,
            ticket,
            started_at,
            timings,
            bridge_config,
            cache_status,
        )
        _save_debug_response(debug_capture, response_base)
        return jsonify(response_base)

    return app


def _start_ocr_warmup(
    ocr: OcrService,
    config: BridgeConfig,
    complete: threading.Event,
    collected_warnings: list[str],
) -> None:
    def run_warmup() -> None:
        started_at = perf_counter()
        try:
            warnings = ocr.warm_up(list(config.ocr_warmup_engines))
            collected_warnings.extend(warnings)
            for warning in warnings:
                print(f"OCR warmup: {warning}", flush=True)
        finally:
            complete.set()
            if config.log_performance:
                print(
                    "[performance] "
                    + json.dumps(
                        {
                            "stage": "ocrWarmup",
                            "engines": list(config.ocr_warmup_engines),
                            "totalMs": round(_elapsed_ms(started_at), 2),
                            "warnings": len(collected_warnings),
                        },
                        separators=(",", ":"),
                    ),
                    flush=True,
                )

    thread = threading.Thread(target=run_warmup, name="ocr-warmup", daemon=True)
    thread.start()


class RequestTicket:
    def __init__(
        self,
        registry: "LatestRequestRegistry | None",
        client_id: str | None,
        request_id: int | None,
    ) -> None:
        self._registry = registry
        self.client_id = client_id
        self.request_id = request_id

    def is_current(self) -> bool:
        if self._registry is None or self.client_id is None or self.request_id is None:
            return True
        return self._registry.is_current(self.client_id, self.request_id)

    @property
    def log_id(self) -> str:
        return str(self.request_id) if self.request_id is not None else "untracked"


class LatestRequestRegistry:
    def __init__(self, capacity: int = 128) -> None:
        self.capacity = capacity
        self._latest: OrderedDict[str, int] = OrderedDict()
        self._lock = threading.Lock()

    def begin(self, payload: dict[str, Any]) -> RequestTicket:
        client_id = payload.get("clientId")
        request_id = payload.get("requestId")
        if client_id is None and request_id is None:
            return RequestTicket(None, None, None)
        if not isinstance(client_id, str) or not client_id.strip():
            raise ValueError("clientId must be a non-empty string")
        client_id = client_id.strip()
        if len(client_id) > 128:
            raise ValueError("clientId is too long")
        if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id < 1:
            raise ValueError("requestId must be a positive integer")

        with self._lock:
            latest = self._latest.get(client_id)
            if latest is None or request_id >= latest:
                self._latest[client_id] = request_id
                self._latest.move_to_end(client_id)
                while len(self._latest) > self.capacity:
                    self._latest.popitem(last=False)

        return RequestTicket(self, client_id, request_id)

    def is_current(self, client_id: str, request_id: int) -> bool:
        with self._lock:
            return self._latest.get(client_id) == request_id


def _detect_text(
    ocr: Any,
    crop: Any,
    engines: list[str],
    ticket: RequestTicket,
    language_tag: str | None = None,
    preprocessing_profile: str = OCR_PREPROCESSING_AUTO,
) -> tuple[Any, list[Any], list[str], dict[str, bool]]:
    detect_with_metadata = getattr(ocr, "detect_text_with_metadata", None)
    if callable(detect_with_metadata):
        optional_kwargs: dict[str, Any] = {}
        if preprocessing_profile != OCR_PREPROCESSING_AUTO:
            optional_kwargs["preprocessing_profile"] = preprocessing_profile
        return detect_with_metadata(
            crop,
            engines,
            cancel_check=lambda: not ticket.is_current(),
            language_tag=language_tag,
            **optional_kwargs,
        )

    best, engine_results, warnings = ocr.detect_text(crop, engines)
    return best, engine_results, warnings, {"cacheHit": False}


def _elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1000


def _attach_performance(
    response: dict[str, Any],
    ticket: RequestTicket,
    started_at: float,
    timings: dict[str, float],
    config: BridgeConfig,
    cache_status: dict[str, bool],
) -> None:
    timings["totalMs"] = _elapsed_ms(started_at)
    rounded_timings = {
        name: round(duration, 2) for name, duration in timings.items()
    }
    response["performance"] = {
        "requestId": ticket.request_id,
        "timings": rounded_timings,
        "cache": dict(cache_status),
    }
    if config.log_performance:
        print(
            "[performance] "
            + json.dumps(
                {
                    "requestId": ticket.log_id,
                    **rounded_timings,
                    "ocrCacheHit": cache_status.get("ocr", False),
                    "translationCacheHit": cache_status.get(
                        "translation", False
                    ),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )


def _superseded_response(
    ticket: RequestTicket,
    started_at: float,
    timings: dict[str, float],
    config: BridgeConfig,
):
    response: dict[str, Any] = {
        "cancelled": True,
        "error": "request was superseded by a newer capture",
    }
    _attach_performance(
        response,
        ticket,
        started_at,
        timings,
        config,
        {"ocr": False, "translation": False},
    )
    return jsonify(response), 409


def _dict_field(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")

    return value


def _error_response(message: str, status_code: int):
    return jsonify({"error": message}), status_code


def _language_code(value: Any) -> str:
    code = str(value).strip()
    return "pt-BR" if code.lower() in {"pt", "pt-br"} else code.lower()


def _requested_ocr_engines(
    payload: dict[str, Any], config: BridgeConfig
) -> list[str]:
    if config.force_ocr_engines:
        return list(config.default_ocr_engines)

    if "engines" not in payload or payload["engines"] is None:
        return list(config.default_ocr_engines)

    requested = payload["engines"]
    if not isinstance(requested, list):
        raise ValueError("engines must be a list")
    if not requested:
        raise ValueError("engines must not be empty")
    if len(requested) > config.max_ocr_engines * 2:
        raise ValueError("too many OCR engines were requested")

    engines: list[str] = []
    for engine in requested:
        if not isinstance(engine, str) or not engine.strip():
            raise ValueError("every engine must be a non-empty string")
        normalized = engine.strip().lower()
        if normalized not in config.allowed_ocr_engines:
            raise ValueError(f"unsupported OCR engine: {engine}")
        if normalized not in engines:
            engines.append(normalized)

    if len(engines) > config.max_ocr_engines:
        raise ValueError("too many OCR engines were requested")
    return engines


def _requested_ocr_preprocessing_profile(payload: dict[str, Any]) -> str:
    requested = payload.get("ocrPreprocessing", OCR_PREPROCESSING_AUTO)
    if requested is None:
        return OCR_PREPROCESSING_AUTO
    if not isinstance(requested, str) or not requested.strip():
        raise ValueError("ocrPreprocessing must be a non-empty string")

    normalized = requested.strip().lower()
    if normalized not in SUPPORTED_OCR_PREPROCESSING_PROFILES:
        raise ValueError(
            f"unsupported OCR preprocessing profile: {requested}"
        )
    return normalized


def _translate(
    translator: Any,
    text: str,
    *,
    source: str,
    target: str,
) -> TranslationResult:
    translate_result = getattr(translator, "translate_result", None)
    if callable(translate_result):
        result = translate_result(text, source=source, target=target)
        if not isinstance(result, TranslationResult):
            raise RuntimeError("translator returned an invalid result")
        return result

    translated = translator.translate(text, source=source, target=target)
    if not isinstance(translated, str):
        raise RuntimeError("translator returned an invalid result")
    return TranslationResult(text=translated)


def _save_debug_response(
    debug_capture: DebugCapture | None,
    response: dict[str, Any],
    status_code: int = 200,
) -> None:
    if debug_capture is None:
        return

    try:
        debug_capture.save_response(response, status_code)
    except Exception:
        warnings = response.setdefault("warnings", [])
        if isinstance(warnings, list):
            warnings.append("debug capture response could not be saved")

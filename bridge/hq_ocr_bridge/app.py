from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request

from .config import BridgeConfig
from .debug_capture import DebugCapture, debug_capture_requested
from .image_utils import crop_visible_selection, image_from_data_url
from .libretranslate import LibreTranslateClient
from .ocr import DEFAULT_ENGINES, OcrService
from .translation_text import prepare_text_for_translation


def create_app(
    config: BridgeConfig | None = None,
    ocr_service: OcrService | None = None,
    translator: LibreTranslateClient | None = None,
) -> Flask:
    bridge_config = config or BridgeConfig.from_env()
    ocr = ocr_service or OcrService(bridge_config)
    translator_client = translator or LibreTranslateClient(bridge_config)

    app = Flask(__name__)

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
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
                "debug": {
                    "saveCaptures": bridge_config.save_debug_captures,
                    "captureDirectory": bridge_config.debug_capture_dir,
                },
            }
        )

    @app.post("/v1/translate-selection")
    def translate_selection():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("request body must be JSON", 400)

        try:
            image = image_from_data_url(payload.get("imageDataUrl"))
            crop, crop_meta = crop_visible_selection(
                image,
                _dict_field(payload, "selection"),
                _dict_field(payload, "viewport"),
            )
        except ValueError as exc:
            return _error(str(exc), 400)

        engines = payload.get("engines") or DEFAULT_ENGINES
        if not isinstance(engines, list):
            return _error("engines must be a list", 400)

        source = _language_code(payload.get("source") or "en")
        target = _language_code(payload.get("target") or "pt-BR")

        debug_capture: DebugCapture | None = None
        if debug_capture_requested(bridge_config, payload):
            try:
                debug_capture = DebugCapture(bridge_config, payload, crop, crop_meta)
            except OSError as exc:
                debug_capture = None
                debug_warning = f"debug capture failed: {exc}"
            else:
                debug_warning = ""
        else:
            debug_warning = ""

        best, engine_results, warnings = ocr.detect_text(crop, engines)
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
            if debug_capture:
                debug_capture.save_response(response_base)
            return jsonify(response_base)

        try:
            translation_source_text = prepare_text_for_translation(best.text)
            response_base["translatedText"] = translator_client.translate(
                translation_source_text,
                source=source,
                target=target,
            )
            if translation_source_text != best.text:
                response_base["translationSourceText"] = translation_source_text
            translation_provider = getattr(translator_client, "last_provider", None)
            if translation_provider:
                response_base["translationProvider"] = translation_provider
            translation_warnings = getattr(translator_client, "last_warnings", [])
            if translation_warnings:
                response_base["warnings"] = [
                    *response_base["warnings"],
                    "translation fallback: " + "; ".join(translation_warnings),
                ]
        except RuntimeError as exc:
            response_base["error"] = str(exc)
            if debug_capture:
                debug_capture.save_response(response_base, 502)
            return jsonify(response_base), 502

        if debug_capture:
            debug_capture.save_response(response_base)
        return jsonify(response_base)

    return app


def _dict_field(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")

    return value


def _error(message: str, status_code: int):
    return jsonify({"error": message}), status_code


def _language_code(value: Any) -> str:
    code = str(value).strip()
    return "pt-BR" if code.lower() in {"pt", "pt-br"} else code.lower()

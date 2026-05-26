from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request

from .config import BridgeConfig
from .image_utils import crop_visible_selection, image_from_data_url
from .libretranslate import LibreTranslateClient
from .ocr import DEFAULT_ENGINES, OcrService


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
        return jsonify(
            {
                "bridge": {"ok": True},
                "libretranslate": translator_client.health(),
                "ocr": ocr.health_checks(),
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

        source = str(payload.get("source") or "en").lower()
        target = str(payload.get("target") or "pt").lower()

        best, engine_results, warnings = ocr.detect_text(crop, engines)
        response_base: dict[str, Any] = {
            "sourceText": best.text if best else "",
            "translatedText": "",
            "engineResults": [result.to_dict() for result in engine_results],
            "warnings": warnings,
            "crop": crop_meta,
        }

        if best is None or not best.text:
            response_base["warnings"] = [*warnings, "No OCR text detected"]
            return jsonify(response_base)

        try:
            response_base["translatedText"] = translator_client.translate(
                best.text,
                source=source,
                target=target,
            )
        except RuntimeError as exc:
            response_base["error"] = str(exc)
            return jsonify(response_base), 502

        return jsonify(response_base)

    return app


def _dict_field(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")

    return value


def _error(message: str, status_code: int):
    return jsonify({"error": message}), status_code

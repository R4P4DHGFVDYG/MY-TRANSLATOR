from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image

from hq_ocr_bridge.app import create_app
from hq_ocr_bridge.config import BridgeConfig
from hq_ocr_bridge.models import EngineResult


class FakeOcrService:
    def health_checks(self):
        return {"fake": {"installed": True}}

    def detect_text(self, image, engines):
        result = EngineResult("fake", "HELLO WORLD", 0.9, 0.9)
        return result, [result], []


class FakeTranslator:
    def __init__(self):
        self.requests = []

    def health(self):
        return {"ok": True}

    def translate(self, text, source="en", target="pt-BR"):
        self.requests.append({"text": text, "source": source, "target": target})
        assert text == "Hello world"
        assert source == "en"
        assert target == "pt-BR"
        return "OLA MUNDO"


def test_translate_selection_contract():
    translator = FakeTranslator()
    app = create_app(
        BridgeConfig(),
        ocr_service=FakeOcrService(),
        translator=translator,
    )
    client = app.test_client()

    response = client.post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(),
            "selection": {"x": 0, "y": 0, "width": 20, "height": 20},
            "viewport": {"width": 20, "height": 20},
            "source": "en",
            "target": "pt-BR",
            "engines": ["easyocr", "tesseract"],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["sourceText"] == "HELLO WORLD"
    assert payload["translationSourceText"] == "Hello world"
    assert payload["translatedText"] == "OLA MUNDO"
    assert payload["engineResults"][0]["engine"] == "fake"
    assert translator.requests == [
        {"text": "Hello world", "source": "en", "target": "pt-BR"}
    ]


def test_invalid_payload_returns_400():
    app = create_app(
        BridgeConfig(),
        ocr_service=FakeOcrService(),
        translator=FakeTranslator(),
    )
    client = app.test_client()

    response = client.post("/v1/translate-selection", json={"imageDataUrl": "bad"})

    assert response.status_code == 400


def test_debug_capture_writes_crop_and_metadata(tmp_path):
    app = create_app(
        BridgeConfig(debug_capture_dir=str(tmp_path)),
        ocr_service=FakeOcrService(),
        translator=FakeTranslator(),
    )
    client = app.test_client()

    response = client.post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(),
            "selection": {"x": 0, "y": 0, "width": 20, "height": 20},
            "viewport": {"width": 20, "height": 20},
            "source": "en",
            "target": "pt-BR",
            "engines": ["easyocr"],
            "debug": True,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    debug_dir = tmp_path / payload["debugCapture"]["id"]
    assert (debug_dir / "crop.png").exists()
    assert (debug_dir / "ocr-preprocessed.png").exists()
    assert (debug_dir / "ocr-preprocessed-standard.png").exists()
    assert (debug_dir / "ocr-preprocessed-soft.png").exists()
    assert (debug_dir / "ocr-preprocessed-binary.png").exists()
    assert (debug_dir / "request.json").exists()
    assert (debug_dir / "response.json").exists()


def _png_data_url() -> str:
    image = Image.new("RGB", (20, 20), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{data}"

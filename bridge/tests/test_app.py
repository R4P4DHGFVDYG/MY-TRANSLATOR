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
    def health(self):
        return {"ok": True}

    def translate(self, text, source="en", target="pt"):
        assert text == "HELLO WORLD"
        assert source == "en"
        assert target == "pt"
        return "OLA MUNDO"


def test_translate_selection_contract():
    app = create_app(
        BridgeConfig(),
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
            "target": "pt",
            "engines": ["easyocr", "tesseract"],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["sourceText"] == "HELLO WORLD"
    assert payload["translatedText"] == "OLA MUNDO"
    assert payload["engineResults"][0]["engine"] == "fake"


def test_invalid_payload_returns_400():
    app = create_app(
        BridgeConfig(),
        ocr_service=FakeOcrService(),
        translator=FakeTranslator(),
    )
    client = app.test_client()

    response = client.post("/v1/translate-selection", json={"imageDataUrl": "bad"})

    assert response.status_code == 400


def _png_data_url() -> str:
    image = Image.new("RGB", (20, 20), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{data}"

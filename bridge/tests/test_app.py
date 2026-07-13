from __future__ import annotations

import base64
from io import BytesIO
import json

from PIL import Image, ImageDraw

from hq_ocr_bridge.app import create_app
from hq_ocr_bridge.config import BridgeConfig
from hq_ocr_bridge.libretranslate import TranslationResult
from hq_ocr_bridge.models import EngineResult


class FakeOcrService:
    def __init__(self):
        self.requests = []

    def health_checks(self):
        return {"fake": {"installed": True}}

    def detect_text(self, image, engines):
        self.requests.append({"engines": engines})
        result = EngineResult("fake", "HELLO WORLD", 0.9, 0.9)
        return result, [result], []


class LanguageAwareOcrService(FakeOcrService):
    def detect_text_with_metadata(
        self,
        image,
        engines,
        *,
        cancel_check,
        language_tag,
        preprocessing_profile="standard",
    ):
        request = {"engines": engines, "languageTag": language_tag}
        if preprocessing_profile != "standard":
            request["preprocessingProfile"] = preprocessing_profile
        self.requests.append(request)
        result = EngineResult("fake", "HELLO WORLD", 0.9, 0.9)
        return result, [result], [], {"cacheHit": False}


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


class ResultTranslator(FakeTranslator):
    def translate_result(self, text, source="en", target="pt-BR"):
        self.requests.append({"text": text, "source": source, "target": target})
        return TranslationResult(
            text="OLA MUNDO",
            provider="google",
            warnings=("deepl: unavailable",),
        )


class FailingTranslator(FakeTranslator):
    def translate(self, text, source="en", target="pt-BR"):
        raise RuntimeError("translation provider is unavailable")


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
            "engines": ["paddleocr", "tesseract"],
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


def test_source_language_is_forwarded_to_windows_ocr():
    ocr_service = LanguageAwareOcrService()
    app = create_app(
        BridgeConfig(),
        ocr_service=ocr_service,
        translator=ResultTranslator(),
    )

    response = app.test_client().post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(),
            "selection": {"x": 0, "y": 0, "width": 20, "height": 20},
            "viewport": {"width": 20, "height": 20},
            "source": "pt-BR",
            "target": "en",
            "engines": ["windowsocr"],
        },
    )

    assert response.status_code == 200
    assert ocr_service.requests == [
        {"engines": ["windowsocr"], "languageTag": "pt-BR"}
    ]


def test_pixel_art_preprocessing_profile_reaches_ocr_service():
    ocr_service = LanguageAwareOcrService()
    app = create_app(
        BridgeConfig(),
        ocr_service=ocr_service,
        translator=ResultTranslator(),
    )

    response = app.test_client().post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(),
            "selection": {"x": 0, "y": 0, "width": 20, "height": 20},
            "viewport": {"width": 20, "height": 20},
            "source": "en",
            "target": "pt-BR",
            "engines": ["tesseract", "windowsocr", "paddleocr"],
            "ocrPreprocessing": "pixel-art",
        },
    )

    assert response.status_code == 200
    assert ocr_service.requests == [
        {
            "engines": ["tesseract", "windowsocr", "paddleocr"],
            "languageTag": "en",
            "preprocessingProfile": "pixel-art",
        }
    ]


def test_invalid_ocr_preprocessing_profile_is_rejected():
    ocr_service = LanguageAwareOcrService()
    app = create_app(
        BridgeConfig(),
        ocr_service=ocr_service,
        translator=ResultTranslator(),
    )

    response = app.test_client().post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(),
            "selection": {"x": 0, "y": 0, "width": 20, "height": 20},
            "viewport": {"width": 20, "height": 20},
            "ocrPreprocessing": "unknown",
        },
    )

    assert response.status_code == 400
    assert "unsupported OCR preprocessing profile" in response.get_json()["error"]
    assert ocr_service.requests == []


def test_translation_result_metadata_is_scoped_to_the_response():
    app = create_app(
        BridgeConfig(),
        ocr_service=FakeOcrService(),
        translator=ResultTranslator(),
    )

    response = app.test_client().post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(),
            "selection": {"x": 0, "y": 0, "width": 20, "height": 20},
            "viewport": {"width": 20, "height": 20},
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["translationProvider"] == "google"
    assert payload["warnings"] == ["translation fallback: deepl: unavailable"]


def test_translation_failure_preserves_ocr_text_and_returns_502():
    app = create_app(
        BridgeConfig(),
        ocr_service=FakeOcrService(),
        translator=FailingTranslator(),
    )

    response = app.test_client().post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(),
            "selection": {"x": 0, "y": 0, "width": 20, "height": 20},
            "viewport": {"width": 20, "height": 20},
        },
    )

    payload = response.get_json()
    assert response.status_code == 502
    assert payload["sourceText"] == "HELLO WORLD"
    assert payload["translatedText"] == ""
    assert payload["error"] == "translation provider is unavailable"


def test_invalid_payload_returns_400():
    app = create_app(
        BridgeConfig(),
        ocr_service=FakeOcrService(),
        translator=FakeTranslator(),
    )
    client = app.test_client()

    response = client.post("/v1/translate-selection", json={"imageDataUrl": "bad"})

    assert response.status_code == 400


def test_force_ocr_engines_ignores_payload_engines():
    ocr_service = FakeOcrService()
    app = create_app(
        BridgeConfig(
            default_ocr_engines=("paddleocr",),
            force_ocr_engines=True,
        ),
        ocr_service=ocr_service,
        translator=FakeTranslator(),
    )
    client = app.test_client()

    response = client.post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(),
            "selection": {"x": 0, "y": 0, "width": 20, "height": 20},
            "viewport": {"width": 20, "height": 20},
            "engines": ["easyocr"],
        },
    )

    assert response.status_code == 200
    assert ocr_service.requests == [{"engines": ["paddleocr"]}]


def test_requested_engines_are_deduplicated_and_validated():
    ocr_service = FakeOcrService()
    app = create_app(
        BridgeConfig(),
        ocr_service=ocr_service,
        translator=FakeTranslator(),
    )
    client = app.test_client()

    response = client.post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(),
            "selection": {"x": 0, "y": 0, "width": 20, "height": 20},
            "viewport": {"width": 20, "height": 20},
            "engines": ["paddleocr", " paddleocr "],
        },
    )

    assert response.status_code == 200
    assert ocr_service.requests == [{"engines": ["paddleocr"]}]

    rejected = client.post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(),
            "selection": {"x": 0, "y": 0, "width": 20, "height": 20},
            "viewport": {"width": 20, "height": 20},
            "engines": ["not-an-engine"],
        },
    )

    assert rejected.status_code == 400
    assert "unsupported OCR engine" in rejected.get_json()["error"]

    easyocr_response = client.post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(),
            "selection": {"x": 0, "y": 0, "width": 20, "height": 20},
            "viewport": {"width": 20, "height": 20},
            "engines": ["easyocr"],
        },
    )

    assert easyocr_response.status_code == 200
    assert ocr_service.requests[-1] == {"engines": ["easyocr"]}


def test_older_desktop_request_is_discarded_before_image_decode():
    ocr_service = FakeOcrService()
    app = create_app(
        BridgeConfig(log_performance=False),
        ocr_service=ocr_service,
        translator=FakeTranslator(),
    )
    client = app.test_client()
    request_payload = {
        "imageDataUrl": _png_data_url(),
        "selection": {"x": 0, "y": 0, "width": 20, "height": 20},
        "viewport": {"width": 20, "height": 20},
        "clientId": "desktop-test",
        "requestId": 2,
    }

    current = client.post("/v1/translate-selection", json=request_payload)
    stale = client.post(
        "/v1/translate-selection",
        json={"clientId": "desktop-test", "requestId": 1},
    )

    assert current.status_code == 200
    assert current.get_json()["performance"]["requestId"] == 2
    assert stale.status_code == 409
    assert stale.get_json()["cancelled"] is True
    assert ocr_service.requests == [{"engines": ["tesseract"]}]


def test_ready_endpoint_is_ready_when_an_ocr_service_is_injected():
    app = create_app(
        BridgeConfig(log_performance=False),
        ocr_service=FakeOcrService(),
        translator=FakeTranslator(),
    )

    response = app.test_client().get("/ready")

    assert response.status_code == 200
    assert response.get_json() == {"ready": True, "warnings": []}


def test_image_limits_and_non_finite_selection_values_are_rejected():
    app = create_app(
        BridgeConfig(
            max_request_bytes=1_024,
            max_image_bytes=1,
            max_image_pixels=10,
        ),
        ocr_service=FakeOcrService(),
        translator=FakeTranslator(),
    )
    client = app.test_client()

    too_large = client.post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(),
            "selection": {"x": 0, "y": 0, "width": 20, "height": 20},
            "viewport": {"width": 20, "height": 20},
        },
    )
    assert too_large.status_code == 413

    app = create_app(
        BridgeConfig(),
        ocr_service=FakeOcrService(),
        translator=FakeTranslator(),
    )
    invalid_value = app.test_client().post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(),
            "selection": {"x": "NaN", "y": 0, "width": 20, "height": 20},
            "viewport": {"width": 20, "height": 20},
        },
    )
    assert invalid_value.status_code == 400
    assert "finite number" in invalid_value.get_json()["error"]


def test_cors_only_allows_explicit_origins():
    app = create_app(
        BridgeConfig(cors_allowed_origins=("chrome-extension://trusted",)),
        ocr_service=FakeOcrService(),
        translator=FakeTranslator(),
    )
    client = app.test_client()

    denied = client.get("/health", headers={"Origin": "https://example.test"})
    allowed = client.get(
        "/health", headers={"Origin": "chrome-extension://trusted"}
    )

    assert "Access-Control-Allow-Origin" not in denied.headers
    assert allowed.headers["Access-Control-Allow-Origin"] == "chrome-extension://trusted"


def test_request_debug_capture_is_disabled_by_default(tmp_path):
    app = create_app(
        BridgeConfig(debug_capture_dir=str(tmp_path)),
        ocr_service=FakeOcrService(),
        translator=FakeTranslator(),
    )

    response = app.test_client().post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(),
            "selection": {"x": 0, "y": 0, "width": 20, "height": 20},
            "viewport": {"width": 20, "height": 20},
            "debug": True,
        },
    )

    assert response.status_code == 200
    assert "debugCapture" not in response.get_json()
    assert list(tmp_path.iterdir()) == []


def test_debug_capture_writes_crop_and_metadata(tmp_path):
    app = create_app(
        BridgeConfig(
            debug_capture_dir=str(tmp_path),
            allow_request_debug_captures=True,
        ),
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
            "engines": ["paddleocr"],
            "debug": True,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload["debugCapture"]) == {"id"}
    debug_dir = tmp_path / payload["debugCapture"]["id"]
    assert (debug_dir / "crop.png").exists()
    assert (debug_dir / "ocr-region.png").exists()
    assert (debug_dir / "ocr-preprocessed.png").exists()
    assert (debug_dir / "ocr-preprocessed-standard.png").exists()
    assert (debug_dir / "ocr-preprocessed-binary.png").exists()
    assert not (debug_dir / "ocr-preprocessed-pixel.png").exists()
    assert (debug_dir / "request.json").exists()
    assert (debug_dir / "response.json").exists()
    request_metadata = json.loads(
        (debug_dir / "request.json").read_text(encoding="utf-8")
    )
    assert request_metadata["ocrRegion"] == {
        "width": 20,
        "height": 20,
        "cropped": False,
    }


def test_debug_capture_saves_the_isolated_text_region(tmp_path):
    app = create_app(
        BridgeConfig(
            debug_capture_dir=str(tmp_path),
            allow_request_debug_captures=True,
        ),
        ocr_service=FakeOcrService(),
        translator=FakeTranslator(),
    )
    image = Image.new("RGB", (600, 180), "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 15, 130, 165), outline="white", width=8)
    draw.ellipse((45, 45, 105, 105), outline="white", width=6)
    for line in range(3):
        y = 28 + line * 50
        for character in range(12):
            x = 220 + character * 25
            draw.rectangle((x, y, x + 12, y + 27), fill="white")

    response = app.test_client().post(
        "/v1/translate-selection",
        json={
            "imageDataUrl": _png_data_url(image),
            "selection": {"x": 0, "y": 0, "width": 600, "height": 180},
            "viewport": {"width": 600, "height": 180},
            "debug": True,
        },
    )

    assert response.status_code == 200
    debug_dir = tmp_path / response.get_json()["debugCapture"]["id"]
    with Image.open(debug_dir / "crop.png") as crop:
        assert crop.size == (600, 180)
    with Image.open(debug_dir / "ocr-region.png") as ocr_region:
        region_size = ocr_region.size

    request_metadata = json.loads(
        (debug_dir / "request.json").read_text(encoding="utf-8")
    )
    assert 340 <= region_size[0] <= 410
    assert region_size[1] == 180
    assert request_metadata["ocrRegion"] == {
        "width": region_size[0],
        "height": region_size[1],
        "cropped": True,
    }


def _png_data_url(image: Image.Image | None = None) -> str:
    image = image or Image.new("RGB", (20, 20), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{data}"

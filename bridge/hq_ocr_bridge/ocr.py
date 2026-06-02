from __future__ import annotations

from io import BytesIO
import importlib.util
import math
import os
from typing import Any

from PIL import Image

from .config import BridgeConfig
from .image_utils import preprocess_variants_for_ocr
from .models import EngineResult
from .ranking import normalize_ocr_text, rank_ocr_results, text_quality_score


DEFAULT_ENGINES = ["paddleocr", "easyocr"]


class OcrService:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self._easyocr_reader: Any | None = None
        self._paddleocr_reader: Any | None = None

    def health_checks(self) -> dict[str, Any]:
        return {
            "easyocr": self._easyocr_health(),
            "paddleocr": self._paddleocr_health(),
            "tesseract": self._tesseract_health(),
        }

    def detect_text(
        self, image: Image.Image, engines: list[str] | None = None
    ) -> tuple[EngineResult | None, list[EngineResult], list[str]]:
        requested = engines or DEFAULT_ENGINES
        variants = preprocess_variants_for_ocr(image)
        results: list[EngineResult] = []
        warnings: list[str] = []

        for engine in requested:
            normalized_engine = str(engine).strip().lower()
            if normalized_engine not in {"easyocr", "paddleocr", "tesseract"}:
                message = f"unknown OCR engine: {engine}"
                warnings.append(message)
                results.append(EngineResult(normalized_engine, "", 0.0, 0.0, message))
                continue

            engine_variants = (
                _paddleocr_variants(variants)
                if normalized_engine == "paddleocr"
                else variants
            )
            for variant_name, prepared in engine_variants:
                try:
                    if normalized_engine == "easyocr":
                        result = self._run_easyocr(prepared)
                    elif normalized_engine == "paddleocr":
                        result = self._run_paddleocr(prepared)
                    else:
                        result = self._run_tesseract(prepared)
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
                    if _is_engine_setup_failure(exc):
                        break
                    continue

                result.engine = f"{normalized_engine}:{variant_name}"
                result.raw_text = result.text
                result.text = normalize_ocr_text(result.text)
                result.score = text_quality_score(result.text, result.raw_confidence)
                results.append(result)

        best = rank_ocr_results(results)
        return best, results, warnings

    def _run_easyocr(self, image: Image.Image) -> EngineResult:
        if importlib.util.find_spec("easyocr") is None:
            raise RuntimeError("easyocr package is not installed")

        import easyocr

        if self._easyocr_reader is None:
            kwargs: dict[str, Any] = {
                "gpu": False,
                "download_enabled": self.config.allow_easyocr_download,
            }
            if self.config.easyocr_model_dir:
                kwargs["model_storage_directory"] = self.config.easyocr_model_dir
            self._easyocr_reader = easyocr.Reader([self.config.easyocr_lang], **kwargs)

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        detections = self._easyocr_reader.readtext(
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
            try:
                confidences.append(float(detection[2]))
            except (TypeError, ValueError):
                continue

        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return EngineResult("easyocr", " ".join(fragments), confidence, confidence)

    def _run_paddleocr(self, image: Image.Image) -> EngineResult:
        if importlib.util.find_spec("paddleocr") is None:
            raise RuntimeError("paddleocr package is not installed")

        import numpy as np

        image = _limit_image_pixels(image, self.config.paddleocr_max_pixels)
        self._configure_paddleocr_environment()

        from paddleocr import PaddleOCR

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
            if self.config.paddleocr_recognition_model:
                kwargs["text_recognition_model_name"] = (
                    self.config.paddleocr_recognition_model
                )
            if not (
                self.config.paddleocr_detection_model
                or self.config.paddleocr_recognition_model
            ):
                kwargs["lang"] = self.config.paddleocr_lang
                kwargs["ocr_version"] = self.config.paddleocr_ocr_version

            self._paddleocr_reader = PaddleOCR(**kwargs)

        detections = self._paddleocr_reader.predict(np.asarray(image.convert("RGB")))
        fragments: list[str] = []
        confidences: list[float] = []
        for detection in detections:
            payload = _paddleocr_payload(detection)
            recognized_texts = (
                str(item).strip() for item in payload.get("rec_texts", [])
            )
            fragments.extend(text for text in recognized_texts if text)
            for confidence in payload.get("rec_scores", []):
                try:
                    confidences.append(float(confidence))
                except (TypeError, ValueError):
                    continue

        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return EngineResult("paddleocr", " ".join(fragments), confidence, confidence)

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
        if importlib.util.find_spec("pytesseract") is None:
            raise RuntimeError("pytesseract package is not installed")

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
            try:
                conf_value = float(confidence)
            except (TypeError, ValueError):
                conf_value = -1.0
            if conf_value >= 0:
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

    def _easyocr_health(self) -> dict[str, Any]:
        installed = importlib.util.find_spec("easyocr") is not None
        model_dir = self.config.easyocr_model_dir
        return {
            "installed": installed,
            "language": self.config.easyocr_lang,
            "modelDirectory": model_dir,
            "modelDirectoryExists": bool(model_dir and os.path.isdir(model_dir)),
            "downloadEnabled": self.config.allow_easyocr_download,
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
            "cacheDirectory": cache_dir,
            "cacheDirectoryExists": os.path.isdir(cache_dir),
            "mkldnnEnabled": self.config.paddleocr_enable_mkldnn,
            "maxPixels": self.config.paddleocr_max_pixels,
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

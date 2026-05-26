from __future__ import annotations

from io import BytesIO
import importlib.util
import os
from typing import Any

from PIL import Image

from .config import BridgeConfig
from .image_utils import preprocess_for_ocr
from .models import EngineResult
from .ranking import normalize_ocr_text, rank_ocr_results, text_quality_score


DEFAULT_ENGINES = ["easyocr", "tesseract"]


class OcrService:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self._easyocr_reader: Any | None = None

    def health_checks(self) -> dict[str, Any]:
        return {
            "easyocr": self._easyocr_health(),
            "tesseract": self._tesseract_health(),
        }

    def detect_text(
        self, image: Image.Image, engines: list[str] | None = None
    ) -> tuple[EngineResult | None, list[EngineResult], list[str]]:
        requested = engines or DEFAULT_ENGINES
        prepared = preprocess_for_ocr(image)
        results: list[EngineResult] = []
        warnings: list[str] = []

        for engine in requested:
            normalized_engine = str(engine).strip().lower()
            try:
                if normalized_engine == "easyocr":
                    result = self._run_easyocr(prepared)
                elif normalized_engine == "tesseract":
                    result = self._run_tesseract(prepared)
                else:
                    raise ValueError(f"unknown OCR engine: {engine}")
            except Exception as exc:
                message = f"{normalized_engine} failed: {exc}"
                warnings.append(message)
                result = EngineResult(normalized_engine, "", 0.0, 0.0, message)

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

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image

from .config import BridgeConfig
from .image_utils import preprocess_for_ocr, preprocess_variants_for_ocr


class DebugCapture:
    def __init__(
        self,
        config: BridgeConfig,
        payload: dict[str, Any],
        crop: Image.Image,
        crop_meta: dict[str, float | int],
    ) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.id = f"{timestamp}_{uuid4().hex[:8]}"
        self.directory = Path(config.debug_capture_dir) / self.id
        self.directory.mkdir(parents=True, exist_ok=False)

        crop.save(self.directory / "crop.png")
        preprocess_for_ocr(crop).save(self.directory / "ocr-preprocessed.png")
        for variant_name, variant_image in preprocess_variants_for_ocr(crop):
            variant_image.save(self.directory / f"ocr-preprocessed-{variant_name}.png")
        self._write_json(
            "request.json",
            {
                "id": self.id,
                "selection": payload.get("selection"),
                "viewport": payload.get("viewport"),
                "source": payload.get("source"),
                "target": payload.get("target"),
                "engines": payload.get("engines"),
                "debug": payload.get("debug"),
                "imageDataUrlLength": len(str(payload.get("imageDataUrl") or "")),
                "crop": crop_meta,
            },
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "directory": str(self.directory),
        }

    def save_response(self, response: dict[str, Any], status_code: int = 200) -> None:
        self._write_json(
            "response.json",
            {
                "statusCode": status_code,
                "response": response,
            },
        )

    def _write_json(self, filename: str, payload: dict[str, Any]) -> None:
        path = self.directory / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def debug_capture_requested(config: BridgeConfig, payload: dict[str, Any]) -> bool:
    return config.save_debug_captures or _truthy(payload.get("debug"))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False

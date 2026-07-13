from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import threading
from typing import Any
from uuid import uuid4

from PIL import Image

from .config import BridgeConfig
from .image_utils import preprocess_variants_for_ocr
from .text_region import isolate_text_region


_CAPTURE_COUNT_LOCK = threading.Lock()
_CAPTURE_COUNTS: dict[str, int] = {}


class DebugCaptureLimitReached(RuntimeError):
    """Raised when diagnostics are enabled but their non-destructive quota is full."""


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
        root = Path(config.debug_capture_dir)
        self.directory = root / self.id
        _reserve_capture(root, config.debug_capture_max_count)
        created = False
        try:
            self.directory.mkdir(parents=True, exist_ok=False)
            created = True

            crop.save(self.directory / "crop.png")
            ocr_region = isolate_text_region(crop)
            ocr_region.save(self.directory / "ocr-region.png")
            preprocessing_profile = str(
                payload.get("ocrPreprocessing") or "standard"
            ).strip().lower()
            if preprocessing_profile == "auto":
                preprocessing_profile = "standard"
            variants = preprocess_variants_for_ocr(
                ocr_region,
                force_pixel_art=preprocessing_profile == "pixel-art",
            )
            variants[0][1].save(self.directory / "ocr-preprocessed.png")
            for variant_name, variant_image in variants:
                variant_image.save(
                    self.directory / f"ocr-preprocessed-{variant_name}.png"
                )
            self._write_json(
                "request.json",
                {
                    "id": self.id,
                    "selection": payload.get("selection"),
                    "viewport": payload.get("viewport"),
                    "source": payload.get("source"),
                    "target": payload.get("target"),
                    "engines": payload.get("engines"),
                    "ocrPreprocessing": preprocessing_profile,
                    "debug": payload.get("debug"),
                    "imageDataUrlLength": len(
                        str(payload.get("imageDataUrl") or "")
                    ),
                    "crop": crop_meta,
                    "ocrRegion": {
                        "width": ocr_region.width,
                        "height": ocr_region.height,
                        "cropped": ocr_region.size != crop.size,
                    },
                },
            )
        except Exception:
            if created:
                shutil.rmtree(self.directory, ignore_errors=True)
            _release_capture(root)
            raise

    def to_dict(self) -> dict[str, str]:
        # The capture directory is intentionally not exposed through the API.
        # It can reveal the local user name and filesystem layout to a caller.
        return {"id": self.id}

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
    return config.save_debug_captures or (
        config.allow_request_debug_captures and _truthy(payload.get("debug"))
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _reserve_capture(root: Path, max_count: int) -> None:
    key = str(root.resolve())
    with _CAPTURE_COUNT_LOCK:
        count = _CAPTURE_COUNTS.get(key)
        if count is None or count >= max_count:
            count = _capture_directory_count(root)
        if count >= max_count:
            _CAPTURE_COUNTS[key] = count
            raise DebugCaptureLimitReached(
                f"debug capture limit reached ({max_count})"
            )
        _CAPTURE_COUNTS[key] = count + 1


def _release_capture(root: Path) -> None:
    key = str(root.resolve())
    with _CAPTURE_COUNT_LOCK:
        count = _CAPTURE_COUNTS.get(key)
        if count is not None:
            _CAPTURE_COUNTS[key] = max(0, count - 1)


def _capture_directory_count(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for item in root.iterdir() if item.is_dir())

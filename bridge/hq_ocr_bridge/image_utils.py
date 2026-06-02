from __future__ import annotations

import base64
from io import BytesIO
import re
from typing import Any

from PIL import Image, ImageFilter, ImageOps


DATA_URL_RE = re.compile(
    r"^data:image/(?P<mime>png|jpe?g|webp);base64,(?P<data>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def image_from_data_url(data_url: str) -> Image.Image:
    if not isinstance(data_url, str):
        raise ValueError("imageDataUrl must be a data URL string")

    match = DATA_URL_RE.match(data_url.strip())
    if not match:
        raise ValueError("imageDataUrl must be a base64 image data URL")

    try:
        raw = base64.b64decode(match.group("data"), validate=True)
        image = Image.open(BytesIO(raw))
        image.load()
    except Exception as exc:
        raise ValueError("imageDataUrl contains an invalid image") from exc

    return image.convert("RGB")


def crop_visible_selection(
    image: Image.Image, selection: dict[str, Any], viewport: dict[str, Any]
) -> tuple[Image.Image, dict[str, float | int]]:
    viewport_width = _positive_float(viewport, "width")
    viewport_height = _positive_float(viewport, "height")
    x = _float_value(selection, "x")
    y = _float_value(selection, "y")
    width = _positive_float(selection, "width")
    height = _positive_float(selection, "height")

    scale_x = image.width / viewport_width
    scale_y = image.height / viewport_height

    left = _clamp(round(x * scale_x), 0, image.width)
    top = _clamp(round(y * scale_y), 0, image.height)
    right = _clamp(round((x + width) * scale_x), 0, image.width)
    bottom = _clamp(round((y + height) * scale_y), 0, image.height)

    if right <= left or bottom <= top:
        raise ValueError("selection does not contain visible pixels")

    crop = image.crop((left, top, right, bottom)).convert("RGB")
    meta = {
        "scaleX": scale_x,
        "scaleY": scale_y,
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": crop.width,
        "height": crop.height,
    }
    return crop, meta


def preprocess_for_ocr(image: Image.Image) -> Image.Image:
    return preprocess_variants_for_ocr(image)[0][1]


def preprocess_variants_for_ocr(image: Image.Image) -> list[tuple[str, Image.Image]]:
    gray = ImageOps.grayscale(image)
    normalized = ImageOps.autocontrast(gray)
    standard = _upscale_for_ocr(normalized.filter(ImageFilter.SHARPEN))
    soft = _upscale_for_ocr(normalized)
    binary = standard.point(lambda pixel: 255 if pixel > 170 else 0)

    return [
        ("standard", standard),
        ("soft", soft),
        ("binary", binary),
    ]


def _upscale_for_ocr(image: Image.Image) -> Image.Image:
    if image.width < 900:
        scale = min(3, max(2, round(900 / max(image.width, 1))))
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        image = image.resize(
            (image.width * scale, image.height * scale),
            resampling,
        )

    return image


def _float_value(data: dict[str, Any], key: str) -> float:
    try:
        return float(data[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc


def _positive_float(data: dict[str, Any], key: str) -> float:
    value = _float_value(data, key)
    if value <= 0:
        raise ValueError(f"{key} must be greater than zero")

    return value


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))

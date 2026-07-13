from __future__ import annotations

import base64
from io import BytesIO
import math
import re
from typing import Any

from PIL import Image, ImageFilter, ImageOps


DATA_URL_RE = re.compile(
    r"^data:image/(?P<mime>png|jpe?g|webp);base64,(?P<data>.+)$",
    re.IGNORECASE | re.DOTALL,
)
MAX_PREPROCESSED_PIXELS = 4_000_000


class ImagePayloadTooLarge(ValueError):
    """Raised when an image payload exceeds a configured safety limit."""


class ImageMediaTypeMismatch(ValueError):
    """Raised when the data URL media type disagrees with decoded content."""


def image_from_data_url(
    data_url: str,
    *,
    max_image_bytes: int | None = None,
    max_image_pixels: int | None = None,
) -> Image.Image:
    if not isinstance(data_url, str):
        raise ValueError("imageDataUrl must be a data URL string")

    match = DATA_URL_RE.match(data_url.strip())
    if not match:
        raise ValueError("imageDataUrl must be a base64 image data URL")

    encoded = match.group("data")
    declared_format = _normalized_image_format(match.group("mime"))
    if max_image_bytes and len(encoded) > _max_base64_length(max_image_bytes):
        raise ImagePayloadTooLarge("imageDataUrl exceeds the allowed image size")

    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("imageDataUrl contains an invalid image") from exc

    if max_image_bytes and len(raw) > max_image_bytes:
        raise ImagePayloadTooLarge("imageDataUrl exceeds the allowed image size")

    try:
        with Image.open(BytesIO(raw)) as image:
            actual_format = _normalized_image_format(image.format or "")
            if actual_format != declared_format:
                raise ImageMediaTypeMismatch(
                    "imageDataUrl media type does not match the image content"
                )
            if max_image_pixels and image.width * image.height > max_image_pixels:
                raise ImagePayloadTooLarge(
                    "imageDataUrl exceeds the allowed pixel count"
                )
            image.load()
            return image.convert("RGB")
    except (ImagePayloadTooLarge, ImageMediaTypeMismatch):
        raise
    except Exception as exc:
        raise ValueError("imageDataUrl contains an invalid image") from exc


def crop_visible_selection(
    image: Image.Image,
    selection: dict[str, Any],
    viewport: dict[str, Any],
    *,
    max_crop_pixels: int | None = None,
) -> tuple[Image.Image, dict[str, float | int]]:
    viewport_width = _positive_float(viewport, "width")
    viewport_height = _positive_float(viewport, "height")
    x = _float_value(selection, "x")
    y = _float_value(selection, "y")
    width = _positive_float(selection, "width")
    height = _positive_float(selection, "height")

    try:
        scale_x = image.width / viewport_width
        scale_y = image.height / viewport_height
        scaled_coordinates = (
            x * scale_x,
            y * scale_y,
            (x + width) * scale_x,
            (y + height) * scale_y,
        )
    except OverflowError as exc:
        raise ValueError("selection coordinates exceed the supported range") from exc
    if not all(
        math.isfinite(value)
        for value in (scale_x, scale_y, *scaled_coordinates)
    ):
        raise ValueError("selection coordinates exceed the supported range")

    left = _clamp(round(scaled_coordinates[0]), 0, image.width)
    top = _clamp(round(scaled_coordinates[1]), 0, image.height)
    right = _clamp(round(scaled_coordinates[2]), 0, image.width)
    bottom = _clamp(round(scaled_coordinates[3]), 0, image.height)

    if right <= left or bottom <= top:
        raise ValueError("selection does not contain visible pixels")

    crop_width = right - left
    crop_height = bottom - top
    if max_crop_pixels and crop_width * crop_height > max_crop_pixels:
        raise ImagePayloadTooLarge("selection exceeds the allowed pixel count")
    if left == 0 and top == 0 and right == image.width and bottom == image.height:
        crop = image if image.mode == "RGB" else image.convert("RGB")
    else:
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
    return preprocess_variants_for_ocr(image, max_variants=1)[0][1]


def preprocess_variants_for_ocr(
    image: Image.Image,
    *,
    max_variants: int = 0,
    engine: str = "tesseract",
    force_pixel_art: bool = False,
) -> list[tuple[str, Image.Image]]:
    normalized_engine = str(engine).strip().lower()
    if normalized_engine == "windowsocr":
        if force_pixel_art:
            return _limited_variants(_pixel_art_variants(image), max_variants)

        original = image if image.mode == "RGB" else image.convert("RGB")
        gray = ImageOps.grayscale(image)
        normalized = ImageOps.autocontrast(gray)
        variants = [("binary", _binary_for_ocr(normalized))]
        if max_variants == 1:
            return variants

        variants.append(("standard", original))
        return variants

    if normalized_engine in {"easyocr", "paddleocr"}:
        original = image if image.mode == "RGB" else image.convert("RGB")
        variants = [("standard", original)]
        if max_variants == 1:
            return variants

        if force_pixel_art:
            pixel_soft = dict(_pixel_art_variants(image))["pixel-soft"]
            variants.append(("pixel-soft", pixel_soft.convert("RGB")))
            return _limited_variants(variants, max_variants)

        gray = ImageOps.grayscale(image)
        normalized = ImageOps.autocontrast(gray, cutoff=1)
        contrast = _upscale_for_ocr(normalized.filter(ImageFilter.SHARPEN))
        variants.append(("contrast", contrast))
        if max_variants == 2:
            return variants

        variants.append(("binary", _binary_for_ocr(normalized)))
        return variants

    if force_pixel_art:
        return _limited_variants(_pixel_art_variants(image), max_variants)

    gray = ImageOps.grayscale(image)
    normalized = ImageOps.autocontrast(gray)
    standard = _upscale_for_ocr(normalized.filter(ImageFilter.SHARPEN))
    variants = [("standard", standard)]
    if max_variants == 1:
        return variants

    variants.append(("binary", _binary_for_ocr(normalized)))
    return variants


def _pixel_art_variants(image: Image.Image) -> list[tuple[str, Image.Image]]:
    gray = ImageOps.grayscale(image)
    normalized = ImageOps.autocontrast(gray)
    binary = _pad_for_ocr(_binary_for_ocr(normalized))

    soft = _normalize_text_polarity(normalized)
    soft = _upscale_pixel_text(soft)
    soft = soft.filter(ImageFilter.GaussianBlur(radius=0.45))
    soft = _pad_for_ocr(ImageOps.autocontrast(soft))
    return [("pixel", binary), ("pixel-soft", soft)]


def _normalize_text_polarity(image: Image.Image) -> Image.Image:
    histogram = image.histogram()[:256]
    dark_pixels = sum(histogram[:96])
    light_pixels = sum(histogram[160:])
    return ImageOps.invert(image) if dark_pixels > light_pixels else image


def _pad_for_ocr(image: Image.Image) -> Image.Image:
    border = max(8, min(32, round(image.height * 0.06)))
    return ImageOps.expand(image, border=border, fill=255)


def _limited_variants(
    variants: list[tuple[str, Image.Image]], max_variants: int
) -> list[tuple[str, Image.Image]]:
    if max_variants > 0:
        return variants[:max_variants]
    return variants


def _upscale_for_ocr(image: Image.Image) -> Image.Image:
    if image.width < 900:
        scale = min(3, max(2, round(900 / max(image.width, 1))))
        pixel_budget = max(
            MAX_PREPROCESSED_PIXELS,
            image.width * image.height,
        )
        while (
            scale > 1
            and image.width * image.height * scale * scale > pixel_budget
        ):
            scale -= 1
        if scale <= 1:
            return image
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        image = image.resize(
            (image.width * scale, image.height * scale),
            resampling,
        )

    return image


def _upscale_pixel_text(image: Image.Image) -> Image.Image:
    if image.width < 550:
        scale = 3
    elif image.width < 1600:
        scale = 2
    else:
        scale = 1

    while (
        scale > 1
        and image.width * image.height * scale * scale > MAX_PREPROCESSED_PIXELS
    ):
        scale -= 1
    if scale <= 1:
        return image

    resampling = getattr(Image, "Resampling", Image).NEAREST
    return image.resize((image.width * scale, image.height * scale), resampling)


def _binary_for_ocr(image: Image.Image) -> Image.Image:
    threshold = _otsu_threshold(image)
    binary = image.point(lambda pixel: 255 if pixel > threshold else 0)
    histogram = binary.histogram()
    white_pixels = histogram[255]
    black_pixels = histogram[0]
    if black_pixels > white_pixels:
        binary = ImageOps.invert(binary)
    return _upscale_pixel_text(binary)


def _otsu_threshold(image: Image.Image) -> int:
    histogram = image.histogram()[:256]
    total = sum(histogram)
    weighted_total = sum(value * count for value, count in enumerate(histogram))
    background_weight = 0
    background_sum = 0
    best_variance = -1.0
    best_threshold = 127

    for value, count in enumerate(histogram):
        background_weight += count
        if background_weight == 0:
            continue
        foreground_weight = total - background_weight
        if foreground_weight == 0:
            break
        background_sum += value * count
        background_mean = background_sum / background_weight
        foreground_mean = (weighted_total - background_sum) / foreground_weight
        variance = (
            background_weight
            * foreground_weight
            * (background_mean - foreground_mean) ** 2
        )
        if variance > best_variance:
            best_variance = variance
            best_threshold = value

    return best_threshold


def _float_value(data: dict[str, Any], key: str) -> float:
    try:
        raw_value = data[key]
        if isinstance(raw_value, bool):
            raise TypeError
        value = float(raw_value)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc

    if not math.isfinite(value):
        raise ValueError(f"{key} must be a finite number")
    return value


def _positive_float(data: dict[str, Any], key: str) -> float:
    value = _float_value(data, key)
    if value <= 0:
        raise ValueError(f"{key} must be greater than zero")

    return value


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def _max_base64_length(max_bytes: int) -> int:
    return ((max_bytes + 2) // 3) * 4


def _normalized_image_format(value: str) -> str:
    normalized = value.strip().lower()
    return "jpeg" if normalized in {"jpg", "jpeg"} else normalized

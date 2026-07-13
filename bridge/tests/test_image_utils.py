from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image
import pytest

from hq_ocr_bridge.image_utils import (
    ImagePayloadTooLarge,
    crop_visible_selection,
    image_from_data_url,
    is_pixel_art_text,
    preprocess_variants_for_ocr,
)


def test_crop_scales_selection_from_viewport_to_screenshot_pixels():
    image = Image.new("RGB", (200, 100), "white")

    crop, meta = crop_visible_selection(
        image,
        {"x": 25, "y": 10, "width": 50, "height": 20},
        {"width": 100, "height": 50},
    )

    assert crop.size == (100, 40)
    assert meta["left"] == 50
    assert meta["top"] == 20
    assert meta["right"] == 150
    assert meta["bottom"] == 60


def test_full_image_selection_reuses_the_already_decoded_rgb_image():
    image = Image.new("RGB", (200, 100), "white")

    crop, _meta = crop_visible_selection(
        image,
        {"x": 0, "y": 0, "width": 200, "height": 100},
        {"width": 200, "height": 100},
    )

    assert crop is image


def test_data_url_loader_rejects_non_image_data():
    with pytest.raises(ValueError):
        image_from_data_url("not-a-data-url")


def test_data_url_loader_accepts_png_data_url():
    image = Image.new("RGB", (4, 3), "black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    data = base64.b64encode(buffer.getvalue()).decode("ascii")

    decoded = image_from_data_url(f"data:image/png;base64,{data}")

    assert decoded.size == (4, 3)


def test_data_url_loader_enforces_encoded_bytes_and_pixel_limits():
    image = Image.new("RGB", (4, 3), "black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    data_url = f"data:image/png;base64,{data}"

    with pytest.raises(ImagePayloadTooLarge):
        image_from_data_url(data_url, max_image_bytes=1)
    with pytest.raises(ImagePayloadTooLarge):
        image_from_data_url(data_url, max_image_pixels=10)


def test_crop_rejects_non_finite_and_oversized_selections():
    image = Image.new("RGB", (200, 100), "white")

    with pytest.raises(ValueError, match="finite number"):
        crop_visible_selection(
            image,
            {"x": "NaN", "y": 0, "width": 50, "height": 20},
            {"width": 100, "height": 50},
        )
    with pytest.raises(ImagePayloadTooLarge):
        crop_visible_selection(
            image,
            {"x": 0, "y": 0, "width": 100, "height": 50},
            {"width": 100, "height": 50},
            max_crop_pixels=100,
        )


def test_tesseract_preprocess_includes_pixel_and_adaptive_binary_variants():
    image = Image.new("RGB", (120, 40), "white")

    variants = preprocess_variants_for_ocr(image)
    names = [name for name, _ in variants]

    assert names == ["standard", "pixel", "binary"]
    assert all(variant.width >= image.width for _, variant in variants)


def test_neural_ocr_receives_original_rgb_before_contrast_variants():
    image = Image.new("RGB", (120, 40), (20, 80, 160))

    variants = preprocess_variants_for_ocr(
        image,
        max_variants=2,
        engine="paddleocr",
    )

    assert [name for name, _variant in variants] == ["standard", "contrast"]
    assert variants[0][1] is image
    assert variants[0][1].mode == "RGB"


def test_windows_ocr_receives_binary_then_original_variant():
    image = Image.new("RGB", (120, 40), "white")

    variants = preprocess_variants_for_ocr(
        image,
        max_variants=2,
        engine="windowsocr",
    )

    assert [name for name, _variant in variants] == ["binary", "standard"]
    assert variants[0][1].mode == "L"
    assert variants[1][1] is image


def test_pixel_variant_normalizes_dark_background_to_black_text_on_white():
    image = Image.new("L", (100, 40), 0)
    for x in range(30, 70):
        for y in range(12, 28):
            image.putpixel((x, y), 255)

    binary = dict(preprocess_variants_for_ocr(image))["pixel"]

    assert binary.getpixel((0, 0)) == 255


def test_pixel_art_uses_nearest_neighbor_binary_and_soft_variants_first():
    image = Image.new("RGB", (96, 32), "black")
    for x in range(12, 84, 12):
        for y in range(8, 24):
            if x <= 80:
                image.putpixel((x, y), (255, 255, 255))
                image.putpixel((x + 1, y), (255, 255, 255))

    assert is_pixel_art_text(image) is True

    variants = preprocess_variants_for_ocr(
        image,
        max_variants=2,
        engine="tesseract",
    )

    assert [name for name, _variant in variants] == ["pixel", "pixel-soft"]
    assert all(variant.mode == "L" for _name, variant in variants)
    assert all(variant.width > image.width for _name, variant in variants)
    assert variants[0][1].getpixel((0, 0)) == 255


def test_neural_ocr_keeps_original_then_adds_pixel_soft_variant_for_pixel_art():
    image = Image.new("RGB", (96, 32), "black")
    for x in range(16, 80):
        for y in range(10, 22):
            if x % 8 in {0, 1} or y in {10, 21}:
                image.putpixel((x, y), (255, 255, 255))

    variants = preprocess_variants_for_ocr(
        image,
        max_variants=2,
        engine="paddleocr",
    )

    assert [name for name, _variant in variants] == ["standard", "pixel-soft"]
    assert variants[0][1] is image
    assert variants[1][1].mode == "RGB"


def test_antialiased_gradient_is_not_classified_as_pixel_art():
    image = Image.new("RGB", (96, 32))
    for x in range(image.width):
        shade = round(255 * x / (image.width - 1))
        for y in range(image.height):
            image.putpixel((x, y), (shade, shade, shade))

    assert is_pixel_art_text(image) is False
    variants = preprocess_variants_for_ocr(
        image,
        max_variants=2,
        engine="tesseract",
    )
    assert [name for name, _variant in variants] == ["standard", "pixel"]


def test_pixel_art_profile_forces_8_bit_variants_when_detection_is_uncertain():
    image = Image.new("RGB", (96, 32))
    for x in range(image.width):
        shade = round(255 * x / (image.width - 1))
        for y in range(image.height):
            image.putpixel((x, y), (shade, shade, shade))

    assert is_pixel_art_text(image) is False

    tesseract_variants = preprocess_variants_for_ocr(
        image,
        max_variants=2,
        engine="tesseract",
        force_pixel_art=True,
    )
    paddle_variants = preprocess_variants_for_ocr(
        image,
        max_variants=2,
        engine="paddleocr",
        force_pixel_art=True,
    )

    assert [name for name, _variant in tesseract_variants] == [
        "pixel",
        "pixel-soft",
    ]
    assert [name for name, _variant in paddle_variants] == [
        "standard",
        "pixel-soft",
    ]

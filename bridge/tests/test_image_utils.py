from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image
import pytest

from hq_ocr_bridge.image_utils import (
    crop_visible_selection,
    image_from_data_url,
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


def test_preprocess_variants_include_standard_soft_and_binary():
    image = Image.new("RGB", (120, 40), "white")

    variants = preprocess_variants_for_ocr(image)
    names = [name for name, _ in variants]

    assert names == ["standard", "soft", "binary"]
    assert all(variant.width >= image.width for _, variant in variants)

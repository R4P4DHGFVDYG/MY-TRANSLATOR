from __future__ import annotations

from PIL import Image, ImageDraw

from hq_ocr_bridge import text_region
from hq_ocr_bridge.text_region import isolate_text_region


def test_isolates_text_to_the_right_of_a_large_dialogue_portrait():
    image = _dialogue_box("left")

    isolated = isolate_text_region(image)

    assert isolated is not image
    assert isolated.height == image.height
    assert 340 <= isolated.width <= 410
    assert isolated.getpixel((0, 35)) == (255, 255, 255)


def test_isolates_text_to_the_left_of_a_large_dialogue_portrait():
    image = _dialogue_box("right")

    isolated = isolate_text_region(image)

    assert isolated is not image
    assert isolated.height == image.height
    assert 340 <= isolated.width <= 430
    assert isolated.getpixel((60, 35)) == (255, 255, 255)


def test_keeps_dark_text_image_without_a_large_edge_graphic_unchanged():
    image = Image.new("RGB", (600, 180), "black")
    _draw_text_components(ImageDraw.Draw(image), 70, 28)

    isolated = isolate_text_region(image)

    assert isolated is image


def test_keeps_light_background_unchanged():
    image = Image.new("RGB", (600, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 15, 130, 165), outline="black", width=8)
    _draw_text_components(draw, 220, 28, color="black")

    isolated = isolate_text_region(image)

    assert isolated is image


def test_keeps_dark_panel_with_graphic_but_no_text_pattern_unchanged():
    image = Image.new("RGB", (600, 180), "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 15, 130, 165), outline="white", width=8)
    draw.rectangle((220, 70, 550, 85), fill="white")

    isolated = isolate_text_region(image)

    assert isolated is image


def test_keeps_large_inset_logo_and_following_text_unchanged():
    image = Image.new("RGB", (600, 180), "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 15, 170, 165), outline="white", width=8)
    draw.ellipse((85, 45, 145, 105), outline="white", width=6)
    _draw_text_components(draw, 240, 28)

    isolated = isolate_text_region(image)

    assert isolated is image


def test_keeps_wide_scene_when_an_edge_element_would_remove_almost_half():
    image = Image.new("RGB", (1000, 220), "black")
    draw = ImageDraw.Draw(image)
    for line in range(3):
        y = 30 + line * 55
        for character in range(15):
            x = 60 + character * 32
            draw.rectangle((x, y, x + 16, y + 32), fill="white")
    draw.rectangle((650, 10, 990, 210), outline="white", width=12)
    draw.ellipse((720, 35, 920, 195), outline="white", width=10)

    isolated = isolate_text_region(image)

    assert isolated is image


def test_keeps_colorful_scene_with_a_character_at_the_edge_unchanged():
    image = Image.new("RGB", (600, 180), (30, 15, 100))
    draw = ImageDraw.Draw(image)
    _draw_text_components(draw, 60, 28)
    draw.rectangle((470, 15, 580, 165), outline="white", width=8)
    draw.ellipse((495, 45, 555, 105), outline="white", width=6)

    isolated = isolate_text_region(image)

    assert isolated is image


def test_keeps_original_when_opencv_is_unavailable(monkeypatch):
    image = _dialogue_box("left")
    monkeypatch.setattr(text_region, "_load_opencv", lambda: None)

    isolated = isolate_text_region(image)

    assert isolated is image


def _dialogue_box(portrait_side: str) -> Image.Image:
    image = Image.new("RGB", (600, 180), "black")
    draw = ImageDraw.Draw(image)
    if portrait_side == "left":
        draw.rectangle((20, 15, 130, 165), outline="white", width=8)
        draw.ellipse((45, 45, 105, 105), outline="white", width=6)
        _draw_text_components(draw, 220, 28)
    else:
        _draw_text_components(draw, 60, 28)
        draw.rectangle((470, 15, 580, 165), outline="white", width=8)
        draw.ellipse((495, 45, 555, 105), outline="white", width=6)
    return image


def _draw_text_components(
    draw: ImageDraw.ImageDraw,
    start_x: int,
    start_y: int,
    *,
    color: str = "white",
) -> None:
    for line in range(3):
        y = start_y + line * 50
        for character in range(12):
            x = start_x + character * 25
            draw.rectangle((x, y, x + 12, y + 27), fill=color)

from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from io import BytesIO
import math
import multiprocessing
import threading
from typing import Any

from PIL import Image


MAX_IMAGE_DIMENSION = 2600
_WORKER_ENGINES: dict[str, tuple[Any, str]] = {}


class WindowsOcrAdapter:
    def __init__(self, language_tag: str) -> None:
        self.language_tag = language_tag
        self._lock = threading.Lock()
        self._executor: ProcessPoolExecutor | None = None

    def recognize(self, image: Image.Image, language_tag: str | None = None) -> str:
        requested = str(language_tag or self.language_tag).strip() or self.language_tag
        encoded = _encode_image(_limit_image_size(image))
        with self._lock:
            executor = self._get_executor()
            try:
                return executor.submit(
                    _recognize_in_worker,
                    encoded,
                    requested,
                ).result()
            except BrokenProcessPool as exc:
                self._reset_executor()
                raise RuntimeError(
                    "Windows OCR worker crashed; the Bridge stayed online"
                ) from exc

    def selected_language(self, language_tag: str | None = None) -> str:
        requested = str(language_tag or self.language_tag).strip() or self.language_tag
        return _resolve_language_tag(requested)

    def close(self) -> None:
        with self._lock:
            self._reset_executor()

    def _get_executor(self) -> ProcessPoolExecutor:
        if self._executor is None:
            self._executor = ProcessPoolExecutor(
                max_workers=1,
                mp_context=multiprocessing.get_context("spawn"),
            )
        return self._executor

    def _reset_executor(self) -> None:
        executor = self._executor
        self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


def _encode_image(image: Image.Image) -> bytes:
    encoded = BytesIO()
    image.convert("RGB").save(encoded, format="BMP")
    return encoded.getvalue()


def _recognize_in_worker(encoded: bytes, language_tag: str) -> str:
    engine, _selected = _worker_engine_for(language_tag)
    return asyncio.run(_recognize_with_engine(engine, encoded))


def _worker_engine_for(language_tag: str) -> tuple[Any, str]:
    key = language_tag.lower()
    cached = _WORKER_ENGINES.get(key)
    if cached is not None:
        return cached

    engine, selected = _create_engine(language_tag)
    cached = (engine, selected)
    _WORKER_ENGINES[key] = cached
    _WORKER_ENGINES.setdefault(selected.lower(), cached)
    _WORKER_ENGINES.setdefault(selected.split("-", 1)[0].lower(), cached)
    return cached


async def _recognize_with_engine(engine: Any, encoded: bytes) -> str:
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    try:
        writer.write_bytes(encoded)
        await writer.store_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        try:
            result = await engine.recognize_async(bitmap)
            return _ordered_result_text(result)
        finally:
            bitmap.close()
    finally:
        writer.close()
        stream.close()


def _ordered_result_text(result: Any) -> str:
    entries: list[dict[str, Any]] = []
    fallback_lines: list[str] = []
    for line_index, line in enumerate(getattr(result, "lines", ())):
        line_text = str(getattr(line, "text", "")).strip()
        if line_text:
            fallback_lines.append(line_text)
        for word_index, word in enumerate(getattr(line, "words", ())):
            text = str(getattr(word, "text", "")).strip()
            bounds = _word_bounds(getattr(word, "bounding_rect", None))
            if text and bounds is not None:
                entries.append(
                    {
                        "text": text,
                        "bounds": bounds,
                        "index": (line_index, word_index),
                    }
                )

    if not entries:
        return "\n".join(fallback_lines)

    lines = _group_words_into_lines(entries)
    return "\n".join(_join_words(line) for line in lines)


def _word_bounds(value: Any) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    try:
        left = float(value.x)
        top = float(value.y)
        width = float(value.width)
        height = float(value.height)
    except (AttributeError, TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (left, top, width, height)):
        return None
    if width <= 0 or height <= 0:
        return None
    return left, top, left + width, top + height


def _group_words_into_lines(
    entries: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    lines: list[list[dict[str, Any]]] = []
    ordered = sorted(
        entries,
        key=lambda entry: (
            (entry["bounds"][1] + entry["bounds"][3]) / 2,
            entry["bounds"][0],
        ),
    )
    for entry in ordered:
        top, bottom = entry["bounds"][1], entry["bounds"][3]
        center = (top + bottom) / 2
        height = bottom - top
        matching_line = None
        matching_distance = math.inf
        for line in lines:
            centers = [
                (item["bounds"][1] + item["bounds"][3]) / 2 for item in line
            ]
            line_center = sum(centers) / len(centers)
            line_height = max(
                item["bounds"][3] - item["bounds"][1] for item in line
            )
            distance = abs(center - line_center)
            if (
                distance <= max(height, line_height) * 0.6
                and distance < matching_distance
            ):
                matching_line = line
                matching_distance = distance
        if matching_line is None:
            lines.append([entry])
        else:
            matching_line.append(entry)

    lines.sort(
        key=lambda line: sum(
            (item["bounds"][1] + item["bounds"][3]) / 2 for item in line
        )
        / len(line)
    )
    for line in lines:
        line.sort(key=lambda entry: (entry["bounds"][0], entry["index"]))
    return lines


def _join_words(entries: list[dict[str, Any]]) -> str:
    text = ""
    for entry in entries:
        word = entry["text"]
        if not text:
            text = word
        elif word[:1] in ".,!?;:%)]}'\"" or text[-1:] in "([{'\"-":
            text += word
        else:
            text += " " + word
    return text


def _limit_image_size(image: Image.Image) -> Image.Image:
    largest_dimension = max(image.size)
    if largest_dimension <= MAX_IMAGE_DIMENSION:
        return image

    scale = MAX_IMAGE_DIMENSION / largest_dimension
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    return image.resize((width, height), resampling)


def windows_ocr_health(language_tag: str) -> dict[str, Any]:
    try:
        _engine, selected = _create_engine(language_tag)
        from winrt.windows.media.ocr import OcrEngine

        return {
            "installed": True,
            "language": selected,
            "availableLanguages": [
                language.language_tag
                for language in OcrEngine.available_recognizer_languages
            ],
        }
    except Exception as exc:
        return {"installed": False, "language": language_tag, "error": str(exc)}


def _resolve_language_tag(language_tag: str) -> str:
    try:
        from winrt.windows.media.ocr import OcrEngine
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "Windows OCR support is not installed; install "
            "requirements-windowsocr.txt"
        ) from exc

    requested = language_tag.strip()
    requested_short = requested.split("-", 1)[0].lower()
    available = list(OcrEngine.available_recognizer_languages)
    selected = next(
        (item for item in available if item.language_tag.lower() == requested.lower()),
        None,
    )
    if selected is None:
        selected = next(
            (
                item
                for item in available
                if item.language_tag.split("-", 1)[0].lower() == requested_short
            ),
            None,
        )
    if selected is None:
        installed = ", ".join(item.language_tag for item in available) or "none"
        raise RuntimeError(
            f"Windows OCR language '{requested}' is not installed "
            f"(available: {installed})"
        )
    return selected.language_tag


def _create_engine(language_tag: str) -> tuple[Any, str]:
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "Windows OCR support is not installed; install "
            "requirements-windowsocr.txt"
        ) from exc

    selected = _resolve_language_tag(language_tag)
    engine = OcrEngine.try_create_from_language(Language(selected))
    if engine is None:
        raise RuntimeError(
            f"Windows OCR could not initialize language '{selected}'"
        )
    return engine, selected

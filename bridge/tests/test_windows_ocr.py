from __future__ import annotations

from concurrent.futures.process import BrokenProcessPool
from types import SimpleNamespace

from PIL import Image

from hq_ocr_bridge import windows_ocr
from hq_ocr_bridge.windows_ocr import (
    MAX_IMAGE_DIMENSION,
    WindowsOcrAdapter,
    _limit_image_size,
    _ordered_result_text,
    _worker_engine_for,
)


def _word(text: str, x: float, y: float, width: float = 40, height: float = 20):
    return SimpleNamespace(
        text=text,
        bounding_rect=SimpleNamespace(x=x, y=y, width=width, height=height),
    )


def test_windows_ocr_orders_words_and_joins_apostrophes():
    result = SimpleNamespace(
        lines=[
            SimpleNamespace(text="that?", words=[_word("that?", 180, 50)]),
            SimpleNamespace(
                text="Who is",
                words=[_word("Who", 10, 50), _word("is", 90, 50)],
            ),
            SimpleNamespace(
                text="It's fine.",
                words=[
                    _word("It'", 10, 90),
                    _word("s", 55, 90, 10),
                    _word("fine.", 80, 90, 50),
                ],
            ),
        ]
    )

    assert _ordered_result_text(result) == "Who is that?\nIt's fine."


def test_windows_ocr_worker_reuses_equivalent_language_engine(monkeypatch):
    calls: list[str] = []
    engine = object()

    def fake_create_engine(language_tag):
        calls.append(language_tag)
        return engine, "en-US"

    monkeypatch.setattr(windows_ocr, "_create_engine", fake_create_engine)
    windows_ocr._WORKER_ENGINES.clear()

    assert _worker_engine_for("en") == (engine, "en-US")
    assert _worker_engine_for("en-US") == (engine, "en-US")
    assert calls == ["en"]
    windows_ocr._WORKER_ENGINES.clear()


def test_windows_ocr_native_crash_resets_worker_without_killing_bridge():
    shutdown_calls: list[tuple[bool, bool]] = []

    class CrashedFuture:
        @staticmethod
        def result():
            raise BrokenProcessPool("native crash")

    class CrashedExecutor:
        @staticmethod
        def submit(*_args, **_kwargs):
            return CrashedFuture()

        @staticmethod
        def shutdown(*, wait, cancel_futures):
            shutdown_calls.append((wait, cancel_futures))

    adapter = WindowsOcrAdapter("en-US")
    adapter._executor = CrashedExecutor()

    try:
        adapter.recognize(Image.new("RGB", (120, 40), "white"))
    except RuntimeError as exc:
        assert "Bridge stayed online" in str(exc)
    else:
        raise AssertionError("native worker crash should be reported")

    assert adapter._executor is None
    assert shutdown_calls == [(False, True)]


def test_windows_ocr_limits_images_to_native_maximum_dimension():
    image = Image.new("RGB", (MAX_IMAGE_DIMENSION * 2, 100), "white")

    limited = _limit_image_size(image)

    assert limited.size == (MAX_IMAGE_DIMENSION, 50)
    assert _limit_image_size(Image.new("RGB", (120, 40), "white")).size == (
        120,
        40,
    )

import json
from pathlib import Path

from PIL import Image
import pytest

from tools import compare_ocr_engines
from tools.compare_ocr_engines import (
    calculate_error_metrics,
    compare_images,
    load_ground_truth,
    lookup_ground_truth,
    parse_variants,
    summarize,
)


def test_load_ground_truth_accepts_wrapped_transcriptions(tmp_path):
    ground_truth_path = tmp_path / "ground-truth.json"
    ground_truth_path.write_text(
        json.dumps(
            {
                "transcriptions": {
                    "first.png": "  CLRE\nCafe\u0301  ",
                    "second": "GOODBYE",
                }
            }
        ),
        encoding="utf-8",
    )

    transcriptions = load_ground_truth(ground_truth_path)

    assert transcriptions == {
        "first.png": "CLRE Café",
        "second": "GOODBYE",
    }
    assert lookup_ground_truth(Path("captures/first.png"), transcriptions) == (
        "CLRE Café"
    )
    assert lookup_ground_truth(Path("captures/second.png"), transcriptions) == (
        "GOODBYE"
    )
    assert lookup_ground_truth(Path("captures/missing.png"), transcriptions) is None


def test_calculate_error_metrics_reports_cer_wer_and_exact_match():
    metrics = calculate_error_metrics("HELLO WORLD", "HELLO WORD")

    assert metrics == {
        "exactMatch": False,
        "characterEdits": 1,
        "referenceCharacters": 11,
        "cer": 0.0909,
        "wordEdits": 1,
        "referenceWords": 2,
        "wer": 0.5,
    }
    assert calculate_error_metrics("SAME", "SAME")["exactMatch"] is True


def test_parse_variants_accepts_production_names_and_rejects_soft():
    assert parse_variants("standard,pixel,pixel-soft,contrast,binary") == [
        "standard",
        "pixel",
        "pixel-soft",
        "contrast",
        "binary",
    ]
    with pytest.raises(ValueError, match="soft"):
        parse_variants("soft")


def test_compare_images_isolates_region_and_uses_engine_specific_variants(
    tmp_path,
    monkeypatch,
):
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (120, 40), (20, 80, 160)).save(image_path)
    isolated_sizes: list[tuple[int, int]] = []

    def fake_isolate(image):
        isolated = image.crop((10, 5, 70, 25))
        isolated_sizes.append(isolated.size)
        return isolated

    monkeypatch.setattr(compare_ocr_engines, "isolate_text_region", fake_isolate)
    tesseract = _FakeRunner("tesseract")
    paddleocr = _FakeRunner("paddleocr")

    records = compare_images(
        [image_path],
        [tesseract, paddleocr],
        ["pixel", "contrast"],
    )

    assert isolated_sizes == [(60, 20)]
    assert [
        variant["variant"]
        for variant in records[0]["engines"][0]["variants"]
    ] == ["pixel"]
    assert [
        variant["variant"]
        for variant in records[0]["engines"][1]["variants"]
    ] == ["contrast"]


def test_compare_images_rejects_variant_unavailable_for_engine(tmp_path):
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (120, 40), "black").save(image_path)

    with pytest.raises(
        ValueError,
        match=r"requested preprocess variants \(pixel\).*easyocr",
    ):
        compare_images(
            [image_path],
            [_FakeRunner("easyocr")],
            ["pixel"],
        )


def test_summarize_aggregates_ground_truth_metrics_for_best_results():
    records = [
        _record("first.png", "HELLO WORLD", "HELLO WORLD", score=0.8),
        _record("second.png", "GOOD NIGHT", "GOOD KNIGHT", score=0.9),
    ]

    summary = summarize(records)["fakeocr"]

    assert summary["groundTruthImages"] == 2
    assert summary["exactMatches"] == 1
    assert summary["exactMatchRate"] == 0.5
    assert summary["totalCharacterEdits"] == 1
    assert summary["totalReferenceCharacters"] == 21
    assert summary["cer"] == 0.0476
    assert summary["totalWordEdits"] == 1
    assert summary["totalReferenceWords"] == 4
    assert summary["wer"] == 0.25


def test_summarize_keeps_legacy_shape_without_ground_truth():
    record = _record("first.png", None, "HELLO WORLD", score=0.8)

    summary = summarize([record])["fakeocr"]

    assert summary == {
        "images": 1,
        "empty": 0,
        "winsByProxyScore": 1,
        "meanScore": 0.8,
        "meanConfidence": 0.9,
        "meanDurationMs": 12.0,
    }


def _record(
    image: str,
    ground_truth: str | None,
    hypothesis: str,
    *,
    score: float,
):
    best = {
        "variant": "standard",
        "text": hypothesis,
        "rawText": hypothesis,
        "rawConfidence": 0.9,
        "score": score,
        "durationMs": 12.0,
        "warning": None,
    }
    if ground_truth is not None:
        best["groundTruthMetrics"] = calculate_error_metrics(
            ground_truth,
            hypothesis,
        )
    record = {
        "image": image,
        "width": 100,
        "height": 50,
        "engines": [
            {
                "engine": "fakeocr",
                "best": best,
                "variants": [best],
            }
        ],
    }
    if ground_truth is not None:
        record["groundTruth"] = ground_truth
    return record


class _FakeRunner:
    def __init__(self, name: str) -> None:
        self.name = name

    def recognize(self, image: Image.Image) -> tuple[str, float]:
        return f"{image.mode} {image.width}x{image.height}", 0.9

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from hq_ocr_bridge.models import EngineResult
from tools.benchmark_ocr import (
    _shutdown_ocr_service,
    AUTOMATIC_PROFILE_ENGINES,
    BenchmarkEntry,
    calculate_metrics,
    load_manifest,
    prepare_manifest,
    render_markdown,
    run_attempts,
    summarize_records,
    write_report,
)


def _save_image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 24), color).save(path)


def _entry(image_path: Path, *, reference: str = "Hello world") -> BenchmarkEntry:
    return BenchmarkEntry(
        entry_id="sample-1",
        image_path=image_path,
        image_value="sample.png",
        reference=reference,
        language="en",
        category="motion",
        split="test",
    )


class FakeOcrService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def detect_text_with_metadata(
        self,
        image: Image.Image,
        engines: list[str],
        *,
        language_tag: str,
        preprocessing_profile: str,
        bypass_cache: bool,
    ):
        self.calls.append(
            {
                "size": image.size,
                "engines": tuple(engines),
                "language": language_tag,
                "preprocessing": preprocessing_profile,
                "bypassCache": bypass_cache,
            }
        )
        if tuple(engines) == AUTOMATIC_PROFILE_ENGINES:
            results = [
                EngineResult("tesseract:standard", "Hello wor1d", 0.6),
                EngineResult("paddleocr:standard", "Hello world", 0.9),
            ]
            return results[-1], results, ["fast engines disagreed"], {"cacheHit": False}
        result = EngineResult(f"{engines[0]}:standard", "Hello world", 0.8)
        return result, [result], [], {"cacheHit": False}


def test_shutdown_closes_benchmark_workers() -> None:
    class FakeExecutor:
        def __init__(self) -> None:
            self.calls: list[tuple[bool, bool]] = []

        def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
            self.calls.append((wait, cancel_futures))

    class FakeAdapter:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    service = type("Service", (), {})()
    service._engine_executor = FakeExecutor()
    service._parallel_executor = FakeExecutor()
    service._windowsocr_adapter = FakeAdapter()

    _shutdown_ocr_service(service)

    assert service._engine_executor.calls == [(True, True)]
    assert service._parallel_executor.calls == [(True, True)]
    assert service._windowsocr_adapter.closed is True


def test_prepare_manifest_uses_only_debug_crops_and_deduplicates(tmp_path: Path) -> None:
    captures = tmp_path / "debug-captures"
    first_crop = captures / "capture-a" / "crop.png"
    duplicate_crop = captures / "capture-b" / "crop.png"
    third_crop = captures / "capture-c" / "crop.png"
    _save_image(first_crop, (0, 0, 0))
    _save_image(duplicate_crop, (0, 0, 0))
    _save_image(third_crop, (255, 255, 255))
    _save_image(captures / "capture-a" / "ocr-preprocessed.png", (10, 10, 10))
    for directory in (first_crop.parent, duplicate_crop.parent, third_crop.parent):
        (directory / "request.json").write_text("{}", encoding="utf-8")

    manifest = tmp_path / "benchmark" / "ground-truth.jsonl"
    result = prepare_manifest(captures, manifest, limit=0, copy_images=True)

    assert result["discovered"] == 3
    assert result["duplicatesRemoved"] == 1
    assert result["selected"] == 2
    entries = load_manifest(manifest)
    assert len(entries) == 2
    assert all(entry.image_path.parent.name == "ground-truth-images" for entry in entries)
    assert all(entry.reference == "" for entry in entries)


def test_prepare_manifest_refuses_to_replace_annotations_without_force(tmp_path: Path) -> None:
    image_path = tmp_path / "source.png"
    manifest = tmp_path / "ground-truth.jsonl"
    _save_image(image_path, (0, 0, 0))
    manifest.write_text("already annotated", encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        prepare_manifest(image_path, manifest)


def test_load_manifest_rejects_duplicate_ids(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    _save_image(image_path, (0, 0, 0))
    row = {"id": "same", "image": "sample.png", "text": "Hello"}
    manifest = tmp_path / "ground-truth.jsonl"
    manifest.write_text(
        json.dumps(row) + "\n" + json.dumps(row) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate manifest id"):
        load_manifest(manifest)


def test_calculate_metrics_normalizes_case_but_preserves_strict_exact() -> None:
    metrics = calculate_metrics("Hello   world", "hello world", "en")

    assert metrics["exactMatch"] is False
    assert metrics["normalizedExactMatch"] is True
    assert metrics["cer"] == 0
    assert metrics["wer"] == 0


def test_run_attempts_uses_real_automatic_engine_order_and_disables_cache(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    _save_image(image_path, (0, 0, 0))
    service = FakeOcrService()

    records = run_attempts(
        [_entry(image_path)],
        service,
        profiles=["automatic", "windowsocr"],
        repeats=2,
        seed=7,
    )

    assert len(records) == 4
    assert all(call["bypassCache"] is True for call in service.calls)
    automatic_calls = [call for call in service.calls if call["engines"] == AUTOMATIC_PROFILE_ENGINES]
    assert len(automatic_calls) == 2
    automatic_records = [record for record in records if record["profile"] == "automatic"]
    assert all(record["fallbackUsed"] is True for record in automatic_records)
    assert all(record["selectedEngine"] == "paddleocr:standard" for record in automatic_records)


def test_run_attempts_keeps_engine_errors_in_the_report(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    _save_image(image_path, (0, 0, 0))

    class FailingService:
        def detect_text_with_metadata(self, *_args, **_kwargs):
            raise RuntimeError("engine unavailable")

    records = run_attempts(
        [_entry(image_path)],
        FailingService(),
        profiles=["easyocr"],
        repeats=1,
    )

    assert records[0]["status"] == "error"
    assert records[0]["error"] == "RuntimeError: engine unavailable"
    assert records[0]["text"] == ""


def test_summary_reports_percentiles_and_automatic_fallback(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    _save_image(image_path, (0, 0, 0))
    records = run_attempts(
        [_entry(image_path)],
        FakeOcrService(),
        profiles=["automatic"],
        repeats=3,
    )
    records[0]["durationMs"] = 10.0
    records[1]["durationMs"] = 20.0
    records[2]["durationMs"] = 30.0

    summary = summarize_records(records)[0]

    assert summary["fallbackRate"] == 1
    assert summary["latencyMs"]["mean"] == 20
    assert summary["latencyMs"]["p50"] == 20
    assert summary["latencyMs"]["p90"] == pytest.approx(28)
    assert summary["latencyMs"]["p95"] == pytest.approx(29)


def test_write_report_creates_json_csv_and_markdown(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    _save_image(image_path, (0, 0, 0))
    attempts = run_attempts(
        [_entry(image_path)],
        FakeOcrService(),
        profiles=["automatic"],
        repeats=1,
    )
    report = {
        "generatedAt": "2026-07-19T00:00:00+00:00",
        "manifest": "ground-truth.jsonl",
        "sampleCount": 1,
        "repeats": 1,
        "preprocessingProfile": "standard",
        "skippedIncomplete": 0,
        "warmup": {"skipped": False, "durationMs": 12.5, "warnings": []},
        "summary": summarize_records(attempts),
        "byCategory": [],
        "attempts": attempts,
    }

    paths = write_report(report, tmp_path / "results")

    assert Path(paths["json"]).is_file()
    assert Path(paths["csv"]).read_text(encoding="utf-8-sig").startswith("id,image")
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "# OCR benchmark" in markdown
    assert "Paddle fallback" in markdown
    assert render_markdown(report) == markdown

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import random
import re
import shutil
import statistics
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence

from PIL import Image


BRIDGE_DIR = Path(__file__).resolve().parents[1]
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

from hq_ocr_bridge.config import BridgeConfig  # noqa: E402
from hq_ocr_bridge.ocr import (  # noqa: E402
    AUTOMATIC_PROFILE_ENGINES,
    OCR_PREPROCESSING_STANDARD,
    SUPPORTED_OCR_PREPROCESSING_PROFILES,
    OcrService,
)
from hq_ocr_bridge.ranking import normalize_ocr_text  # noqa: E402


IMAGE_SUFFIXES = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".webp"})
PROFILE_ENGINES: dict[str, tuple[str, ...]] = {
    "automatic": AUTOMATIC_PROFILE_ENGINES,
    "tesseract": ("tesseract",),
    "windowsocr": ("windowsocr",),
    "paddleocr": ("paddleocr",),
    "easyocr": ("easyocr",),
}
DEFAULT_PROFILES = tuple(PROFILE_ENGINES)
BENCHMARK_DEPENDENCIES = ("Pillow", "easyocr", "paddleocr", "pytesseract", "winsdk")


@dataclass(frozen=True)
class BenchmarkEntry:
    entry_id: str
    image_path: Path
    image_value: str
    reference: str
    language: str
    category: str
    split: str
    sequence: str | None = None
    frame_index: int | None = None
    sha256: str | None = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_identifier(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", ascii_value).strip("-_").lower()
    return safe or "capture"


def _relative_or_absolute(path: Path, base_dir: Path) -> str:
    try:
        return Path(os.path.relpath(path.resolve(), base_dir.resolve())).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def discover_images(source: Path, source_format: str = "auto") -> list[Path]:
    source = source.expanduser().resolve()
    if not source.exists():
        raise ValueError(f"Image source does not exist: {source}")

    if source.is_file():
        if source.suffix.lower() not in IMAGE_SUFFIXES:
            raise ValueError(f"Unsupported image file: {source}")
        return [source]

    images = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not images:
        raise ValueError(f"No supported images were found in: {source}")

    debug_crops = [
        path
        for path in images
        if path.name.lower() == "crop.png"
        and ((path.parent / "request.json").exists() or (path.parent / "response.json").exists())
    ]
    if source_format == "debug-captures":
        if not debug_crops:
            raise ValueError("No debug-capture crop.png files were found")
        return debug_crops
    if source_format == "images":
        return images
    if source_format != "auto":
        raise ValueError(f"Unsupported source format: {source_format}")
    return debug_crops or images


def prepare_manifest(
    source: Path,
    manifest_path: Path,
    *,
    source_format: str = "auto",
    limit: int = 200,
    seed: int = 42,
    language: str = "en",
    category: str = "unclassified",
    copy_images: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    if limit < 0:
        raise ValueError("limit must be zero or greater")

    manifest_path = manifest_path.expanduser().resolve()
    if manifest_path.exists() and not force:
        raise ValueError(f"Manifest already exists (use --force to replace it): {manifest_path}")

    candidates = discover_images(source, source_format)
    unique_candidates: list[tuple[Path, str]] = []
    seen_hashes: set[str] = set()
    for path in candidates:
        digest = _sha256_file(path)
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        unique_candidates.append((path, digest))

    rng = random.Random(seed)
    rng.shuffle(unique_candidates)
    if limit:
        unique_candidates = unique_candidates[:limit]
    unique_candidates.sort(key=lambda item: str(item[0]).casefold())
    if not unique_candidates:
        raise ValueError("No unique images remain after deduplication")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    image_dir = manifest_path.parent / f"{manifest_path.stem}-images"
    if copy_images:
        image_dir.mkdir(parents=True, exist_ok=True)

    used_ids: set[str] = set()
    rows: list[dict[str, Any]] = []
    for source_path, digest in unique_candidates:
        source_name = source_path.parent.name if source_path.name.lower() == "crop.png" else source_path.stem
        entry_id = _safe_identifier(source_name)
        if entry_id in used_ids:
            entry_id = f"{entry_id}-{digest[:8]}"
        used_ids.add(entry_id)

        selected_path = source_path
        if copy_images:
            selected_path = image_dir / f"{entry_id}{source_path.suffix.lower()}"
            shutil.copy2(source_path, selected_path)

        rows.append(
            {
                "id": entry_id,
                "image": _relative_or_absolute(selected_path, manifest_path.parent),
                "text": "",
                "language": language,
                "category": category,
                "split": "test",
                "sequence": None,
                "frameIndex": None,
                "sha256": digest,
            }
        )

    temporary_path = manifest_path.with_suffix(f"{manifest_path.suffix}.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as file_handle:
        for row in rows:
            file_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary_path.replace(manifest_path)

    return {
        "manifest": str(manifest_path),
        "discovered": len(candidates),
        "duplicatesRemoved": len(candidates) - len(seen_hashes),
        "selected": len(rows),
        "copiedImages": copy_images,
    }


def load_manifest(manifest_path: Path) -> list[BenchmarkEntry]:
    manifest_path = manifest_path.expanduser().resolve()
    if not manifest_path.is_file():
        raise ValueError(f"Manifest does not exist: {manifest_path}")

    entries: list[BenchmarkEntry] = []
    seen_ids: set[str] = set()
    with manifest_path.open("r", encoding="utf-8-sig") as file_handle:
        for line_number, raw_line in enumerate(file_handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on manifest line {line_number}: {exc.msg}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Manifest line {line_number} must contain an object")

            entry_id = str(row.get("id") or "").strip()
            image_value = str(row.get("image") or "").strip()
            if not entry_id or not image_value:
                raise ValueError(f"Manifest line {line_number} requires id and image")
            if entry_id in seen_ids:
                raise ValueError(f"Duplicate manifest id: {entry_id}")
            seen_ids.add(entry_id)

            image_path = Path(image_value).expanduser()
            if not image_path.is_absolute():
                image_path = manifest_path.parent / image_path
            image_path = image_path.resolve()
            if not image_path.is_file():
                raise ValueError(f"Image for {entry_id} does not exist: {image_path}")

            frame_index_value = row.get("frameIndex")
            try:
                frame_index = int(frame_index_value) if frame_index_value is not None else None
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid frameIndex for {entry_id}") from exc

            entries.append(
                BenchmarkEntry(
                    entry_id=entry_id,
                    image_path=image_path,
                    image_value=image_value,
                    reference=str(row.get("text") or "").strip(),
                    language=str(row.get("language") or "en").strip() or "en",
                    category=str(row.get("category") or "unclassified").strip() or "unclassified",
                    split=str(row.get("split") or "test").strip() or "test",
                    sequence=(str(row["sequence"]).strip() if row.get("sequence") is not None else None),
                    frame_index=frame_index,
                    sha256=(str(row["sha256"]).strip() if row.get("sha256") else None),
                )
            )
    if not entries:
        raise ValueError("Manifest is empty")
    return entries


def _canonical_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value or "")
    return re.sub(r"\s+", " ", normalized).strip()


def _levenshtein(reference: Sequence[Any], hypothesis: Sequence[Any]) -> int:
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for reference_index, reference_item in enumerate(reference, start=1):
        current = [reference_index]
        for hypothesis_index, hypothesis_item in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[hypothesis_index] + 1,
                    previous[hypothesis_index - 1] + (reference_item != hypothesis_item),
                )
            )
        previous = current
    return previous[-1]


def calculate_metrics(reference: str, hypothesis: str, language: str = "en") -> dict[str, Any]:
    canonical_reference = _canonical_text(reference)
    canonical_hypothesis = _canonical_text(hypothesis)
    evaluation_reference = normalize_ocr_text(canonical_reference, language).casefold()
    evaluation_hypothesis = normalize_ocr_text(canonical_hypothesis, language).casefold()

    character_errors = _levenshtein(evaluation_reference, evaluation_hypothesis)
    reference_words = evaluation_reference.split()
    hypothesis_words = evaluation_hypothesis.split()
    word_errors = _levenshtein(reference_words, hypothesis_words)
    reference_characters = len(evaluation_reference)
    reference_word_count = len(reference_words)
    return {
        "exactMatch": canonical_reference == canonical_hypothesis,
        "normalizedExactMatch": evaluation_reference == evaluation_hypothesis,
        "characterErrors": character_errors,
        "referenceCharacters": reference_characters,
        "cer": character_errors / max(1, reference_characters),
        "wordErrors": word_errors,
        "referenceWords": reference_word_count,
        "wer": word_errors / max(1, reference_word_count),
    }


def _engine_base(engine: str) -> str:
    return str(engine or "").split(":", 1)[0].strip().lower()


def _dependency_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for dependency in BENCHMARK_DEPENDENCIES:
        try:
            versions[dependency] = importlib_metadata.version(dependency)
        except importlib_metadata.PackageNotFoundError:
            versions[dependency] = None
    return versions


def _shutdown_ocr_service(service: Any) -> None:
    for attribute in ("_engine_executor", "_parallel_executor"):
        executor = getattr(service, attribute, None)
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
    windows_adapter = getattr(service, "_windowsocr_adapter", None)
    if windows_adapter is not None:
        windows_adapter.close()


def run_attempts(
    entries: Sequence[BenchmarkEntry],
    service: Any,
    *,
    profiles: Sequence[str],
    repeats: int,
    preprocessing_profile: str = OCR_PREPROCESSING_STANDARD,
    seed: int = 42,
) -> list[dict[str, Any]]:
    if repeats < 1:
        raise ValueError("repeats must be at least one")
    unknown_profiles = [profile for profile in profiles if profile not in PROFILE_ENGINES]
    if unknown_profiles:
        raise ValueError(f"Unsupported profiles: {', '.join(unknown_profiles)}")

    tasks = [
        (entry, profile, repeat)
        for entry in entries
        for profile in profiles
        for repeat in range(1, repeats + 1)
    ]
    random.Random(seed).shuffle(tasks)
    records: list[dict[str, Any]] = []

    for execution_index, (entry, profile, repeat) in enumerate(tasks, start=1):
        load_started = perf_counter()
        try:
            with Image.open(entry.image_path) as source_image:
                image = source_image.convert("RGB")
                image.load()
            image_load_ms = (perf_counter() - load_started) * 1000
        except Exception as exc:
            duration_ms = (perf_counter() - load_started) * 1000
            metrics = calculate_metrics(entry.reference, "", entry.language)
            records.append(
                {
                    "executionIndex": execution_index,
                    "id": entry.entry_id,
                    "image": entry.image_value,
                    "category": entry.category,
                    "language": entry.language,
                    "split": entry.split,
                    "sequence": entry.sequence,
                    "frameIndex": entry.frame_index,
                    "profile": profile,
                    "repeat": repeat,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "reference": entry.reference,
                    "text": "",
                    "selectedEngine": None,
                    "score": None,
                    "durationMs": round(duration_ms, 3),
                    "imageLoadMs": round(duration_ms, 3),
                    "fallbackUsed": False,
                    "cacheHit": False,
                    "warnings": [],
                    "engineResults": [],
                    **metrics,
                }
            )
            continue

        started = perf_counter()
        try:
            best, engine_results, warnings, metadata = service.detect_text_with_metadata(
                image,
                list(PROFILE_ENGINES[profile]),
                language_tag=entry.language,
                preprocessing_profile=preprocessing_profile,
                bypass_cache=True,
            )
            duration_ms = (perf_counter() - started) * 1000
            text = best.text if best is not None else ""
            fallback_used = profile == "automatic" and any(
                _engine_base(result.engine) == "paddleocr" for result in engine_results
            )
            record = {
                "executionIndex": execution_index,
                "id": entry.entry_id,
                "image": entry.image_value,
                "category": entry.category,
                "language": entry.language,
                "split": entry.split,
                "sequence": entry.sequence,
                "frameIndex": entry.frame_index,
                "profile": profile,
                "repeat": repeat,
                "status": "ok",
                "error": None,
                "reference": entry.reference,
                "text": text,
                "selectedEngine": best.engine if best is not None else None,
                "score": float(best.score) if best is not None else None,
                "durationMs": round(duration_ms, 3),
                "imageLoadMs": round(image_load_ms, 3),
                "fallbackUsed": fallback_used,
                "cacheHit": bool(metadata.get("cacheHit", False)),
                "warnings": list(warnings),
                "engineResults": [result.to_dict() for result in engine_results],
            }
        except Exception as exc:
            duration_ms = (perf_counter() - started) * 1000
            text = ""
            record = {
                "executionIndex": execution_index,
                "id": entry.entry_id,
                "image": entry.image_value,
                "category": entry.category,
                "language": entry.language,
                "split": entry.split,
                "sequence": entry.sequence,
                "frameIndex": entry.frame_index,
                "profile": profile,
                "repeat": repeat,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "reference": entry.reference,
                "text": "",
                "selectedEngine": None,
                "score": None,
                "durationMs": round(duration_ms, 3),
                "imageLoadMs": round(image_load_ms, 3),
                "fallbackUsed": False,
                "cacheHit": False,
                "warnings": [],
                "engineResults": [],
            }
        record.update(calculate_metrics(entry.reference, text, entry.language))
        records.append(record)

    return sorted(records, key=lambda item: (item["id"], item["profile"], item["repeat"]))


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize_records(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    profiles = sorted({str(record["profile"]) for record in records})
    for profile in profiles:
        group = [record for record in records if record["profile"] == profile]
        durations = [float(record["durationMs"]) for record in group]
        attempts = len(group)
        character_errors = sum(int(record["characterErrors"]) for record in group)
        reference_characters = sum(int(record["referenceCharacters"]) for record in group)
        word_errors = sum(int(record["wordErrors"]) for record in group)
        reference_words = sum(int(record["referenceWords"]) for record in group)
        automatic_group = [record for record in group if record["profile"] == "automatic"]
        summaries.append(
            {
                "profile": profile,
                "attempts": attempts,
                "samples": len({str(record["id"]) for record in group}),
                "successRate": sum(record["status"] == "ok" for record in group) / max(1, attempts),
                "exactMatchRate": sum(bool(record["exactMatch"]) for record in group) / max(1, attempts),
                "normalizedExactMatchRate": sum(bool(record["normalizedExactMatch"]) for record in group) / max(1, attempts),
                "emptyOutputRate": sum(not str(record["text"]).strip() for record in group) / max(1, attempts),
                "cer": character_errors / max(1, reference_characters),
                "wer": word_errors / max(1, reference_words),
                "fallbackRate": (
                    sum(bool(record["fallbackUsed"]) for record in automatic_group)
                    / max(1, len(automatic_group))
                    if automatic_group
                    else None
                ),
                "latencyMs": {
                    "mean": statistics.fmean(durations) if durations else None,
                    "p50": _percentile(durations, 0.50),
                    "p90": _percentile(durations, 0.90),
                    "p95": _percentile(durations, 0.95),
                    "max": max(durations) if durations else None,
                },
            }
        )
    return summaries


def summarize_dimension(records: Sequence[dict[str, Any]], dimension: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    values = sorted({str(record[dimension]) for record in records})
    for value in values:
        for summary in summarize_records([record for record in records if str(record[dimension]) == value]):
            rows.append({dimension: value, **summary})
    return rows


def _rounded(value: Any, digits: int = 4) -> Any:
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, dict):
        return {key: _rounded(item, digits) for key, item in value.items()}
    if isinstance(value, list):
        return [_rounded(item, digits) for item in value]
    return value


def _percentage(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def _milliseconds(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# OCR benchmark",
        "",
        f"Generated: `{report['generatedAt']}`  ",
        f"Manifest: `{report['manifest']}`  ",
        f"Samples: **{report['sampleCount']}** | Repeats: **{report['repeats']}** | Attempts: **{len(report['attempts'])}**  ",
        f"Preprocessing: `{report['preprocessingProfile']}` | Cache during measurements: **disabled**",
        "",
        "Lower CER, WER and latency are better. Accuracy uses the annotated text in the manifest.",
        "",
        "## Overall",
        "",
        "| Profile | Success | Exact | Normalized exact | CER | WER | Mean ms | P50 ms | P90 ms | P95 ms | Paddle fallback |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for summary in report["summary"]:
        latency = summary["latencyMs"]
        lines.append(
            "| {profile} | {success} | {exact} | {normalized} | {cer:.4f} | {wer:.4f} | {mean} | {p50} | {p90} | {p95} | {fallback} |".format(
                profile=summary["profile"],
                success=_percentage(summary["successRate"]),
                exact=_percentage(summary["exactMatchRate"]),
                normalized=_percentage(summary["normalizedExactMatchRate"]),
                cer=summary["cer"],
                wer=summary["wer"],
                mean=_milliseconds(latency["mean"]),
                p50=_milliseconds(latency["p50"]),
                p90=_milliseconds(latency["p90"]),
                p95=_milliseconds(latency["p95"]),
                fallback=_percentage(summary["fallbackRate"]),
            )
        )

    if report["byCategory"]:
        lines.extend(
            [
                "",
                "## By category",
                "",
                "| Category | Profile | Exact | CER | WER | P95 ms |",
                "| --- | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in report["byCategory"]:
            lines.append(
                f"| {row['category']} | {row['profile']} | {_percentage(row['exactMatchRate'])} | {row['cer']:.4f} | {row['wer']:.4f} | {_milliseconds(row['latencyMs']['p95'])} |"
            )

    failures = [attempt for attempt in report["attempts"] if attempt["status"] != "ok"]
    lines.extend(["", "## Run notes", ""])
    warmup_label = (
        "skipped"
        if report["warmup"]["skipped"]
        else f"{report['warmup']['durationMs']:.1f} ms"
    )
    lines.append(f"- Warm-up: {warmup_label}.")
    lines.append(f"- Warm-up warnings: {len(report['warmup']['warnings'])}.")
    lines.append(f"- Failed attempts: {len(failures)}.")
    lines.append(f"- Entries without ground truth skipped: {report['skippedIncomplete']}.")
    lines.append("- This benchmark measures OCR only; it does not call the online translation providers.")
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "benchmark-results.json"
    csv_path = output_dir / "benchmark-attempts.csv"
    markdown_path = output_dir / "benchmark-summary.md"

    with json_path.open("w", encoding="utf-8", newline="\n") as file_handle:
        json.dump(_rounded(report), file_handle, ensure_ascii=False, indent=2)
        file_handle.write("\n")

    csv_fields = [
        "id",
        "image",
        "category",
        "language",
        "profile",
        "repeat",
        "status",
        "error",
        "reference",
        "text",
        "selectedEngine",
        "score",
        "durationMs",
        "imageLoadMs",
        "fallbackUsed",
        "exactMatch",
        "normalizedExactMatch",
        "cer",
        "wer",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["attempts"])

    markdown_path.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    return {"json": str(json_path), "csv": str(csv_path), "markdown": str(markdown_path)}


def _parse_profiles(values: Sequence[str]) -> list[str]:
    profiles: list[str] = []
    for value in values:
        for profile in value.split(","):
            normalized = profile.strip().lower()
            if normalized and normalized not in profiles:
                profiles.append(normalized)
    unknown = [profile for profile in profiles if profile not in PROFILE_ENGINES]
    if unknown:
        raise ValueError(f"Unsupported profiles: {', '.join(unknown)}")
    if not profiles:
        raise ValueError("At least one OCR profile is required")
    return profiles


def _selected_entries(
    entries: Sequence[BenchmarkEntry],
    *,
    split: str,
    limit: int,
    seed: int,
) -> tuple[list[BenchmarkEntry], int]:
    candidates = list(entries if split == "all" else [entry for entry in entries if entry.split == split])
    incomplete = [entry for entry in candidates if not _canonical_text(entry.reference)]
    selected = [entry for entry in candidates if _canonical_text(entry.reference)]
    if limit < 0:
        raise ValueError("limit must be zero or greater")
    if limit and len(selected) > limit:
        selected = random.Random(seed).sample(selected, limit)
    selected.sort(key=lambda entry: entry.entry_id)
    if not selected:
        raise ValueError("No annotated entries were selected. Fill the text field in the manifest first.")
    return selected, len(incomplete)


def execute_benchmark(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, str]]:
    manifest_path = args.manifest.expanduser().resolve()
    profiles = _parse_profiles(args.profiles)
    entries, skipped_incomplete = _selected_entries(
        load_manifest(manifest_path),
        split=args.split,
        limit=args.limit,
        seed=args.seed,
    )

    config = BridgeConfig.from_env()
    service = OcrService(config)
    warmup_engines = list(
        dict.fromkeys(engine for profile in profiles for engine in PROFILE_ENGINES[profile])
    )
    try:
        warmup_started = perf_counter()
        warmup_warnings = [] if args.skip_warmup else service.warm_up(warmup_engines)
        warmup_duration_ms = (perf_counter() - warmup_started) * 1000

        attempts = run_attempts(
            entries,
            service,
            profiles=profiles,
            repeats=args.repeats,
            preprocessing_profile=args.preprocessing_profile,
            seed=args.seed,
        )
    finally:
        _shutdown_ocr_service(service)
    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path),
        "manifestSha256": _sha256_file(manifest_path),
        "sampleCount": len(entries),
        "skippedIncomplete": skipped_incomplete,
        "profiles": profiles,
        "profileEngines": {profile: list(PROFILE_ENGINES[profile]) for profile in profiles},
        "repeats": args.repeats,
        "seed": args.seed,
        "split": args.split,
        "preprocessingProfile": args.preprocessing_profile,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": _dependency_versions(),
        "ocrConfig": {
            "allowedEngines": list(config.allowed_ocr_engines),
            "maxVariants": config.ocr_max_variants,
            "isolateTextRegion": config.ocr_isolate_text_region,
            "acceptScore": config.ocr_accept_score,
            "acceptConfidence": config.ocr_accept_confidence,
            "paddleOcrVersion": config.paddleocr_ocr_version,
            "paddleDetectionModel": config.paddleocr_detection_model,
            "paddleRecognitionModel": config.paddleocr_recognition_model,
            "easyOcrLanguage": config.easyocr_lang,
            "windowsOcrLanguage": config.windows_ocr_lang,
            "tesseractLanguage": config.tesseract_lang,
        },
        "warmup": {
            "skipped": bool(args.skip_warmup),
            "engines": warmup_engines,
            "durationMs": warmup_duration_ms,
            "warnings": warmup_warnings,
        },
        "summary": summarize_records(attempts),
        "byCategory": summarize_dimension(attempts, "category"),
        "byLanguage": summarize_dimension(attempts, "language"),
        "attempts": attempts,
    }

    output_dir = args.output_dir
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = BRIDGE_DIR / "benchmark" / "results" / f"{manifest_path.stem}-{timestamp}"
    paths = write_report(report, output_dir)
    return report, paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Development-only OCR benchmark using the application's real OCR pipeline."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser(
        "prepare", help="Create an annotation manifest from screenshots or debug captures."
    )
    prepare_parser.add_argument("--images", type=Path, required=True, help="Image file or directory to scan.")
    prepare_parser.add_argument(
        "--manifest",
        type=Path,
        default=BRIDGE_DIR / "benchmark" / "data" / "ground-truth.jsonl",
        help="JSONL manifest to create.",
    )
    prepare_parser.add_argument(
        "--source-format",
        choices=("auto", "debug-captures", "images"),
        default="auto",
        help="Auto uses only crop.png when a debug-capture tree is detected.",
    )
    prepare_parser.add_argument("--limit", type=int, default=200, help="Maximum unique images; zero keeps all.")
    prepare_parser.add_argument("--seed", type=int, default=42, help="Deterministic sampling seed.")
    prepare_parser.add_argument("--language", default="en", help="Initial OCR language tag.")
    prepare_parser.add_argument("--category", default="unclassified", help="Initial category label.")
    prepare_parser.add_argument(
        "--reference-source",
        action="store_true",
        help="Reference source files instead of copying a stable local dataset.",
    )
    prepare_parser.add_argument("--force", action="store_true", help="Replace an existing manifest.")

    run_parser = subparsers.add_parser("run", help="Run OCR profiles and create JSON, CSV and Markdown reports.")
    run_parser.add_argument("--manifest", type=Path, required=True, help="Annotated JSONL manifest.")
    run_parser.add_argument(
        "--profiles",
        nargs="+",
        default=list(DEFAULT_PROFILES),
        help=f"Profiles to test: {', '.join(DEFAULT_PROFILES)}.",
    )
    run_parser.add_argument("--repeats", type=int, default=3, help="Measured attempts per image/profile.")
    run_parser.add_argument("--seed", type=int, default=42, help="Deterministic task order and sampling seed.")
    run_parser.add_argument("--split", default="test", help="Manifest split to run, or all.")
    run_parser.add_argument("--limit", type=int, default=0, help="Maximum annotated images; zero keeps all.")
    run_parser.add_argument(
        "--preprocessing-profile",
        choices=sorted(SUPPORTED_OCR_PREPROCESSING_PROFILES),
        default=OCR_PREPROCESSING_STANDARD,
        help="Use standard to match the normal Automatic mode.",
    )
    run_parser.add_argument("--skip-warmup", action="store_true", help="Include cold model startup in attempts.")
    run_parser.add_argument("--output-dir", type=Path, help="Report directory; defaults to benchmark/results.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_manifest(
                args.images,
                args.manifest,
                source_format=args.source_format,
                limit=args.limit,
                seed=args.seed,
                language=args.language,
                category=args.category,
                copy_images=not args.reference_source,
                force=args.force,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("Fill the text fields in the manifest before running the benchmark.")
            return 0

        report, paths = execute_benchmark(args)
        print(json.dumps(_rounded(report["summary"]), ensure_ascii=False, indent=2))
        print(json.dumps(paths, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

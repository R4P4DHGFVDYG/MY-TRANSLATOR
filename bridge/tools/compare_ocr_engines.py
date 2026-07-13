from __future__ import annotations

import argparse
import json
import os
from io import BytesIO
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, Protocol
import unicodedata

import numpy as np
from PIL import Image


BRIDGE_DIR = Path(__file__).resolve().parents[1]
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

from hq_ocr_bridge.image_utils import preprocess_variants_for_ocr
from hq_ocr_bridge.ranking import normalize_ocr_text, text_quality_score
from hq_ocr_bridge.text_region import isolate_text_region


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_VARIANTS = ["standard"]


class OcrRunner(Protocol):
    name: str

    def recognize(self, image: Image.Image) -> tuple[str, float]:
        pass


class EasyOcrRunner:
    name = "easyocr"

    def __init__(
        self,
        lang: str,
        *,
        allow_download: bool = False,
        model_dir: str | None = None,
    ) -> None:
        self.lang = lang
        self.allow_download = allow_download
        self.model_dir = model_dir
        self._reader: Any | None = None

    def recognize(self, image: Image.Image) -> tuple[str, float]:
        if self._reader is None:
            import easyocr

            kwargs: dict[str, Any] = {
                "gpu": False,
                "download_enabled": self.allow_download,
            }
            if self.model_dir:
                kwargs["model_storage_directory"] = self.model_dir
            self._reader = easyocr.Reader([self.lang], **kwargs)

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        detections = self._reader.readtext(
            buffer.getvalue(),
            detail=1,
            paragraph=False,
        )

        fragments: list[str] = []
        confidences: list[float] = []
        for detection in detections:
            if len(detection) < 3:
                continue
            text = str(detection[1]).strip()
            if text:
                fragments.append(text)
            try:
                confidences.append(float(detection[2]))
            except (TypeError, ValueError):
                continue

        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return " ".join(fragments), confidence


class PaddleOcrRunner:
    name = "paddleocr"

    def __init__(
        self,
        lang: str,
        *,
        cache_dir: Path,
        model_source: str,
        disable_mkldnn: bool,
        ocr_version: str,
    ) -> None:
        self.lang = lang
        self.cache_dir = cache_dir
        self.model_source = model_source
        self.disable_mkldnn = disable_mkldnn
        self.ocr_version = ocr_version
        self._reader: Any | None = None

    def recognize(self, image: Image.Image) -> tuple[str, float]:
        if self._reader is None:
            self._configure_environment()

            from paddleocr import PaddleOCR

            self._reader = PaddleOCR(
                lang=self.lang,
                ocr_version=self.ocr_version,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )

        results = self._reader.predict(np.asarray(image.convert("RGB")))
        fragments: list[str] = []
        confidences: list[float] = []
        for result in results:
            payload = _paddle_result_payload(result)
            fragments.extend(str(text).strip() for text in payload.get("rec_texts", []))
            for confidence in payload.get("rec_scores", []):
                try:
                    confidences.append(float(confidence))
                except (TypeError, ValueError):
                    continue

        fragments = [fragment for fragment in fragments if fragment]
        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return " ".join(fragments), confidence

    def _configure_environment(self) -> None:
        os.environ["PADDLE_PDX_CACHE_HOME"] = str(self.cache_dir.resolve())
        os.environ["PADDLE_PDX_MODEL_SOURCE"] = self.model_source
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        os.environ["PADDLEOCR_DISABLE_AUTO_LOGGING_CONFIG"] = "1"
        if self.disable_mkldnn:
            os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "False"


def main() -> int:
    args = parse_args()
    try:
        images = collect_images(args.images, args.limit, args.all)
        variants = parse_variants(args.variants)
        runners = build_runners(args)
        ground_truth = load_ground_truth(args.ground_truth) if args.ground_truth else None
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not images:
        print(f"No images found in {args.images}", file=sys.stderr)
        return 2

    try:
        records = compare_images(
            images,
            runners,
            variants,
            ground_truth=ground_truth,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    summary = summarize(records)

    output = {
        "images": [str(path) for path in images],
        "variants": variants,
        "summary": summary,
        "records": records,
    }
    if args.ground_truth:
        output["groundTruth"] = {
            "path": str(args.ground_truth),
            "matchedImages": sum("groundTruth" in record for record in records),
            "missingImages": [
                record["image"] for record in records if "groundTruth" not in record
            ],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print_summary(summary, records, args.output)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare EasyOCR and PaddleOCR on local comic screenshots."
    )
    parser.add_argument(
        "--images",
        type=Path,
        default=BRIDGE_DIR.parent / "exemplos do OCR",
        help="Directory or image file to process.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=BRIDGE_DIR / ".pytest-tmp" / "ocr-engine-comparison.json",
        help="JSON output path with full OCR details.",
    )
    parser.add_argument(
        "--ground-truth",
        type=Path,
        help=(
            "JSON object mapping an image path, filename, or stem to its expected "
            "transcription. A top-level 'transcriptions' object is also accepted."
        ),
    )
    parser.add_argument(
        "--engines",
        default="easyocr,paddleocr",
        help="Comma-separated engines: easyocr,paddleocr.",
    )
    parser.add_argument(
        "--variants",
        default=",".join(DEFAULT_VARIANTS),
        help=(
            "Comma-separated preprocess variants: "
            "standard,pixel,pixel-soft,contrast,binary."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Limit number of images. Defaults to 1 to avoid CPU/RAM spikes.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all matching images. Heavy on CPU/RAM with PaddleOCR.",
    )
    parser.add_argument("--easyocr-lang", default="en")
    parser.add_argument("--easyocr-model-dir", default="")
    parser.add_argument("--allow-easyocr-download", action="store_true")
    parser.add_argument("--paddle-lang", default="en")
    parser.add_argument("--paddle-ocr-version", default="PP-OCRv5")
    parser.add_argument("--paddle-model-source", default="bos")
    parser.add_argument(
        "--paddle-cache",
        type=Path,
        default=BRIDGE_DIR / ".paddlex-cache",
    )
    parser.add_argument(
        "--paddle-enable-mkldnn",
        action="store_true",
        help="Enable MKL-DNN/oneDNN. Disabled by default due a local CPU failure.",
    )
    return parser.parse_args()


def collect_images(path: Path, limit: int, include_all: bool) -> list[Path]:
    if not path.exists():
        raise ValueError(f"Image path does not exist: {path}")
    if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
        return [path]
    if not path.is_dir():
        raise ValueError(f"Image path is neither a file nor a directory: {path}")
    images = [
        item
        for item in sorted(path.iterdir())
        if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS
    ]
    if include_all:
        return images
    return images[: max(limit, 1)]


def load_ground_truth(path: Path) -> dict[str, str]:
    if not path.exists():
        raise ValueError(f"Ground-truth path does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read ground-truth JSON {path}: {exc}") from exc

    if isinstance(payload, dict) and "transcriptions" in payload:
        payload = payload["transcriptions"]
    if not isinstance(payload, dict):
        raise ValueError("Ground-truth JSON must be an object of image-to-text mappings")

    transcriptions: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("Ground-truth keys and transcriptions must be strings")
        transcriptions[key] = _normalize_ground_truth_text(value)
    return transcriptions


def parse_variants(value: str) -> list[str]:
    variants = [item.strip().lower() for item in value.split(",") if item.strip()]
    allowed = {"standard", "pixel", "pixel-soft", "contrast", "binary"}
    unknown = sorted(set(variants) - allowed)
    if unknown:
        raise ValueError(f"Unknown variants: {', '.join(unknown)}")
    if not variants:
        raise ValueError("At least one preprocess variant must be selected")
    return variants


def build_runners(args: argparse.Namespace) -> list[OcrRunner]:
    requested = [item.strip().lower() for item in args.engines.split(",") if item.strip()]
    if not requested:
        raise ValueError("At least one OCR engine must be selected")
    runners: list[OcrRunner] = []
    for engine in requested:
        if engine == "easyocr":
            runners.append(
                EasyOcrRunner(
                    args.easyocr_lang,
                    allow_download=args.allow_easyocr_download,
                    model_dir=args.easyocr_model_dir or None,
                )
            )
        elif engine == "paddleocr":
            runners.append(
                PaddleOcrRunner(
                    args.paddle_lang,
                    cache_dir=args.paddle_cache,
                    model_source=args.paddle_model_source,
                    disable_mkldnn=not args.paddle_enable_mkldnn,
                    ocr_version=args.paddle_ocr_version,
                )
            )
        else:
            raise ValueError(f"Unknown engine: {engine}")
    return runners


def compare_images(
    images: list[Path],
    runners: list[OcrRunner],
    requested_variants: list[str],
    *,
    ground_truth: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for image_path in images:
        print(f"Processing {image_path.name}", flush=True)
        with Image.open(image_path) as source_image:
            image = source_image.convert("RGB")
        recognition_image = isolate_text_region(image)
        reference = lookup_ground_truth(image_path, ground_truth)
        engine_records = [
            run_engine(
                runner,
                _variants_for_engine(
                    recognition_image,
                    runner.name,
                    requested_variants,
                ),
                ground_truth=reference,
            )
            for runner in runners
        ]
        record = {
            "image": str(image_path),
            "width": image.width,
            "height": image.height,
            "engines": engine_records,
        }
        if reference is not None:
            record["groundTruth"] = reference
        records.append(record)
    return records


def run_engine(
    runner: OcrRunner,
    variants: list[tuple[str, Image.Image]],
    *,
    ground_truth: str | None = None,
) -> dict[str, Any]:
    if not variants:
        raise ValueError(f"No preprocess variants are available for {runner.name}")

    variant_records: list[dict[str, Any]] = []
    for variant_name, variant_image in variants:
        start = perf_counter()
        try:
            raw_text, raw_confidence = runner.recognize(variant_image)
            warning = None
        except Exception as exc:
            raw_text = ""
            raw_confidence = 0.0
            warning = str(exc)
        duration_ms = round((perf_counter() - start) * 1000, 1)
        text = normalize_ocr_text(raw_text)
        variant_record = {
            "variant": variant_name,
            "text": text,
            "rawText": raw_text,
            "rawConfidence": round(float(raw_confidence), 4),
            "score": text_quality_score(text, raw_confidence),
            "durationMs": duration_ms,
            "warning": warning,
        }
        if ground_truth is not None:
            variant_record["groundTruthMetrics"] = calculate_error_metrics(
                ground_truth,
                text,
            )
        variant_records.append(variant_record)

    best = max(
        variant_records,
        key=lambda item: (item["score"], item["rawConfidence"], len(item["text"])),
    )
    return {"engine": runner.name, "best": best, "variants": variant_records}


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_engine: dict[str, dict[str, Any]] = {}
    for record in records:
        for engine_record in record["engines"]:
            engine = engine_record["engine"]
            best = engine_record["best"]
            bucket = by_engine.setdefault(
                engine,
                {
                    "images": 0,
                    "empty": 0,
                    "winsByProxyScore": 0,
                    "totalScore": 0.0,
                    "totalConfidence": 0.0,
                    "totalDurationMs": 0.0,
                    "groundTruthImages": 0,
                    "exactMatches": 0,
                    "totalCharacterEdits": 0,
                    "totalReferenceCharacters": 0,
                    "totalWordEdits": 0,
                    "totalReferenceWords": 0,
                },
            )
            bucket["images"] += 1
            bucket["empty"] += 0 if best["text"] else 1
            bucket["totalScore"] += best["score"]
            bucket["totalConfidence"] += best["rawConfidence"]
            bucket["totalDurationMs"] += sum(
                variant["durationMs"] for variant in engine_record["variants"]
            )
            metrics = best.get("groundTruthMetrics")
            if metrics is not None:
                bucket["groundTruthImages"] += 1
                bucket["exactMatches"] += int(metrics["exactMatch"])
                bucket["totalCharacterEdits"] += metrics["characterEdits"]
                bucket["totalReferenceCharacters"] += metrics["referenceCharacters"]
                bucket["totalWordEdits"] += metrics["wordEdits"]
                bucket["totalReferenceWords"] += metrics["referenceWords"]

        winning_engine = max(
            record["engines"],
            key=lambda item: (
                item["best"]["score"],
                item["best"]["rawConfidence"],
                len(item["best"]["text"]),
            ),
        )["engine"]
        by_engine[winning_engine]["winsByProxyScore"] += 1

    for bucket in by_engine.values():
        images = max(int(bucket["images"]), 1)
        bucket["meanScore"] = round(bucket.pop("totalScore") / images, 4)
        bucket["meanConfidence"] = round(bucket.pop("totalConfidence") / images, 4)
        bucket["meanDurationMs"] = round(bucket.pop("totalDurationMs") / images, 1)
        ground_truth_images = bucket["groundTruthImages"]
        if ground_truth_images:
            bucket["exactMatchRate"] = round(
                bucket["exactMatches"] / ground_truth_images,
                4,
            )
            bucket["cer"] = error_rate(
                bucket["totalCharacterEdits"],
                bucket["totalReferenceCharacters"],
            )
            bucket["wer"] = error_rate(
                bucket["totalWordEdits"],
                bucket["totalReferenceWords"],
            )
        else:
            for key in (
                "groundTruthImages",
                "exactMatches",
                "totalCharacterEdits",
                "totalReferenceCharacters",
                "totalWordEdits",
                "totalReferenceWords",
            ):
                bucket.pop(key)

    return by_engine


def print_summary(
    summary: dict[str, Any],
    records: list[dict[str, Any]],
    output_path: Path,
) -> None:
    print("\nSummary")
    for engine, data in sorted(summary.items()):
        print(
            f"{engine}: wins={data['winsByProxyScore']}/{data['images']} "
            f"empty={data['empty']} meanScore={data['meanScore']} "
            f"meanConfidence={data['meanConfidence']} "
            f"meanDurationMs={data['meanDurationMs']}"
        )
        if data.get("groundTruthImages"):
            print(
                f"  groundTruth={data['groundTruthImages']} "
                f"exact={data['exactMatches']} "
                f"exactRate={data['exactMatchRate']} "
                f"CER={data['cer']} WER={data['wer']}"
            )

    print("\nPer image best text")
    for record in records:
        print(Path(record["image"]).name)
        for engine_record in record["engines"]:
            best = engine_record["best"]
            text = truncate(best["text"], 130)
            print(
                f"  {engine_record['engine']}[{best['variant']}]: "
                f"score={best['score']} conf={best['rawConfidence']} "
                f"timeMs={best['durationMs']} text={text!r}"
            )
            if best["warning"]:
                print(f"    warning={best['warning']}")
            metrics = best.get("groundTruthMetrics")
            if metrics is not None:
                print(
                    f"    exact={metrics['exactMatch']} "
                    f"CER={metrics['cer']} WER={metrics['wer']}"
                )

    print(f"\nFull JSON written to {output_path}")


def _paddle_result_payload(result: Any) -> dict[str, Any]:
    data = getattr(result, "json", None)
    if callable(data):
        data = data()
    if isinstance(data, dict):
        payload = data.get("res", data)
        if isinstance(payload, dict):
            return payload
    if isinstance(result, dict):
        payload = result.get("res", result)
        if isinstance(payload, dict):
            return payload
    return {}


def lookup_ground_truth(
    image_path: Path,
    transcriptions: dict[str, str] | None,
) -> str | None:
    if transcriptions is None:
        return None
    candidates = (
        str(image_path),
        image_path.as_posix(),
        image_path.name,
        image_path.stem,
    )
    for candidate in candidates:
        if candidate in transcriptions:
            return transcriptions[candidate]
    return None


def _normalize_ground_truth_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return " ".join(normalized.split())


def _variants_for_engine(
    image: Image.Image,
    engine: str,
    requested_variants: list[str],
) -> list[tuple[str, Image.Image]]:
    available = preprocess_variants_for_ocr(image, engine=engine)
    selected = [
        (name, variant)
        for name, variant in available
        if name in requested_variants
    ]
    if selected:
        return selected

    available_names = ", ".join(name for name, _variant in available)
    requested_names = ", ".join(requested_variants)
    raise ValueError(
        f"None of the requested preprocess variants ({requested_names}) are "
        f"available for {engine}; available variants: {available_names}"
    )


def calculate_error_metrics(reference: str, hypothesis: str) -> dict[str, Any]:
    character_edits = levenshtein_distance(list(reference), list(hypothesis))
    reference_words = reference.split()
    hypothesis_words = hypothesis.split()
    word_edits = levenshtein_distance(reference_words, hypothesis_words)
    return {
        "exactMatch": reference == hypothesis,
        "characterEdits": character_edits,
        "referenceCharacters": len(reference),
        "cer": error_rate(character_edits, len(reference)),
        "wordEdits": word_edits,
        "referenceWords": len(reference_words),
        "wer": error_rate(word_edits, len(reference_words)),
    }


def levenshtein_distance(reference: list[Any], hypothesis: list[Any]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for reference_index, reference_item in enumerate(reference, start=1):
        current = [reference_index]
        for hypothesis_index, hypothesis_item in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[hypothesis_index] + 1,
                    previous[hypothesis_index - 1]
                    + int(reference_item != hypothesis_item),
                )
            )
        previous = current
    return previous[-1]


def error_rate(edits: int, reference_units: int) -> float:
    return round(edits / max(reference_units, 1), 4)


def truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3] + "..."


if __name__ == "__main__":
    raise SystemExit(main())

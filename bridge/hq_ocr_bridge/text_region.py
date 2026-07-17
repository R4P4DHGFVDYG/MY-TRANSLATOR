from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PIL import Image


_MAX_EDGE_GRAPHIC_FRACTION = 0.42
_MAX_SATURATED_PIXEL_FRACTION = 0.45
_SATURATION_SPREAD_THRESHOLD = 48


@dataclass(frozen=True)
class _CropCandidate:
    box: tuple[int, int, int, int]
    score: float


def isolate_text_region(image: Image.Image) -> Image.Image:
    """Remove a large edge graphic from a dark text box when detection is clear.

    The detector deliberately handles only a narrow, high-confidence layout: a
    mostly dark image, bright text, a large graphic touching either horizontal
    edge, and a blank vertical separator between both regions. Ambiguous images
    and environments without OpenCV are returned unchanged.
    """

    if not isinstance(image, Image.Image):
        raise TypeError("image must be a PIL image")

    modules = _load_opencv()
    if modules is None:
        return image
    cv2, numpy = modules

    try:
        box = _detect_text_region(image, cv2, numpy)
    except (ValueError, cv2.error):
        return image
    if box is None:
        return image
    return image.crop(box)


def _load_opencv() -> tuple[Any, Any] | None:
    try:
        import cv2
        import numpy
    except ImportError:
        return None
    return cv2, numpy


def _detect_text_region(
    image: Image.Image, cv2: Any, numpy: Any
) -> tuple[int, int, int, int] | None:
    width, height = image.size
    if width < 160 or height < 48 or width < height * 1.5:
        return None

    rgb = numpy.asarray(image.convert("RGB"))
    channel_spread = rgb.max(axis=2) - rgb.min(axis=2)
    saturated_pixel_fraction = float(
        (channel_spread >= _SATURATION_SPREAD_THRESHOLD).mean()
    )
    if saturated_pixel_fraction > _MAX_SATURATED_PIXEL_FRACTION:
        return None
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if float(numpy.median(gray)) > 96:
        return None
    if float(numpy.percentile(gray, 95) - numpy.percentile(gray, 10)) < 70:
        return None

    otsu_threshold, _unused = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    bright_threshold = max(100, min(220, int(otsu_threshold) + 20))
    foreground = (gray >= bright_threshold).astype("uint8")

    count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        foreground, connectivity=8
    )
    if count <= 1:
        return None

    min_component_area = max(3, round(width * height * 0.00001))
    kept_labels = numpy.zeros(count, dtype=bool)
    kept_labels[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_component_area
    foreground = kept_labels[labels].astype("uint8")

    foreground_ratio = float(foreground.mean())
    if foreground_ratio < 0.003 or foreground_ratio > 0.32:
        return None

    blank_limit = max(1, round(height * 0.005))
    blank_columns = foreground.sum(axis=0) <= blank_limit
    gaps = _true_runs(blank_columns)
    minimum_gap = max(10, round(width * 0.025))

    candidates: list[_CropCandidate] = []
    for start, end in gaps:
        gap_width = end - start
        if gap_width < minimum_gap:
            continue

        if width * 0.10 <= end <= width * 0.48:
            candidate = _candidate_for_left_graphic(
                foreground,
                stats,
                centroids,
                start,
                end,
                width,
                height,
                cv2,
            )
            if candidate is not None:
                candidates.append(candidate)

        if width * 0.52 <= start <= width * 0.90:
            candidate = _candidate_for_right_graphic(
                foreground,
                stats,
                centroids,
                start,
                end,
                width,
                height,
                cv2,
            )
            if candidate is not None:
                candidates.append(candidate)

    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate.score).box


def _candidate_for_left_graphic(
    foreground: Any,
    stats: Any,
    centroids: Any,
    gap_start: int,
    gap_end: int,
    width: int,
    height: int,
    cv2: Any,
) -> _CropCandidate | None:
    removed_fraction = gap_end / width
    if removed_fraction > _MAX_EDGE_GRAPHIC_FRACTION:
        return None
    if not _has_large_edge_graphic(
        foreground[:, :gap_start],
        stats,
        centroids,
        0,
        gap_start,
        width,
        height,
        cv2,
    ):
        return None
    text_score = _text_region_score(foreground[:, gap_end:])
    if text_score is None:
        return None
    gap_score = min((gap_end - gap_start) / max(width * 0.08, 1), 1.0)
    return _CropCandidate(
        (gap_end, 0, width, height),
        text_score + gap_score * 0.25,
    )


def _candidate_for_right_graphic(
    foreground: Any,
    stats: Any,
    centroids: Any,
    gap_start: int,
    gap_end: int,
    width: int,
    height: int,
    cv2: Any,
) -> _CropCandidate | None:
    removed_fraction = (width - gap_start) / width
    if removed_fraction > _MAX_EDGE_GRAPHIC_FRACTION:
        return None
    if not _has_large_edge_graphic(
        foreground[:, gap_end:],
        stats,
        centroids,
        gap_end,
        width,
        width,
        height,
        cv2,
    ):
        return None
    text_score = _text_region_score(foreground[:, :gap_start])
    if text_score is None:
        return None
    gap_score = min((gap_end - gap_start) / max(width * 0.08, 1), 1.0)
    return _CropCandidate(
        (0, 0, gap_start, height),
        text_score + gap_score * 0.25,
    )


def _has_large_edge_graphic(
    edge_region: Any,
    stats: Any,
    centroids: Any,
    lower_x: int,
    upper_x: int,
    width: int,
    height: int,
    cv2: Any,
) -> bool:
    if edge_region.size == 0:
        return False

    active_rows = edge_region.sum(axis=1) >= 2
    row_indexes = active_rows.nonzero()[0]
    if len(row_indexes) == 0:
        return False
    vertical_span = (int(row_indexes[-1]) - int(row_indexes[0]) + 1) / height
    if vertical_span < 0.50:
        return False

    active_columns = (edge_region.sum(axis=0) >= 2).nonzero()[0]
    if len(active_columns) == 0:
        return False
    maximum_edge_margin = width * 0.05
    if lower_x == 0 and int(active_columns[0]) > maximum_edge_margin:
        return False
    if (
        upper_x == width
        and edge_region.shape[1] - int(active_columns[-1]) - 1 > maximum_edge_margin
    ):
        return False

    for index in range(1, len(stats)):
        center_x = float(centroids[index][0])
        if not lower_x <= center_x < upper_x:
            continue
        component_width = int(stats[index, cv2.CC_STAT_WIDTH])
        component_height = int(stats[index, cv2.CC_STAT_HEIGHT])
        component_area = int(stats[index, cv2.CC_STAT_AREA])
        is_tall_graphic = (
            component_height >= height * 0.35
            and component_width >= width * 0.04
            and component_area >= width * height * 0.002
        )
        is_dense_graphic = component_area >= width * height * 0.012
        if is_tall_graphic or is_dense_graphic:
            return True
    return False


def _text_region_score(region: Any) -> float | None:
    height, width = region.shape
    if width < 80:
        return None

    foreground_ratio = float(region.mean())
    if foreground_ratio < 0.003 or foreground_ratio > 0.30:
        return None

    active_columns = (region.sum(axis=0) >= 2).nonzero()[0]
    if len(active_columns) < 8:
        return None
    column_runs = _true_runs(region.sum(axis=0) >= 2)
    text_like_runs = [
        (start, end)
        for start, end in column_runs
        if 1 <= end - start <= width * 0.18
    ]
    if len(text_like_runs) < 4:
        return None
    horizontal_span = (
        int(active_columns[-1]) - int(active_columns[0]) + 1
    ) / width
    if horizontal_span < 0.25:
        return None

    row_threshold = max(2, round(width * 0.002))
    active_rows = region.sum(axis=1) >= row_threshold
    line_runs = _merge_runs(_true_runs(active_rows), max(3, round(height * 0.03)))
    plausible_lines = [
        (start, end)
        for start, end in line_runs
        if height * 0.04 <= end - start <= height * 0.45
    ]
    if not 1 <= len(plausible_lines) <= 6:
        return None

    return min(horizontal_span, 1.0) + min(len(plausible_lines) / 3, 1.0) * 0.3


def _true_runs(values: Any) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(values):
        if bool(value) and start is None:
            start = index
        elif not bool(value) and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(values)))
    return runs


def _merge_runs(
    runs: list[tuple[int, int]], maximum_gap: int
) -> list[tuple[int, int]]:
    if not runs:
        return []

    merged = [runs[0]]
    for start, end in runs[1:]:
        previous_start, previous_end = merged[-1]
        if start - previous_end <= maximum_gap:
            merged[-1] = (previous_start, end)
        else:
            merged.append((start, end))
    return merged

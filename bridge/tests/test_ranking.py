from hq_ocr_bridge.models import EngineResult
from hq_ocr_bridge.ranking import normalize_ocr_text, rank_ocr_results, text_quality_score


def test_normalize_ocr_text_collapses_spacing():
    assert normalize_ocr_text("  HELLO\n\n  WORLD  ") == "HELLO WORLD"


def test_text_quality_penalizes_empty_text():
    assert text_quality_score("", 0.9) == 0.0


def test_rank_prefers_consensus_and_confidence():
    weak = EngineResult("tesseract", "HELLO W0RLD", 0.6, 0.6)
    strong = EngineResult("easyocr", "HELLO WORLD", 0.72, 0.72)

    best = rank_ocr_results([weak, strong])

    assert best is strong

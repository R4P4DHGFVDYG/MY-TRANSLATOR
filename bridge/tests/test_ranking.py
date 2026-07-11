from hq_ocr_bridge.models import EngineResult
from hq_ocr_bridge.ranking import normalize_ocr_text, rank_ocr_results, text_quality_score


def test_normalize_ocr_text_collapses_spacing():
    assert normalize_ocr_text("  HELLO\n\n  WORLD  ") == "HELLO WORLD"


def test_normalize_ocr_text_fixes_comic_letter_confusions():
    text = "LONG As 4ou BEHAVE 4OURSELVES; THAT Is."

    assert normalize_ocr_text(text) == "LONG AS YOU BEHAVE YOURSELVES; THAT IS."


def test_normalize_ocr_text_fixes_common_comic_punctuation():
    text = "I thought WE WERE Old PALS; 7"

    assert normalize_ocr_text(text) == "I THOUGHT WE WERE OLD PALS..."


def test_normalize_ocr_text_fixes_mixed_case_contractions():
    text = "Im Sure Some Poor SAP Down TheRE Will APprECiATE IT"

    assert normalize_ocr_text(text) == "I'M SURE SOME POOR SAP DOWN THERE WILL APPRECIATE IT"


def test_normalize_ocr_text_fixes_leading_ellipsis_noise():
    assert normalize_ocr_text("1a with his hostage") == "...with his hostage"


def test_normalize_ocr_text_fixes_tis_noise():
    assert normalize_ocr_text("(tis COOL: YOU SounD Like YoU NEED A BreAtHEr") == (
        "IT'S COOL: YOU SOUND LIKE YOU NEED A BREATHER"
    )


def test_normalize_ocr_text_fixes_observed_paddleocr_confusions():
    assert normalize_ocr_text("I BRING MY ENTIRE 2IO POUNDS DOWN") == (
        "I BRING MY ENTIRE 210 POUNDS DOWN"
    )
    assert normalize_ocr_text("I TRY TO TAKE IT A LITTLE EAS/ER") == (
        "I TRY TO TAKE IT A LITTLE EASIER"
    )
    assert normalize_ocr_text("ROBIN-- JASON TOOD. HAD BEEN") == (
        "ROBIN-- JASON TODD. HAD BEEN"
    )


def test_normalize_ocr_text_keeps_sentence_case_when_not_all_caps():
    text = "third lap around and I still can t find it My"

    assert normalize_ocr_text(text) == "third lap around and I still can't find it My"


def test_text_quality_penalizes_empty_text():
    assert text_quality_score("", 0.9) == 0.0


def test_rank_prefers_consensus_and_confidence():
    weak = EngineResult("tesseract", "HELLO W0RLD", 0.6, 0.6)
    strong = EngineResult("easyocr", "HELLO WORLD", 0.72, 0.72)

    best = rank_ocr_results([weak, strong])

    assert best is strong


def test_engine_result_includes_raw_text_when_normalized():
    result = EngineResult("easyocr:standard", "YOU", 0.8, 0.8, raw_text="4ou")

    assert result.to_dict()["rawText"] == "4ou"


def test_ranking_and_serialization_ignore_non_finite_confidence_values():
    invalid = EngineResult("easyocr", "HELLO WORLD", float("nan"), float("inf"))
    valid = EngineResult("tesseract", "HELLO", 0.4, 0.4)

    best = rank_ocr_results([invalid, valid])

    assert best is valid
    assert invalid.to_dict()["score"] == 0.0
    assert "rawConfidence" not in invalid.to_dict()

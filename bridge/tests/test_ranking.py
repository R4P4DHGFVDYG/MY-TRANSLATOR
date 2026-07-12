from hq_ocr_bridge.models import EngineResult
from hq_ocr_bridge.ranking import (
    normalize_ocr_text,
    ocr_suspicion_score,
    rank_ocr_results,
    text_quality_score,
)


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


def test_normalize_ocr_text_fixes_observed_tesseract_confusions():
    assert normalize_ocr_text("* You quickly look away.") == (
        "You quickly look away."
    )
    assert normalize_ocr_text("*... and, don't forget") == (
        "...and don't forget"
    )
    assert normalize_ocr_text("CIt''s your moms van. )") == (
        "(It's your mom's van.)"
    )


def test_normalize_ocr_text_keeps_sentence_case_when_not_all_caps():
    text = "third lap around and I still can t find it My"

    assert normalize_ocr_text(text) == "third lap around and I still can't find it My"


def test_normalize_ocr_text_preserves_real_id_and_ill_words():
    assert normalize_ocr_text("SHOW ME YOUR ID") == "SHOW ME YOUR ID"
    assert normalize_ocr_text("I FEEL ILL") == "I FEEL ILL"


def test_suspicious_ocr_artifacts_reduce_quality_even_with_high_confidence():
    clean = text_quality_score("THIS IS INTERESTING", 0.98)
    noisy = text_quality_score(
        "U1L - THIS /S INTERESTING",
        0.98,
        raw_text="U1L - THIS /S INTERESTING",
    )

    assert ocr_suspicion_score("U1L S/GH") > 0
    assert noisy < clean


def test_quality_does_not_penalize_legitimate_game_codes():
    legitimate = text_quality_score("H2O AND R2-D2 C-130 and/or", 0.98)
    letter_substitutions = text_quality_score("HZO AND RZ-DZ C-I3O and/or", 0.98)

    assert ocr_suspicion_score("H2O R2-D2 C-130 and/or") == 0
    assert legitimate >= letter_substitutions


def test_text_quality_penalizes_empty_text():
    assert text_quality_score("", 0.9) == 0.0


def test_rank_prefers_consensus_and_confidence():
    weak = EngineResult("tesseract", "HELLO W0RLD", 0.6, 0.6)
    strong = EngineResult("easyocr", "HELLO WORLD", 0.72, 0.72)

    best = rank_ocr_results([weak, strong])

    assert best is strong


def test_rank_keeps_primary_spelling_when_verifier_is_similar_and_overconfident():
    primary = EngineResult(
        "tesseract:standard", "(It's your mom's van.)", 0.73, 0.72
    )
    verifier = EngineResult(
        "paddleocr:standard", "(It's your mom's yan.", 0.95, 0.98
    )

    best = rank_ocr_results(
        [primary, verifier],
        primary_engine="tesseract",
    )

    assert best is primary


def test_rank_uses_verifier_when_uncertain_primary_clearly_disagrees():
    primary = EngineResult("tesseract:standard", "ZZZ", 0.52, 0.55)
    verifier = EngineResult(
        "paddleocr:standard", "CLEAR SUBTITLE", 0.92, 0.94
    )

    best = rank_ocr_results(
        [primary, verifier],
        primary_engine="tesseract",
    )

    assert best is verifier


def test_rank_does_not_treat_same_engine_variants_as_independent_consensus():
    standard = EngineResult("tesseract:standard", "HELLO WORLD", 0.6, 0.6)
    binary = EngineResult("tesseract:binary", "HELLO WORLD", 0.65, 0.65)

    best = rank_ocr_results([standard, binary])

    assert best is binary
    assert standard.score == 0.6
    assert binary.score == 0.65


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

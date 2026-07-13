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


def test_normalize_ocr_text_fixes_observed_dialogue_punctuation_confusions():
    assert normalize_ocr_text(
        "HAHAT Susie, we : re supposed to hit them at the same timet"
    ) == "HAHA! Susie, we're supposed to hit them at the same time!"
    assert normalize_ocr_text("same timef") == "same time!"


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


def test_non_english_normalization_preserves_language_specific_text():
    assert normalize_ocr_text("IM HAUS", "de") == "IM HAUS"
    assert normalize_ocr_text("AÇÃO NÃO", "pt-BR") == "AÇÃO NÃO"
    assert normalize_ocr_text("Привет мир", "ru") == "Привет мир"


def test_unicode_letters_are_not_treated_as_ocr_noise():
    assert ocr_suspicion_score("AÇÃO NÃO") == 0
    assert ocr_suspicion_score("Привет мир") == 0
    assert ocr_suspicion_score("こんにちは世界") == 0
    assert text_quality_score(
        "こんにちは世界", None, language_tag="ja"
    ) > 0.5


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


def test_unknown_confidence_is_missing_evidence_instead_of_zero_confidence():
    unknown = text_quality_score("HELLO WORLD", None)
    known_zero = text_quality_score("HELLO WORLD", 0.0)

    assert unknown > known_zero
    result = EngineResult("windowsocr", "HELLO WORLD", unknown, None)
    assert result.to_dict()["confidenceKnown"] is False
    assert "rawConfidence" not in result.to_dict()


def test_rank_prefers_consensus_and_confidence():
    weak = EngineResult("tesseract", "HELLO W0RLD", 0.6, 0.6)
    strong = EngineResult("easyocr", "HELLO WORLD", 0.72, 0.72)

    best = rank_ocr_results([weak, strong])

    assert best is strong


def test_rank_prefers_exact_consensus_between_independent_engines():
    standard = EngineResult("tesseract:standard", "S50 WHAT", 0.91, 0.92)
    pixel = EngineResult("tesseract:pixel", "SO WHAT", 0.79, 0.80)
    verifier = EngineResult("paddleocr:standard", "SO WHAT", 0.88, 0.95)

    best = rank_ocr_results(
        [standard, pixel, verifier],
        primary_engine="tesseract",
    )

    assert best is verifier


def test_same_engine_variants_do_not_create_independent_consensus():
    standard = EngineResult("tesseract:standard", "PRIMARY", 0.81, 0.82)
    pixel = EngineResult("tesseract:pixel", "PRIMARY", 0.82, 0.83)
    verifier = EngineResult("paddleocr:standard", "CLEAR RESULT", 0.95, 0.96)

    best = rank_ocr_results(
        [standard, pixel, verifier],
        primary_engine="tesseract",
    )

    assert best is verifier


def test_rank_keeps_primary_spelling_when_verifier_is_similar_and_overconfident():
    primary = EngineResult(
        "tesseract:standard", "(It's your mom's van.)", 0.73, 0.72
    )
    primary_variant = EngineResult(
        "tesseract:pixel", "(It's your mom's van.)", 0.72, 0.71
    )
    verifier = EngineResult(
        "paddleocr:standard", "(It's your mom's yan.", 0.95, 0.98
    )

    best = rank_ocr_results(
        [primary, primary_variant, verifier],
        primary_engine="tesseract",
    )

    assert best is primary


def test_rank_uses_clear_verifier_advantage_without_primary_variant_consensus():
    standard = EngineResult(
        "tesseract:standard",
        "HAHAT Susie, we're supposed to hit them at the same timef",
        0.8999,
        0.8867,
    )
    pixel = EngineResult(
        "tesseract:pixel",
        "HAHAT Susie, we're supposed to hit them at the same timet",
        0.8839,
        0.8575,
    )
    verifier = EngineResult(
        "paddleocr:standard",
        "HAHA! Susie, we: re supposed to hit them at the same timet",
        0.9349,
        0.9524,
    )

    best = rank_ocr_results(
        [standard, pixel, verifier],
        primary_engine="tesseract",
    )

    assert best is verifier


def test_rank_uses_high_confidence_verifier_for_terminal_digit_artifact():
    standard = EngineResult(
        "tesseract:standard",
        "U-unm... (maybe she's misunderstanding, but her face... 7)",
        0.8298,
        0.77,
    )
    pixel = EngineResult(
        "tesseract:pixel",
        "U-um... (maybe she's misunderstanding, but her face... 7)",
        0.8486,
        0.8067,
    )
    verifier = EngineResult(
        "paddleocr:standard",
        "U-um... (maybe she's misunderstanding, but her face...?)",
        0.9301,
        0.9733,
    )

    best = rank_ocr_results(
        [standard, pixel, verifier],
        primary_engine="tesseract",
    )

    assert best is verifier


def test_rank_allows_clear_verifier_advantage_below_near_identity_threshold():
    primary = EngineResult(
        "tesseract:standard",
        "U-unM maybe ail misunderstanding but her face 7",
        0.81,
        0.74,
    )
    verifier = EngineResult(
        "paddleocr:standard",
        "U-um maybe she's misunderstanding but her face",
        0.93,
        0.97,
    )

    best = rank_ocr_results(
        [primary, verifier],
        primary_engine="tesseract",
    )

    assert best is verifier


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
    assert invalid.to_dict()["confidenceKnown"] is False

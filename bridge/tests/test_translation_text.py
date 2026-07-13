from hq_ocr_bridge.translation_text import prepare_text_for_translation


def test_prepare_text_for_translation_softens_comic_caps():
    assert prepare_text_for_translation("VERY MOODY.") == "Very moody."
    assert prepare_text_for_translation("I TRY TO KEEP MY TEMPER IN CHECK.") == (
        "I try to keep my temper in check."
    )


def test_prepare_text_for_translation_keeps_non_caps_text():
    assert prepare_text_for_translation("third lap around") == "third lap around"


def test_prepare_text_for_translation_handles_sentence_boundaries():
    assert prepare_text_for_translation("ROBIN-- JASON TODD. HAD BEEN ODD.") == (
        "Robin-- Jason todd. Had been odd."
    )


def test_prepare_text_for_translation_does_not_apply_english_rules_to_other_languages():
    assert prepare_text_for_translation("IM HAUS", "de") == "IM HAUS"
    assert prepare_text_for_translation("ESTOU EM CASA", "pt-BR") == "ESTOU EM CASA"
    assert prepare_text_for_translation("こんにちは世界", "ja") == "こんにちは世界"

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

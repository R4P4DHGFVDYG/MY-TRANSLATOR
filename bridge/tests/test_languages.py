import pytest

from hq_ocr_bridge.languages import (
    SUPPORTED_LANGUAGE_CODES,
    language_base,
    normalize_language_code,
)


def test_language_catalog_contains_supported_source_and_target_codes():
    assert len(SUPPORTED_LANGUAGE_CODES) == 14
    assert {"en", "pt-BR", "ja", "zh-CN", "zh-TW", "ru"}.issubset(
        SUPPORTED_LANGUAGE_CODES
    )


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("PT", "pt-BR"),
        ("pt-br", "pt-BR"),
        ("EN-US", "en"),
        ("ja-JP", "ja"),
        ("zh-Hans", "zh-CN"),
        ("zh-hant", "zh-TW"),
    ],
)
def test_language_aliases_are_canonicalized(requested, expected):
    assert normalize_language_code(requested) == expected


def test_language_base_uses_canonical_code_and_rejects_unknown_values():
    assert language_base("pt-br") == "pt"
    assert language_base("zh-Hant") == "zh"
    with pytest.raises(ValueError, match="unsupported language code"):
        normalize_language_code("not-a-language")

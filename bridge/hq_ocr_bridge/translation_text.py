from __future__ import annotations

import re


WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
FIRST_ALPHA_RE = re.compile(r"[A-Za-z]")
STANDALONE_I_RE = re.compile(r"\bi(?:'([a-z]+))?\b")


def prepare_text_for_translation(text: str) -> str:
    stripped = text.strip()
    if not _looks_like_comic_caps(stripped):
        return stripped

    lowered = stripped.lower()
    prepared = _sentence_case(lowered)
    return STANDALONE_I_RE.sub(_uppercase_i, prepared)


def _looks_like_comic_caps(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 4:
        return False

    uppercase_ratio = sum(1 for ch in letters if ch.isupper()) / len(letters)
    words = WORD_RE.findall(text)
    return uppercase_ratio >= 0.75 and bool(words)


def _sentence_case(text: str) -> str:
    chars: list[str] = []
    capitalize_next = True
    index = 0
    while index < len(text):
        char = text[index]
        if char.isalpha() and capitalize_next:
            chars.append(char.upper())
            capitalize_next = False
        else:
            chars.append(char)

        if char in ".!?":
            capitalize_next = True
        elif text[index : index + 2] == "--":
            capitalize_next = True
        elif char.isalpha():
            capitalize_next = False
        index += 1

    return "".join(chars)


def _uppercase_i(match: re.Match[str]) -> str:
    suffix = match.group(1)
    if suffix:
        return "I'" + suffix
    return "I"

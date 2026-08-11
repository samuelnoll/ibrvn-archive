from __future__ import annotations

import re
import unicodedata


CTB_YEAR_SUFFIX = re.compile(r"\s*\|\s*CTB\s+(?:19|20)\d{2}\s*$", re.I)
STUDY_PREFIX = re.compile(
    r"^\s*(?:CTB|Estudo|Confer[e\u00ea]ncia)\b\s*[:|\-]?\s*",
    re.I,
)
BRACKETED_TEXT = re.compile(r"\s*\[[^\]]+\]\s*")


def clean_study_title(value: str) -> str:
    original = str(value or "").strip()
    title = BRACKETED_TEXT.sub(" ", original)
    title = CTB_YEAR_SUFFIX.sub("", title)

    while STUDY_PREFIX.match(title):
        title = STUDY_PREFIX.sub("", title, count=1)

    title = re.sub(r"\s+", " ", title).strip(" |:-")
    return title or original


def title_identity(value: str) -> str:
    title = clean_study_title(value)
    decomposed = unicodedata.normalize("NFKD", title)
    ascii_title = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", ascii_title.casefold()))

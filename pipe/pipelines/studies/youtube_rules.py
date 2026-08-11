from __future__ import annotations

import unicodedata


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).casefold().strip()


def is_study_playlist(title: str) -> bool:
    return normalize_text(title).startswith("estudo ")


def infer_study_type(playlist_titles: list[str]) -> str:
    normalized = " ".join(normalize_text(title) for title in playlist_titles)

    if "ctb" in normalized or "treinamento biblico" in normalized:
        return "ctb"

    if "pfd" in normalized or "formacao de discipulos" in normalized:
        return "pfd"

    if "palestra" in normalized or "conferencia" in normalized:
        return "lecture_or_conference"

    return "weekly"

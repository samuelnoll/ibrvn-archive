from __future__ import annotations

import unicodedata


SUPPORTED_PLAYLIST_PREFIXES = (
    "estudo ",
    "ctb ",
    "conferencia ",
    "retiro ",
)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).casefold().strip()


def is_study_playlist(title: str) -> bool:
    normalized = normalize_text(title)
    return normalized.startswith(SUPPORTED_PLAYLIST_PREFIXES)


def infer_study_type(playlist_titles: list[str]) -> str:
    normalized = " ".join(normalize_text(title) for title in playlist_titles)

    if normalized.startswith("ctb ") or "treinamento biblico" in normalized:
        return "ctb"

    if "pfd" in normalized or "formacao de discipulos" in normalized:
        return "pfd"

    if (
        normalized.startswith(("conferencia ", "retiro "))
        or "palestra" in normalized
        or "conferencia" in normalized
    ):
        return "lecture_or_conference"

    if "ctb" in normalized:
        return "ctb"

    return "weekly"

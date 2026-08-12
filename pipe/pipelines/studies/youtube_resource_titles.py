from __future__ import annotations

from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

from pipe.pipelines.studies.youtube_source_to_bronze import youtube_get


YOUTUBE_BATCH_SIZE = 50


def youtube_resource_reference(url: str) -> tuple[str, str] | None:
    parts = urlsplit(str(url or ""))
    host = parts.netloc.casefold().removeprefix("www.")

    if host not in {"youtube.com", "m.youtube.com", "youtu.be"}:
        return None

    query = parse_qs(parts.query)
    video_id = next(iter(query.get("v", [])), "")

    if host == "youtu.be" and not video_id:
        video_id = parts.path.strip("/").split("/", 1)[0]

    if video_id:
        return "video", video_id

    playlist_id = next(iter(query.get("list", [])), "")

    if playlist_id:
        return "playlist", playlist_id

    return None


def fetch_youtube_titles(
    api_key: str,
    references: set[tuple[str, str]],
) -> dict[tuple[str, str], str]:
    titles = {}

    for resource_kind, endpoint in (("video", "videos"), ("playlist", "playlists")):
        resource_ids = sorted(
            resource_id
            for kind, resource_id in references
            if kind == resource_kind
        )

        for start in range(0, len(resource_ids), YOUTUBE_BATCH_SIZE):
            batch = resource_ids[start:start + YOUTUBE_BATCH_SIZE]
            payload = youtube_get(
                api_key,
                endpoint,
                {
                    "part": "snippet",
                    "id": ",".join(batch),
                    "maxResults": YOUTUBE_BATCH_SIZE,
                },
                f"reading titles for {len(batch)} WordPress YouTube resources",
            )

            for item in payload.get("items", []):
                title = str(item.get("snippet", {}).get("title") or "").strip()

                if title:
                    titles[(resource_kind, str(item.get("id") or ""))] = title

    return titles


def enrich_youtube_resource_titles(
    studies: list,
    api_key: str,
    title_fetcher=fetch_youtube_titles,
) -> tuple[list, int]:
    references = {
        reference
        for study in studies
        for resource in study.resources
        if resource.resource_type == "youtube"
        if (reference := youtube_resource_reference(resource.canonical_url))
    }

    if not references:
        return studies, 0

    titles = title_fetcher(api_key, references)
    enriched_count = 0
    enriched_studies = []

    for study in studies:
        resources = []

        for resource in study.resources:
            reference = youtube_resource_reference(resource.canonical_url)
            title = titles.get(reference) if reference else None

            if title and title != resource.label:
                resource = replace(resource, label=title)
                enriched_count += 1

            resources.append(resource)

        enriched_studies.append(replace(study, resources=tuple(resources)))

    return enriched_studies, enriched_count

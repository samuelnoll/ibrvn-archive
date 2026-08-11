from __future__ import annotations

import hashlib
import html as html_lib
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlunsplit

from lxml import html
from lxml.etree import ParserError


NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "excerpt": "http://wordpress.org/export/1.2/excerpt/",
    "wp": "http://wordpress.org/export/1.2/",
}

PUBLIC_ROOT_TYPES = {
    "ctb": "ctb",
    "palestras-conferencias": "lecture_or_conference",
    "materiais-de-estudo": "weekly",
}

MEDIA_EXTENSIONS = {
    "audio": {"aac", "flac", "m4a", "mp3", "oga", "ogg", "wav", "wma"},
    "pdf": {"pdf"},
    "word": {"doc", "docx", "odt", "rtf"},
    "presentation": {"odp", "ppt", "pptx"},
    "spreadsheet": {"csv", "ods", "xls", "xlsx"},
    "image": {"avif", "gif", "jpeg", "jpg", "png", "svg", "webp"},
    "video_file": {"avi", "m4v", "mkv", "mov", "mp4", "mpeg", "webm"},
    "archive": {"7z", "rar", "tar", "gz", "zip"},
}


@dataclass(frozen=True)
class WordpressItem:
    post_id: str
    post_type: str
    status: str
    title: str
    slug: str
    link: str
    post_parent: str
    post_date: str
    content: str
    attachment_url: str
    mime_type: str


@dataclass(frozen=True)
class ResourceCandidate:
    url: str
    label: str
    method: str
    element_tag: str
    position: int


@dataclass(frozen=True)
class ParsedResource:
    resource_key: str
    study_key: str
    resource_type: str
    label: str
    source_url: str
    canonical_url: str
    mime_type: str
    position: int


@dataclass(frozen=True)
class ParsedStudy:
    study_key: str
    source_item_id: str
    wordpress_post_id: str
    study_type: str
    title: str
    study_date: str
    source_url: str
    collection_slug: str
    resources: tuple[ParsedResource, ...]


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).casefold().strip()


def parse_wordpress_xml(xml_path: Path) -> list[WordpressItem]:
    root = ET.parse(xml_path).getroot()
    items = []

    for element in root.findall("./channel/item"):
        items.append(WordpressItem(
            post_id=element.findtext("wp:post_id", "", NS) or "",
            post_type=element.findtext("wp:post_type", "", NS) or "",
            status=element.findtext("wp:status", "", NS) or "",
            title=element.findtext("title", "") or "",
            slug=element.findtext("wp:post_name", "", NS) or "",
            link=element.findtext("link", "") or "",
            post_parent=element.findtext("wp:post_parent", "", NS) or "",
            post_date=element.findtext("wp:post_date", "", NS) or "",
            content=element.findtext("content:encoded", "", NS) or "",
            attachment_url=(
                element.findtext("wp:attachment_url", "", NS) or ""
            ),
            mime_type=element.findtext("wp:post_mime_type", "", NS) or "",
        ))

    return items


def canonicalize_url(value: str) -> str:
    value = html_lib.unescape((value or "").strip()).rstrip(".,;")

    if value.startswith("//"):
        value = f"https:{value}"

    parts = urlsplit(value)

    if not parts.netloc:
        return value

    host = parts.netloc.casefold()

    if host.startswith("www."):
        host = host[4:]

    if host in {"youtu.be", "youtube.com", "m.youtube.com"}:
        video_id = ""

        if host == "youtu.be":
            video_id = parts.path.strip("/").split("/", 1)[0]
        elif parts.path == "/watch":
            video_id = parse_qs(parts.query).get("v", [""])[0]
        elif parts.path.startswith(("/embed/", "/shorts/", "/live/")):
            path_parts = parts.path.strip("/").split("/", 1)
            video_id = path_parts[1] if len(path_parts) == 2 else ""

        if video_id:
            return f"https://youtube.com/watch?v={video_id}"

    scheme = "https" if host == "ibrvn.com.br" else parts.scheme.casefold()
    path = unquote(parts.path).rstrip("/") or "/"
    return urlunsplit((scheme, host, path, parts.query, ""))


def resource_extension(url: str) -> str:
    filename = unquote(urlsplit(url).path).rsplit("/", 1)[-1]
    return filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""


def clean_candidate_url(raw_url: str, base_url: str) -> str:
    value = html_lib.unescape((raw_url or "").strip())

    if not value or value.startswith(("#", "data:", "javascript:", "mailto:")):
        return ""

    return urljoin(base_url, value.rstrip(".,;"))


def element_label(element, fallback: str) -> str:
    label = " ".join(element.text_content().split())
    label = label or element.attrib.get("title", "")
    label = label or element.attrib.get("alt", "")
    return label.strip() or fallback.strip()


def is_supported_raw_url(url: str) -> bool:
    known_extensions = {
        extension
        for extensions in MEDIA_EXTENSIONS.values()
        for extension in extensions
    }
    host = urlsplit(canonicalize_url(url)).netloc.casefold()
    return (
        resource_extension(url) in known_extensions
        or host in {
            "docs.google.com",
            "drive.google.com",
            "m.youtube.com",
            "player.vimeo.com",
            "vimeo.com",
            "www.vimeo.com",
            "youtu.be",
            "youtube.com",
        }
    )


def parse_html_document(item: WordpressItem):
    try:
        return html.fragment_fromstring(
            item.content or "<div></div>",
            create_parent="div",
        )
    except (ParserError, ValueError):
        return None


def extract_resource_candidates(item: WordpressItem) -> list[ResourceCandidate]:
    document = parse_html_document(item)
    candidates = []
    position = 0

    if document is not None:
        attributes_by_tag = {
            "a": "href",
            "audio": "src",
            "embed": "src",
            "iframe": "src",
            "img": "src",
            "object": "data",
            "source": "src",
            "video": "src",
        }

        for element in document.iter():
            tag = element.tag.casefold() if isinstance(element.tag, str) else ""
            attribute = attributes_by_tag.get(tag)

            if not attribute or attribute not in element.attrib:
                continue

            url = clean_candidate_url(element.attrib.get(attribute, ""), item.link)

            if not url:
                continue

            position += 1
            candidates.append(ResourceCandidate(
                url=url,
                label=element_label(element, item.title),
                method=f"html_{tag}_{attribute}",
                element_tag=tag,
                position=position,
            ))

    known_urls = {canonicalize_url(candidate.url) for candidate in candidates}
    visible_text = document.text_content() if document is not None else item.content
    pattern = re.compile(r'''(?:https?:)?//[^\s"'<>\]\)]+''', re.I)

    for raw_url in pattern.findall(html_lib.unescape(visible_text)):
        url = clean_candidate_url(raw_url, item.link)
        canonical_url = canonicalize_url(url)

        if (
            not url
            or canonical_url in known_urls
            or not is_supported_raw_url(url)
        ):
            continue

        position += 1
        candidates.append(ResourceCandidate(
            url=url,
            label=item.title,
            method="raw_content_url",
            element_tag="text",
            position=position,
        ))
        known_urls.add(canonical_url)

    return candidates


def content_anchor_urls(item: WordpressItem) -> list[str]:
    document = parse_html_document(item)

    if document is None:
        return []

    return [
        url
        for element in document.xpath("//a[@href]")
        if (url := clean_candidate_url(element.attrib.get("href", ""), item.link))
    ]


def resolve_content_item(
    url: str,
    items_by_id: dict[str, WordpressItem],
    items_by_link: dict[str, WordpressItem],
) -> WordpressItem | None:
    query = parse_qs(urlsplit(url).query)
    post_id = next(iter(query.get("page_id", []) or query.get("p", [])), "")

    if post_id:
        return items_by_id.get(post_id)

    return items_by_link.get(canonicalize_url(url))


def is_descendant_of(
    item: WordpressItem,
    root_id: str,
    items_by_id: dict[str, WordpressItem],
) -> bool:
    parent_id = item.post_parent
    visited = set()

    while parent_id and parent_id != "0" and parent_id not in visited:
        if parent_id == root_id:
            return True

        visited.add(parent_id)
        parent = items_by_id.get(parent_id)

        if not parent:
            return False

        parent_id = parent.post_parent

    return False


def classify_resource(
    url: str,
    element_tag: str,
    mime_type: str,
    items_by_link: dict[str, WordpressItem],
) -> str:
    canonical_url = canonicalize_url(url)
    host = urlsplit(canonical_url).netloc.casefold()
    extension = resource_extension(canonical_url)
    normalized_mime = (mime_type or "").casefold()

    if host in {"youtube.com", "youtu.be", "m.youtube.com"}:
        return "youtube"

    if host in {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}:
        return "video_platform"

    for resource_type, extensions in MEDIA_EXTENSIONS.items():
        if extension in extensions:
            return resource_type

    if normalized_mime.startswith("audio/"):
        return "audio"

    if normalized_mime == "application/pdf":
        return "pdf"

    if normalized_mime.startswith("image/") or element_tag == "img":
        return "image"

    if normalized_mime.startswith("video/"):
        return "video_file"

    if "docs.google.com" in host or "drive.google.com" in host:
        return "document"

    if canonical_url in items_by_link:
        return "internal_link"

    if host.endswith("ibrvn.com.br"):
        return "internal_link"

    return "external_link"


def stable_key(*parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def resource_display_name(
    url: str,
    resource_type: str,
    fallback: str,
) -> str:
    parts = urlsplit(url)
    filename = unquote(parts.path).rstrip("/").rsplit("/", 1)[-1]

    if filename and filename not in {"watch", "playlist"}:
        return filename

    query = parse_qs(parts.query)

    if resource_type == "youtube":
        youtube_id = next(iter(query.get("v", []) or query.get("list", [])), "")

        if youtube_id:
            return youtube_id

    if parts.netloc:
        return parts.netloc.casefold().removeprefix("www.")

    return fallback.strip() or url


def build_resources(
    item: WordpressItem,
    study_key: str,
    items_by_link: dict[str, WordpressItem],
    items_by_attachment_url: dict[str, WordpressItem],
) -> tuple[ParsedResource, ...]:
    deduplicated: dict[str, ParsedResource] = {}

    for candidate in extract_resource_candidates(item):
        original_canonical = canonicalize_url(candidate.url)
        attachment = items_by_link.get(original_canonical)
        resolved_url = candidate.url

        if attachment and attachment.post_type == "attachment":
            resolved_url = attachment.attachment_url or candidate.url

        resolved_attachment = items_by_attachment_url.get(
            canonicalize_url(resolved_url)
        )
        attachment = resolved_attachment or attachment
        mime_type = attachment.mime_type if attachment else ""
        canonical_url = canonicalize_url(resolved_url)
        resource_type = classify_resource(
            resolved_url,
            candidate.element_tag,
            mime_type,
            items_by_link,
        )

        if resource_type == "image":
            continue

        resource = ParsedResource(
            resource_key=stable_key(study_key, canonical_url),
            study_key=study_key,
            resource_type=resource_type,
            label=resource_display_name(
                resolved_url,
                resource_type,
                candidate.label,
            ),
            source_url=resolved_url,
            canonical_url=canonical_url,
            mime_type=mime_type,
            position=candidate.position,
        )

        current = deduplicated.get(canonical_url)

        if current is None or candidate.method != "raw_content_url":
            deduplicated[canonical_url] = resource

    return tuple(sorted(deduplicated.values(), key=lambda value: value.position))


def normalize_date(value: str) -> str:
    try:
        return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S").date().isoformat()
    except (TypeError, ValueError):
        return ""


def infer_study_date(item: WordpressItem) -> str:
    title_year = re.search(r"\b(19\d{2}|20\d{2})\b", item.title)

    if title_year:
        return f"{title_year.group(1)}-01-01"

    return normalize_date(item.post_date)


def pfd_number(url: str) -> int | None:
    filename = unquote(urlsplit(url).path).rsplit("/", 1)[-1]
    match = re.search(r"\bPFD[-_ ]*(?:Estudo[-_ ]*)?(\d{1,3})\b", filename, re.I)
    return int(match.group(1)) if match else None


def resource_upload_year(url: str) -> str:
    match = re.search(r"/uploads/(19\d{2}|20\d{2})/", url)
    return f"{match.group(1)}-01-01" if match else ""


def discover_public_studies(items: list[WordpressItem]) -> list[ParsedStudy]:
    items_by_id = {item.post_id: item for item in items}
    items_by_link = {
        canonicalize_url(item.link): item
        for item in items
        if item.link
    }
    items_by_attachment_url = {
        canonicalize_url(item.attachment_url): item
        for item in items
        if item.attachment_url
    }
    roots = {
        item.slug: item
        for item in items
        if item.post_type == "page"
        and item.status == "publish"
        and item.slug in PUBLIC_ROOT_TYPES
    }
    missing_roots = sorted(set(PUBLIC_ROOT_TYPES) - set(roots))

    if missing_roots:
        raise ValueError(
            "Missing published WordPress study roots: " + ", ".join(missing_roots)
        )

    weekly_root = next((
        item
        for item in items
        if item.post_type == "page" and item.slug == "estudos-semanais"
    ), None)
    studies: dict[str, ParsedStudy] = {}

    for root_slug, root in roots.items():
        for url in content_anchor_urls(root):
            item = resolve_content_item(url, items_by_id, items_by_link)

            if (
                not item
                or item.post_id == root.post_id
                or item.post_type != "page"
                or item.status != "publish"
            ):
                continue

            if root_slug == "materiais-de-estudo" and not (
                weekly_root
                and is_descendant_of(item, weekly_root.post_id, items_by_id)
            ):
                continue

            study_key = f"wordpress:{item.post_id}"
            studies.setdefault(study_key, ParsedStudy(
                study_key=study_key,
                source_item_id=item.post_id,
                wordpress_post_id=item.post_id,
                study_type=PUBLIC_ROOT_TYPES[root_slug],
                title=item.title.strip() or item.slug,
                study_date=infer_study_date(item),
                source_url=item.link,
                collection_slug=item.slug,
                resources=build_resources(
                    item,
                    study_key,
                    items_by_link,
                    items_by_attachment_url,
                ),
            ))

    pfd_root = roots["materiais-de-estudo"]

    for candidate in extract_resource_candidates(pfd_root):
        canonical_url = canonicalize_url(candidate.url)

        if resource_extension(canonical_url) != "pdf":
            continue

        number = pfd_number(canonical_url)

        if number is None:
            continue

        study_key = f"wordpress:pfd:{number}"
        resource = ParsedResource(
            resource_key=stable_key(study_key, canonical_url),
            study_key=study_key,
            resource_type="pdf",
            label=resource_display_name(
                candidate.url,
                "pdf",
                candidate.label,
            ),
            source_url=candidate.url,
            canonical_url=canonical_url,
            mime_type="application/pdf",
            position=candidate.position,
        )
        existing = studies.get(study_key)

        if existing:
            resources = {item.canonical_url: item for item in existing.resources}
            resources.setdefault(canonical_url, resource)
            studies[study_key] = ParsedStudy(
                **{
                    **existing.__dict__,
                    "resources": tuple(resources.values()),
                }
            )
            continue

        label = candidate.label.strip() or f"Estudo {number}"
        studies[study_key] = ParsedStudy(
            study_key=study_key,
            source_item_id=f"{pfd_root.post_id}:pfd:{number}",
            wordpress_post_id=pfd_root.post_id,
            study_type="pfd",
            title=f"Estudo {number} - {label}",
            study_date=resource_upload_year(canonical_url) or normalize_date(
                pfd_root.post_date
            ),
            source_url=pfd_root.link,
            collection_slug=f"pfd-estudo-{number}",
            resources=(resource,),
        )

    return sorted(
        studies.values(),
        key=lambda study: (study.study_type, study.study_date, study.title),
    )


def parse_public_studies(xml_path: Path) -> list[ParsedStudy]:
    return discover_public_studies(parse_wordpress_xml(xml_path))

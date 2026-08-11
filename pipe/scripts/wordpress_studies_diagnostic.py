from __future__ import annotations

import argparse
import csv
import html as html_lib
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, fields
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
    "materiais-de-estudo": "mixed_pfd_weekly",
}

MEDIA_EXTENSIONS = {
    "archive": {"7z", "rar", "tar", "tgz", "zip"},
    "audio": {"mp3", "m4a", "ogg", "wav", "wma"},
    "document": {"doc", "docx", "odt", "rtf"},
    "image": {"gif", "jpeg", "jpg", "png", "svg", "webp"},
    "pdf": {"pdf"},
    "slides": {"key", "odp", "ppt", "pptx"},
    "spreadsheet": {"csv", "ods", "xls", "xlsx"},
    "video_file": {"avi", "mkv", "mov", "mp4", "webm"},
}

PRIMARY_RESOURCE_TYPES = {
    "archive",
    "audio",
    "document",
    "external_link",
    "pdf",
    "slides",
    "spreadsheet",
    "video_file",
    "video_platform",
    "youtube",
}

@dataclass
class TaxonomyTerm:
    domain: str
    name: str
    slug: str


@dataclass
class WordpressItem:
    post_id: str
    post_parent: str
    post_type: str
    status: str
    title: str
    slug: str
    link: str
    post_date: str
    content: str
    excerpt: str
    attachment_url: str
    mime_type: str
    terms: list[TaxonomyTerm] = field(default_factory=list)
    metadata: dict[str, list[str]] = field(default_factory=dict)

    @property
    def category_slugs(self) -> set[str]:
        return {
            term.slug
            for term in self.terms
            if term.domain == "category"
        }


@dataclass
class Resource:
    owner_id: str
    owner_title: str
    owner_kind: str
    study_type: str
    collection_slug: str
    resource_type: str
    label: str
    original_url: str
    resolved_url: str
    canonical_url: str
    extraction_method: str
    attachment_id: str
    attachment_parent: str
    mime_type: str
    position: int


@dataclass
class ContentUnit:
    post_id: str
    post_type: str
    status: str
    title: str
    slug: str
    link: str
    post_parent: str
    parent_title: str
    node_kind: str
    study_type: str
    collection_slug: str
    discovery_reason: str
    resource_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class ManualAction:
    priority: str
    action: str
    wordpress_id: str
    item_type: str
    title: str
    current_value: str
    recommended_value: str
    reason: str


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", normalized).casefold().strip()


def parse_wordpress_xml(xml_path: Path) -> list[WordpressItem]:
    root = ET.parse(xml_path).getroot()
    items = []

    for element in root.findall("./channel/item"):
        terms = []

        for category in element.findall("category"):
            terms.append(TaxonomyTerm(
                domain=category.attrib.get("domain", ""),
                name=(category.text or "").strip(),
                slug=category.attrib.get("nicename", "").strip(),
            ))

        metadata: dict[str, list[str]] = defaultdict(list)

        for postmeta in element.findall("wp:postmeta", NS):
            key = postmeta.findtext("wp:meta_key", "", NS)
            value = postmeta.findtext("wp:meta_value", "", NS)

            if key:
                metadata[key].append(value)

        items.append(WordpressItem(
            post_id=element.findtext("wp:post_id", "", NS),
            post_parent=element.findtext("wp:post_parent", "0", NS),
            post_type=element.findtext("wp:post_type", "", NS),
            status=element.findtext("wp:status", "", NS),
            title=element.findtext("title", "") or "",
            slug=element.findtext("wp:post_name", "", NS) or "",
            link=element.findtext("link", "") or "",
            post_date=element.findtext("wp:post_date", "", NS) or "",
            content=element.findtext("content:encoded", "", NS) or "",
            excerpt=element.findtext("excerpt:encoded", "", NS) or "",
            attachment_url=(
                element.findtext("wp:attachment_url", "", NS) or ""
            ),
            mime_type=element.findtext("wp:post_mime_type", "", NS) or "",
            terms=terms,
            metadata=dict(metadata),
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
            video_id = parts.path.strip("/").split("/", 1)[1]

        if video_id:
            return f"https://youtube.com/watch?v={video_id}"

    scheme = "https" if host == "ibrvn.com.br" else parts.scheme.casefold()
    path = unquote(parts.path).rstrip("/") or "/"
    query = parts.query

    return urlunsplit((scheme, host, path, query, ""))


def resource_extension(url: str) -> str:
    name = unquote(urlsplit(url).path).rsplit("/", 1)[-1]

    if "." not in name:
        return ""

    return name.rsplit(".", 1)[-1].casefold()


def classify_resource(
    url: str,
    element_tag: str,
    mime_type: str,
    content_links: dict[str, WordpressItem],
) -> str:
    canonical_url = canonicalize_url(url)
    host = urlsplit(canonical_url).netloc.casefold()
    extension = resource_extension(canonical_url)
    mime_type = (mime_type or "").casefold()

    if host in {"youtube.com", "youtu.be", "m.youtube.com"}:
        return "youtube"

    if host in {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}:
        return "video_platform"

    for resource_type, extensions in MEDIA_EXTENSIONS.items():
        if extension in extensions:
            return resource_type

    if mime_type.startswith("audio/"):
        return "audio"

    if mime_type == "application/pdf":
        return "pdf"

    if mime_type.startswith("image/") or element_tag == "img":
        return "image"

    if mime_type.startswith("video/"):
        return "video_file"

    if "docs.google.com" in host or "drive.google.com" in host:
        return "document"

    if canonical_url in content_links:
        return "internal_page"

    if host.endswith("ibrvn.com.br"):
        return "internal_link"

    return "external_link"


def clean_candidate_url(raw_url: str, base_url: str) -> str:
    value = html_lib.unescape((raw_url or "").strip())

    if not value or value.startswith(("#", "data:", "javascript:", "mailto:")):
        return ""

    value = value.rstrip(".,;")
    return urljoin(base_url, value)


def is_supported_raw_url(url: str) -> bool:
    extension = resource_extension(url)
    known_extensions = {
        value
        for extensions in MEDIA_EXTENSIONS.values()
        for value in extensions
    }
    host = urlsplit(canonicalize_url(url)).netloc.casefold()

    return (
        extension in known_extensions
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


def element_label(element, fallback: str) -> str:
    label = " ".join(element.text_content().split())
    label = label or element.attrib.get("title", "")
    label = label or element.attrib.get("alt", "")
    return label.strip() or fallback.strip()


def extract_resource_candidates(
    owner: WordpressItem,
) -> list[tuple[str, str, str, str, int]]:
    candidates = []
    position = 0

    try:
        document = html.fragment_fromstring(
            owner.content or "<div></div>",
            create_parent="div",
        )
    except (ParserError, ValueError):
        document = None

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
            tag = element.tag if isinstance(element.tag, str) else ""
            attribute = attributes_by_tag.get(tag.casefold())

            if not attribute or attribute not in element.attrib:
                continue

            position += 1
            raw_url = clean_candidate_url(
                element.attrib.get(attribute, ""),
                owner.link,
            )

            if not raw_url:
                continue

            candidates.append((
                raw_url,
                element_label(element, owner.title),
                f"html_{tag}_{attribute}",
                tag,
                position,
            ))

    known_urls = {
        canonicalize_url(candidate[0])
        for candidate in candidates
    }
    url_pattern = re.compile(r'''(?:https?:)?//[^\s"'<>\]\)]+''', re.I)

    # Scan visible/shortcode text only. Scanning the raw HTML would truncate
    # legacy unescaped URLs that contain spaces inside href attributes.
    text_content = (
        document.text_content()
        if document is not None
        else owner.content
    )

    for raw_match in url_pattern.findall(html_lib.unescape(text_content)):
        raw_url = clean_candidate_url(raw_match, owner.link)
        canonical_url = canonicalize_url(raw_url)

        if (
            not raw_url
            or canonical_url in known_urls
            or not is_supported_raw_url(raw_url)
        ):
            continue

        position += 1
        candidates.append((
            raw_url,
            owner.title,
            "raw_content_url",
            "text",
            position,
        ))
        known_urls.add(canonical_url)

    return candidates


def build_resource(
    owner: WordpressItem,
    unit: ContentUnit,
    candidate: tuple[str, str, str, str, int],
    items_by_link: dict[str, WordpressItem],
    items_by_attachment_url: dict[str, WordpressItem],
) -> Resource:
    raw_url, label, method, element_tag, position = candidate
    canonical_original = canonicalize_url(raw_url)
    attachment = items_by_link.get(canonical_original)
    resolved_url = raw_url

    if attachment and attachment.post_type == "attachment":
        resolved_url = attachment.attachment_url or raw_url

    resolved_attachment = items_by_attachment_url.get(
        canonicalize_url(resolved_url)
    )
    attachment = resolved_attachment or attachment
    mime_type = attachment.mime_type if attachment else ""
    attachment_id = attachment.post_id if attachment else ""
    attachment_parent = attachment.post_parent if attachment else ""

    return Resource(
        owner_id=owner.post_id,
        owner_title=owner.title,
        owner_kind=unit.node_kind,
        study_type=unit.study_type,
        collection_slug=unit.collection_slug,
        resource_type=classify_resource(
            resolved_url,
            element_tag,
            mime_type,
            items_by_link,
        ),
        label=label,
        original_url=raw_url,
        resolved_url=resolved_url,
        canonical_url=canonicalize_url(resolved_url),
        extraction_method=method,
        attachment_id=attachment_id,
        attachment_parent=attachment_parent,
        mime_type=mime_type,
        position=position,
    )


def find_root_items(items: list[WordpressItem]) -> dict[str, WordpressItem]:
    roots = {}

    for item in items:
        if (
            item.post_type == "page"
            and item.status == "publish"
            and item.slug in PUBLIC_ROOT_TYPES
        ):
            roots[item.slug] = item

    return roots


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


def content_anchor_urls(item: WordpressItem) -> list[str]:
    try:
        document = html.fragment_fromstring(
            item.content or "<div></div>",
            create_parent="div",
        )
    except (ParserError, ValueError):
        return []

    return [
        clean_candidate_url(element.attrib.get("href", ""), item.link)
        for element in document.xpath("//a[@href]")
        if clean_candidate_url(element.attrib.get("href", ""), item.link)
    ]


def resolve_content_item(
    url: str,
    items_by_id: dict[str, WordpressItem],
    items_by_link: dict[str, WordpressItem],
) -> WordpressItem | None:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    post_id = next(iter(
        query.get("page_id", []) or query.get("p", [])
    ), "")

    if post_id and post_id in items_by_id:
        return items_by_id[post_id]

    return items_by_link.get(canonicalize_url(url))


def is_public_study_child(
    item: WordpressItem,
    root_slug: str,
    items_by_id: dict[str, WordpressItem],
) -> bool:
    if item.status != "publish" or item.post_type != "page":
        return False

    if root_slug != "materiais-de-estudo":
        return True

    weekly_root = next(
        (
            candidate
            for candidate in items_by_id.values()
            if candidate.slug == "estudos-semanais"
            and candidate.post_type == "page"
        ),
        None,
    )

    return bool(
        weekly_root
        and is_descendant_of(item, weekly_root.post_id, items_by_id)
    )


def discover_content_units(
    items: list[WordpressItem],
) -> list[ContentUnit]:
    items_by_id = {item.post_id: item for item in items}
    items_by_link = {
        canonicalize_url(item.link): item
        for item in items
        if item.link
    }
    roots = find_root_items(items)
    units = []

    for root_slug, root_item in roots.items():
        units.append(ContentUnit(
            post_id=root_item.post_id,
            post_type=root_item.post_type,
            status=root_item.status,
            title=root_item.title,
            slug=root_item.slug,
            link=root_item.link,
            post_parent=root_item.post_parent,
            parent_title="",
            node_kind="study_hub",
            study_type=PUBLIC_ROOT_TYPES[root_slug],
            collection_slug=root_item.slug,
            discovery_reason="public_navigation_root",
        ))

        child_study_type = (
            "weekly"
            if root_slug == "materiais-de-estudo"
            else PUBLIC_ROOT_TYPES[root_slug]
        )

        for url in content_anchor_urls(root_item):
            item = resolve_content_item(url, items_by_id, items_by_link)

            if (
                not item
                or item.post_id == root_item.post_id
                or not is_public_study_child(item, root_slug, items_by_id)
            ):
                continue

            parent = items_by_id.get(item.post_parent)
            units.append(ContentUnit(
                post_id=item.post_id,
                post_type=item.post_type,
                status=item.status,
                title=item.title,
                slug=item.slug,
                link=item.link,
                post_parent=item.post_parent,
                parent_title=parent.title if parent else "",
                node_kind="study_collection",
                study_type=child_study_type,
                collection_slug=item.slug,
                discovery_reason=f"linked_from_public_root_{root_slug}",
            ))

    units_by_id = {}

    for unit in units:
        units_by_id.setdefault(unit.post_id, unit)

    return list(units_by_id.values())


def extract_resources(
    units: list[ContentUnit],
    items: list[WordpressItem],
) -> list[Resource]:
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
    resources = []

    for unit in units:
        owner = items_by_id[unit.post_id]
        candidates = extract_resource_candidates(owner)
        owner_resources = [
            build_resource(
                owner,
                unit,
                candidate,
                items_by_link,
                items_by_attachment_url,
            )
            for candidate in candidates
        ]
        deduplicated = {}

        for resource in owner_resources:
            key = resource.canonical_url
            current = deduplicated.get(key)

            if current is None:
                deduplicated[key] = resource
                continue

            if current.extraction_method == "raw_content_url":
                deduplicated[key] = resource

        resources.extend(deduplicated.values())
        unit.resource_counts = dict(Counter(
            resource.resource_type
            for resource in deduplicated.values()
        ))

    return resources


def metadata_action(unit: ContentUnit) -> ManualAction:
    study_type = (
        "<weekly or another approved type>"
        if unit.study_type == "review_required"
        else unit.study_type
    )
    values = (
        f"archive_content_type={unit.node_kind}; "
        f"archive_study_type={study_type}"
    )

    if unit.collection_slug and unit.node_kind == "study_session":
        values += f"; archive_collection_slug={unit.collection_slug}"

    return ManualAction(
        priority="recommended",
        action="add_archive_metadata",
        wordpress_id=unit.post_id,
        item_type=unit.post_type,
        title=unit.title,
        current_value="nao encontrado no XML",
        recommended_value=values,
        reason=(
            "Campos personalizados nativos tornam a classificacao "
            "deterministica sem depender de titulos, HTML ou categorias."
        ),
    )


def build_manual_actions(
    units: list[ContentUnit],
) -> list[ManualAction]:
    actions = [metadata_action(unit) for unit in units]

    for unit in units:
        if (
            unit.node_kind == "study_collection"
            and unit.study_type == "lecture_or_conference"
        ):
            actions.append(ManualAction(
                priority="high",
                action="classify_lecture_or_conference",
                wordpress_id=unit.post_id,
                item_type=unit.post_type,
                title=unit.title,
                current_value="hierarquia conjunta Palestras & Conferencias",
                recommended_value=(
                    "archive_study_type=lecture OR "
                    "archive_study_type=conference"
                ),
                reason=(
                    "O XML nao distingue palestra de conferencia."
                ),
            ))

    return sorted(
        actions,
        key=lambda action: (
            {"high": 0, "recommended": 1, "optional": 2}.get(
                action.priority,
                9,
            ),
            action.action,
            int(action.wordpress_id or 0),
        ),
    )


def find_relevant_orphan_attachments(
    items: list[WordpressItem],
    resources: list[Resource],
) -> list[dict[str, str]]:
    referenced_urls = {
        resource.canonical_url
        for resource in resources
    }
    keywords = (
        "atributo",
        "catecismo",
        "ctb",
        "doutrina",
        "estudo",
        "exercicio",
        "pfd",
        "puritano",
    )
    rows = []

    for item in items:
        if item.post_type != "attachment" or item.post_parent != "0":
            continue

        haystack = normalize_text(f"{item.title} {item.attachment_url}")

        if not any(keyword in haystack for keyword in keywords):
            continue

        canonical_url = canonicalize_url(item.attachment_url)
        rows.append({
            "attachment_id": item.post_id,
            "title": item.title,
            "attachment_url": item.attachment_url,
            "mime_type": item.mime_type,
            "referenced_by_selected_content": str(
                canonical_url in referenced_urls
            ).lower(),
            "diagnosis": (
                "pai ausente, mas a URL e referenciada"
                if canonical_url in referenced_urls
                else "pai ausente e a URL exata nao foi referenciada"
            ),
        })

    return rows


def find_possible_resource_aliases(
    resources: list[Resource],
) -> list[dict[str, str]]:
    groups: dict[tuple[str, str], list[Resource]] = defaultdict(list)

    for resource in resources:
        if resource.resource_type not in PRIMARY_RESOURCE_TYPES:
            continue

        filename = unquote(
            urlsplit(resource.canonical_url).path
        ).rsplit("/", 1)[-1]
        fingerprint = normalize_text(filename)

        if not fingerprint:
            continue

        groups[(resource.resource_type, fingerprint)].append(resource)

    rows = []

    for (resource_type, fingerprint), matches in sorted(groups.items()):
        urls = sorted({resource.canonical_url for resource in matches})

        if len(urls) < 2:
            continue

        rows.append({
            "resource_type": resource_type,
            "filename_fingerprint": fingerprint,
            "distinct_urls": str(len(urls)),
            "owner_ids": " | ".join(sorted({
                resource.owner_id for resource in matches
            }, key=int)),
            "owner_titles": " | ".join(sorted({
                resource.owner_title for resource in matches
            })),
            "urls": " | ".join(urls),
            "diagnosis": (
                "mesmo nome normalizado em URLs diferentes; comparar hashes "
                "apos o download antes de unificar"
            ),
        })

    return rows


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def markdown_escape(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown_report(
    xml_path: Path,
    items: list[WordpressItem],
    units: list[ContentUnit],
    resources: list[Resource],
    actions: list[ManualAction],
    resource_aliases: list[dict[str, str]],
) -> str:
    type_counts = Counter(item.post_type for item in items)
    status_counts = Counter(item.status for item in items)
    unit_counts = Counter(unit.node_kind for unit in units)
    resource_counts = Counter(
        resource.resource_type
        for resource in resources
    )
    primary_urls = {
        resource.canonical_url
        for resource in resources
        if resource.resource_type in PRIMARY_RESOURCE_TYPES
    }
    high_actions = [action for action in actions if action.priority == "high"]
    ctb_parent_actions = [
        action
        for action in actions
        if action.action == "set_page_parent"
    ]
    conference_actions = [
        action
        for action in actions
        if action.action == "classify_lecture_or_conference"
    ]
    weekly_units = [
        unit
        for unit in units
        if unit.node_kind == "study_session" and unit.study_type == "weekly"
    ]
    mapped_weekly = [unit for unit in weekly_units if unit.collection_slug]
    attachment_items = [
        item for item in items if item.post_type == "attachment"
    ]
    orphan_count = sum(
        item.post_parent == "0" for item in attachment_items
    )
    category_usage = Counter(
        term.slug
        for item in items
        if item.status == "publish"
        for term in item.terms
        if term.domain == "category"
    )
    attachment_extensions = Counter(
        resource_extension(item.attachment_url) or "no_extension"
        for item in attachment_items
    )
    pfd_pdfs = [
        resource
        for resource in resources
        if resource.owner_id == "5091"
        and resource.resource_type == "pdf"
        and "pfd" in normalize_text(resource.resolved_url)
    ]
    pfd_numbers = set()

    for resource in pfd_pdfs:
        match = re.search(
            r"pfd[-_ ]*estudo[-_ ]*(\d+)|pfd[-_ ]*(\d+)",
            normalize_text(unquote(resource.resolved_url)),
        )

        if match:
            pfd_numbers.add(int(next(
                group for group in match.groups() if group
            )))

    if pfd_numbers:
        pfd_summary = (
            f"A pagina 5091 referencia **{len(pfd_pdfs)} PDFs do PFD**, "
            f"cobrindo os numeros **{min(pfd_numbers)} a {max(pfd_numbers)}**. "
            "O total excede a quantidade de estudos porque o estudo 1 aparece "
            "em duas URLs."
        )
    else:
        pfd_summary = "Nenhum PDF numerado do PFD foi identificado."

    lines = [
        "# Diagnostico de estudos do WordPress",
        "",
        f"- Fonte: `{xml_path}`",
        f"- Itens WXR: **{len(items)}**",
        f"- Tipos de item: `{dict(type_counts)}`",
        f"- Status: `{dict(status_counts)}`",
        "- Escopo: leitura do XML; nenhum banco, pipeline ou DAG foi executado.",
        "- Disponibilidade das URLs nao foi testada pela rede.",
        "",
        "## Resultado executivo",
        "",
        (
            f"Foram identificadas **{len(units)} unidades de conteudo** "
            f"(`{dict(unit_counts)}`) e **{len(primary_urls)} URLs canonicas** "
            "de recursos primarios."
        ),
        "",
        (
            f"O relatorio gerou **{len(high_actions)} acoes de alta prioridade** "
            "e manteve recomendacoes de metadados separadas para que a futura "
            "ingestao de estudos nao dependa de titulos ou HTML."
        ),
        "",
        "## Alteracoes de alta prioridade no WordPress",
        "",
        "### Corrigir hierarquia CTB",
        "",
    ]

    if ctb_parent_actions:
        for action in ctb_parent_actions:
            lines.append(
                f"- ID `{action.wordpress_id}` - **{action.title}**: "
                f"{action.recommended_value}."
            )
    else:
        lines.append("- Nenhuma pagina CTB fora da hierarquia foi encontrada.")

    lines.extend([
        "",
        "### Classificar palestra ou conferencia",
        "",
        (
            "A pagina-raiz combina os dois tipos. Preencher "
            "`archive_study_type=lecture` ou "
            "`archive_study_type=conference` nestas paginas:"
        ),
        "",
    ])

    for action in conference_actions:
        lines.append(f"- ID `{action.wordpress_id}` - {action.title}")

    lines.extend([
        "",
        "### Resolver candidatos fora da hierarquia",
        "",
    ])

    review_actions = [
        action
        for action in actions
        if action.action == "review_study_candidate"
    ]

    for action in review_actions:
        lines.append(
            f"- ID `{action.wordpress_id}` - **{action.title}**: "
            f"{action.recommended_value}."
        )

    lines.extend([
        "",
        "### Limpar ambiguidades do PFD",
        "",
        pfd_summary,
        "",
    ])

    pfd_actions = [
        action
        for action in actions
        if "pfd" in action.action
        or "pfd" in normalize_text(action.title)
    ]

    for action in pfd_actions:
        lines.append(
            f"- ID `{action.wordpress_id}` - **{action.title}**: "
            f"{action.recommended_value}."
        )

    lines.extend([
        "",
        "## Metadados recomendados",
        "",
        (
            "Usar campos personalizados nativos, com nomes sem `_` inicial, "
            "para que sejam exportados no WXR:"
        ),
        "",
        "- `archive_content_type`: `study_hub`, `study_collection` ou `study_session`.",
        "- `archive_study_type`: `ctb`, `weekly`, `lecture`, `conference` ou `pfd`.",
        "- `archive_collection_slug`: colecao de um post/aula quando aplicavel.",
        "",
        (
            f"Os **{len(weekly_units)} posts** de Estudos Semanais foram "
            f"mapeados para colecoes; **{len(mapped_weekly)}** tiveram o "
            "mapeamento inferido com seguranca pelo titulo. Os valores exatos "
            "estao em `manual_actions.csv`."
        ),
        "",
        "## Taxonomias e hierarquia observadas",
        "",
        (
            f"- Categoria `estudos-semanais`: {category_usage['estudos-semanais']} "
            "itens publicados."
        ),
        f"- Categoria `ctb`: {category_usage['ctb']} itens publicados.",
        f"- Categoria `palestras`: {category_usage['palestras']} itens publicados.",
        (
            "- CTB e Palestras/Conferencias estao organizados principalmente "
            "como paginas-filhas, nao como posts categorizados."
        ),
        (
            "- Nao e recomendado instalar categorizacao de paginas apenas para "
            "a extracao; hierarquia mais campos personalizados e suficiente."
        ),
        "",
        "## Recursos encontrados",
        "",
        f"- Contagens por tipo, antes da deduplicacao global: `{dict(resource_counts)}`",
        f"- URLs canonicas de recursos primarios: **{len(primary_urls)}**",
        (
            f"- Grupos com mesmo nome de arquivo em URLs diferentes: "
            f"**{len(resource_aliases)}**. Eles exigem comparacao por hash, nao "
            "fusao automatica."
        ),
        (
            "- Extensoes dos anexos no WXR: "
            f"`{dict(attachment_extensions.most_common())}`."
        ),
        (
            "- Nao ha anexos `.doc` ou `.docx`; existe um `.ppt`. Links para "
            "documentos externos ainda podem existir sem extensao reconhecivel."
        ),
        "- O XML contem metadados e URLs, mas nao contem os arquivos binarios.",
        "- Imagens foram inventariadas separadamente e nao sao tratadas automaticamente como material de estudo.",
        "",
        "## Anexos orfaos",
        "",
        (
            f"Existem **{len(attachment_items)} anexos** no XML; "
            f"**{orphan_count}** tem `post_parent=0`. Foram separados "
            f"**{len(orphan_attachments)}** anexos orfaos com nomes relacionados "
            "a estudos."
        ),
        "",
        (
            "Nao e necessario corrigir o pai de todo anexo. Priorize garantir "
            "que o arquivo esteja linkado na pagina canonica. O CSV de orfaos "
            "indica quais URLs nem sequer foram referenciadas exatamente pelos "
            "conteudos selecionados."
        ),
        "",
        "## Inventario de unidades",
        "",
        "| ID | Tipo | Classificacao | Colecao | Recursos | Titulo |",
        "|---:|---|---|---|---|---|",
    ])

    for unit in sorted(units, key=lambda value: int(value.post_id)):
        resource_summary = ", ".join(
            f"{key}={value}"
            for key, value in sorted(unit.resource_counts.items())
        ) or "none"
        lines.append(
            f"| {unit.post_id} | {unit.node_kind} | {unit.study_type} | "
            f"{markdown_escape(unit.collection_slug)} | "
            f"{markdown_escape(resource_summary)} | "
            f"{markdown_escape(unit.title)} |"
        )

    lines.extend([
        "",
        "## Arquivos auxiliares",
        "",
        "- `content_inventory.csv`: classificacao e contagens por pagina/post.",
        "- `resource_inventory.csv`: cada recurso, sua origem e resolucao de anexo.",
        "- `manual_actions.csv`: checklist exato para alteracoes no WordPress.",
        "- `orphan_attachments.csv`: anexos relacionados a estudos sem pagina-pai.",
        "- `possible_resource_aliases.csv`: URLs diferentes com o mesmo nome de arquivo.",
        "- `diagnostic.json`: resumo para validacao automatizada.",
        "",
    ])

    return "\n".join(lines)


def render_public_navigation_report(
    xml_path: Path,
    items: list[WordpressItem],
    units: list[ContentUnit],
    resources: list[Resource],
    actions: list[ManualAction],
    resource_aliases: list[dict[str, str]],
) -> str:
    unit_counts = Counter(unit.node_kind for unit in units)
    resource_counts = Counter(
        resource.resource_type for resource in resources
    )
    primary_urls = {
        resource.canonical_url
        for resource in resources
        if resource.resource_type in PRIMARY_RESOURCE_TYPES
    }
    roots = [unit for unit in units if unit.node_kind == "study_hub"]
    published_pages = [
        item
        for item in items
        if item.status == "publish" and item.post_type == "page"
    ]
    conference_actions = [
        action
        for action in actions
        if action.action == "classify_lecture_or_conference"
    ]
    ctb_without_parent = [
        unit
        for unit in units
        if unit.study_type == "ctb"
        and unit.node_kind == "study_collection"
        and unit.post_parent == "0"
    ]
    pfd_pdfs = [
        resource
        for resource in resources
        if resource.owner_id == "5091"
        and resource.resource_type == "pdf"
        and "pfd" in normalize_text(resource.resolved_url)
    ]
    pfd_numbers = set()

    for resource in pfd_pdfs:
        match = re.search(
            r"pfd[-_ ]*estudo[-_ ]*(\d+)|pfd[-_ ]*(\d+)",
            normalize_text(unquote(resource.resolved_url)),
        )

        if match:
            pfd_numbers.add(int(next(
                group for group in match.groups() if group
            )))

    lines = [
        "# Diagnostico publico de estudos do WordPress",
        "",
        f"- Fonte: `{xml_path}`",
        "- Criterio: somente paginas com `status=publish` diretamente linkadas no conteudo das tres paginas principais.",
        "- Raizes: CTB (ID 9), Palestras & Conferencias (ID 1298) e Materiais de Estudo (ID 5091).",
        "- Recursos: somente links e midias presentes no HTML/shortcodes das paginas incluidas.",
        "- `post_parent`, categorias, titulos e anexos associados nao incluem conteudo por conta propria.",
        "- Nenhum banco, pipeline ou DAG foi executado.",
        "",
        "## Resultado executivo",
        "",
        (
            f"Foram identificadas **{len(units)} paginas publicamente "
            f"alcancaveis** (`{dict(unit_counts)}`) e "
            f"**{len(primary_urls)} URLs canonicas** de recursos primarios."
        ),
        "",
        (
            f"O checklist contem **{len(actions)} recomendacoes**, das quais "
            f"**{len(conference_actions)}** exigem decisao manual entre "
            "palestra e conferencia."
        ),
        "",
        "## Paginas principais",
        "",
        "| ID | Pagina | Classificacao | Paginas linkadas |",
        "|---:|---|---|---:|",
    ]

    for root in sorted(roots, key=lambda value: int(value.post_id)):
        linked_count = sum(
            unit.discovery_reason == f"linked_from_public_root_{root.slug}"
            for unit in units
        )
        lines.append(
            f"| {root.post_id} | {markdown_escape(root.title)} | "
            f"{root.study_type} | {linked_count} |"
        )

    lines.extend([
        "",
        "## Alteracoes recomendadas no WordPress",
        "",
        "### Palestra ou conferencia",
        "",
        (
            "A raiz combina os dois tipos. Preencher "
            "`archive_study_type=lecture` ou "
            "`archive_study_type=conference` nestas paginas publicas:"
        ),
        "",
    ])

    for action in conference_actions:
        lines.append(f"- ID `{action.wordpress_id}` - {action.title}")

    lines.extend([
        "",
        "### Hierarquia CTB",
        "",
        (
            f"Ha **{len(ctb_without_parent)} paginas CTB publicas** com "
            "`post_parent=0`, mas todas aparecem como banners/links na raiz "
            "CTB. Corrigir o pai pode melhorar a organizacao editorial, mas "
            "nao e necessario para esta extracao."
        ),
        "",
        "### Programa de Formacao de Discipulos",
        "",
        (
            f"A pagina Materiais de Estudo apresenta **{len(pfd_pdfs)} PDFs**, "
            f"cobrindo os estudos **{min(pfd_numbers)} a {max(pfd_numbers)}**."
            if pfd_numbers
            else "Nenhum PDF numerado do PFD foi identificado."
        ),
        "",
        (
            "O estudo 1 possui exatamente um link publico. A duplicidade do "
            "diagnostico anterior era um anexo associado, mas nao renderizado "
            "na pagina raiz."
        ),
        "",
        "### Metadados deterministas",
        "",
        "- `archive_content_type`: `study_hub` ou `study_collection`.",
        "- `archive_study_type`: `ctb`, `weekly`, `lecture`, `conference` ou `pfd`.",
        "- O arquivo `manual_actions.csv` contem valores somente para as paginas publicamente alcancaveis.",
        "",
        "## Fora do escopo",
        "",
        (
            f"O WXR possui **{len(published_pages)} paginas publicadas**, mas "
            f"somente **{len(units)}** aparecem no grafo das tres raizes."
        ),
        "",
        "- Posts da categoria Estudos Semanais que nao aparecem nas raizes.",
        "- NUTRE e O Nosso Santo Auxilio, ausentes das tres paginas principais.",
        "- Rascunhos, paginas privadas e itens apenas encontrados por titulo.",
        "- Anexos-filhos, anexos orfaos e arquivos apenas na biblioteca de midia.",
        "",
        "## Recursos encontrados",
        "",
        f"- Contagens por tipo: `{dict(resource_counts)}`",
        f"- URLs canonicas de recursos primarios: **{len(primary_urls)}**",
        (
            f"- Possiveis aliases pelo mesmo nome de arquivo: "
            f"**{len(resource_aliases)}**."
        ),
        "- Imagens sao inventariadas, mas nao tratadas automaticamente como material.",
        "- O XML contem URLs e metadados, nao os arquivos binarios.",
        "",
        "## Inventario de paginas",
        "",
        "| ID | Tipo | Classificacao | Recursos | Titulo |",
        "|---:|---|---|---|---|",
    ])

    for unit in sorted(units, key=lambda value: int(value.post_id)):
        resource_summary = ", ".join(
            f"{key}={value}"
            for key, value in sorted(unit.resource_counts.items())
        ) or "none"
        lines.append(
            f"| {unit.post_id} | {unit.node_kind} | {unit.study_type} | "
            f"{markdown_escape(resource_summary)} | "
            f"{markdown_escape(unit.title)} |"
        )

    lines.extend([
        "",
        "## Arquivos auxiliares",
        "",
        "- `content_inventory.csv`: somente paginas no grafo publico.",
        "- `resource_inventory.csv`: somente recursos renderizados nessas paginas.",
        "- `manual_actions.csv`: metadados e decisoes manuais do escopo publico.",
        "- `possible_resource_aliases.csv`: URLs publicas com o mesmo nome de arquivo.",
        "- `diagnostic.json`: resumo para validacao automatizada.",
        "",
    ])

    return "\n".join(lines)


def write_outputs(
    output_dir: Path,
    xml_path: Path,
    items: list[WordpressItem],
    units: list[ContentUnit],
    resources: list[Resource],
    actions: list[ManualAction],
    resource_aliases: list[dict[str, str]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    content_rows = []

    for unit in units:
        row = asdict(unit)
        row["resource_counts"] = json.dumps(
            row["resource_counts"],
            ensure_ascii=False,
            sort_keys=True,
        )
        content_rows.append(row)

    write_csv(
        output_dir / "content_inventory.csv",
        content_rows,
        [item.name for item in fields(ContentUnit)],
    )
    write_csv(
        output_dir / "resource_inventory.csv",
        [asdict(resource) for resource in resources],
        [item.name for item in fields(Resource)],
    )
    write_csv(
        output_dir / "manual_actions.csv",
        [asdict(action) for action in actions],
        [item.name for item in fields(ManualAction)],
    )
    (output_dir / "orphan_attachments.csv").unlink(missing_ok=True)
    write_csv(
        output_dir / "possible_resource_aliases.csv",
        resource_aliases,
        [
            "resource_type",
            "filename_fingerprint",
            "distinct_urls",
            "owner_ids",
            "owner_titles",
            "urls",
            "diagnosis",
        ],
    )

    primary_resources = [
        resource
        for resource in resources
        if resource.resource_type in PRIMARY_RESOURCE_TYPES
    ]
    summary = {
        "source_xml": str(xml_path),
        "selection_mode": "published_pages_linked_from_public_roots",
        "public_root_ids": [9, 1298, 5091],
        "total_wxr_items": len(items),
        "published_pages_in_wxr": sum(
            item.status == "publish" and item.post_type == "page"
            for item in items
        ),
        "content_units": len(units),
        "content_unit_types": dict(Counter(
            unit.node_kind for unit in units
        )),
        "resources_before_global_deduplication": len(resources),
        "resource_types": dict(Counter(
            resource.resource_type for resource in resources
        )),
        "unique_primary_resource_urls": len({
            resource.canonical_url for resource in primary_resources
        }),
        "manual_actions": len(actions),
        "high_priority_actions": sum(
            action.priority == "high" for action in actions
        ),
        "possible_resource_alias_groups": len(resource_aliases),
    }

    with (output_dir / "diagnostic.json").open(
        "w",
        encoding="utf-8",
    ) as file_handle:
        json.dump(summary, file_handle, ensure_ascii=False, indent=2)
        file_handle.write("\n")

    report = render_public_navigation_report(
        xml_path,
        items,
        units,
        resources,
        actions,
        resource_aliases,
    )
    (output_dir / "diagnostic.md").write_text(
        report,
        encoding="utf-8-sig",
    )


def run(xml_path: Path, output_dir: Path) -> dict[str, int]:
    items = parse_wordpress_xml(xml_path)
    units = discover_content_units(items)
    resources = extract_resources(units, items)
    actions = build_manual_actions(units)
    resource_aliases = find_possible_resource_aliases(resources)

    if not units:
        raise RuntimeError("No study content units were discovered")

    write_outputs(
        output_dir,
        xml_path,
        items,
        units,
        resources,
        actions,
        resource_aliases,
    )

    return {
        "items": len(items),
        "units": len(units),
        "resources": len(resources),
        "actions": len(actions),
        "high_priority_actions": sum(
            action.priority == "high" for action in actions
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose study content in a WordPress WXR export without writing "
            "to the application database."
        )
    )
    parser.add_argument("xml_path", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/diagnostics/wordpress-studies"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run(args.xml_path.resolve(), args.output_dir.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Reports written to: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from urllib.parse import urlparse
from urllib.parse import quote

_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(text: str | None) -> str | None:
    if text is None:
        return None

    normalized = html.unescape(str(text))
    normalized = _HTML_TAG_RE.sub(" ", normalized)
    normalized = " ".join(normalized.split())
    normalized = "".join(ch for ch in normalized if ord(ch) >= 32 or ch in "\n\r\t")

    replacements = {
        "\u00a0": " ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
    }
    for src, dst in replacements.items():
        normalized = normalized.replace(src, dst)

    normalized = normalized.strip()
    return normalized or None


def normalize_authors(authors: list[str] | None) -> list[str]:
    if not authors:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for author in authors:
        cleaned = clean_text(author)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
    return normalized


def normalize_url(value: str | None) -> str | None:
    cleaned = clean_text(value)
    if not cleaned:
        return None

    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    return cleaned


def normalize_doi(value: str | None) -> str | None:
    cleaned = clean_text(value)
    if not cleaned:
        return None

    cleaned = cleaned.replace("https://doi.org/", "").replace("http://doi.org/", "")
    cleaned = cleaned.strip()
    if not _DOI_PATTERN.match(cleaned):
        return None
    return cleaned.lower()


def derive_article_url(
    *,
    source: str | None,
    url: str | None,
    doi: str | None,
    source_id: str | None,
) -> str | None:
    normalized_source = (source or "").strip().lower()
    direct = normalize_url(url)
    if direct:
        return direct

    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        return f"https://doi.org/{normalized_doi}"

    sid = clean_text(source_id)
    if not sid:
        return None

    if normalized_source == "arxiv":
        if sid.startswith("http://") or sid.startswith("https://"):
            return sid
        clean_id = sid.replace("arXiv:", "").replace("arxiv:", "")
        return f"https://arxiv.org/abs/{clean_id}"

    if normalized_source == "openalex":
        return sid if sid.startswith("http") else f"https://openalex.org/{sid}"

    if normalized_source == "core":
        return sid if sid.startswith("http") else f"https://core.ac.uk/works/{sid}"

    if normalized_source == "europepmc":
        if sid.startswith("PMC:"):
            pmc_id = sid.split(":", 1)[1]
            return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/"
        return sid if sid.startswith("http") else f"https://europepmc.org/article/{quote(sid)}"

    if normalized_source == "crossref":
        return None

    if normalized_source == "elibrary":
        if sid.startswith("http://") or sid.startswith("https://"):
            return sid
        if sid.isdigit():
            return f"https://www.elibrary.ru/item.asp?id={sid}"
        return f"https://www.elibrary.ru/{sid.lstrip('/')}"

    if normalized_source == "freepatent":
        if sid.startswith("http://") or sid.startswith("https://"):
            return sid
        return f"https://www.freepatent.ru/{sid.lstrip('/')}"

    if normalized_source == "patentscope":
        if sid.startswith("http://") or sid.startswith("https://"):
            return sid
        return f"https://patentscope.wipo.int/search/en/detail.jsf?docId={quote(sid)}"

    if normalized_source == "rospatent":
        if sid.startswith("http://") or sid.startswith("https://"):
            return sid
        return f"https://searchplatform.rospatent.gov.ru/doc/{quote(sid)}"

    return None


def normalize_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None

    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y"):
                try:
                    parsed = datetime.strptime(raw[:10] if fmt == "%Y-%m-%d" else raw, fmt)
                    break
                except ValueError:
                    continue

    if parsed is None:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso_utc(value: datetime | str | None) -> str | None:
    dt = normalize_datetime(value)
    if dt is None:
        return None
    return dt.isoformat()


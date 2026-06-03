r"""Revalidate stored paper.keywords against exact document text.

Dry-run by default. From project root:
  .venv\Scripts\python.exe backend\scripts\revalidate_keywords_exact_text.py --limit 100

Apply cleanup:
  .venv\Scripts\python.exe backend\scripts\revalidate_keywords_exact_text.py --apply --limit 1000

The script does not call Qwen. It only removes existing keywords that are not
found as boundary-aware terms in title/abstract/raw content parts/full_text.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
for _path in (ROOT, BACKEND):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from app.db.models.paper import Paper
from app.db.session import async_session_maker
from app.services.paper_content_service import (
    _build_keyword_source_text,
    _validate_keywords_against_source,
)


def _keywords_as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    return []


_KEYWORD_SOURCE_CONTENT_TYPES = {"body", "heading", "abstract", "caption", "table"}
_KEYWORD_SOURCE_EXCLUDED_TYPES = {"reference", "footnote", "affiliation", "formula"}
_KEYWORD_REFERENCE_TITLE_RE = re.compile(r"^\s*(references|bibliography|литература|список\s+литературы)\s*$", re.IGNORECASE)
_KEYWORD_REFERENCE_LINE_RE = re.compile(
    r"^\s*(?:\[?\d{1,3}\]?\.?|\(\d{1,3}\))\s+.{20,}\b(?:doi|https?://|journal|vol\.?|pp\.?|arxiv|patent)\b",
    re.IGNORECASE,
)


def _clean_keyword_source_block(text: str) -> str:
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    in_references = False
    for raw_line in value.split("\n"):
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            if not in_references:
                lines.append("")
            continue
        if _KEYWORD_REFERENCE_TITLE_RE.match(line):
            in_references = True
            continue
        if in_references or _KEYWORD_REFERENCE_LINE_RE.match(line):
            continue
        if line.startswith(("[Formula candidate", "[Table candidate")):
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _keyword_source_text_for_loaded_part(part: Any) -> str:
    content_type = str(getattr(part, "content_type", "body") or "body").strip().lower().replace("-", "_")
    page_profile = str(getattr(part, "page_profile", "") or "").strip().lower()
    metadata = getattr(part, "extraction_metadata", None) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    if content_type in _KEYWORD_SOURCE_EXCLUDED_TYPES or page_profile in {"references", "bibliography"}:
        return ""
    if content_type == "table":
        if int(metadata.get("table_blocks_validated_count") or 0) <= 0:
            return ""
        return _clean_keyword_source_block(str(metadata.get("tables_text") or ""))
    if content_type not in _KEYWORD_SOURCE_CONTENT_TYPES:
        return ""
    projected = str(metadata.get("qwen_text") or "").strip()
    raw_text = str(getattr(part, "raw_text", None) or "").strip()
    return _clean_keyword_source_block(projected or raw_text)


def _raw_source_from_loaded_parts(paper: Paper) -> str:
    blocks: list[str] = []
    for part in getattr(paper, "content_parts", []) or []:
        text = _keyword_source_text_for_loaded_part(part)
        if text:
            blocks.append(text)
    return "\n\n".join(blocks).strip()


async def _run(args: argparse.Namespace) -> int:
    async with async_session_maker() as db:
        query = select(Paper).options(selectinload(Paper.content_parts)).order_by(Paper.id.asc())
        if args.paper_id:
            query = query.where(Paper.id == args.paper_id)
        if args.source:
            query = query.where(Paper.source == args.source)
        if args.limit:
            query = query.limit(args.limit)

        result = await db.execute(query)
        papers = list(result.scalars().unique().all())

        checked = changed = removed_total = kept_total = 0
        for paper in papers:
            existing = _keywords_as_list(paper.keywords)
            if not existing:
                continue
            source_text, source_mode = _build_keyword_source_text(
                title=paper.title,
                abstract=paper.abstract,
                raw_text=_raw_source_from_loaded_parts(paper),
                full_text=paper.full_text,
            )
            accepted, rejected = _validate_keywords_against_source(existing, source_text, limit=50)
            checked += 1
            kept_total += len(accepted)
            removed_total += len(rejected)

            if rejected or accepted != existing:
                changed += 1
                print(
                    f"paper_id={paper.id} source={paper.source} mode={source_mode} "
                    f"kept={len(accepted)} removed={len(rejected)} title={paper.title[:90]!r}"
                )
                if rejected:
                    print(f"  removed: {rejected[:20]}")
                if args.apply:
                    paper.keywords = accepted

        if args.apply and changed:
            await db.commit()
        else:
            await db.rollback()

        action = "applied" if args.apply else "dry-run"
        print(
            f"Done ({action}): checked={checked}, changed={changed}, "
            f"kept={kept_total}, removed={removed_total}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Revalidate stored keywords against exact document text")
    parser.add_argument("--apply", action="store_true", help="Write cleaned keywords back to the database")
    parser.add_argument("--limit", type=int, default=0, help="Maximum papers to scan, 0 means no limit")
    parser.add_argument("--paper-id", type=int, default=0, help="Only validate one paper ID")
    parser.add_argument("--source", default="", help="Only validate one source, for example arXiv or FreePatent")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

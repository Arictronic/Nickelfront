r"""Debug raw PDF extraction without Qwen/AI stages.

Usage from project root:
  .venv\Scripts\python.exe backend\scripts\debug_pdf_extract.py storage\papers_pdf\paper_13.pdf --mode auto
  venv\Scripts\python.exe backend\scripts\debug_pdf_extract.py path\to\file.pdf --mode columns
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
for _path in (ROOT, BACKEND):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from app.services.pdf_content_parser import pdf_parser


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract raw PDF text with Nickelfront PDFParser")
    parser.add_argument("pdf", type=Path, help="PDF file path")
    parser.add_argument("--mode", default="auto", choices=["auto", "layout", "simple", "columns"], help="Extraction mode")
    parser.add_argument("--no-tables", action="store_true", help="Disable table markdown extraction")
    parser.add_argument("--keep-headers", action="store_true", help="Do not remove repeated headers/footers")
    parser.add_argument(
        "--repair-cross-page",
        action="store_true",
        help="Experimental: move lowercase continuations across page boundaries. Disabled by default.",
    )
    parser.add_argument(
        "--domain-profile",
        default="generic",
        choices=["generic", "materials", "patents"],
        help="Parser domain/profile option",
    )
    parser.add_argument(
        "--content-blocks-mode",
        default="final",
        choices=["final", "raw"],
        help="Content block mode option",
    )
    parser.add_argument(
        "--rebuild-content-blocks-from-final-text",
        action="store_true",
        help="Force parser option rebuild_content_blocks_from_final_text",
    )
    parser.add_argument("--no-content-blocks", action="store_true", help="Disable content_blocks metadata")
    parser.add_argument("--out", type=Path, default=Path("debug_pdf_extract.txt"), help="Output txt path")
    parser.add_argument("--meta", type=Path, default=Path("debug_pdf_extract_meta.json"), help="Output metadata json path")
    args = parser.parse_args()

    if not args.pdf.exists():
        raise SystemExit(f"PDF not found: {args.pdf}")

    options = {
        "extraction_mode": args.mode,
        "detect_columns": True,
        "extract_tables": not args.no_tables,
        "remove_headers_footers": not args.keep_headers,
        "merge_hyphenated_words": True,
        "normalize_math": True,
        "mark_formula_candidates": True,
        "normalize_cid_glyphs": True,
        "normalize_private_use_glyphs": True,
        "repair_cross_page_continuations": args.repair_cross_page,
        "domain_profile": args.domain_profile,
        "content_blocks_mode": args.content_blocks_mode,
        "rebuild_content_blocks_from_final_text": args.rebuild_content_blocks_from_final_text,
        "emit_content_blocks": not args.no_content_blocks,
        "ocr_enabled": False,
    }
    pages = pdf_parser.extract_pages_from_file(str(args.pdf), options=options)
    text = "\n\n".join(page.text for page in pages if page.text.strip()).strip()
    args.out.write_text(text, encoding="utf-8")
    args.meta.write_text(json.dumps([page.as_dict() for page in pages], ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"pages={len(pages)} chars={len(text)}")
    for page in pages[:10]:
        print(
            f"page={page.page_number} method={page.method} score={page.quality_score} "
            f"chars={len(page.text)} warnings={','.join(page.warnings) or '-'}"
        )
    print(f"text: {args.out}")
    print(f"meta: {args.meta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

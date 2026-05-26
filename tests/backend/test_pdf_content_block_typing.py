from __future__ import annotations

import json
from pathlib import Path

from app.services.pdf_content_parser import PDFParser


def test_rebuild_content_blocks_emits_markdown_table_block() -> None:
    parser = PDFParser()
    lines = [
        {"text": "[Table candidate 1]"},
        {"text": "| Alloy | Ni | Cr | Al |"},
        {"text": "| --- | --- | --- | --- |"},
        {"text": "| IN738 | 61.0 | 16.0 | 3.4 |"},
        {"text": "The alloy was heat treated before creep testing."},
    ]

    blocks, meta = parser._content_blocks_from_lines(lines, page_num=7, metadata={"table_count": 1})

    table_blocks = [block for block in blocks if block["type"] == "table"]
    body_blocks = [block for block in blocks if block["type"] == "body"]
    assert table_blocks
    assert "| IN738 | 61.0 | 16.0 | 3.4 |" in table_blocks[0]["text"]
    assert body_blocks
    assert meta["content_block_table_count"] == 1


def test_caption_continuation_does_not_swallow_long_table_body_text() -> None:
    parser = PDFParser()
    long_body = (
        "The processing route was selected to obtain a stable gamma prime microstructure "
        "after heat treatment and to compare the resulting creep resistance with the "
        "baseline nickel superalloy under identical test conditions."
    )
    lines = [
        {"text": "Table 1. Nominal chemical composition of investigated alloys."},
        {"text": long_body},
    ]

    blocks, _ = parser._content_blocks_from_lines(lines, page_num=3, metadata={})

    assert blocks[0]["type"] == "caption"
    assert blocks[1]["type"] == "body"


def test_formula_candidate_marker_is_not_inserted_into_clean_text() -> None:
    parser = PDFParser()
    text = parser._clean_page_text("E = mc^2\nThe equation is used below.", {"mark_formula_candidates": True})

    assert "[Formula candidate]" not in text
    assert "E = mc^2" in text


def test_retype_content_blocks_merges_split_markdown_table_fragments() -> None:
    parser = PDFParser()
    blocks = [
        {"type": "body", "page": 53, "text": "The paragraph before the table should stay body."},
        {"type": "body", "page": 53, "text": "[Table candidate 2]"},
        {"type": "body", "page": 53, "text": "| Parameters for Diffusion Coefficients |  |  |  |"},
        {"type": "body", "page": 53, "text": "| --- | --- | --- | --- |"},
        {
            "type": "formula",
            "page": 53,
            "text": "| A110 | 1.229 | A120 | 0.0116 |\n| A111 | 0.0731 | A121 | 0.0923 |",
        },
    ]

    retyped, meta = parser._retype_content_blocks(
        blocks,
        metadata={"page": 53, "table_count": 1, "table_cells": 8},
        page_num=53,
    )

    table_blocks = [block for block in retyped if block["type"] == "table"]
    body_blocks = [block for block in retyped if block["type"] == "body"]

    assert len(table_blocks) == 1
    assert "[Table candidate 2]" in table_blocks[0]["text"]
    assert "| A111 | 0.0731 | A121 | 0.0923 |" in table_blocks[0]["text"]
    assert body_blocks
    assert meta["content_block_table_count"] == 1
    assert meta["content_block_table_validated_count"] == 1


def test_retype_content_blocks_restores_table_from_audit_page_53() -> None:
    parser = PDFParser()
    page = _load_audit_page("paper_18__6c5fc31634dd.json", 53)

    retyped, meta = parser._retype_content_blocks(
        page["metadata"]["content_blocks"],
        metadata=page["metadata"],
        page_num=53,
    )

    table_blocks = [block for block in retyped if block["type"] == "table"]
    assert len(table_blocks) == 1
    assert "A110" in table_blocks[0]["text"]
    assert "A225" in table_blocks[0]["text"]
    assert meta["content_block_table_validated_count"] == 1


def test_retype_content_blocks_restores_table_from_audit_page_77() -> None:
    parser = PDFParser()
    page = _load_audit_page("paper_18__6c5fc31634dd.json", 77)

    retyped, meta = parser._retype_content_blocks(
        page["metadata"]["content_blocks"],
        metadata=page["metadata"],
        page_num=77,
    )

    table_blocks = [block for block in retyped if block["type"] == "table"]
    assert len(table_blocks) == 1
    assert "| Element | Pt | Zr | Y |" in table_blocks[0]["text"]
    assert "| CMSX-4 |" in table_blocks[0]["text"]
    assert meta["content_block_table_validated_count"] == 1


def test_retype_content_blocks_restores_table_from_formula_heavy_audit_pages() -> None:
    parser = PDFParser()

    page_3 = _load_audit_page("paper_3__dc44a3578538.json", 7)
    retyped_3, meta_3 = parser._retype_content_blocks(
        page_3["metadata"]["content_blocks"],
        metadata=page_3["metadata"],
        page_num=7,
    )
    table_3 = [block for block in retyped_3 if block["type"] == "table"]
    assert len(table_3) == 1
    assert "| 208Pb 82 |" in table_3[0]["text"]
    assert meta_3["content_block_table_validated_count"] == 1

    page_38 = _load_audit_page("paper_38__f8273546e8c6.json", 4)
    retyped_38, meta_38 = parser._retype_content_blocks(
        page_38["metadata"]["content_blocks"],
        metadata=page_38["metadata"],
        page_num=4,
    )
    table_38 = [block for block in retyped_38 if block["type"] == "table"]
    assert len(table_38) == 1
    assert "| ВЖМ4 |" in table_38[0]["text"]
    assert "| ВЖМ6 |" in table_38[0]["text"]
    assert meta_38["content_block_table_validated_count"] == 1


def _load_audit_page(filename: str, page_number: int) -> dict:
    base = Path(__file__).resolve().parents[2] / "storage" / "pdf_parser_audit" / "latest" / "meta"
    pages = json.loads((base / filename).read_text(encoding="utf-8"))
    return next(page for page in pages if int(page["page_number"]) == page_number)

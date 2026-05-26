from __future__ import annotations

from backend.scripts.pdf_parser_batch_audit import build_downstream_projection_audit


def test_downstream_projection_audit_keeps_tables_and_excludes_formula_markers() -> None:
    meta = {
        "table_count": 1,
        "content_blocks": [
            {"type": "body", "text": "The IN738 alloy was heat treated before creep testing."},
            {"type": "table", "text": "[Table candidate 1]\n| Alloy | Ni | Cr |\n| IN738 | 61 | 16 |"},
            {"type": "formula", "text": "[Formula candidate]\nE = mc^2 □"},
            {"type": "reference", "text": "References\n[1] Smith et al. Journal 2020."},
        ],
    }

    audit = build_downstream_projection_audit(meta)

    assert audit["table_projection_chars"] > 0
    assert audit["formula_projection_chars"] > 0
    assert audit["qwen_projection_leakage_hits"] == 0
    assert audit["embedding_projection_leakage_hits"] == 0
    assert audit["embedding_reference_hits"] == 0
    assert "tables_detected_without_table_blocks" not in audit["projection_issues"]


def test_downstream_projection_audit_flags_detected_tables_without_table_blocks() -> None:
    audit = build_downstream_projection_audit(
        {
            "table_count": 1,
            "content_blocks": [
                {"type": "body", "text": "Alloy Ni Cr Al\nIN738 61 16 3.4"},
            ],
        }
    )

    assert audit["tables_detected_without_table_blocks"] == 1
    assert "tables_detected_without_table_blocks" in audit["projection_issues"]

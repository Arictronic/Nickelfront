from __future__ import annotations
import logging
import math
import re
import unicodedata
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .compat import Document, RecursiveCharacterTextSplitter
from .constants import *
from .models import PdfExtractionError, PdfPageExtraction

logger = logging.getLogger(__name__)

class PDFTablesOcrMixin:
    """Native PDF table extraction and validation helpers."""

    def _table_candidate_metrics(
        self,
        table: list[list[str | None]],
        markdown: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rows = [[self._clean_table_cell(cell) for cell in (row or [])] for row in (table or []) if row]
        rows = [[cell for cell in row] for row in rows if any(cell.strip() for cell in row)]
        text = "\n".join(" | ".join(row) for row in rows).strip() or markdown
        non_empty_cells = [cell for row in rows for cell in row if cell.strip()]
        numeric_cells = [
            cell
            for cell in non_empty_cells
            if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?(?:%|°C|K|MPa|GPa|h|s|min)?", cell.strip())
        ]
        alpha_cells = [cell for cell in non_empty_cells if re.search(r"[A-Za-zА-Яа-я]", cell)]
        row_widths = [len(row) for row in rows if row]
        populated_widths = [sum(1 for cell in row if cell.strip()) for row in rows]
        max_cols = max(row_widths, default=0)
        expected_cells = max(1, len(rows) * max(1, max_cols))
        density = len(non_empty_cells) / expected_cells
        repeated_width = max(Counter(row_widths).values(), default=0)
        repeated_populated_width = max(Counter(populated_widths).values(), default=0)
        dense_rows = sum(1 for count in populated_widths if max_cols > 0 and count >= max(2, int(max_cols * 0.5)))
        mixed_rows = sum(
            1
            for row in rows
            if any(re.search(r"[A-Za-zА-Яа-я]", cell) for cell in row)
            and any(re.search(r"[-+]?\d+(?:[.,]\d+)?", cell) for cell in row)
        )
        width_regularity = repeated_width / max(1, len(row_widths))
        populated_width_regularity = repeated_populated_width / max(1, len(populated_widths))
        structural_score = round(
            0.35 * min(1.0, density / 0.65)
            + 0.25 * max(width_regularity, populated_width_regularity)
            + 0.20 * min(1.0, dense_rows / max(1, len(rows)))
            + 0.20 * min(1.0, (len(numeric_cells) + len(alpha_cells)) / max(1, len(non_empty_cells))),
            4,
        )
        profile = self._domain_profile(metadata)
        return {
            "rows": len(rows),
            "cols": max_cols,
            "non_empty_cells": len(non_empty_cells),
            "numeric_cells": len(numeric_cells),
            "alpha_cells": len(alpha_cells),
            "density": round(len(non_empty_cells) / expected_cells, 4),
            "repeated_width": repeated_width,
            "repeated_populated_width": repeated_populated_width,
            "dense_rows": dense_rows,
            "mixed_rows": mixed_rows,
            "width_regularity": round(width_regularity, 4),
            "populated_width_regularity": round(populated_width_regularity, 4),
            "structural_score": structural_score,
            "generic_context_hint": bool(_TABLE_CONTEXT_HINT_RE.search(text)),
            "profile_table_hint": bool(profile.strong_table_hint_re.search(text) or profile.table_context_hint_re.search(text)),
            "element_count": len(self._domain_element_hits(text, metadata)),
            "plot_artifact_hint": bool(self._looks_like_plot_artifact_text(text, metadata)),
            "text": text,
        }

    def _classify_pdf_table_candidate(
        self,
        table: list[list[str | None]],
        markdown: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[bool, str, dict[str, Any]]:
        metrics = self._table_candidate_metrics(table, markdown, metadata=metadata)
        rows = int(metrics["rows"] or 0)
        cols = int(metrics["cols"] or 0)
        non_empty = int(metrics["non_empty_cells"] or 0)
        numeric = int(metrics["numeric_cells"] or 0)
        alpha = int(metrics["alpha_cells"] or 0)
        density = float(metrics.get("density") or 0.0)
        repeated_width = int(metrics.get("repeated_width") or 0)
        repeated_populated_width = int(metrics.get("repeated_populated_width") or 0)
        dense_rows = int(metrics.get("dense_rows") or 0)
        mixed_rows = int(metrics.get("mixed_rows") or 0)
        structural_score = float(metrics.get("structural_score") or 0.0)
        generic_hint = bool(metrics.get("generic_context_hint"))
        text = str(metrics.get("text") or "")

        if rows < 2 or cols < 2 or non_empty < 4:
            return False, "rejected_too_small", metrics




        regular_grid = bool(
            rows >= 2
            and cols >= 2
            and density >= 0.35
            and (repeated_width >= 2 or repeated_populated_width >= 2)
            and dense_rows >= max(2, rows // 2)
            and structural_score >= 0.48
        )
        structured_numeric = bool(rows >= 3 and cols >= 2 and numeric >= 3 and alpha >= 2 and dense_rows >= 2)
        structured_text_grid = bool(rows >= 3 and cols >= 3 and alpha >= 4 and dense_rows >= 3)
        profile_bonus = bool(self._has_table_domain_bonus_signal(text, metadata) and regular_grid)

        if metrics.get("plot_artifact_hint") and not (regular_grid and (generic_hint or structured_numeric or structured_text_grid)):
            return False, "rejected_plot_axis_grid", metrics
        if regular_grid and structured_numeric:
            return True, "accepted_structural_numeric_grid", metrics
        if regular_grid and structured_text_grid:
            return True, "accepted_structural_text_grid", metrics
        if regular_grid and (generic_hint or mixed_rows >= 2):
            return True, "accepted_structural_grid", metrics
        if profile_bonus:
            return True, "accepted_profile_bonus_structural_table", metrics
        return False, "rejected_no_table_structure", metrics

    def _extract_tables_markdown(self, page: Any, metadata: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
        try:
            tables = page.extract_tables() or []
        except Exception:
            return "", {"table_count": 0, "table_cells": 0, "table_error": "extract_failed"}

        blocks: list[str] = []
        cell_count = 0
        raw_count = 0
        rejected_count = 0
        reject_reasons: dict[str, int] = {}
        diagnostics: list[dict[str, Any]] = []
        for table_idx, table in enumerate(tables, start=1):
            if not table:
                continue
            raw_count += 1
            markdown = self._table_to_markdown(table)
            if not markdown:
                rejected_count += 1
                reject_reasons["rejected_empty_after_cleanup"] = reject_reasons.get("rejected_empty_after_cleanup", 0) + 1
                continue
            accepted, reason, metrics = self._classify_pdf_table_candidate(table, markdown, metadata=metadata)
            diag = {
                "index": table_idx,
                "accepted": accepted,
                "reason": reason,
                "rows": metrics.get("rows"),
                "cols": metrics.get("cols"),
                "numeric_cells": metrics.get("numeric_cells"),
                "alpha_cells": metrics.get("alpha_cells"),
                "density": metrics.get("density"),
                "repeated_width": metrics.get("repeated_width"),
                "repeated_populated_width": metrics.get("repeated_populated_width"),
                "dense_rows": metrics.get("dense_rows"),
                "mixed_rows": metrics.get("mixed_rows"),
                "width_regularity": metrics.get("width_regularity"),
                "populated_width_regularity": metrics.get("populated_width_regularity"),
                "structural_score": metrics.get("structural_score"),
                "generic_context_hint": metrics.get("generic_context_hint"),
                "profile_table_hint": metrics.get("profile_table_hint"),
                "element_count": metrics.get("element_count"),
            }
            if len(diagnostics) < 12:
                diagnostics.append(diag)
            if not accepted:
                rejected_count += 1
                reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
                continue
            blocks.append(f"[Table candidate {table_idx}]\n\n{markdown}")
            cell_count += sum(len(row or []) for row in table)

        meta: dict[str, Any] = {
            "table_count": len(blocks),
            "table_cells": cell_count,
            "table_candidates_raw_count": raw_count,
            "table_candidates_accepted_count": len(blocks),
            "table_candidates_rejected_count": rejected_count,
            "table_candidate_diagnostics": diagnostics,
        }
        for reason, count in reject_reasons.items():
            meta[f"table_candidates_{reason}"] = count
        return "\n\n".join(blocks).strip(), meta

    def _table_to_markdown(self, table: list[list[str | None]]) -> str:
        rows: list[list[str]] = []
        max_cols = 0
        for row in table:
            if not row:
                continue
            cleaned = [self._clean_table_cell(cell) for cell in row]
            if not any(cleaned):
                continue
            max_cols = max(max_cols, len(cleaned))
            rows.append(cleaned)
        if not rows or max_cols <= 1:
            return ""
        normalized = [row + [""] * (max_cols - len(row)) for row in rows]
        header = normalized[0]
        body = normalized[1:] or [[""] * max_cols]
        out = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * max_cols) + " |",
        ]
        out.extend("| " + " | ".join(row) + " |" for row in body)
        return "\n".join(out)

    def _clean_table_cell(self, cell: str | None) -> str:
        text = unicodedata.normalize("NFKC", str(cell or ""))
        text = _CONTROL_RE.sub(" ", text)
        text = text.replace("|", "\\|")
        text = re.sub(r"\s+", " ", text).strip()
        return text

__all__ = ["PDFTablesOcrMixin"]

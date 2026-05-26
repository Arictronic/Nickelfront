r"""Batch audit Nickelfront PDFParser on local PDF storage.

Purpose:
  - run raw PDF extraction for every PDF in storage/papers_pdf;
  - save extracted text + per-page metadata;
  - create compact reports that can be sent back for debugging.

Usage from project root:
  .venv\Scripts\python.exe backend\scripts\pdf_parser_batch_audit.py
  venv\Scripts\python.exe backend\scripts\pdf_parser_batch_audit.py --limit 20
  venv\Scripts\python.exe backend\scripts\pdf_parser_batch_audit.py --pdf-dir storage\papers_pdf --mode auto

Output:
  storage\pdf_parser_audit\latest\REPORT.md
  storage\pdf_parser_audit\latest\summary.csv
  storage\pdf_parser_audit\latest\summary.json
  storage\pdf_parser_audit\latest\problem_pages.json
  storage\pdf_parser_audit\latest\texts\*.txt
  storage\pdf_parser_audit\latest\meta\*.json
  storage\pdf_parser_audit\pdf_parser_audit_report.zip
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import multiprocessing
import os
import queue
import re
import shutil
import statistics
import sys
import time
import traceback
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
for _path in (ROOT, BACKEND):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from app.services.pdf_content_parser import PDFParser

DEFAULT_PDF_DIR = ROOT / "storage" / "papers_pdf"
DEFAULT_OUT_BASE = ROOT / "storage" / "pdf_parser_audit"
AUDIT_VERSION = "v47_parser_typing_stabilization_full"
ALLOWED_OCR_REASONS = {
    "disabled",
    "manual_skip",
    "not_recommended",
    "low_quality_score",
    "empty_text_layer",
    "engine_unavailable",
    "dependencies_missing",
    "ocr_failed",
    "applied",
}
OCR_PRIORITY_DOC_NAMES = {
    "paper_70.pdf",
    "paper_107.pdf",
    "paper_18.pdf",
    "paper_68.pdf",
    "paper_17.pdf",
    "paper_134.pdf",
}

BAD_WARNING_HINTS = {
    "empty_text",
    "low_text_chars",
    "possible_scanned_page",
    "ocr_failed",
    "ocr_not_installed",
}






SUSPICIOUS_TOKEN_PATTERNS = [
    re.compile(r"\ufffd"),
    re.compile(r"\][A-Za-z0-9_.:\-/]{6,}\["),
    re.compile(r"\b\d+v\d+\.\d+:viXra\b", re.IGNORECASE),
    re.compile(r"\b[0-9]{4}\s+yaM\b"),
]
CID_TOKEN_RE = re.compile(r"\(cid:\d+\)|\bcid:\d+\b", re.IGNORECASE)
LATEXIT_TOKEN_RE = re.compile(r"<+\s*latexit\b|l+\s*a+\s*t+\s*e+\s*x+\s*i+\s*t+", re.IGNORECASE)
PRIVATE_USE_RE = re.compile(r"[\ue000-\uf8ff]")
FORMULA_HINT_RE = re.compile(r"[=∑∫√≈≤≥±×÷→←↔∞αβγδλμσΩωπθ{}^_]|\b(?:Eq|Fig|Figure|Table)\.", re.IGNORECASE)
FIGURE_ONLY_HINT_RE = re.compile(r"\b(?:Fig\.|Figure|Table|Supplementary|Appendix)\b", re.IGNORECASE)
WATERMARK_TOKEN_RE = re.compile(r"\b(?:DRAFT|CONFIDENTIAL|UNCORRECTED\s+PROOF|ACCEPTED\s+MANUSCRIPT|SUBMITTED\s+VERSION|AUTHOR\s+VERSION)\b", re.IGNORECASE)
GRAPH_AXIS_LINE_RE = re.compile(r"^\s*(?:\(?[a-z]\)?\s*)?(?:[-+]?\d+(?:[.,]\d+)?(?:\s+|$)){2,}(?:[A-Za-z%°/\-]+)?\s*$", re.IGNORECASE)
REFERENCE_HEADING_HINT_RE = re.compile(r"(?:^|\n)\s*(?:References|Bibliography|Литература|Список\s+литературы)\s*(?:\n|$)", re.IGNORECASE)
REFERENCE_BIB_LINE_HINT_RE = re.compile(
    r"^\s*(?:\[?\d{1,3}\]?\.?|\(\d{1,3}\))\s+"
    r"(?:[A-ZА-Я][A-Za-zА-Яа-я'’.-]{2,}(?:,|\s+et\s+al\.|\s+and\s+|\s*&\s+)|"
    r"[A-ZА-Я][A-Za-zА-Яа-я'’.-]{2,}\s+[A-Z]\.)"
    r".{20,}\b(?:doi|journal|vol\.?|pp\.?|https?://|arxiv|proceedings|phys\.|sci\.|nature|materials|acta|metall|alloys?\s+compd)\b",
    re.IGNORECASE | re.MULTILINE,
)

def reference_leak_hits(text: str) -> int:
    value = str(text or "")
    return len(REFERENCE_HEADING_HINT_RE.findall(value)) + len(REFERENCE_BIB_LINE_HINT_RE.findall(value))

def reference_page_hint(text: str) -> bool:
    value = str(text or "")
    return bool(REFERENCE_HEADING_HINT_RE.search(value) or len(REFERENCE_BIB_LINE_HINT_RE.findall(value)) >= 3)

PROTECTED_REFERENCE_SECTION_RE = re.compile(
    r"^\s*(?:conflict\s+of\s+interest|competing\s+interests?|acknowledg(?:e)?ments?|"
    r"funding|data\s+availability|code\s+availability|author\s+contributions?|ethics|"
    r"конфликт\s+интересов|благодарност[ьи]|финансировани[ея]|доступност[ьи]\s+данных|"
    r"вклад\s+авторов)\b",
    re.IGNORECASE,
)
REFERENCE_ENUMERATOR_RE = re.compile(r"^\s*(?:\[\d{1,3}\]|\d{1,3}\.|\d{1,3}\)|\(\d{1,3}\))\s+")
BIBLIOGRAPHIC_SIGNAL_RE = re.compile(
    r"\b(?:doi|https?://|journal|vol\.?|volume|pp\.?|pages?|et\s+al\.|arxiv|"
    r"proceedings|phys\.?|chem\.?|mater\.?|materials|science|nature|acta|metall|"
    r"alloys?\s+compd|springer|elsevier|wiley|mdpi|журнал|вестник|труды|\d{4})\b",
    re.IGNORECASE,
)
FIGURE_HEAVY_HINT_RE = re.compile(r"\b(?:Fig\.?|Figure|Table|Supplementary|Appendix)\s*S?\d*\b", re.IGNORECASE)
LABEL_ONLY_RE = re.compile(r"^\s*(?:(?:\([a-z]\)|[a-z])\s*){2,}(?:S?\d+)?\s*$|^\s*S\d+\s*$", re.IGNORECASE)
TITLE_AFFILIATION_RE = re.compile(
    r"\b(?:University|Institute|Department|Laboratory|College|School|Faculty|Center|Centre|Correspondence|corresponding author|email|e-mail|present address|\bORCID\b)\b",
    re.IGNORECASE,
)
FORMULA_HEAVY_RE = re.compile(r"[=∑∫√≈≤≥±×÷→←↔∞αβγδλμσΩωπθ{}^_]")
INLINE_MARKER_CLEAN_RE = re.compile(r"\[(?:Formula candidate|Table candidate\s*\d*)\]", re.IGNORECASE)
BOX_GLYPH_RE = re.compile(r"[□�]")
PROJECTION_QWEN_MAIN_TYPES = {"body", "caption", "heading", "abstract", "affiliation", "footnote"}
PROJECTION_QWEN_SEPARATE_TYPES = {"table", "formula", "reference"}
PROJECTION_QWEN_TYPES = PROJECTION_QWEN_MAIN_TYPES | PROJECTION_QWEN_SEPARATE_TYPES
PROJECTION_EMBED_TYPES = {"body", "caption", "heading", "abstract", "affiliation"}
PROJECTION_PERSIST_TYPES = {"body", "heading", "caption", "formula", "table", "reference", "footnote", "affiliation", "abstract"}
AUDIT_BLOCK_TYPES = PROJECTION_PERSIST_TYPES | {"noise", "unknown"}
VALID_TABLE_SOURCES = {
    "pdfplumber_candidate",
    "markdown_table",
    "structured_labeled_table",
    "structured_material_table",
    "structured_numeric_table",
    "parser_detected_fallback",
}

CAPTION_START_RE = re.compile(
    r"^\s*(?:fig\.?|figure|table|scheme|algorithm|supplementary\s+(?:fig\.?|figure|table)|рис\.?|табл\.?)\s*[sа-яa-z0-9IVXivx.-]*[\s:.-]",
    re.IGNORECASE,
)
STRICT_CAPTION_MARKER_RE = re.compile(
    r"^\s*(?:fig(?:ure)?|table|scheme|algorithm|рис\.?|табл\.?)\s*(?:[s]?\d+[a-z]?|[ivx]+|[a-z])(?:[\s:.\-]|$)",
    re.IGNORECASE,
)
SECTION_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?(?:abstract|keywords?|introduction|experimental|materials\s+and\s+methods|methods|results|discussion|conclusions?|acknowledg(?:e)?ments?|references|bibliography|appendix|supplementary|аннотация|ключевые\s+слова|введение|методика|результаты|обсуждение|выводы|заключение|литература)\s*$",
    re.IGNORECASE,
)
MARKDOWN_TABLE_RE = re.compile(r"(?m)^\s*\|.+\|\s*$")
NUMERIC_TABLE_ROW_RE = re.compile(r"(?m)^\s*(?:[A-Za-zА-Яа-я0-9/%°+.,()\-]+\s+){2,}[-+]?\d+(?:[.,]\d+)?(?:\s+[-+]?\d+(?:[.,]\d+)?){2,}\s*$")
SENTENCE_END_RE = re.compile(r"[.!?][\s)\]]+[A-ZА-Я]")
HEADER_FOOTER_LEFTOVER_RE = re.compile(
    r"(?im)^\s*(?:"
    r"arxiv:\d{4}\.\d+|doi:\s*10\.|downloaded\s+from|"
    r"copyright|all\s+rights\s+reserved|page\s+\d+\s*(?:of|/)\s*\d+|"
    r"\d{1,4}\s*/\s*\d{1,4}|www\.[^\s]+|https?://[^\s]+"
    r")\s*$",
    re.IGNORECASE,
)
DOMAIN_SPECIFIC_RE = re.compile(
    r"\b(?:nickel|ni[-\s]?base[dh]?|superalloys?|heat[-\s]?resistant\s+alloys?|"
    r"alloys?|composition|microstructure|phase|oxide|oxidation|corrosion|"
    r"wt\.?\s*%|at\.?\s*%|\u0412\u041a\u041d\u0410|\u0412\u041f\u0440|\u042d\u041f\d*|\u0441\u043f\u043b\u0430\u0432(?:\u044b|\u0430|\u043e\u0432)?|"
    r"\u043c\u0438\u043a\u0440\u043e\u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440|\u043a\u043e\u0440\u0440\u043e\u0437|\u043e\u043a\u0441\u0438\u0434)\b",
    re.IGNORECASE,
)
STATUS_RANK = {"OK": 0, "WARN": 1, "BAD": 2, "FAIL": 3}
REGRESSION_METRICS = [
    "status",
    "avg_score",
    "min_score",
    "problem_pages",
    "serious_pages",
    "review_pages",
    "content_block_typing_issue_pages",
    "unknown_blocks_count",
    "misclassification_risk_blocks",
    "unknown_recovered_as_strong_type",
    "low_confidence_blocks",
    "block_confusion_issue_pages",
    "layout_issue_pages",
    "reference_like_body_blocks",
    "formula_like_body_blocks",
    "table_like_body_blocks",
    "caption_like_body_blocks",
    "body_like_reference_blocks",
    "body_like_formula_blocks",
    "heading_like_body_blocks",
    "possible_column_mixing_pages",
    "word_layout_two_column_pages",
    "short_line_heavy_pages",
    "orphan_line_heavy_pages",
    "low_text_density_pages",
    "qwen_projection_leakage_hits",
    "embedding_projection_leakage_hits",
    "embedding_reference_hits",
    "projection_input_block_count",
    "qwen_projection_block_count",
    "embedding_projection_block_count",
    "excluded_from_embedding_block_count",
    "excluded_from_qwen_block_count",
    "excluded_from_all_projection_block_count",
    "cid_tokens",
    "latexit_tokens",
    "private_use_glyphs",
    "content_blocks_cid_after_cleanup",
    "content_blocks_pua_after_cleanup",
    "content_blocks_latexit_after_cleanup",
    "ocr_pages_failed",
    "ocr_quality_regressed_pages",
    "content_sync_issue_pages",
    "content_sync_low_ratio_pages",
    "final_blocks_missing_pages",
    "final_block_text_not_in_page_pages",
    "raw_content_blocks_unavailable_pages",
    "final_header_footer_leftover_blocks",
    "domain_specific_generic_issue_pages",
    "domain_specific_matches",
    "ocr_unexplained_used_pages",
    "ocr_skipped_bad_text_layer_pages",
]


def safe_block_type(value: object) -> str:
    text = str(value or "body").strip().lower().replace("-", "_")
    aliases = {"figure_label": "caption", "references": "reference", "reference_page": "reference", "text": "body"}
    return aliases.get(text, text) if aliases.get(text, text) in PROJECTION_PERSIST_TYPES else "body"


def audit_block_type(value: object) -> str:
    """Preserve diagnostic-only block types instead of silently folding them to body."""
    text = str(value or "body").strip().lower().replace("-", "_")
    aliases = {
        "figure_label": "caption",
        "references": "reference",
        "reference_page": "reference",
        "text": "body",
        "unknown_block": "unknown",
        "dropped": "noise",
    }
    normalized = aliases.get(text, text)
    return normalized if normalized in AUDIT_BLOCK_TYPES else "unknown"


def clean_projection_text(text: str) -> str:
    value = str(text or "")
    value = LATEXIT_TOKEN_RE.sub(" ", value)
    value = CID_TOKEN_RE.sub(" ", value)
    value = PRIVATE_USE_RE.sub(" ", value)
    value = INLINE_MARKER_CLEAN_RE.sub("", value)
    value = BOX_GLYPH_RE.sub(" ", value)
    value = re.sub(r"(?m)^\s*\[(?:Formula candidate|Table candidate\s*\d*)\]\s*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def is_validated_table_block(block: dict[str, Any]) -> bool:
    if safe_block_type(block.get("type")) != "table":
        return False
    text = clean_projection_text(str(block.get("text") or ""))
    if block.get("table_validated") is True and str(block.get("table_source") or "") in VALID_TABLE_SOURCES:
        return True


    if text and re.search(r"(?m)^\s*\|.+\|\s*$", text):
        return True
    return False


def projection_leak_counts(text: str) -> dict[str, int]:
    value = str(text or "")
    return {
        "formula_candidate_markers": len(INLINE_MARKER_CLEAN_RE.findall(value)),
        "box_glyphs": len(BOX_GLYPH_RE.findall(value)),
        "cid_tokens": len(CID_TOKEN_RE.findall(value)),
        "private_use_glyphs": len(PRIVATE_USE_RE.findall(value)),
        "latexit_tokens": len(LATEXIT_TOKEN_RE.findall(value)),
        "reference_hits": reference_leak_hits(value),
    }


def build_downstream_projection_audit(metadata: dict[str, Any], *, sample_blocks: int = 8) -> dict[str, Any]:
    blocks = metadata.get("final_content_blocks") or metadata.get("content_blocks") or metadata.get("content_blocks_sample") or []
    if not isinstance(blocks, list):
        blocks = []
    qwen_parts: list[str] = []
    embedding_parts: list[str] = []
    table_parts: list[str] = []
    formula_parts: list[str] = []
    reference_parts: list[str] = []
    type_counts: Counter[str] = Counter()
    qwen_type_counts: Counter[str] = Counter()
    embedding_type_counts: Counter[str] = Counter()
    excluded_from_qwen_type_counts: Counter[str] = Counter()
    excluded_from_embedding_type_counts: Counter[str] = Counter()
    excluded_from_all_type_counts: Counter[str] = Counter()
    decision_samples: list[dict[str, Any]] = []
    excluded_samples: list[dict[str, Any]] = []
    validated_table_blocks = 0
    unvalidated_table_blocks = 0
    table_sources: Counter[str] = Counter()
    suspicious_table_blocks: list[dict[str, Any]] = []
    profile = str(metadata.get("page_profile") or "").lower()
    reference_context = bool(metadata.get("reference_page") or profile == "references")
    reference_context_embedding_suppressed = 0
    for idx, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        block_type = audit_block_type(block.get("type"))
        text = clean_projection_text(str(block.get("text") or ""))
        if not text:
            continue
        type_counts[block_type] += 1

        qwen_enabled = block_type in PROJECTION_QWEN_TYPES
        embedding_enabled = block_type in PROJECTION_EMBED_TYPES
        exclusion_reasons: list[str] = []





        if reference_context and block_type in PROJECTION_EMBED_TYPES:
            embedding_enabled = False
            reference_context_embedding_suppressed += 1
            exclusion_reasons.append("reference_context_embedding_suppressed")
        if block_type in {"noise", "unknown"}:
            qwen_enabled = False
            embedding_enabled = False
            exclusion_reasons.append(f"{block_type}_block")
        if block_type in {"table", "formula", "reference"}:
            embedding_enabled = False
            exclusion_reasons.append(f"{block_type}_kept_out_of_embeddings")

        if qwen_enabled:
            qwen_type_counts[block_type] += 1
            qwen_parts.append(text)
        else:
            excluded_from_qwen_type_counts[block_type] += 1
        if embedding_enabled:
            embedding_type_counts[block_type] += 1
            embedding_parts.append(text)
        else:
            excluded_from_embedding_type_counts[block_type] += 1
        if not qwen_enabled and not embedding_enabled:
            excluded_from_all_type_counts[block_type] += 1
            if len(excluded_samples) < max(0, sample_blocks):
                excluded_samples.append(
                    {
                        "block_index": idx,
                        "type": block_type,
                        "reasons": exclusion_reasons or ["not_enabled_for_projection"],
                        "snippet": text_snippet(text, 400),
                    }
                )
        if len(decision_samples) < max(0, sample_blocks):
            decision_samples.append(
                {
                    "block_index": idx,
                    "type": block_type,
                    "to_qwen": bool(qwen_enabled),
                    "to_embeddings": bool(embedding_enabled),
                    "excluded_reasons": exclusion_reasons,
                    "snippet": text_snippet(text, 260),
                }
            )

        if block_type == "table":
            if is_validated_table_block(block):
                validated_table_blocks += 1
                table_source = str(block.get("table_source") or "unknown")
                table_sources[table_source] += 1
                table_parts.append(text)
            else:
                unvalidated_table_blocks += 1
                suspicious_table_blocks.append(
                    {
                        "reason": str(block.get("table_rejected_reason") or "missing_validation"),
                        "fallback": str(block.get("table_rejected_fallback_type") or ""),
                        "snippet": text_snippet(text, 500),
                    }
                )
        elif block_type == "formula":
            formula_parts.append(text)
        elif block_type == "reference":
            reference_parts.append(text)

    qwen_text = clean_projection_text("\n\n".join(qwen_parts))
    embedding_text = clean_projection_text("\n\n".join(embedding_parts))
    tables_text = clean_projection_text("\n\n".join(table_parts))
    formulas_text = clean_projection_text("\n\n".join(formula_parts))
    references_text = clean_projection_text("\n\n".join(reference_parts))
    qwen_leaks = projection_leak_counts(qwen_text)
    embedding_leaks = projection_leak_counts(embedding_text)

    issues: list[str] = []
    qwen_leak_hits = sum(value for key, value in qwen_leaks.items() if key != "reference_hits")
    embedding_leak_hits = sum(value for key, value in embedding_leaks.items() if key != "reference_hits")
    if qwen_leak_hits > 0:
        issues.append("qwen_projection_leakage")
    if embedding_leak_hits > 0:
        issues.append("embedding_projection_leakage")
    if embedding_leaks.get("reference_hits", 0) > 0:
        issues.append("embedding_reference_leakage")
    parser_table_detected = int(metadata.get("table_count") or metadata.get("tables_detected") or 0)
    if parser_table_detected > 0 and type_counts.get("table", 0) == 0:
        issues.append("tables_detected_without_table_blocks")
    if type_counts.get("table", 0) > 0 and not tables_text:
        issues.append("table_block_without_table_projection")
    if unvalidated_table_blocks > 0:
        issues.append("table_blocks_without_validation")

    return {
        "projection_input_block_count": int(sum(type_counts.values())),
        "projection_input_type_counts": dict(type_counts),
        "qwen_projection_block_count": int(sum(qwen_type_counts.values())),
        "embedding_projection_block_count": int(sum(embedding_type_counts.values())),
        "qwen_projection_type_counts": dict(qwen_type_counts),
        "embedding_projection_type_counts": dict(embedding_type_counts),
        "excluded_from_qwen_block_count": int(sum(excluded_from_qwen_type_counts.values())),
        "excluded_from_embedding_block_count": int(sum(excluded_from_embedding_type_counts.values())),
        "excluded_from_all_projection_block_count": int(sum(excluded_from_all_type_counts.values())),
        "excluded_from_qwen_type_counts": dict(excluded_from_qwen_type_counts),
        "excluded_from_embedding_type_counts": dict(excluded_from_embedding_type_counts),
        "excluded_from_all_projection_type_counts": dict(excluded_from_all_type_counts),
        "projection_decision_samples": decision_samples[:sample_blocks],
        "projection_excluded_samples": excluded_samples[:sample_blocks],
        "qwen_projection_chars": len(qwen_text),
        "embedding_projection_chars": len(embedding_text),
        "table_projection_chars": len(tables_text),
        "formula_projection_chars": len(formulas_text),
        "reference_projection_chars": len(references_text),
        "qwen_projection_leakage_hits": qwen_leak_hits,
        "embedding_projection_leakage_hits": embedding_leak_hits,
        "embedding_reference_hits": int(embedding_leaks.get("reference_hits", 0)),
        "reference_context_embedding_suppressed_blocks": int(reference_context_embedding_suppressed),
        "table_blocks_without_qwen_projection": 1 if type_counts.get("table", 0) > 0 and qwen_type_counts.get("table", 0) == 0 else 0,
        "tables_detected_without_table_blocks": 1 if parser_table_detected > 0 and type_counts.get("table", 0) == 0 else 0,
        "table_blocks_validated_count": validated_table_blocks,
        "table_blocks_unvalidated_count": unvalidated_table_blocks,
        "table_blocks_without_validation": 1 if unvalidated_table_blocks > 0 else 0,
        "table_source_counts": dict(table_sources),
        "suspicious_table_blocks": suspicious_table_blocks[:8],
        "downstream_projection_issue_pages": 1 if issues else 0,
        "projection_issues": issues,
    }

def normalize_for_audit_compare(text: str) -> str:
    value = clean_projection_text(str(text or ""))
    value = HEADER_FOOTER_LEFTOVER_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value


def _metadata_blocks(metadata: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, list):
            return [block for block in value if isinstance(block, dict)]
    return []


def _block_type_counts(blocks: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for block in blocks:
        counts[audit_block_type(block.get("type"))] += 1
    return counts


def _joined_block_text(blocks: list[dict[str, Any]]) -> str:
    return "\n\n".join(str(block.get("text") or "").strip() for block in blocks if str(block.get("text") or "").strip())


def _count_header_footer_leftovers(blocks: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    count = 0
    samples: list[dict[str, Any]] = []
    for idx, block in enumerate(blocks):
        text = str(block.get("text") or "")
        matches = [m.group(0).strip() for m in HEADER_FOOTER_LEFTOVER_RE.finditer(text) if m.group(0).strip()]
        if not matches:
            continue
        count += len(matches)
        if len(samples) < 5:
            samples.append({"block_index": idx, "type": safe_block_type(block.get("type")), "matches": matches[:3], "snippet": text_snippet(text, 300)})
    return count, samples


def build_content_sync_audit(metadata: dict[str, Any], page_text: str, *, sample_blocks: int = 8) -> dict[str, Any]:
    """Audit final page.text vs final content_blocks without changing parser output."""
    final_blocks = _metadata_blocks(metadata, "final_content_blocks", "content_blocks", "content_blocks_sample")
    raw_blocks = _metadata_blocks(metadata, "raw_content_blocks", "raw_content_blocks_sample", "content_blocks_raw", "pre_cleanup_content_blocks")
    final_counts = _block_type_counts(final_blocks)
    raw_counts = _block_type_counts(raw_blocks)
    final_text = _joined_block_text(final_blocks)
    page_norm = normalize_for_audit_compare(page_text)
    blocks_norm = normalize_for_audit_compare(final_text)
    ratio = 1.0
    length_ratio = 1.0
    if page_norm or blocks_norm:
        ratio = SequenceMatcher(None, page_norm[:12000], blocks_norm[:12000]).ratio()
        length_ratio = len(blocks_norm) / max(1, len(page_norm))
    issues: list[str] = []
    samples: list[dict[str, Any]] = []


    if page_norm and not final_blocks:
        issues.append("final_blocks_missing_for_text")
    if final_blocks and not page_norm:
        issues.append("final_blocks_exist_but_page_text_empty")
    if page_norm and blocks_norm and (ratio < 0.72 or length_ratio < 0.45 or length_ratio > 1.65):
        issues.append("final_text_blocks_sync_low_ratio")
    not_in_page = 0
    for idx, block in enumerate(final_blocks):
        block_text = normalize_for_audit_compare(str(block.get("text") or ""))
        if not block_text:
            continue
        probe = block_text[: min(240, len(block_text))]
        if len(probe) >= 40 and probe not in page_norm:
            not_in_page += 1
            if len(samples) < max(0, sample_blocks):
                samples.append({
                    "block_index": idx,
                    "type": safe_block_type(block.get("type")),
                    "issue": "block_text_not_found_in_final_page_text",
                    "snippet": text_snippet(str(block.get("text") or ""), 500),
                })
    if not_in_page > 0 and not_in_page / max(1, len(final_blocks)) >= 0.25:
        issues.append("final_block_text_not_in_page_text")
    header_footer_count, header_footer_samples = _count_header_footer_leftovers(final_blocks)
    if header_footer_count > 0:
        issues.append("header_footer_left_in_final_blocks")
    samples.extend(header_footer_samples[: max(0, sample_blocks - len(samples))])
    critical = any(issue in {"final_blocks_missing_for_text", "final_blocks_exist_but_page_text_empty", "final_text_blocks_sync_low_ratio", "final_block_text_not_in_page_text"} for issue in issues)
    return {
        "raw_content_block_count": len(raw_blocks),
        "final_content_block_count": len(final_blocks),
        "raw_block_type_counts": dict(raw_counts),
        "final_block_type_counts": dict(final_counts),
        "final_blocks_text_chars": len(final_text),
        "final_text_blocks_sync_ratio": round(ratio, 4),
        "final_blocks_to_page_text_length_ratio": round(length_ratio, 4),
        "final_block_text_not_in_page_blocks": int(not_in_page),
        "final_header_footer_leftover_blocks": int(header_footer_count),
        "raw_content_blocks_available": 1 if raw_blocks else 0,
        "raw_content_blocks_unavailable_pages": 0 if raw_blocks else 1,
        "final_blocks_missing_pages": 1 if "final_blocks_missing_for_text" in issues else 0,
        "content_sync_low_ratio_pages": 1 if "final_text_blocks_sync_low_ratio" in issues else 0,
        "final_block_text_not_in_page_pages": 1 if "final_block_text_not_in_page_text" in issues else 0,
        "content_sync_issue_pages": 1 if critical else 0,
        "content_sync_warning_pages": 1 if issues and not critical else 0,
        "issues": issues,
        "samples": samples[:sample_blocks],
    }


def build_ocr_decision_risk_audit(
    metadata: dict[str, Any],
    page_text: str,
    *,
    page_score: float,
    page_warnings: list[str],
    ocr_enabled: bool,
    ocr_force: bool,
) -> dict[str, Any]:
    reason = normalize_ocr_reason(metadata.get("ocr_reason"))
    decision = str(metadata.get("ocr_decision") or metadata.get("ocr_merge_decision") or "").strip().lower()
    ocr_used = int(metadata.get("ocr_pages_used") or 0) > 0
    ocr_failed = int(metadata.get("ocr_pages_failed") or 0) > 0 or reason in {"engine_unavailable", "dependencies_missing", "ocr_failed"}
    bad_text_layer = bool(
        metadata.get("ocr_recommended")
        or metadata.get("low_confidence_page")
        or "ocr_recommended" in page_warnings
        or "possible_scanned_page" in page_warnings
        or "empty_text" in page_warnings
        or ("low_text_chars" in page_warnings and page_score < 0.52)
        or (len(str(page_text or "").strip()) < 120 and page_score < 0.45)
    )
    clear_used_reason = bool(
        ocr_force
        or bad_text_layer
        or reason in {"low_quality_score", "empty_text_layer", "applied"}
        or decision in {"prefer_ocr", "replace_low_quality", "ocr_only", "hybrid_lines_ocr_only"}
    )
    issues: list[str] = []
    if ocr_enabled and ocr_used and not clear_used_reason:
        issues.append("ocr_used_without_clear_reason")
    if ocr_enabled and bad_text_layer and not ocr_used and not ocr_failed:
        issues.append("ocr_skipped_on_bad_text_layer")
    if ocr_enabled and not metadata.get("ocr_reason"):
        issues.append("ocr_missing_reason")
    if not ocr_enabled and bad_text_layer:
        issues.append("ocr_recommended_but_disabled")
    return {
        "ocr_unexplained_used_pages": 1 if "ocr_used_without_clear_reason" in issues else 0,
        "ocr_skipped_bad_text_layer_pages": 1 if "ocr_skipped_on_bad_text_layer" in issues else 0,
        "ocr_missing_reason_pages": 1 if "ocr_missing_reason" in issues else 0,
        "ocr_decision_issue_pages": 1 if issues else 0,
        "issues": issues,
        "reason": reason,
        "decision": decision,
        "bad_text_layer": bool(bad_text_layer),
        "ocr_used": bool(ocr_used),
    }


def build_domain_specific_audit(page_text: str, *, audit_domain_mode: str, page_profile: str = "") -> dict[str, Any]:
    text = str(page_text or "")
    matches = DOMAIN_SPECIFIC_RE.findall(text)
    normalized = Counter(str(m).lower() for m in matches)
    word_count = max(1, len(re.findall(r"\b[\wА-Яа-я-]{2,}\b", text)))
    match_density = len(matches) / word_count
    profile = str(page_profile or "").lower()
    non_generic_profiles = {"title", "references", "reference_continuation", "figure_only", "figure_plate", "supplement"}
    domain_warning_applicable = profile not in non_generic_profiles and len(text) >= 320
    issue = bool(
        str(audit_domain_mode or "generic").lower() == "generic"
        and len(matches) >= 12
        and match_density >= 0.06
        and domain_warning_applicable
    )
    return {
        "domain_specific_matches": int(len(matches)),
        "domain_specific_top_terms": dict(normalized.most_common(8)),
        "domain_specific_generic_issue_pages": 1 if issue else 0,
        "issues": ["domain_specific_matches_in_generic_mode"] if issue else [],
    }


def diagnostic_recommendation(category: str) -> str:
    recommendations = {
        "content_sync": "Проверить пересборку final_content_blocks после финальной очистки page.text; downstream должен читать только синхронные final blocks.",
        "projection": "Проверить projection слой parser result -> RAG/Qwen: references/formulas/tables не должны уходить в embeddings как body.",
        "block_typing": "Проверить типизацию content_blocks и правила retype после очистки; не чинить extraction вслепую по одному примеру.",
        "layout": "Проверить reading order/layout detection на странице: колонки, короткие строки, axis/sidebar noise.",
        "ocr_decision": "Проверить OCR decision/preflight: причина запуска или пропуска OCR должна быть записана в metadata.",
        "domain_specific": "Если аудит запущен в generic mode, вынести предметные эвристики в materials/patents profile или запускать аудит с подходящим audit-domain-mode.",
        "headers_footers": "Проверить footer/header cleanup и синхронную очистку content_blocks вместе с page.text.",
    }
    return recommendations.get(category, "Проверить указанную зону parser audit по samples и metadata страницы.")


DIAGNOSTIC_CODE_ALIASES: dict[str, str] = {
    "final_text_blocks_sync_low_ratio": "final_text_blocks_sync_low_ratio",
    "final_block_text_not_in_page_text": "final_block_text_not_in_page_text",
    "final_blocks_missing_for_text": "final_blocks_missing_for_text",
    "final_blocks_exist_but_page_text_empty": "final_blocks_exist_but_page_text_empty",
    "header_footer_left_in_final_blocks": "duplicated_headers_footers",
    "reference_like_body_blocks": "references_in_body",
    "formula_like_body_blocks": "formulas_in_body",
    "table_like_body_blocks": "table_markdown_in_body",
    "caption_like_body_blocks": "caption_lost_as_body",
    "heading_like_body_blocks": "heading_lost_as_body",
    "body_like_caption_blocks": "caption_false_positive",
    "weak_table_blocks": "weak_table_block",
    "embedding_reference_leakage": "references_in_embeddings",
    "embedding_projection_leakage": "projection_noise_in_embeddings",
    "qwen_projection_leakage": "projection_noise_in_qwen",
    "table_blocks_without_validation": "table_without_validation",
    "tables_detected_without_table_blocks": "tables_without_final_table_blocks",
    "possible_column_mixing": "two_column_interleaved_order",
    "word_layout_used_on_two_column_page": "two_column_interleaved_order",
    "short_line_heavy": "layout_short_line_noise",
    "orphan_line_heavy": "layout_orphan_line_noise",
    "low_text_density": "layout_low_text_density",
    "ocr_used_without_clear_reason": "ocr_triggered_without_reason",
    "ocr_skipped_on_bad_text_layer": "ocr_skipped_on_bad_text_layer",
    "ocr_missing_reason": "ocr_missing_reason",
    "ocr_recommended_but_disabled": "ocr_skipped_on_bad_text_layer",
    "domain_specific_matches_in_generic_mode": "domain_terms_used_in_generic",
    "misclassification_risk_blocks": "low_margin_type_assignment",
    "low_margin_type_assignment": "low_margin_type_assignment",
}


def diagnostic_codes(category: str, issues: list[str]) -> list[str]:
    codes: list[str] = []
    for issue in issues:
        code = DIAGNOSTIC_CODE_ALIASES.get(str(issue), str(issue))
        if code not in codes:
            codes.append(code)
    return codes


def diagnostic_owner(category: str, codes: list[str]) -> str:
    if any(code in codes for code in {"final_text_blocks_sync_low_ratio", "final_block_text_not_in_page_text", "heading_lost_as_body"}):
        return "Agent 2 / content_blocks + final text sync"
    if any(code in codes for code in {"references_in_body", "formulas_in_body", "table_markdown_in_body", "caption_false_positive", "weak_table_block", "low_margin_type_assignment"}):
        return "Agent 3 / tables-captions-formulas-references typing"
    if any(code.startswith("projection_") or code in {"references_in_embeddings", "projection_noise_in_embeddings", "projection_noise_in_qwen"} for code in codes):
        return "Agent 5 / downstream projection audit boundary"
    if any(code.startswith("ocr_") for code in codes):
        return "Agent 4 / OCR decision + preflight"
    if any(code.startswith("two_column_") or code.startswith("layout_") for code in codes):
        return "Agent 6 / layout-reading order"
    if any(code == "domain_terms_used_in_generic" for code in codes):
        return "Agent 1 / domain profiles"
    if any(code == "duplicated_headers_footers" for code in codes):
        return "Agent 2 / cleanup sync"
    return f"Agent 8 / diagnostics triage ({category})"


def build_page_quality_diagnostics(
    *,
    file_name: str,
    page_no: int,
    page_text: str,
    method: str,
    page_score: float,
    page_warnings: list[str],
    page_profile: str,
    content_sync_audit: dict[str, Any],
    projection_audit: dict[str, Any],
    block_confusion_audit: dict[str, Any],
    layout_audit: dict[str, Any],
    ocr_risk_audit: dict[str, Any],
    domain_audit: dict[str, Any],
    sample_chars: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def add(severity: str, category: str, issues: list[str], metrics: dict[str, Any] | None = None, samples: list[dict[str, Any]] | None = None) -> None:
        if not issues:
            return
        codes = diagnostic_codes(category, issues)
        items.append({
            "file": file_name,
            "page": page_no,
            "severity": severity,
            "category": category,
            "issues": issues,
            "codes": codes,
            "recommended_owner": diagnostic_owner(category, codes),
            "recommendation": diagnostic_recommendation(category),
            "page_profile": page_profile,
            "method": method,
            "score": page_score,
            "warnings": page_warnings,
            "metrics": metrics or {},
            "samples": samples or [],
            "snippet": text_snippet(page_text, max_chars=sample_chars),
        })

    sync_issues = list(content_sync_audit.get("issues") or [])
    if sync_issues:
        severity = "CRITICAL" if int(content_sync_audit.get("content_sync_issue_pages") or 0) else "WARNING"
        category = "headers_footers" if sync_issues == ["header_footer_left_in_final_blocks"] else "content_sync"
        add(severity, category, sync_issues, {k: content_sync_audit.get(k) for k in (
            "raw_content_block_count", "final_content_block_count", "final_block_type_counts",
            "final_text_blocks_sync_ratio", "final_blocks_to_page_text_length_ratio",
            "final_block_text_not_in_page_blocks", "final_header_footer_leftover_blocks",
        )}, list(content_sync_audit.get("samples") or []))

    projection_issues = list(projection_audit.get("projection_issues") or [])
    if projection_issues:
        severity = "CRITICAL" if any("embedding" in issue or "reference" in issue for issue in projection_issues) else "WARNING"
        add(severity, "projection", projection_issues, {k: projection_audit.get(k) for k in (
            "projection_input_block_count", "qwen_projection_block_count", "embedding_projection_block_count",
            "excluded_from_embedding_block_count", "excluded_from_qwen_block_count", "excluded_from_all_projection_block_count",
            "qwen_projection_type_counts", "embedding_projection_type_counts", "excluded_from_embedding_type_counts",
            "qwen_projection_chars", "embedding_projection_chars", "qwen_projection_leakage_hits",
            "embedding_projection_leakage_hits", "embedding_reference_hits", "table_blocks_without_validation",
            "tables_detected_without_table_blocks",
        )}, list(projection_audit.get("suspicious_table_blocks") or []) + list(projection_audit.get("projection_excluded_samples") or [])[:3])

    block_issues = [key for key in (
        "reference_like_body_blocks", "formula_like_body_blocks", "table_like_body_blocks",
        "caption_like_body_blocks", "heading_like_body_blocks", "body_like_reference_blocks",
        "body_like_formula_blocks", "body_like_caption_blocks", "weak_table_blocks",
        "misclassification_risk_blocks",
    ) if int(block_confusion_audit.get(key) or 0) > 0]
    if block_issues:
        severity = "CRITICAL" if any(key in block_issues for key in {"reference_like_body_blocks", "formula_like_body_blocks", "table_like_body_blocks"}) else "WARNING"
        add(severity, "block_typing", block_issues, {"block_type_counts": block_confusion_audit.get("block_type_counts"), "issue_count": block_confusion_audit.get("block_confusion_issue_count")}, list(block_confusion_audit.get("samples") or []))

    layout_issues = [issue for issue in list(layout_audit.get("issues") or []) if issue != "two_column_detected"]
    if layout_issues:
        add("WARNING", "layout", layout_issues, {k: layout_audit.get(k) for k in ("line_count", "word_count", "avg_line_len", "short_line_ratio", "orphan_line_ratio", "numeric_axis_lines")})

    ocr_issues = list(ocr_risk_audit.get("issues") or [])
    if ocr_issues:
        severity = "CRITICAL" if "ocr_skipped_on_bad_text_layer" in ocr_issues else "WARNING"
        add(severity, "ocr_decision", ocr_issues, {k: ocr_risk_audit.get(k) for k in ("reason", "decision", "bad_text_layer", "ocr_used")})

    domain_issues = list(domain_audit.get("issues") or [])
    if domain_issues:
        add("WARNING", "domain_specific", domain_issues, {"matches": domain_audit.get("domain_specific_matches"), "top_terms": domain_audit.get("domain_specific_top_terms")})

    return items


DANGLING_HYPHEN_RE = re.compile(r"[A-Za-z]{2,}-\s*(?:\n\s*)+(?:\d{1,4}\s*(?:\n\s*)+)?[a-z]{2,}")
PAGE_NUMBER_IN_TEXT_RE = re.compile(r"\n\s*\d{1,4}\s*\n")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def sha1_short(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def safe_name(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9А-Яа-я._-]+", "_", path.stem).strip("._")
    return stem[:120] or "document"


def safe_relpath(path: Path, root: Path = ROOT) -> str:
    """Return a stable path for reports even when --out-base is outside project."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def resolve_tesseract_binary() -> str | None:
    path_cmd = shutil.which("tesseract")
    if path_cmd:
        return path_cmd
    for candidate in (
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ):
        if candidate.exists():
            return str(candidate)
    return None


def detect_ocr_runtime_availability() -> dict[str, Any]:
    engines: dict[str, dict[str, Any]] = {
        "tesseract": {"available": False, "reason": ""},
        "paddle": {"available": False, "reason": ""},
        "ocrmypdf": {"available": False, "reason": ""},
        "surya": {"available": False, "reason": "experimental"},
    }
    try:
        import pytesseract
        from PIL import Image
        import fitz
        tesseract_cmd = resolve_tesseract_binary()
        engines["tesseract"] = {
            "available": bool(tesseract_cmd),
            "reason": "" if tesseract_cmd else "binary_missing:tesseract",
            "binary": tesseract_cmd or "",
        }
    except Exception as exc:
        engines["tesseract"] = {"available": False, "reason": f"deps_missing:{exc.__class__.__name__}"}
    try:
        import paddleocr
        import paddle
        engines["paddle"] = {"available": True, "reason": ""}
    except Exception as exc:
        engines["paddle"] = {"available": False, "reason": f"deps_missing:{exc.__class__.__name__}"}
    try:
        engines["ocrmypdf"] = {"available": bool(shutil.which("ocrmypdf")), "reason": "" if shutil.which("ocrmypdf") else "binary_missing"}
    except Exception as exc:
        engines["ocrmypdf"] = {"available": False, "reason": f"check_failed:{exc.__class__.__name__}"}
    return {"engines": engines}


def compact_counter(counter: Counter[str], limit: int = 8) -> str:
    if not counter:
        return "-"
    return ";".join(f"{k}:{v}" for k, v in counter.most_common(limit))


def parse_compact_counter(value: str | None) -> Counter[str]:
    counter: Counter[str] = Counter()
    raw = str(value or "").strip()
    if not raw or raw == "-":
        return counter
    for chunk in raw.split(";"):
        if ":" not in chunk:
            continue
        key, val = chunk.rsplit(":", 1)
        key = key.strip()
        if not key:
            continue
        try:
            counter[key] += int(val.strip())
        except Exception:
            continue
    return counter


def normalize_ocr_reason(value: str | None) -> str:
    reason = str(value or "").strip().lower()
    return reason if reason in ALLOWED_OCR_REASONS else "ocr_failed"


def sample_list_hash(paths: list[Path], *, root: Path) -> str:
    rels = []
    for p in paths:
        rels.append(str(p.relative_to(root) if p.is_relative_to(root) else p))
    blob = "\n".join(sorted(rels)).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:12]


def text_snippet(text: str, max_chars: int = 500) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "…"


def count_middle_page_number_lines(text: str) -> int:
    """Count page-number-only lines that are probably inside content.

    Edge page numbers are normal PDF artifacts and are handled by the parser.
    They should not mark a whole document BAD. We only count page number lines
    that appear away from the first/last two non-empty lines.
    """
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) <= 4:
        return 0
    middle = lines[2:-2]
    return sum(1 for line in middle if re.fullmatch(r"\d{1,4}", line))


def count_suspicious_tokens(text: str) -> dict[str, int]:
    text = text or ""
    counts = {
        "control_chars": len(CONTROL_RE.findall(text)),
        "replacement_chars": text.count("�") + text.count("\ufffd"),
        "cid_tokens": len(CID_TOKEN_RE.findall(text)),
        "latexit_tokens": len(LATEXIT_TOKEN_RE.findall(text)),
        "private_use_glyphs": len(PRIVATE_USE_RE.findall(text)),
        "watermark_tokens": len(WATERMARK_TOKEN_RE.findall(text)),
        "dangling_hyphen_breaks": len(DANGLING_HYPHEN_RE.findall(text)),
        "page_number_lines": count_middle_page_number_lines(text),
    }
    pattern_hits = 0
    for pattern in SUSPICIOUS_TOKEN_PATTERNS:
        pattern_hits += len(pattern.findall(text))
    counts["suspicious_pattern_hits"] = pattern_hits
    return counts




def _count_numeric_table_rows(text: str) -> int:
    return len(NUMERIC_TABLE_ROW_RE.findall(str(text or "")))


def _looks_protected_reference_service_block(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    return bool(value and PROTECTED_REFERENCE_SECTION_RE.match(value))


def _looks_equation_numbered_body_block(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return False
    if not re.match(r"^\(\d{1,3}\)\s+(?:[a-zа-я]|[A-ZА-Я]?[a-zа-я]{2,})", value):
        return False
    return not BIBLIOGRAPHIC_SIGNAL_RE.search(value)


def _looks_reference_like_block(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if _looks_protected_reference_service_block(value) or _looks_equation_numbered_body_block(value):
        return False
    if REFERENCE_HEADING_HINT_RE.search(value):
        return True
    bib_lines = len(REFERENCE_BIB_LINE_HINT_RE.findall(value))
    if bib_lines >= 1:
        return True
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    enumerated_lines = [line for line in lines if REFERENCE_ENUMERATOR_RE.match(line)]
    signal_lines = [line for line in enumerated_lines if BIBLIOGRAPHIC_SIGNAL_RE.search(line)]
    if len(signal_lines) >= 2:
        return True
    if len(lines) <= 2 and len(signal_lines) == 1 and len(value) < 220:
        return False
    if len(enumerated_lines) >= 3 and len(signal_lines) >= 1:
        return True
    return bool(len(value) > 260 and reference_leak_hits(value) >= 2)


def _looks_formula_like_block(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if CAPTION_START_RE.search(value) or _looks_reference_like_block(value):
        return False
    math_hits = len(FORMULA_HEAVY_RE.findall(value))
    short_lines = [line.strip() for line in value.splitlines() if line.strip()]
    line_count = len(short_lines)
    word_count = len(re.findall(r"\b[\wА-Яа-я-]{2,}\b", value))
    math_density = math_hits / max(1, len(value))
    formula_line_count = sum(1 for line in short_lines if len(FORMULA_HEAVY_RE.findall(line)) >= 2 or re.search(r"\b(?:where|где)\b", line, re.IGNORECASE))
    sentence_like = len(SENTENCE_END_RE.findall(value))
    has_assignment = bool(re.search(r"(?m)^\s*(?:\(?\d+\)?\s*)?[A-Za-zαβγδλμσΩωπθ][A-Za-z0-9_{}^()]*\s*=", value))
    if sentence_like >= 1 and not has_assignment and math_hits < 12:
        return False
    if line_count > 10 and not has_assignment:
        return False
    if word_count > 26 and not has_assignment and math_density < 0.045:
        return False
    return bool(math_hits >= 10 or formula_line_count >= 3 or has_assignment)


def _looks_table_like_block(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if MARKDOWN_TABLE_RE.search(value):
        return True
    numeric_rows = _count_numeric_table_rows(value)
    if numeric_rows >= 2:
        return True
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    dense_rows = 0
    for line in lines:
        tokens = re.split(r"\s{2,}|\t+", line)
        if len([t for t in tokens if t.strip()]) >= 4 and len(re.findall(r"[-+]?\d+(?:[.,]\d+)?", line)) >= 2:
            dense_rows += 1
    return dense_rows >= 2


def _looks_caption_like_block(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    lines = [ln.strip() for ln in value.splitlines() if ln.strip()]
    first_line = lines[0] if lines else value



    if len(value) > 220:
        return False
    if len(first_line) > 120:
        return False
    if len(lines) > 2:
        return False
    word_count = len(re.findall(r"\b[\wА-Яа-я-]{2,}\b", value))
    if word_count > 22:
        return False
    if len(SENTENCE_END_RE.findall(value)) > 1:
        return False
    if not CAPTION_START_RE.match(first_line):
        return False


    return bool(STRICT_CAPTION_MARKER_RE.match(first_line))


def _looks_heading_like_block(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value or len(value) > 150 or len(value.split()) > 16:
        return False
    if not re.match(r"^[A-ZА-Я0-9]", value):
        return False
    symbol_ratio = len(re.findall(r"[^A-Za-zА-Яа-я0-9\s]", value)) / max(1, len(value))
    if symbol_ratio > 0.18:
        return False
    word_count = len(re.findall(r"\b[\wА-Яа-я-]{2,}\b", value))
    if word_count > 12:
        return False
    if SECTION_HEADING_RE.search(value):
        return True
    if re.match(r"^\d+(?:\.\d+)*\.?\s+[A-ZА-Я][A-Za-zА-Яа-я0-9,()\-/ ]{3,}$", value):
        return True
    letters = [ch for ch in value if ch.isalpha()]
    if len(letters) >= 6 and sum(1 for ch in letters if ch.isupper()) / max(1, len(letters)) >= 0.75:
        return True
    return False


def _looks_body_like_block(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if len(value) < 220:
        return False
    if _looks_reference_like_block(value) or _looks_table_like_block(value):
        return False
    sentence_like = len(SENTENCE_END_RE.findall(value))
    math_density = len(FORMULA_HEAVY_RE.findall(value)) / max(1, len(value))
    return sentence_like >= 2 and math_density < 0.035


def _looks_ocr_noise_like_block(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return False
    if len(value) < 48:
        return False
    alpha = len(re.findall(r"[A-Za-zА-Яа-я]", value))
    digits = len(re.findall(r"\d", value))
    punct = len(re.findall(r"[^A-Za-zА-Яа-я0-9\s]", value))
    upper = len(re.findall(r"[A-ZА-Я]", value))
    alpha_ratio = alpha / max(1, len(value))
    punct_ratio = punct / max(1, len(value))
    upper_ratio = upper / max(1, alpha) if alpha else 0.0


    return bool(
        alpha_ratio < 0.62
        or punct_ratio > 0.14
        or (upper_ratio > 0.72 and digits >= 4)
    )


def build_block_confusion_audit(metadata: dict[str, Any], page_text: str, *, sample_blocks: int = 8) -> dict[str, Any]:
    """Find suspicious content_block typing without calling downstream services.

    This is intentionally heuristic: it does not replace PDFParser typing; it gives
    the audit a second opinion so parser patches can be compared faster.
    """
    blocks = metadata.get("content_blocks") or metadata.get("content_blocks_sample") or []
    if not isinstance(blocks, list):
        blocks = []
    counters: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []

    for idx, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        block_type = safe_block_type(block.get("type"))
        raw_text = str(block.get("text") or "")
        clean_text = clean_projection_text(raw_text)
        if not clean_text:
            continue
        type_counts[block_type] += 1

        reference_like = _looks_reference_like_block(clean_text)
        formula_like = _looks_formula_like_block(clean_text)
        table_like = _looks_table_like_block(clean_text)
        caption_like = _looks_caption_like_block(clean_text)
        heading_like = _looks_heading_like_block(clean_text)
        body_like = _looks_body_like_block(clean_text)
        ocr_noise_like = _looks_ocr_noise_like_block(clean_text)
        score_margin = float(block.get("score_margin") or 0.0)
        reason_tokens = {str(x).strip().lower() for x in (block.get("reasons") or []) if str(x).strip()}
        prose_formula_suppressed = bool(
            {"prose_sentence_penalty_formula", "formula_like_but_prose_penalized", "inline_formula_prose_body_preferred", "assignment_units_prose_body_preferred", "assignment_fragment_prose_body_preferred"} & reason_tokens
        )
        reference_fragment_suppressed = bool(
            {"reference_fragment_context_boost", "reference_short_continuation_boost", "reference_citation_id_boost", "reference_year_pages_boost"} & reason_tokens
        )
        heading_noise_suppressed = "heading_like_but_prose_or_symbolic" in reason_tokens
        heading_author_affil_suppressed = "author_affiliation_list_preferred" in reason_tokens
        caption_inline_prose_suppressed = "inline_figure_reference_prose_body_preferred" in reason_tokens
        caption_figure_ref_lead_suppressed = "figure_reference_lead_prose_body_preferred" in reason_tokens
        caption_marker_prose_suppressed = "caption_marker_prose_body_preferred" in reason_tokens
        caption_overrun_prose_suppressed = "caption_overrun_prose_body_preferred" in reason_tokens
        pipe_grid_table_suppressed = "pipe_grid_table_like" in reason_tokens
        markdown_table_suppressed = "markdown_table_block_like" in reason_tokens
        pipe_separator_noise_suppressed = "pipe_separator_noise_line" in reason_tokens
        noise_margin_suppressed = bool(
            {"isolated_glyph_line_noise", "pipe_separator_noise_line", "ocr_noise_like_block"} & reason_tokens
        )

        page_profile = str(metadata.get("page_profile") or "").lower()
        figure_context = page_profile in {"figure_only", "figure_plate", "figure_label_only", "supplement"}
        reference_context = page_profile in {"references", "reference_continuation"}
        formula_context = page_profile == "formula_heavy"
        issues: list[str] = []
        if block_type == "body" and reference_like and not body_like and not reference_context and not reference_fragment_suppressed:
            issues.append("reference_like_body_block")
        if (
            block_type == "body"
            and formula_like
            and not body_like
            and not prose_formula_suppressed
            and not ocr_noise_like
            and not figure_context
            and not formula_context
            and len(clean_text) <= 260
        ):
            issues.append("formula_like_body_block")
        if block_type == "body" and table_like and not pipe_grid_table_suppressed and not markdown_table_suppressed and not pipe_separator_noise_suppressed:
            issues.append("table_like_body_block")
        if (
            block_type == "body"
            and caption_like
            and not body_like
            and not ocr_noise_like
            and len(clean_text) <= 220
            and not figure_context
            and not caption_inline_prose_suppressed
            and not caption_figure_ref_lead_suppressed
            and not caption_marker_prose_suppressed
        ):
            issues.append("caption_like_body_block")
        heading_word_count = len(re.findall(r"\b[\wА-Яа-я-]{2,}\b", clean_text))
        heading_sentence_like = len(SENTENCE_END_RE.findall(clean_text))
        non_alpha = len(re.findall(r"[^A-Za-zА-Яа-я0-9\s]", clean_text))
        non_alpha_ratio = non_alpha / max(1, len(clean_text))
        if (
            block_type == "body"
            and heading_like
            and len(clean_text) < 64
            and heading_word_count <= 10
            and heading_sentence_like == 0
            and non_alpha_ratio < 0.16
            and not heading_noise_suppressed
            and not heading_author_affil_suppressed
            and not ocr_noise_like
            and not figure_context
            and not formula_context
        ):
            issues.append("heading_like_body_block")
        if block_type == "reference" and body_like and not reference_like:


            if (
                page_profile != "references"
                or _looks_protected_reference_service_block(clean_text)
                or _looks_equation_numbered_body_block(clean_text)
            ):
                issues.append("body_like_reference_block")
        if block_type == "formula" and body_like and not formula_like and not formula_context and len(clean_text) <= 260:
            issues.append("body_like_formula_block")
        if (
            block_type == "caption"
            and body_like
            and not caption_like
            and not figure_context
            and len(clean_text) <= 220
            and not caption_overrun_prose_suppressed
        ):
            issues.append("body_like_caption_block")
        if block_type == "table" and not is_validated_table_block(block) and not table_like:
            issues.append("weak_table_block")
        block_confidence = float(block.get("confidence") or block.get("quality") or 0.0)
        low_margin_structural_consensus = bool(
            (block_type == "heading" and heading_like and not body_like)
            or (block_type == "reference" and reference_like and not body_like)
            or (block_type == "formula" and formula_like and not body_like)
            or (block_type == "caption" and caption_like and not body_like)
            or (block_type == "table" and table_like)
        )
        if (
            ((score_margin > 0.0 and score_margin < 0.08) or (0.52 <= block_confidence < 0.62 and score_margin < 0.04 and block_type != "unknown"))
            and not low_margin_structural_consensus
            and not noise_margin_suppressed
        ):
            issues.append("low_margin_type_assignment")

        for issue in issues:
            counters[issue + "s"] += 1
        if issues and len(samples) < max(0, sample_blocks):
            samples.append(
                {
                    "block_index": idx,
                    "declared_type": block_type,
                    "issues": issues,
                    "hints": {
                        "reference_like": reference_like,
                        "formula_like": formula_like,
                        "table_like": table_like,
                        "caption_like": caption_like,
                        "heading_like": heading_like,
                        "body_like": body_like,
                    },
                    "snippet": text_snippet(clean_text, max_chars=650),
                }
            )

    issue_count = sum(counters.values())
    return {
        "block_confusion_issue_pages": 1 if issue_count else 0,
        "block_confusion_issue_count": int(issue_count),
        "block_type_counts": dict(type_counts),
        "reference_like_body_blocks": int(counters.get("reference_like_body_blocks", 0)),
        "formula_like_body_blocks": int(counters.get("formula_like_body_blocks", 0)),
        "table_like_body_blocks": int(counters.get("table_like_body_blocks", 0)),
        "caption_like_body_blocks": int(counters.get("caption_like_body_blocks", 0)),
        "heading_like_body_blocks": int(counters.get("heading_like_body_blocks", 0)),
        "body_like_reference_blocks": int(counters.get("body_like_reference_blocks", 0)),
        "body_like_formula_blocks": int(counters.get("body_like_formula_blocks", 0)),
        "body_like_caption_blocks": int(counters.get("body_like_caption_blocks", 0)),
        "weak_table_blocks": int(counters.get("weak_table_blocks", 0)),
        "misclassification_risk_blocks": int(counters.get("low_margin_type_assignments", 0)),
        "samples": samples,
    }


def build_layout_diagnostics(metadata: dict[str, Any], page_text: str, *, method: str, warnings: list[str], page_score: float) -> dict[str, Any]:
    lines = [line.rstrip() for line in str(page_text or "").splitlines() if line.strip()]
    non_empty_line_count = len(lines)
    word_count = len(re.findall(r"\b[\wА-Яа-я-]{2,}\b", str(page_text or "")))
    char_count = len(str(page_text or ""))
    avg_line_len = char_count / max(1, non_empty_line_count)
    short_lines = sum(1 for line in lines if 1 <= len(line.strip()) <= 18)
    orphan_lines = sum(1 for line in lines if len(line.strip()) <= 3)
    numeric_axis_lines = sum(1 for line in lines if GRAPH_AXIS_LINE_RE.match(line))
    columns_detected = bool(metadata.get("columns_detected"))
    column_mixing_noise = int(metadata.get("column_mixing_noise") or 0)
    rotated_sidebar_noise = int(metadata.get("rotated_sidebar_noise") or 0)
    is_formula_heavy = bool(metadata.get("formula_heavy_page") or str(metadata.get("page_profile") or "").lower() == "formula_heavy")
    is_graph_axis_page = bool(metadata.get("graph_axis_text_detected") or "graph_axis_text_detected" in warnings)
    layout_content_rich = bool(word_count >= 160 and page_score >= 0.70)
    suppress_short_orphan_noise = bool((is_formula_heavy or is_graph_axis_page) and layout_content_rich)
    figure_caption_line_count = len(
        re.findall(r"(?mi)^\s*(?:fig(?:ure)?\.?|fig\.)\s*[s]?\d+[a-z]?\b", str(page_text or ""))
    )
    low_density_caption_page = bool(
        non_empty_line_count <= 3
        and word_count >= 60
        and figure_caption_line_count >= 2
    )
    low_density_disclosure_page = bool(
        non_empty_line_count <= 7
        and word_count >= 35
        and bool(
            re.search(
                r"(?:conflict\s+of\s+interest|fund(?:ing|ed)|acknowledg(?:e|ment)|contract\s+no\.?|department\s+of\s+energy)",
                str(page_text or ""),
                re.IGNORECASE,
            )
        )
    )

    issues: list[str] = []
    if columns_detected:
        issues.append("two_column_detected")
    if columns_detected and method == "pdfplumber_word_layout":
        issues.append("word_layout_used_on_two_column_page")
    if column_mixing_noise > 0 or "possible_two_columns" in warnings:
        issues.append("possible_column_mixing")
        if columns_detected or method in {"pdfplumber_word_layout", "pdfplumber_layout"}:
            issues.append("two_column_interleaved_order")
    if (
        non_empty_line_count >= 12
        and short_lines / max(1, non_empty_line_count) >= 0.42
        and page_score < 0.82
        and not suppress_short_orphan_noise
    ):
        issues.append("short_line_heavy")
    if non_empty_line_count >= 12 and orphan_lines / max(1, non_empty_line_count) >= 0.18 and not suppress_short_orphan_noise:
        issues.append("orphan_line_heavy")
    if (
        word_count < 80
        and char_count > 0
        and not metadata.get("figure_only_page")
        and not metadata.get("reference_page")
        and not low_density_caption_page
        and not low_density_disclosure_page
    ):
        issues.append("low_text_density")
    if numeric_axis_lines >= 4 and not metadata.get("graph_axis_text_detected"):
        issues.append("axis_like_lines_not_marked")
    if rotated_sidebar_noise > 0:
        issues.append("rotated_sidebar_noise")

    return {
        "layout_issue_pages": 1 if any(issue != "two_column_detected" for issue in issues) else 0,
        "layout_issue_count": len([issue for issue in issues if issue != "two_column_detected"]),
        "two_column_pages": 1 if columns_detected else 0,
        "word_layout_two_column_pages": 1 if "word_layout_used_on_two_column_page" in issues else 0,
        "possible_column_mixing_pages": 1 if "possible_column_mixing" in issues else 0,
        "short_line_heavy_pages": 1 if "short_line_heavy" in issues else 0,
        "orphan_line_heavy_pages": 1 if "orphan_line_heavy" in issues else 0,
        "low_text_density_pages": 1 if "low_text_density" in issues else 0,
        "axis_like_lines_not_marked_pages": 1 if "axis_like_lines_not_marked" in issues else 0,
        "rotated_sidebar_noise_pages": 1 if "rotated_sidebar_noise" in issues else 0,
        "line_count": non_empty_line_count,
        "word_count": word_count,
        "avg_line_len": round(avg_line_len, 2),
        "short_line_ratio": round(short_lines / max(1, non_empty_line_count), 3),
        "orphan_line_ratio": round(orphan_lines / max(1, non_empty_line_count), 3),
        "numeric_axis_lines": numeric_axis_lines,
        "issues": issues,
    }


def _summary_identity(row: dict[str, Any]) -> str:
    sha = str(row.get("sha1_12") or "").strip()
    if sha:
        return "sha1:" + sha
    return "file:" + str(row.get("file") or row.get("filename") or "").replace("\\", "/").lower()


def load_summary_rows(path: Path) -> list[dict[str, Any]]:
    value = path
    if value.is_dir():
        candidate = value / "summary.json"
        if not candidate.exists():
            candidate = value / "latest" / "summary.json"
        value = candidate
    if not value.exists():
        raise FileNotFoundError(f"Baseline summary not found: {value}")
    if value.suffix.lower() == ".zip":
        with zipfile.ZipFile(value) as zf:
            names = [name for name in zf.namelist() if name.endswith("summary.json")]
            if not names:
                raise FileNotFoundError(f"summary.json not found inside zip: {value}")
            with zf.open(sorted(names, key=len)[0]) as f:
                return json.loads(f.read().decode("utf-8"))
    return json.loads(value.read_text(encoding="utf-8"))


def _numeric_delta(current: dict[str, Any], previous: dict[str, Any], key: str) -> float | int | None:
    try:
        cur = float(current.get(key) or 0)
        prev = float(previous.get(key) or 0)
    except Exception:
        return None
    delta = cur - prev
    if delta.is_integer():
        return int(delta)
    return round(delta, 4)


def build_regression_report(rows: list[dict[str, Any]], baseline_rows: list[dict[str, Any]]) -> dict[str, Any]:
    previous_by_id = {_summary_identity(row): row for row in baseline_rows if _summary_identity(row)}
    current_by_id = {_summary_identity(row): row for row in rows if _summary_identity(row)}
    documents: list[dict[str, Any]] = []
    totals = Counter()

    for identity, current in current_by_id.items():
        previous = previous_by_id.get(identity)
        if previous is None:
            totals["new_docs"] += 1
            documents.append({"identity": identity, "file": current.get("file"), "change": "new"})
            continue
        prev_status = str(previous.get("status") or "")
        cur_status = str(current.get("status") or "")
        prev_rank = STATUS_RANK.get(prev_status, 99)
        cur_rank = STATUS_RANK.get(cur_status, 99)
        if cur_rank > prev_rank:
            change = "regressed"
            totals["regressed_docs"] += 1
        elif cur_rank < prev_rank:
            change = "improved"
            totals["improved_docs"] += 1
        else:
            change = "same"
            totals["same_status_docs"] += 1

        metric_deltas: dict[str, Any] = {}
        for key in REGRESSION_METRICS:
            if key == "status":
                continue
            delta = _numeric_delta(current, previous, key)
            if delta not in (None, 0):
                metric_deltas[key] = delta
        if metric_deltas and change == "same":
            totals["metric_changed_docs"] += 1
        documents.append(
            {
                "identity": identity,
                "file": current.get("file"),
                "previous_status": prev_status,
                "current_status": cur_status,
                "change": change,
                "metric_deltas": metric_deltas,
            }
        )

    for identity, previous in previous_by_id.items():
        if identity not in current_by_id:
            totals["missing_docs"] += 1
            documents.append({"identity": identity, "file": previous.get("file"), "change": "missing"})

    documents.sort(key=lambda item: (item.get("change") not in {"regressed", "improved"}, str(item.get("file") or item.get("identity") or "")))
    return {
        "baseline_docs": len(baseline_rows),
        "current_docs": len(rows),
        "totals": dict(totals),
        "documents": documents,
    }


def has_severe_metric_regression(regression_report: dict[str, Any] | None) -> bool:
    if not regression_report:
        return False
    severe_positive_metrics = {
        "empty_pages",
        "problem_pages",
        "serious_pages",
        "reading_order_issues",
        "column_mixing_issues",
        "content_block_typing_issue_pages",
        "reference_like_body_blocks",
        "body_like_reference_blocks",
        "formula_like_body_blocks",
        "body_like_formula_blocks",
        "table_like_body_blocks",
        "tables_detected_without_table_blocks",
        "table_blocks_without_validation",
    }
    for doc in regression_report.get("documents", []):
        deltas = doc.get("metric_deltas") or {}
        if not isinstance(deltas, dict):
            continue
        for key in severe_positive_metrics:
            try:
                if float(deltas.get(key) or 0) > 0:
                    return True
            except Exception:
                continue
    return False


QUALITY_GATE_METRICS = {
    "empty_pages",
    "problem_pages",
    "serious_pages",
    "reading_order_issues",
    "column_mixing_issues",
    "content_block_typing_issue_pages",
    "reference_like_body_blocks",
    "body_like_reference_blocks",
    "formula_like_body_blocks",
    "body_like_formula_blocks",
    "table_like_body_blocks",
    "tables_detected_without_table_blocks",
    "unknown_blocks_count",
    "misclassification_risk_blocks",
    "low_confidence_blocks",
    "ocr_pages_failed",
    "ocr_quality_regressed_pages",
}

OCR_QUALITY_GATE_METRICS = {
    "ocr_pages_failed",
    "ocr_quality_regressed_pages",
    "unknown_blocks_count",
    "low_confidence_blocks",
}
OCR_QUALITY_GATE_THRESHOLDS = {
    "ocr_pages_failed": 0.0,
    "ocr_quality_regressed_pages": 0.0,
    "unknown_blocks_count": 2.0,
    "low_confidence_blocks": 3.0,
}
MAX_OCR_DEBUG_ITEMS = 500


def build_quality_regression_summary(regression_report: dict[str, Any] | None) -> dict[str, Any]:
    if not regression_report:
        return {
            "triggered": False,
            "regressed_docs": 0,
            "metric_hits": {},
            "documents": [],
        }
    metric_hits: Counter[str] = Counter()
    docs: list[dict[str, Any]] = []
    for doc in regression_report.get("documents", []):
        deltas = doc.get("metric_deltas") or {}
        if not isinstance(deltas, dict):
            continue
        positive_hits: dict[str, float] = {}
        for key in QUALITY_GATE_METRICS:
            try:
                delta = float(deltas.get(key) or 0.0)
            except Exception:
                continue
            if delta > 0:
                positive_hits[key] = delta
                metric_hits[key] += 1
        if positive_hits:
            docs.append(
                {
                    "identity": doc.get("identity"),
                    "file": doc.get("file"),
                    "change": doc.get("change"),
                    "quality_metric_deltas": positive_hits,
                }
            )
    docs.sort(key=lambda item: str(item.get("file") or item.get("identity") or ""))
    return {
        "triggered": bool(docs),
        "regressed_docs": len(docs),
        "metric_hits": dict(metric_hits),
        "documents": docs,
    }


def build_ocr_quality_regression_summary(
    regression_report: dict[str, Any] | None,
    *,
    ocr_enabled: bool,
) -> dict[str, Any]:
    if not regression_report or not ocr_enabled:
        return {"triggered": False, "regressed_docs": 0, "metric_hits": {}, "documents": []}
    metric_hits: Counter[str] = Counter()
    docs: list[dict[str, Any]] = []
    for doc in regression_report.get("documents", []):
        deltas = doc.get("metric_deltas") or {}
        if not isinstance(deltas, dict):
            continue
        positive_hits: dict[str, float] = {}
        for key in OCR_QUALITY_GATE_METRICS:
            try:
                delta = float(deltas.get(key) or 0.0)
            except Exception:
                continue
            threshold = float(OCR_QUALITY_GATE_THRESHOLDS.get(key, 0.0))
            if delta > threshold:
                positive_hits[key] = delta
                metric_hits[key] += 1
        try:
            improved_delta = float(deltas.get("ocr_quality_improved_pages") or 0.0)
        except Exception:
            improved_delta = 0.0
        try:
            regressed_delta = float(deltas.get("ocr_quality_regressed_pages") or 0.0)
        except Exception:
            regressed_delta = 0.0
        if improved_delta < regressed_delta:
            positive_hits["ocr_improved_vs_regressed_balance"] = regressed_delta - improved_delta
            metric_hits["ocr_improved_vs_regressed_balance"] += 1
        if positive_hits:
            docs.append(
                {
                    "identity": doc.get("identity"),
                    "file": doc.get("file"),
                    "change": doc.get("change"),
                    "ocr_quality_metric_deltas": positive_hits,
                }
            )
    docs.sort(key=lambda item: str(item.get("file") or item.get("identity") or ""))
    return {
        "triggered": bool(docs),
        "regressed_docs": len(docs),
        "metric_hits": dict(metric_hits),
        "documents": docs,
    }

def quality_label(
    *,
    avg_score: float,
    min_score: float,
    review_pages: int,
    serious_pages: int,
    total_pages: int,
    suspicious_hits: int,
    failed: bool,
) -> str:
    if failed:
        return "FAIL"

    page_count = max(1, int(total_pages or 1))
    serious_ratio = serious_pages / page_count
    review_ratio = review_pages / page_count




    if avg_score < 0.55:
        return "BAD"
    if serious_pages >= max(6, math.ceil(page_count * 0.35)) and avg_score < 0.78:
        return "BAD"
    if serious_ratio >= 0.45 and min_score < 0.25:
        return "BAD"
    if suspicious_hits > max(40, page_count * 5) and avg_score < 0.82:
        return "BAD"





    if serious_pages > 0:
        return "WARN"
    if review_pages > 0:
        return "WARN"
    if suspicious_hits > 0:
        return "WARN"
    if avg_score < 0.78 or min_score < 0.25:
        return "WARN"
    if review_ratio >= 0.60 and avg_score < 0.85:
        return "WARN"
    return "OK"

def page_to_dict(page: Any) -> dict[str, Any]:
    if hasattr(page, "as_dict"):
        return page.as_dict()
    return {
        "page_number": getattr(page, "page_number", None),
        "text": getattr(page, "text", ""),
        "method": getattr(page, "method", "unknown"),
        "quality_score": getattr(page, "quality_score", 0),
        "warnings": getattr(page, "warnings", []),
        "metadata": getattr(page, "metadata", {}),
    }


def analyze_pdf(
    parser: PDFParser,
    pdf_path: Path,
    *,
    out_text_dir: Path,
    out_meta_dir: Path,
    mode: str,
    parser_mode: str,
    force_strategy: str,
    ocr_mode: str,
    extract_tables: bool,
    keep_headers: bool,
    repair_cross_page: bool,
    domain_profile: str,
    content_blocks_mode: str,
    rebuild_content_blocks_from_final_text: bool,
    emit_content_blocks: bool,
    ocr_enabled: bool,
    ocr_control_mode: str,
    ocr_engine: str,
    ocr_force: bool,
    ocr_skip: bool,
    ocr_pages: str,
    ocr_dpi: int,
    ocr_languages: str,
    ocr_merge_strategy: str,
    ocr_min_quality_score: float,
    ocr_min_confidence: float,
    ocr_min_text_chars: int,
    ocr_min_words: int,
    ocr_min_text_density: float,
    ocr_broken_encoding_noise_ratio: float,
    ocr_allow_paddle: bool,
    ocr_allow_ocrmypdf_page: bool,
    ocr_debug: bool,
    ocr_surya_experimental: bool,
    ai_mode: str,
    ai_enabled: bool,
    ai_provider: str,
    ai_model: str,
    ai_render_dpi: int,
    ai_page_image_format: str,
    audit_domain_mode: str,
    sample_chars: int,
    sample_blocks: int = 8,
) -> dict[str, Any]:
    started = time.perf_counter()
    file_size = pdf_path.stat().st_size
    file_hash = sha1_short(pdf_path)
    base_name = f"{safe_name(pdf_path)}__{file_hash}"
    text_path = out_text_dir / f"{base_name}.txt"
    meta_path = out_meta_dir / f"{base_name}.json"

    options = {
        "parser_mode": parser_mode,
        "extraction_mode": mode,
        "force_strategy": force_strategy,
        "ocr_mode": ocr_mode,
        "detect_columns": True,
        "extract_tables": extract_tables,
        "remove_headers_footers": not keep_headers,
        "merge_hyphenated_words": True,
        "normalize_math": True,
        "normalize_cid_glyphs": True,
        "normalize_private_use_glyphs": True,
        "mark_formula_candidates": True,
        "repair_cross_page_continuations": repair_cross_page,
        "domain_profile": domain_profile,
        "content_blocks_mode": content_blocks_mode,
        "rebuild_content_blocks_from_final_text": rebuild_content_blocks_from_final_text,
        "emit_content_blocks": emit_content_blocks,
        "ocr_enabled": ocr_enabled,
        "ocr_control_mode": ocr_control_mode,
        "ocr_engine": ocr_engine,
        "ocr_force": ocr_force,
        "ocr_skip": ocr_skip,
        "ocr_pages": ocr_pages,
        "ocr_only_pages": ocr_pages,
        "ocr_dpi": int(ocr_dpi),
        "ocr_languages": ocr_languages,
        "ocr_merge_strategy": ocr_merge_strategy,
        "ocr_min_quality_score": float(ocr_min_quality_score),
        "ocr_min_confidence": float(ocr_min_confidence),
        "ocr_min_text_chars": int(ocr_min_text_chars),
        "ocr_min_words": int(ocr_min_words),
        "ocr_min_text_density": float(ocr_min_text_density),
        "ocr_broken_encoding_noise_ratio": float(ocr_broken_encoding_noise_ratio),
        "ocr_allow_paddle": bool(ocr_allow_paddle),
        "ocr_allow_ocrmypdf_page": bool(ocr_allow_ocrmypdf_page),
        "ocr_debug": bool(ocr_debug),
        "ocr_surya_experimental": bool(ocr_surya_experimental),
        "ai_mode": str(ai_mode),
        "ai_enabled": bool(ai_enabled),
        "ai_provider": str(ai_provider),
        "ai_model": str(ai_model),
        "ai_render_dpi": int(ai_render_dpi),
        "ai_page_image_format": str(ai_page_image_format),
        "drop_graph_axis_from_body": True,
        "drop_arxiv_footer_from_body": True,
        "line_type_metadata": True,
    }

    result: dict[str, Any] = {
        "file": str(pdf_path.relative_to(ROOT) if pdf_path.is_relative_to(ROOT) else pdf_path),
        "filename": pdf_path.name,
        "sha1_12": file_hash,
        "size_bytes": file_size,
        "status": "OK",
        "error": "",
        "traceback": "",
        "pages": 0,
        "chars": 0,
        "avg_score": 0.0,
        "primary_selected_strategy": "-",
        "selected_strategies": "-",
        "selected_strategy_counts": "-",
        "ocr_used_page_count": 0,
        "ocr_used_pages": "-",
        "ai_used_page_count": 0,
        "ai_used_pages": "-",
        "ai_status": "-",
        "ai_reason": "-",
        "min_score": 0.0,
        "problem_pages": 0,
        "serious_pages": 0,
        "review_pages": 0,
        "informational_pages": 0,
        "ordinary_ok_pages": 0,
        "content_block_typing_issue_pages": 0,
        "unknown_blocks_count": 0,
        "misclassification_risk_blocks": 0,
        "unknown_recovered_as_strong_type": 0,
        "low_confidence_blocks": 0,
        "ocr_pages_used": 0,
        "ocr_pages_skipped": 0,
        "ocr_pages_failed": 0,
        "ocr_recommended_but_disabled": 0,
        "ocr_avg_confidence": 0.0,
        "ocr_engine_counts": "-",
        "ocr_reason_counts": "-",
        "ocr_quality_improved_pages": 0,
        "ocr_quality_regressed_pages": 0,
        "ocr_debug_artifacts_count": 0,
        "ocr_debug_artifacts_truncated": 0,
        "methods": "-",
        "warnings": "-",
        "suspicious_hits": 0,
        "dangling_hyphen_breaks": 0,
        "page_number_lines": 0,
        "cid_tokens": 0,
        "latexit_tokens": 0,
        "private_use_glyphs": 0,
        "watermark_tokens": 0,
        "footnote_pages": 0,
        "watermark_words_removed": 0,
        "figure_heavy_pages": 0,
        "figure_only_pages": 0,
        "graph_axis_pages": 0,
        "reference_pages": 0,
        "formula_heavy_pages": 0,
        "footnote_false_positive_candidates": 0,
        "rejected_footnotes_graph_axis": 0,
        "rejected_footnotes_reference": 0,
        "rejected_footnotes_table": 0,
        "rejected_footnotes_figure_label": 0,
        "reference_context_footnotes_disabled_pages": 0,
        "title_page_affiliation_footnotes": 0,
        "graph_axis_informational_pages": 0,
        "page_profiles": "-",
        "title_pages": 0,
        "reference_informational_pages": 0,
        "figure_only_informational_pages": 0,
        "figure_plate_pages": 0,
        "graph_heavy_pages": 0,
        "arxiv_footer_lines_removed": 0,
        "graph_axis_lines_removed": 0,
        "page_number_lines_removed": 0,
        "non_body_lines_removed": 0,
        "math_microline_repairs": 0,
        "content_block_count": 0,
        "content_body_blocks": 0,
        "content_caption_blocks": 0,
        "content_formula_blocks": 0,
        "content_table_blocks": 0,
        "content_reference_blocks": 0,
        "content_noise_blocks": 0,
        "body_blocks_on_reference_pages": 0,
        "body_blocks_on_formula_heavy_pages": 0,
        "content_blocks_pua_after_cleanup": 0,
        "content_blocks_cid_after_cleanup": 0,
        "content_blocks_latexit_after_cleanup": 0,
        "reference_pages_without_reference_blocks": 0,
        "formula_heavy_pages_without_formula_blocks": 0,
        "content_block_retyped_to_reference_count": 0,
        "content_block_retyped_to_formula_count": 0,
        "content_block_retyped_to_caption_count": 0,
        "content_block_split_mixed_count": 0,
        "content_block_dropped_noise_count": 0,
        "content_block_typing_issue_pages": 0,
        "ordinary_ok_pages": 0,
        "line_type_body": 0,
        "line_type_caption": 0,
        "line_type_formula": 0,
        "line_type_reference": 0,
        "line_type_graph_axis": 0,
        "line_type_arxiv_footer": 0,
        "downstream_projection_issue_pages": 0,
        "block_confusion_issue_pages": 0,
        "block_confusion_issue_count": 0,
        "reference_like_body_blocks": 0,
        "formula_like_body_blocks": 0,
        "table_like_body_blocks": 0,
        "caption_like_body_blocks": 0,
        "heading_like_body_blocks": 0,
        "body_like_reference_blocks": 0,
        "body_like_formula_blocks": 0,
        "body_like_caption_blocks": 0,
        "weak_table_blocks": 0,
        "layout_issue_pages": 0,
        "layout_issue_count": 0,
        "two_column_pages": 0,
        "word_layout_two_column_pages": 0,
        "possible_column_mixing_pages": 0,
        "short_line_heavy_pages": 0,
        "orphan_line_heavy_pages": 0,
        "low_text_density_pages": 0,
        "axis_like_lines_not_marked_pages": 0,
        "rotated_sidebar_noise_pages": 0,
        "qwen_projection_chars": 0,
        "embedding_projection_chars": 0,
        "projection_input_block_count": 0,
        "qwen_projection_block_count": 0,
        "embedding_projection_block_count": 0,
        "excluded_from_qwen_block_count": 0,
        "excluded_from_embedding_block_count": 0,
        "excluded_from_all_projection_block_count": 0,
        "qwen_projection_type_counts": "-",
        "embedding_projection_type_counts": "-",
        "excluded_from_qwen_type_counts": "-",
        "excluded_from_embedding_type_counts": "-",
        "excluded_from_all_projection_type_counts": "-",
        "table_projection_chars": 0,
        "formula_projection_chars": 0,
        "reference_projection_chars": 0,
        "qwen_projection_leakage_hits": 0,
        "embedding_projection_leakage_hits": 0,
        "embedding_reference_hits": 0,
        "table_blocks_without_qwen_projection": 0,
        "tables_detected_without_table_blocks": 0,
        "table_candidates_raw_count": 0,
        "table_candidates_accepted_count": 0,
        "table_candidates_rejected_count": 0,
        "table_candidates_rejected_plot_axis_grid": 0,
        "table_candidates_rejected_no_table_semantics": 0,
        "table_candidates_rejected_too_small": 0,
        "table_blocks_validated_count": 0,
        "table_blocks_unvalidated_count": 0,
        "table_blocks_without_validation": 0,
        "raw_content_block_count": 0,
        "final_content_block_count": 0,
        "raw_content_blocks_unavailable_pages": 0,
        "content_sync_issue_pages": 0,
        "content_sync_warning_pages": 0,
        "content_sync_low_ratio_pages": 0,
        "final_blocks_missing_pages": 0,
        "final_block_text_not_in_page_pages": 0,
        "final_header_footer_leftover_blocks": 0,
        "final_text_blocks_sync_ratio_min": 1.0,
        "final_block_type_counts": "-",
        "domain_specific_matches": 0,
        "domain_specific_generic_issue_pages": 0,
        "domain_specific_top_terms": "-",
        "ocr_unexplained_used_pages": 0,
        "ocr_skipped_bad_text_layer_pages": 0,
        "ocr_missing_reason_pages": 0,
        "ocr_decision_issue_pages": 0,
        "critical_diagnostic_pages": 0,
        "warning_diagnostic_pages": 0,
        "critical_diagnostic_count": 0,
        "warning_diagnostic_count": 0,
        "diagnostic_categories": "-",
        "diagnostic_codes": "-",
        "elapsed_sec": 0.0,
        "text_path": safe_relpath(text_path),
        "meta_path": safe_relpath(meta_path),
        "sample": "",
    }

    problem_page_items: list[dict[str, Any]] = []
    informational_page_items: list[dict[str, Any]] = []
    content_block_issue_items: list[dict[str, Any]] = []
    block_confusion_items: list[dict[str, Any]] = []
    layout_issue_items: list[dict[str, Any]] = []
    quality_diagnostic_items: list[dict[str, Any]] = []
    ocr_debug_items: list[dict[str, Any]] = []

    try:
        pages = parser.extract_pages_from_file(str(pdf_path), options=options)
        pages_dicts = [page_to_dict(page) for page in pages]
        full_text = "\n\n".join(str(p.get("text") or "").strip() for p in pages_dicts if str(p.get("text") or "").strip()).strip()
        text_path.write_text(full_text, encoding="utf-8")
        meta_path.write_text(json.dumps(pages_dicts, ensure_ascii=False, indent=2), encoding="utf-8")

        scores = [float(p.get("quality_score") or 0.0) for p in pages_dicts]
        method_counter = Counter(str(p.get("method") or "unknown") for p in pages_dicts)
        strategy_counter: Counter[str] = Counter()
        selected_strategy_order: list[str] = []
        ocr_used_pages: list[int] = []
        ocr_engine_counter: Counter[str] = Counter()
        ocr_reason_counter: Counter[str] = Counter()
        warning_counter: Counter[str] = Counter()
        suspicious_total = Counter()
        classification_total = Counter()
        ocr_conf_sum = 0.0
        ocr_conf_count = 0
        final_block_type_total: Counter[str] = Counter()
        domain_term_total: Counter[str] = Counter()
        min_sync_ratio = 1.0

        for p in pages_dicts:
            page_no = int(p.get("page_number") or 0)
            page_text = str(p.get("text") or "")
            page_score = float(p.get("quality_score") or 0.0)
            page_warnings = [str(w) for w in (p.get("warnings") or [])]
            warning_counter.update(page_warnings)
            metadata = p.get("metadata") if isinstance(p.get("metadata"), dict) else {}
            selected_strategy = str(metadata.get("selected_strategy") or metadata.get("extraction_strategy") or p.get("method") or "unknown").strip().lower()
            if selected_strategy:
                strategy_counter[selected_strategy] += 1
                if selected_strategy not in selected_strategy_order:
                    selected_strategy_order.append(selected_strategy)
            if bool(metadata.get("ocr_used")) or int(metadata.get("ocr_pages_used") or 0) > 0 or selected_strategy == "ocr":
                ocr_used_pages.append(page_no)
            reason_name = normalize_ocr_reason(metadata.get("ocr_reason"))
            if reason_name:
                ocr_reason_counter[reason_name] += 1
            if isinstance(metadata.get("ocr_debug_payload"), dict):
                if len(ocr_debug_items) < MAX_OCR_DEBUG_ITEMS:
                    ocr_debug_items.append(
                        {
                            "file": result["file"],
                            "page": page_no,
                            "engine": str(metadata.get("ocr_engine") or ""),
                            "reason": reason_name,
                            "decision": str(metadata.get("ocr_decision") or ""),
                            "payload": metadata.get("ocr_debug_payload"),
                        }
                    )
                else:
                    classification_total["ocr_debug_artifacts_truncated"] += 1
            if not ocr_enabled and bool(metadata.get("ocr_recommended")):
                classification_total["ocr_recommended_but_disabled"] += 1
            page_profile = str(metadata.get("page_profile") or "unknown")
            classification_total[f"page_profile:{page_profile}"] += 1
            projection_audit = build_downstream_projection_audit(metadata, sample_blocks=sample_blocks)
            for proj_key in (
                "downstream_projection_issue_pages",
                "projection_input_block_count",
                "qwen_projection_block_count",
                "embedding_projection_block_count",
                "excluded_from_qwen_block_count",
                "excluded_from_embedding_block_count",
                "excluded_from_all_projection_block_count",
                "qwen_projection_chars",
                "embedding_projection_chars",
                "table_projection_chars",
                "formula_projection_chars",
                "reference_projection_chars",
                "qwen_projection_leakage_hits",
                "embedding_projection_leakage_hits",
                "embedding_reference_hits",
                "reference_context_embedding_suppressed_blocks",
                "table_blocks_without_qwen_projection",
                "tables_detected_without_table_blocks",
                "table_blocks_validated_count",
                "table_blocks_unvalidated_count",
                "table_blocks_without_validation",
            ):
                classification_total[proj_key] += int(projection_audit.get(proj_key) or 0)
            for prefix, key in (
                ("qwen_projection_type", "qwen_projection_type_counts"),
                ("embedding_projection_type", "embedding_projection_type_counts"),
                ("excluded_from_qwen_type", "excluded_from_qwen_type_counts"),
                ("excluded_from_embedding_type", "excluded_from_embedding_type_counts"),
                ("excluded_from_all_projection_type", "excluded_from_all_projection_type_counts"),
            ):
                for block_type, count in Counter(projection_audit.get(key) or {}).items():
                    classification_total[f"{prefix}:{block_type}"] += int(count or 0)
            projection_issues = list(projection_audit.get("projection_issues") or [])
            if projection_issues:
                content_block_issue_items.append(
                    {
                        "file": result["file"],
                        "page": page_no,
                        "severity": "DOWNSTREAM",
                        "projection_issues": projection_issues,
                        "projection_audit": {k: v for k, v in projection_audit.items() if k != "projection_issues"},
                        "suspicious_table_blocks": projection_audit.get("suspicious_table_blocks") or [],
                        "page_profile": page_profile,
                        "warnings": page_warnings,
                        "snippet": text_snippet(page_text, max_chars=sample_chars),
                    }
                )

            content_sync_audit = build_content_sync_audit(metadata, page_text, sample_blocks=sample_blocks)
            min_sync_ratio = min(min_sync_ratio, float(content_sync_audit.get("final_text_blocks_sync_ratio") or 1.0))
            final_block_type_total.update(Counter(content_sync_audit.get("final_block_type_counts") or {}))
            for sync_key in (
                "raw_content_block_count",
                "final_content_block_count",
                "raw_content_blocks_unavailable_pages",
                "content_sync_issue_pages",
                "content_sync_warning_pages",
                "content_sync_low_ratio_pages",
                "final_blocks_missing_pages",
                "final_block_text_not_in_page_pages",
                "final_header_footer_leftover_blocks",
            ):
                classification_total[sync_key] += int(content_sync_audit.get(sync_key) or 0)

            ocr_risk_audit = build_ocr_decision_risk_audit(
                metadata,
                page_text,
                page_score=page_score,
                page_warnings=page_warnings,
                ocr_enabled=ocr_enabled,
                ocr_force=ocr_force,
            )
            for ocr_risk_key in (
                "ocr_unexplained_used_pages",
                "ocr_skipped_bad_text_layer_pages",
                "ocr_missing_reason_pages",
                "ocr_decision_issue_pages",
            ):
                classification_total[ocr_risk_key] += int(ocr_risk_audit.get(ocr_risk_key) or 0)

            domain_audit = build_domain_specific_audit(
                page_text,
                audit_domain_mode=audit_domain_mode,
                page_profile=str(metadata.get("page_profile") or ""),
            )
            classification_total["domain_specific_matches"] += int(domain_audit.get("domain_specific_matches") or 0)
            classification_total["domain_specific_generic_issue_pages"] += int(domain_audit.get("domain_specific_generic_issue_pages") or 0)
            domain_term_total.update(Counter(domain_audit.get("domain_specific_top_terms") or {}))

            block_confusion_audit = build_block_confusion_audit(metadata, page_text, sample_blocks=sample_blocks)
            for diag_key in (
                "block_confusion_issue_pages",
                "block_confusion_issue_count",
                "reference_like_body_blocks",
                "formula_like_body_blocks",
                "table_like_body_blocks",
                "caption_like_body_blocks",
                "heading_like_body_blocks",
                "body_like_reference_blocks",
                "body_like_formula_blocks",
                "body_like_caption_blocks",
                "weak_table_blocks",
            ):
                classification_total[diag_key] += int(block_confusion_audit.get(diag_key) or 0)
            if block_confusion_audit.get("block_confusion_issue_pages"):
                block_confusion_items.append(
                    {
                        "file": result["file"],
                        "page": page_no,
                        "page_profile": page_profile,
                        "method": p.get("method"),
                        "score": page_score,
                        "warnings": page_warnings,
                        "summary": {k: v for k, v in block_confusion_audit.items() if k not in {"samples", "block_type_counts"}},
                        "block_type_counts": block_confusion_audit.get("block_type_counts") or {},
                        "samples": block_confusion_audit.get("samples") or [],
                    }
                )

            layout_audit = build_layout_diagnostics(
                metadata,
                page_text,
                method=str(p.get("method") or "unknown"),
                warnings=page_warnings,
                page_score=page_score,
            )
            for layout_key in (
                "layout_issue_pages",
                "layout_issue_count",
                "two_column_pages",
                "word_layout_two_column_pages",
                "possible_column_mixing_pages",
                "short_line_heavy_pages",
                "orphan_line_heavy_pages",
                "low_text_density_pages",
                "axis_like_lines_not_marked_pages",
                "rotated_sidebar_noise_pages",
            ):
                classification_total[layout_key] += int(layout_audit.get(layout_key) or 0)
            if layout_audit.get("layout_issue_pages"):
                layout_issue_items.append(
                    {
                        "file": result["file"],
                        "page": page_no,
                        "page_profile": page_profile,
                        "method": p.get("method"),
                        "score": page_score,
                        "warnings": page_warnings,
                        "layout": layout_audit,
                        "snippet": text_snippet(page_text, max_chars=sample_chars),
                    }
                )

            page_diagnostics = build_page_quality_diagnostics(
                file_name=result["file"],
                page_no=page_no,
                page_text=page_text,
                method=str(p.get("method") or "unknown"),
                page_score=page_score,
                page_warnings=page_warnings,
                page_profile=page_profile,
                content_sync_audit=content_sync_audit,
                projection_audit=projection_audit,
                block_confusion_audit=block_confusion_audit,
                layout_audit=layout_audit,
                ocr_risk_audit=ocr_risk_audit,
                domain_audit=domain_audit,
                sample_chars=sample_chars,
            )
            if page_diagnostics:
                quality_diagnostic_items.extend(page_diagnostics)
                for item in page_diagnostics:
                    severity = str(item.get("severity") or "WARNING").upper()
                    category = str(item.get("category") or "unknown")
                    classification_total[f"diagnostic_category:{category}"] += 1
                    for code in item.get("codes") or []:
                        classification_total[f"diagnostic_code:{code}"] += 1
                    if severity == "CRITICAL":
                        classification_total["critical_diagnostic_count"] += 1
                    else:
                        classification_total["warning_diagnostic_count"] += 1

            for key in (
                "arxiv_footer_lines_removed",
                "removed_arxiv_footer_lines",
                "removed_graph_axis_lines",
                "removed_page_number_lines",
                "non_body_lines_removed",
                "math_microline_repairs",
                "content_block_count",
                "content_block_body_count",
                "content_block_caption_count",
                "content_block_formula_count",
                "content_block_table_count",
                "content_block_reference_count",
                "content_block_noise_count",
                "content_block_unknown_count",
                "body_blocks_on_reference_pages",
                "body_blocks_on_formula_heavy_pages",
                "content_blocks_pua_after_cleanup",
                "content_blocks_cid_after_cleanup",
                "content_blocks_latexit_after_cleanup",
                "reference_pages_without_reference_blocks",
                "formula_heavy_pages_without_formula_blocks",
                "content_block_retyped_to_reference_count",
                "content_block_retyped_to_formula_count",
                "content_block_retyped_to_caption_count",
                "content_block_split_mixed_count",
                "content_block_dropped_noise_count",
                "caption_continuation_lines",
                "caption_continuation_blocks",
                "formula_candidate_count",
                "math_symbol_count",
                "reference_continuation_page",
                "line_type_body",
                "line_type_caption",
                "line_type_formula",
                "line_type_reference",
                "line_type_graph_axis",
                "line_type_arxiv_footer",
                "table_candidates_raw_count",
                "table_candidates_accepted_count",
                "table_candidates_rejected_count",
                "table_candidates_rejected_plot_axis_grid",
                "table_candidates_rejected_no_table_semantics",
                "table_candidates_rejected_too_small",
                "ocr_pages_used",
                "ocr_pages_skipped",
                "ocr_pages_failed",
                "ocr_recommended_but_disabled",
                "ocr_quality_improved_pages",
                "ocr_quality_regressed_pages",
            ):
                try:
                    classification_total[key] += int(metadata.get(key) or 0)
                except Exception:
                    pass
            if metadata.get("ocr_pages_used"):
                engine_name = str(metadata.get("ocr_engine") or "unknown").strip().lower()
                ocr_engine_counter[engine_name or "unknown"] += 1
                try:
                    conf = float(metadata.get("ocr_avg_confidence") or 0.0)
                except Exception:
                    conf = 0.0
                if conf > 0:
                    ocr_conf_sum += conf
                    ocr_conf_count += 1
            blocks = metadata.get("content_blocks") or metadata.get("content_blocks_sample") or []
            if isinstance(blocks, list):
                low_conf_blocks = 0
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    try:
                        if float(block.get("confidence") or 0.0) < 0.52:
                            low_conf_blocks += 1
                    except Exception:
                        continue
                classification_total["low_confidence_blocks"] += low_conf_blocks
            suspicious = Counter(count_suspicious_tokens(page_text))
            suspicious_total.update(suspicious)
            metadata_noise = int(metadata.get("rotated_sidebar_noise") or 0) + int(metadata.get("column_mixing_noise") or 0)
            stripped = page_text.strip()
            label_only_page = bool(LABEL_ONLY_RE.match(stripped))
            formula_or_figure_like = bool(FORMULA_HINT_RE.search(page_text) or FIGURE_ONLY_HINT_RE.search(page_text) or label_only_page)
            figure_heavy = bool(metadata.get("figure_heavy_page") or "figure_heavy_page" in page_warnings)
            figure_only = bool(metadata.get("figure_only_page") or "figure_only_page" in page_warnings or label_only_page)
            graph_axis = bool(metadata.get("graph_axis_text_detected") or "graph_axis_text_detected" in page_warnings)
            reference_page = bool(metadata.get("reference_page") or "reference_page" in page_warnings or reference_page_hint(page_text))
            formula_heavy = bool(metadata.get("formula_heavy_page") or "formula_heavy_page" in page_warnings)
            reference_continuation = bool(metadata.get("reference_continuation_page") or "reference_continuation_page" in page_warnings)
            caption_continuation_lines = int(metadata.get("caption_continuation_lines") or 0)
            caption_continuation_blocks = int(metadata.get("caption_continuation_blocks") or 0)
            formula_candidate_count = int(metadata.get("formula_candidate_count") or 0)
            content_formula_blocks = int(metadata.get("content_block_formula_count") or 0)
            math_symbol_count = int(metadata.get("math_symbol_count") or 0)
            figure_plate = bool(metadata.get("figure_plate_page"))
            graph_heavy = bool(metadata.get("graph_heavy_page"))
            if figure_plate:
                classification_total["figure_plate_pages"] += 1
            if graph_heavy:
                classification_total["graph_heavy_pages"] += 1
            if figure_heavy:
                classification_total["figure_heavy_pages"] += 1
            if figure_only:
                classification_total["figure_only_pages"] += 1
            if graph_axis:
                classification_total["graph_axis_pages"] += 1
            if reference_page:
                classification_total["reference_pages"] += 1
            if reference_continuation:
                classification_total["reference_continuation_pages"] += 1
            if caption_continuation_blocks:
                classification_total["caption_continuation_blocks"] += caption_continuation_blocks
                classification_total["caption_continuation_lines"] += caption_continuation_lines
            if formula_heavy:
                classification_total["formula_heavy_pages"] += 1

            severe_noise = (
                suspicious.get("control_chars", 0) > 0
                or suspicious.get("replacement_chars", 0) > 0
                or metadata_noise > 0
                or suspicious.get("suspicious_pattern_hits", 0) > 0
            )



            cid_tokens = suspicious.get("cid_tokens", 0)
            latexit_tokens = suspicious.get("latexit_tokens", 0)
            private_use_glyphs = suspicious.get("private_use_glyphs", 0)
            watermark_tokens = suspicious.get("watermark_tokens", 0)
            footnote_line_count = int(metadata.get("footnote_line_count") or 0)
            watermark_words_removed = int(metadata.get("watermark_words_removed") or 0)
            rejected_graph_axis = int(metadata.get("rejected_footnote_graph_axis") or 0)
            rejected_reference = int(metadata.get("rejected_footnote_reference") or 0)
            rejected_table = int(metadata.get("rejected_footnote_table") or 0)
            rejected_figure_label = int(metadata.get("rejected_footnote_figure_label") or 0)
            reference_context_disabled = int(metadata.get("reference_context_footnotes_disabled") or 0)
            classification_total["rejected_footnotes_graph_axis"] += rejected_graph_axis
            classification_total["rejected_footnotes_reference"] += rejected_reference
            classification_total["rejected_footnotes_table"] += rejected_table
            classification_total["rejected_footnotes_figure_label"] += rejected_figure_label
            if reference_context_disabled:
                classification_total["reference_context_footnotes_disabled_pages"] += 1



            title_page = bool(
                page_no == 1
                and page_score >= 0.45
                and not severe_noise
                and cid_tokens == 0
                and latexit_tokens == 0
                and private_use_glyphs == 0
                and (
                    TITLE_AFFILIATION_RE.search(page_text)
                    or re.search(r"\b(?:Abstract|Keywords?)\b", page_text, re.IGNORECASE)
                )
            )
            if title_page:
                classification_total["title_pages"] += 1

            title_page_affiliation_footnotes = bool(
                title_page
                and footnote_line_count > 0
                and page_score >= 0.70
                and TITLE_AFFILIATION_RE.search(page_text)
            )
            if title_page_affiliation_footnotes:
                classification_total["title_page_affiliation_footnotes"] += 1




            graph_axis_informational = bool(
                graph_axis
                and not severe_noise
                and cid_tokens == 0
                and latexit_tokens == 0
                and private_use_glyphs == 0
                and (figure_heavy or formula_or_figure_like or page_score >= 0.75)
                and page_score >= 0.30
            )
            if graph_axis_informational:
                classification_total["graph_axis_informational_pages"] += 1



            reference_informational = bool(
                (reference_page or reference_continuation)
                and not severe_noise
                and cid_tokens == 0
                and latexit_tokens == 0
                and private_use_glyphs == 0
                and page_score >= 0.20
            )
            if reference_informational:
                classification_total["reference_informational_pages"] += 1



            figure_only_informational = bool(
                (figure_only or label_only_page)
                and not severe_noise
                and cid_tokens == 0
                and latexit_tokens == 0
                and private_use_glyphs == 0
            )
            if figure_only_informational:
                classification_total["figure_only_informational_pages"] += 1

            formula_heavy_informational = bool(
                formula_heavy
                and not severe_noise
                and cid_tokens == 0
                and latexit_tokens == 0
                and private_use_glyphs == 0
                and (page_score >= 0.30 or formula_candidate_count >= 2 or content_formula_blocks >= 3 or math_symbol_count >= 15)
            )
            if formula_heavy_informational:
                classification_total["formula_heavy_informational_pages"] += 1

            block_body_on_reference = int(metadata.get("body_blocks_on_reference_pages") or 0)
            block_body_on_formula = int(metadata.get("body_blocks_on_formula_heavy_pages") or 0)
            block_pua_after = int(metadata.get("content_blocks_pua_after_cleanup") or 0)
            block_cid_after = int(metadata.get("content_blocks_cid_after_cleanup") or 0)
            block_latexit_after = int(metadata.get("content_blocks_latexit_after_cleanup") or 0)
            block_ref_without_reference = int(metadata.get("reference_pages_without_reference_blocks") or 0)
            block_formula_without_formula = int(metadata.get("formula_heavy_pages_without_formula_blocks") or 0)
            projection_reference_leaks = int(projection_audit.get("embedding_reference_hits") or 0)
            reference_typing_issue = bool(
                (block_body_on_reference > 0 or block_ref_without_reference > 0)
                and not reference_informational
            )
            if reference_informational and projection_reference_leaks > 0:
                reference_typing_issue = True
            content_block_typing_issue = bool(
                reference_typing_issue
                or block_pua_after > 0
                or block_cid_after > 0
                or block_latexit_after > 0
                or (block_formula_without_formula > 0 and formula_heavy and int(metadata.get("content_block_body_count") or 0) > 0)
            )
            if content_block_typing_issue:
                classification_total["content_block_typing_issue_pages"] += 1

            clean_short_body = bool(
                not severe_noise
                and cid_tokens == 0
                and latexit_tokens == 0
                and private_use_glyphs == 0
                and not (figure_heavy or reference_page or formula_heavy or title_page)
                and len(stripped) >= 500
                and page_score >= 0.42
                and ("word_layout_mode" in page_warnings or str(p.get("method") or "") == "pdfplumber_word_layout")
            )
            if clean_short_body:
                classification_total["clean_short_body_pages"] += 1

            footnote_false_positive = (
                footnote_line_count > 0
                and not title_page_affiliation_footnotes
                and not reference_informational
                and not figure_only_informational
                and (reference_page or ((figure_heavy or graph_axis) and not figure_only))
            )
            if footnote_false_positive:
                classification_total["footnote_false_positive_candidates"] += 1
            pua_heavy = private_use_glyphs > 25 and not (formula_or_figure_like or formula_heavy or reference_page)
            cid_heavy = cid_tokens > 12 and not (formula_or_figure_like or formula_heavy or reference_page)
            latexit_heavy = latexit_tokens > 0 and not (formula_heavy or figure_heavy)
            low_text = len(stripped) < 120
            likely_figure_only = (figure_only or label_only_page or (low_text and formula_or_figure_like)) and not severe_noise

            serious = (
                severe_noise
                or cid_heavy
                or pua_heavy
                or latexit_heavy
                or "empty_text" in page_warnings
                or ("possible_scanned_page" in page_warnings and len(stripped) < 150 and not likely_figure_only)
                or (page_score < 0.25 and not likely_figure_only and not reference_informational and not formula_heavy_informational)
            )
            dangling_breaks = suspicious.get("dangling_hyphen_breaks", 0)
            page_number_lines = suspicious.get("page_number_lines", 0)
            harmless_layout_mode = bool(
                "word_layout_mode" in page_warnings
                and not severe_noise
                and cid_tokens == 0
                and latexit_tokens == 0
                and private_use_glyphs == 0
                and (page_score >= 0.72 or clean_short_body)
            )
            review = (
                serious
                or (page_score < 0.68 and not (figure_heavy or reference_page or formula_heavy or title_page or clean_short_body))
                or any(w in BAD_WARNING_HINTS for w in page_warnings if w not in {"possible_scanned_page", "word_layout_mode"})
                or ("possible_scanned_page" in page_warnings and not likely_figure_only and not figure_only_informational)
                or (dangling_breaks > 0 and page_score < 0.86 and not reference_informational and not formula_heavy_informational)
                or cid_tokens > 0
                or latexit_tokens > 0
                or private_use_glyphs > 0
                or (page_number_lines > 5 and page_score < 0.72 and not reference_informational)
                or (watermark_words_removed > 0 and not reference_page)
                or (low_text and not likely_figure_only and not reference_informational and not formula_heavy_informational)
                or footnote_false_positive
                or content_block_typing_issue
            )
            special_informational_page = bool(
                title_page_affiliation_footnotes
                or graph_axis_informational
                or reference_informational
                or figure_only_informational
                or (figure_plate and not severe_noise and page_score >= 0.40)
                or formula_heavy_informational
                or (title_page and not review)
            )
            ordinary_ok_page = bool((clean_short_body or harmless_layout_mode) and not special_informational_page and not review and not serious)
            if ordinary_ok_page:
                classification_total["ordinary_ok_pages"] += 1

            if (special_informational_page or clean_short_body or harmless_layout_mode) and not serious and not content_block_typing_issue:



                review = False
            if special_informational_page and not serious:
                informational_page_items.append(
                    {
                        "file": result["file"],
                        "page": page_no,
                        "severity": "INFO",
                        "method": p.get("method"),
                        "score": page_score,
                        "warnings": page_warnings,
                        "metadata_noise": metadata_noise,
                        "suspicious": dict(suspicious),
                        "classes": {
                            "title_page": title_page,
                            "figure_heavy_page": figure_heavy,
                            "figure_only_page": figure_only,
                            "figure_only_informational": figure_only_informational,
                            "graph_axis_text_detected": graph_axis,
                            "graph_axis_informational": graph_axis_informational,
                            "reference_page": reference_page,
                            "reference_continuation_page": reference_continuation,
                            "reference_informational": reference_informational,
                            "formula_heavy_page": formula_heavy,
                            "formula_heavy_informational": formula_heavy_informational,
                            "clean_short_body": clean_short_body,
                            "caption_continuation_blocks": caption_continuation_blocks,
                            "label_only_page": label_only_page,
                            "footnote_false_positive_candidate": footnote_false_positive,
                            "title_page_affiliation_footnotes": title_page_affiliation_footnotes,
                            "harmless_layout_mode": harmless_layout_mode,
                            "content_block_typing_issue": content_block_typing_issue,
                            "ordinary_ok_page": ordinary_ok_page,
                        },
                        "snippet": text_snippet(page_text, max_chars=sample_chars),
                    }
                )

            if review:
                problem_page_items.append(
                    {
                        "file": result["file"],
                        "page": page_no,
                        "severity": "SERIOUS" if serious else "REVIEW",
                        "method": p.get("method"),
                        "score": page_score,
                        "warnings": page_warnings,
                        "metadata_noise": metadata_noise,
                        "suspicious": dict(suspicious),
                        "classes": {
                            "figure_heavy_page": figure_heavy,
                            "figure_only_page": figure_only,
                            "graph_axis_text_detected": graph_axis,
                            "graph_axis_informational": graph_axis_informational,
                            "reference_page": reference_page,
                            "reference_continuation_page": reference_continuation,
                            "formula_heavy_page": formula_heavy,
                            "formula_heavy_informational": formula_heavy_informational,
                            "clean_short_body": clean_short_body,
                            "label_only_page": label_only_page,
                            "footnote_false_positive_candidate": footnote_false_positive,
                            "title_page_affiliation_footnotes": title_page_affiliation_footnotes,
                            "content_block_typing_issue": content_block_typing_issue,
                        },
                        "snippet": text_snippet(page_text, max_chars=sample_chars),
                    }
                )

        avg_score = statistics.mean(scores) if scores else 0.0
        min_score = min(scores) if scores else 0.0
        serious_pages = sum(1 for item in problem_page_items if item.get("severity") == "SERIOUS")
        review_pages = len(problem_page_items)
        informational_pages = len(informational_page_items)
        critical_diagnostic_pages = len({(item.get("file"), item.get("page")) for item in quality_diagnostic_items if str(item.get("severity") or "").upper() == "CRITICAL"})
        warning_diagnostic_pages = len({(item.get("file"), item.get("page")) for item in quality_diagnostic_items if str(item.get("severity") or "").upper() == "WARNING"})
        result.update(
            {
                "pages": len(pages_dicts),
                "chars": len(full_text),
                "avg_score": round(avg_score, 3),
                "min_score": round(min_score, 3),
                "problem_pages": review_pages,
                "serious_pages": serious_pages,
                "review_pages": review_pages,
                "informational_pages": informational_pages,
                "ordinary_ok_pages": int(classification_total.get("ordinary_ok_pages", 0)),
                "content_block_typing_issue_pages": int(classification_total.get("content_block_typing_issue_pages", 0)),
                "unknown_blocks_count": int(classification_total.get("content_block_unknown_count", 0)),
                "misclassification_risk_blocks": int(classification_total.get("misclassification_risk_blocks", 0)),
                "unknown_recovered_as_strong_type": int(classification_total.get("unknown_recovered_as_strong_type", 0)),
                "low_confidence_blocks": int(classification_total.get("low_confidence_blocks", 0)),
                "ocr_pages_used": int(classification_total.get("ocr_pages_used", 0)),
                "ocr_pages_skipped": int(classification_total.get("ocr_pages_skipped", 0)),
                "ocr_pages_failed": int(classification_total.get("ocr_pages_failed", 0)),
                "ocr_recommended_but_disabled": int(classification_total.get("ocr_recommended_but_disabled", 0)),
                "ocr_avg_confidence": round(ocr_conf_sum / max(1, ocr_conf_count), 3) if ocr_conf_count > 0 else 0.0,
                "ocr_engine_counts": compact_counter(ocr_engine_counter),
                "ocr_reason_counts": compact_counter(ocr_reason_counter),
                "ocr_quality_improved_pages": int(classification_total.get("ocr_quality_improved_pages", 0)),
                "ocr_quality_regressed_pages": int(classification_total.get("ocr_quality_regressed_pages", 0)),
                "ocr_debug_artifacts_count": len(ocr_debug_items),
                "ocr_debug_artifacts_truncated": int(classification_total.get("ocr_debug_artifacts_truncated", 0)),
                "methods": compact_counter(method_counter),
                "primary_selected_strategy": max(selected_strategy_order, key=lambda name: (strategy_counter.get(name, 0), -selected_strategy_order.index(name))) if selected_strategy_order else "-",
                "selected_strategies": ",".join(selected_strategy_order) if selected_strategy_order else "-",
                "selected_strategy_counts": compact_counter(strategy_counter),
                "ocr_used_page_count": len(ocr_used_pages),
                "ocr_used_pages": ",".join(str(page) for page in ocr_used_pages) if ocr_used_pages else "-",
                "ai_used_page_count": sum(1 for p in pages_dicts if bool(((p.get("metadata") if isinstance(p.get("metadata"), dict) else {}) or {}).get("ai_used"))),
                "ai_used_pages": ",".join(str(p.get("page_number") or "") for p in pages_dicts if bool(((p.get("metadata") if isinstance(p.get("metadata"), dict) else {}) or {}).get("ai_used"))) or "-",
                "ai_status": compact_counter(Counter(str(((p.get("metadata") if isinstance(p.get("metadata"), dict) else {}) or {}).get("ai_status") or "not_requested") for p in pages_dicts)),
                "ai_reason": compact_counter(Counter(str(((p.get("metadata") if isinstance(p.get("metadata"), dict) else {}) or {}).get("ai_reason") or "not_requested") for p in pages_dicts)),
                "warnings": compact_counter(warning_counter),
                "suspicious_hits": int(suspicious_total.get("suspicious_pattern_hits", 0)),
                "dangling_hyphen_breaks": int(suspicious_total.get("dangling_hyphen_breaks", 0)),
                "page_number_lines": int(suspicious_total.get("page_number_lines", 0)),
                "cid_tokens": int(suspicious_total.get("cid_tokens", 0)),
                "latexit_tokens": int(suspicious_total.get("latexit_tokens", 0)),
                "private_use_glyphs": int(suspicious_total.get("private_use_glyphs", 0)),
                "watermark_tokens": int(suspicious_total.get("watermark_tokens", 0)),
                "footnote_pages": sum(1 for p in pages_dicts if int(((p.get("metadata") if isinstance(p.get("metadata"), dict) else {}) or {}).get("footnote_line_count") or 0) > 0),
                "watermark_words_removed": sum(int(((p.get("metadata") if isinstance(p.get("metadata"), dict) else {}) or {}).get("watermark_words_removed") or 0) for p in pages_dicts),
                "figure_heavy_pages": int(classification_total.get("figure_heavy_pages", 0)),
                "figure_only_pages": int(classification_total.get("figure_only_pages", 0)),
                "graph_axis_pages": int(classification_total.get("graph_axis_pages", 0)),
                "reference_pages": int(classification_total.get("reference_pages", 0)),
                "formula_heavy_pages": int(classification_total.get("formula_heavy_pages", 0)),
                "footnote_false_positive_candidates": int(classification_total.get("footnote_false_positive_candidates", 0)),
                "rejected_footnotes_graph_axis": int(classification_total.get("rejected_footnotes_graph_axis", 0)),
                "rejected_footnotes_reference": int(classification_total.get("rejected_footnotes_reference", 0)),
                "rejected_footnotes_table": int(classification_total.get("rejected_footnotes_table", 0)),
                "rejected_footnotes_figure_label": int(classification_total.get("rejected_footnotes_figure_label", 0)),
                "reference_context_footnotes_disabled_pages": int(classification_total.get("reference_context_footnotes_disabled_pages", 0)),
                "title_page_affiliation_footnotes": int(classification_total.get("title_page_affiliation_footnotes", 0)),
                "graph_axis_informational_pages": int(classification_total.get("graph_axis_informational_pages", 0)),
                "reference_informational_pages": int(classification_total.get("reference_informational_pages", 0)),
                "reference_continuation_pages": int(classification_total.get("reference_continuation_pages", 0)),
                "figure_only_informational_pages": int(classification_total.get("figure_only_informational_pages", 0)),
                "formula_heavy_informational_pages": int(classification_total.get("formula_heavy_informational_pages", 0)),
                "clean_short_body_pages": int(classification_total.get("clean_short_body_pages", 0)),
                "caption_continuation_blocks": int(classification_total.get("caption_continuation_blocks", 0)),
                "caption_continuation_lines": int(classification_total.get("caption_continuation_lines", 0)),
                "title_pages": int(classification_total.get("title_pages", 0)),
                "page_profiles": compact_counter(Counter({k.split(":", 1)[1]: v for k, v in classification_total.items() if k.startswith("page_profile:")})),
                "figure_plate_pages": int(classification_total.get("figure_plate_pages", 0)),
                "graph_heavy_pages": int(classification_total.get("graph_heavy_pages", 0)),
                "arxiv_footer_lines_removed": int(classification_total.get("arxiv_footer_lines_removed", 0)) + int(classification_total.get("removed_arxiv_footer_lines", 0)),
                "graph_axis_lines_removed": int(classification_total.get("removed_graph_axis_lines", 0)),
                "page_number_lines_removed": int(classification_total.get("removed_page_number_lines", 0)),
                "non_body_lines_removed": int(classification_total.get("non_body_lines_removed", 0)),
                "math_microline_repairs": int(classification_total.get("math_microline_repairs", 0)),
                "content_block_count": int(classification_total.get("content_block_count", 0)),
                "content_body_blocks": int(classification_total.get("content_block_body_count", 0)),
                "content_caption_blocks": int(classification_total.get("content_block_caption_count", 0)),
                "content_formula_blocks": int(classification_total.get("content_block_formula_count", 0)),
                "content_table_blocks": int(classification_total.get("content_block_table_count", 0)),
                "content_reference_blocks": int(classification_total.get("content_block_reference_count", 0)),
                "content_noise_blocks": int(classification_total.get("content_block_noise_count", 0)),
                "body_blocks_on_reference_pages": int(classification_total.get("body_blocks_on_reference_pages", 0)),
                "body_blocks_on_formula_heavy_pages": int(classification_total.get("body_blocks_on_formula_heavy_pages", 0)),
                "content_blocks_pua_after_cleanup": int(classification_total.get("content_blocks_pua_after_cleanup", 0)),
                "content_blocks_cid_after_cleanup": int(classification_total.get("content_blocks_cid_after_cleanup", 0)),
                "content_blocks_latexit_after_cleanup": int(classification_total.get("content_blocks_latexit_after_cleanup", 0)),
                "reference_pages_without_reference_blocks": int(classification_total.get("reference_pages_without_reference_blocks", 0)),
                "formula_heavy_pages_without_formula_blocks": int(classification_total.get("formula_heavy_pages_without_formula_blocks", 0)),
                "content_block_retyped_to_reference_count": int(classification_total.get("content_block_retyped_to_reference_count", 0)),
                "content_block_retyped_to_formula_count": int(classification_total.get("content_block_retyped_to_formula_count", 0)),
                "content_block_retyped_to_caption_count": int(classification_total.get("content_block_retyped_to_caption_count", 0)),
                "content_block_split_mixed_count": int(classification_total.get("content_block_split_mixed_count", 0)),
                "content_block_dropped_noise_count": int(classification_total.get("content_block_dropped_noise_count", 0)),
                "line_type_body": int(classification_total.get("line_type_body", 0)),
                "line_type_caption": int(classification_total.get("line_type_caption", 0)),
                "line_type_formula": int(classification_total.get("line_type_formula", 0)),
                "line_type_reference": int(classification_total.get("line_type_reference", 0)),
                "line_type_graph_axis": int(classification_total.get("line_type_graph_axis", 0)),
                "line_type_arxiv_footer": int(classification_total.get("line_type_arxiv_footer", 0)),
                "downstream_projection_issue_pages": int(classification_total.get("downstream_projection_issue_pages", 0)),
                "block_confusion_issue_pages": int(classification_total.get("block_confusion_issue_pages", 0)),
                "block_confusion_issue_count": int(classification_total.get("block_confusion_issue_count", 0)),
                "reference_like_body_blocks": int(classification_total.get("reference_like_body_blocks", 0)),
                "formula_like_body_blocks": int(classification_total.get("formula_like_body_blocks", 0)),
                "table_like_body_blocks": int(classification_total.get("table_like_body_blocks", 0)),
                "caption_like_body_blocks": int(classification_total.get("caption_like_body_blocks", 0)),
                "heading_like_body_blocks": int(classification_total.get("heading_like_body_blocks", 0)),
                "body_like_reference_blocks": int(classification_total.get("body_like_reference_blocks", 0)),
                "body_like_formula_blocks": int(classification_total.get("body_like_formula_blocks", 0)),
                "body_like_caption_blocks": int(classification_total.get("body_like_caption_blocks", 0)),
                "weak_table_blocks": int(classification_total.get("weak_table_blocks", 0)),
                "misclassification_risk_blocks": int(classification_total.get("misclassification_risk_blocks", 0)),
                "layout_issue_pages": int(classification_total.get("layout_issue_pages", 0)),
                "layout_issue_count": int(classification_total.get("layout_issue_count", 0)),
                "two_column_pages": int(classification_total.get("two_column_pages", 0)),
                "word_layout_two_column_pages": int(classification_total.get("word_layout_two_column_pages", 0)),
                "possible_column_mixing_pages": int(classification_total.get("possible_column_mixing_pages", 0)),
                "short_line_heavy_pages": int(classification_total.get("short_line_heavy_pages", 0)),
                "orphan_line_heavy_pages": int(classification_total.get("orphan_line_heavy_pages", 0)),
                "low_text_density_pages": int(classification_total.get("low_text_density_pages", 0)),
                "axis_like_lines_not_marked_pages": int(classification_total.get("axis_like_lines_not_marked_pages", 0)),
                "rotated_sidebar_noise_pages": int(classification_total.get("rotated_sidebar_noise_pages", 0)),
                "qwen_projection_chars": int(classification_total.get("qwen_projection_chars", 0)),
                "embedding_projection_chars": int(classification_total.get("embedding_projection_chars", 0)),
                "projection_input_block_count": int(classification_total.get("projection_input_block_count", 0)),
                "qwen_projection_block_count": int(classification_total.get("qwen_projection_block_count", 0)),
                "embedding_projection_block_count": int(classification_total.get("embedding_projection_block_count", 0)),
                "excluded_from_qwen_block_count": int(classification_total.get("excluded_from_qwen_block_count", 0)),
                "excluded_from_embedding_block_count": int(classification_total.get("excluded_from_embedding_block_count", 0)),
                "excluded_from_all_projection_block_count": int(classification_total.get("excluded_from_all_projection_block_count", 0)),
                "qwen_projection_type_counts": compact_counter(Counter({k.split(":", 1)[1]: v for k, v in classification_total.items() if k.startswith("qwen_projection_type:")})),
                "embedding_projection_type_counts": compact_counter(Counter({k.split(":", 1)[1]: v for k, v in classification_total.items() if k.startswith("embedding_projection_type:")})),
                "excluded_from_qwen_type_counts": compact_counter(Counter({k.split(":", 1)[1]: v for k, v in classification_total.items() if k.startswith("excluded_from_qwen_type:")})),
                "excluded_from_embedding_type_counts": compact_counter(Counter({k.split(":", 1)[1]: v for k, v in classification_total.items() if k.startswith("excluded_from_embedding_type:")})),
                "excluded_from_all_projection_type_counts": compact_counter(Counter({k.split(":", 1)[1]: v for k, v in classification_total.items() if k.startswith("excluded_from_all_projection_type:")})),
                "table_projection_chars": int(classification_total.get("table_projection_chars", 0)),
                "formula_projection_chars": int(classification_total.get("formula_projection_chars", 0)),
                "reference_projection_chars": int(classification_total.get("reference_projection_chars", 0)),
                "qwen_projection_leakage_hits": int(classification_total.get("qwen_projection_leakage_hits", 0)),
                "embedding_projection_leakage_hits": int(classification_total.get("embedding_projection_leakage_hits", 0)),
                "embedding_reference_hits": int(classification_total.get("embedding_reference_hits", 0)),
                "table_blocks_without_qwen_projection": int(classification_total.get("table_blocks_without_qwen_projection", 0)),
                "tables_detected_without_table_blocks": int(classification_total.get("tables_detected_without_table_blocks", 0)),
                "table_blocks_validated_count": int(classification_total.get("table_blocks_validated_count", 0)),
                "table_blocks_unvalidated_count": int(classification_total.get("table_blocks_unvalidated_count", 0)),
                "table_blocks_without_validation": int(classification_total.get("table_blocks_without_validation", 0)),
                "raw_content_block_count": int(classification_total.get("raw_content_block_count", 0)),
                "final_content_block_count": int(classification_total.get("final_content_block_count", 0)),
                "raw_content_blocks_unavailable_pages": int(classification_total.get("raw_content_blocks_unavailable_pages", 0)),
                "content_sync_issue_pages": int(classification_total.get("content_sync_issue_pages", 0)),
                "content_sync_warning_pages": int(classification_total.get("content_sync_warning_pages", 0)),
                "content_sync_low_ratio_pages": int(classification_total.get("content_sync_low_ratio_pages", 0)),
                "final_blocks_missing_pages": int(classification_total.get("final_blocks_missing_pages", 0)),
                "final_block_text_not_in_page_pages": int(classification_total.get("final_block_text_not_in_page_pages", 0)),
                "final_header_footer_leftover_blocks": int(classification_total.get("final_header_footer_leftover_blocks", 0)),
                "final_text_blocks_sync_ratio_min": round(min_sync_ratio, 4),
                "final_block_type_counts": compact_counter(final_block_type_total),
                "domain_specific_matches": int(classification_total.get("domain_specific_matches", 0)),
                "domain_specific_generic_issue_pages": int(classification_total.get("domain_specific_generic_issue_pages", 0)),
                "domain_specific_top_terms": compact_counter(domain_term_total),
                "ocr_unexplained_used_pages": int(classification_total.get("ocr_unexplained_used_pages", 0)),
                "ocr_skipped_bad_text_layer_pages": int(classification_total.get("ocr_skipped_bad_text_layer_pages", 0)),
                "ocr_missing_reason_pages": int(classification_total.get("ocr_missing_reason_pages", 0)),
                "ocr_decision_issue_pages": int(classification_total.get("ocr_decision_issue_pages", 0)),
                "critical_diagnostic_pages": critical_diagnostic_pages,
                "warning_diagnostic_pages": warning_diagnostic_pages,
                "critical_diagnostic_count": int(classification_total.get("critical_diagnostic_count", 0)),
                "warning_diagnostic_count": int(classification_total.get("warning_diagnostic_count", 0)),
                "diagnostic_categories": compact_counter(Counter({k.split(":", 1)[1]: v for k, v in classification_total.items() if k.startswith("diagnostic_category:")})),
                "diagnostic_codes": compact_counter(Counter({k.split(":", 1)[1]: v for k, v in classification_total.items() if k.startswith("diagnostic_code:")})),
                "table_candidates_raw_count": int(classification_total.get("table_candidates_raw_count", 0)),
                "table_candidates_accepted_count": int(classification_total.get("table_candidates_accepted_count", 0)),
                "table_candidates_rejected_count": int(classification_total.get("table_candidates_rejected_count", 0)),
                "table_candidates_rejected_plot_axis_grid": int(classification_total.get("table_candidates_rejected_plot_axis_grid", 0)),
                "table_candidates_rejected_no_table_semantics": int(classification_total.get("table_candidates_rejected_no_table_semantics", 0)),
                "table_candidates_rejected_too_small": int(classification_total.get("table_candidates_rejected_too_small", 0)),
                "sample": text_snippet(full_text, max_chars=sample_chars),
            }
        )
        result["status"] = quality_label(
            avg_score=avg_score,
            min_score=min_score,
            review_pages=review_pages,
            serious_pages=serious_pages,
            total_pages=len(pages_dicts),
            suspicious_hits=int(result["suspicious_hits"]),
            failed=False,
        )
    except Exception as exc:
        result.update(
            {
                "status": "FAIL",
                "error": str(exc),
                "traceback": traceback.format_exc(limit=10),
            }
        )
    finally:
        result["elapsed_sec"] = round(time.perf_counter() - started, 3)

    result["problem_page_items"] = problem_page_items
    result["informational_page_items"] = informational_page_items
    result["content_block_issue_items"] = content_block_issue_items
    result["block_confusion_items"] = block_confusion_items
    result["layout_issue_items"] = layout_issue_items
    result["quality_diagnostic_items"] = quality_diagnostic_items
    result["ocr_debug_items"] = ocr_debug_items
    return result


def build_failed_audit_row(
    pdf_path: Path,
    *,
    out_text_dir: Path,
    out_meta_dir: Path,
    error: str,
    tb: str = "",
    elapsed_sec: float = 0.0,
) -> dict[str, Any]:
    """Create a normal summary row for a PDF that failed before page metadata existed."""
    try:
        file_size = pdf_path.stat().st_size
    except Exception:
        file_size = 0
    try:
        file_hash = sha1_short(pdf_path)
    except Exception:
        file_hash = "unknown"
    base_name = f"{safe_name(pdf_path)}__{file_hash}"
    text_path = out_text_dir / f"{base_name}.txt"
    meta_path = out_meta_dir / f"{base_name}.json"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        text_path.write_text("", encoding="utf-8")
        meta_path.write_text(
            json.dumps(
                {
                    "file": str(pdf_path),
                    "status": "FAIL",
                    "error": error,
                    "traceback": tb,
                    "elapsed_sec": round(float(elapsed_sec or 0.0), 3),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass
    return {
        "file": str(pdf_path.relative_to(ROOT) if pdf_path.is_relative_to(ROOT) else pdf_path),
        "filename": pdf_path.name,
        "sha1_12": file_hash,
        "size_bytes": file_size,
        "status": "FAIL",
        "error": error,
        "traceback": tb,
        "pages": 0,
        "chars": 0,
        "avg_score": 0.0,
        "min_score": 0.0,
        "problem_pages": 0,
        "serious_pages": 0,
        "review_pages": 0,
        "informational_pages": 0,
        "ordinary_ok_pages": 0,
        "methods": "-",
        "warnings": "audit_pdf_failed:1",
        "suspicious_hits": 0,
        "ocr_pages_used": 0,
        "ocr_pages_skipped": 0,
        "ocr_pages_failed": 0,
        "ocr_reason_counts": "-",
        "final_text_blocks_sync_ratio_min": 1.0,
        "final_block_type_counts": "-",
        "diagnostic_categories": "-",
        "diagnostic_codes": "-",
        "elapsed_sec": round(float(elapsed_sec or 0.0), 3),
        "text_path": safe_relpath(text_path),
        "meta_path": safe_relpath(meta_path),
        "sample": "",
        "problem_page_items": [],
        "informational_page_items": [],
        "content_block_issue_items": [],
        "block_confusion_items": [],
        "layout_issue_items": [],
        "quality_diagnostic_items": [],
        "ocr_debug_items": [],
    }


def _analyze_pdf_worker(result_queue: Any, kwargs: dict[str, Any]) -> None:
    """Run one PDF audit in an isolated process so pdfminer cannot block the whole batch."""
    try:
        parser = PDFParser()
        row = analyze_pdf(parser, **kwargs)
        result_queue.put({"ok": True, "row": row})
    except BaseException as exc:
        result_queue.put({"ok": False, "error": str(exc), "traceback": traceback.format_exc(limit=10)})


def analyze_pdf_with_timeout(kwargs: dict[str, Any], timeout_sec: int) -> dict[str, Any]:
    """Run analyze_pdf with a per-document timeout.

    pdfminer/pdfplumber can spend a very long time in font/encoding parsing on
    malformed PDFs. Batch audit should mark that document as FAIL and continue
    with the next file instead of forcing the user to Ctrl+C the whole run.
    """
    pdf_path = Path(kwargs["pdf_path"])
    out_text_dir = Path(kwargs["out_text_dir"])
    out_meta_dir = Path(kwargs["out_meta_dir"])
    started = time.perf_counter()
    if timeout_sec <= 0:
        parser = PDFParser()
        return analyze_pdf(parser, **kwargs)

    ctx_name = "spawn" if os.name == "nt" else "fork"
    ctx = multiprocessing.get_context(ctx_name)
    result_queue = ctx.Queue(maxsize=1)
    process = ctx.Process(target=_analyze_pdf_worker, args=(result_queue, kwargs))
    process.start()
    payload: dict[str, Any] | None = None
    deadline = started + float(timeout_sec)





    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            break
        try:
            payload = result_queue.get(timeout=min(0.5, remaining))
            break
        except queue.Empty:
            if not process.is_alive():
                break

    elapsed = time.perf_counter() - started

    if payload is None and process.is_alive():
        process.terminate()
        process.join(5)
        if process.is_alive():
            try:
                process.kill()
            except Exception:
                pass
            process.join(2)
        return build_failed_audit_row(
            pdf_path,
            out_text_dir=out_text_dir,
            out_meta_dir=out_meta_dir,
            error=f"per_pdf_timeout_sec_exceeded:{int(timeout_sec)}",
            tb="",
            elapsed_sec=elapsed,
        )

    process.join(2)

    if payload is None:
        try:
            payload = result_queue.get_nowait()
        except queue.Empty:
            return build_failed_audit_row(
                pdf_path,
                out_text_dir=out_text_dir,
                out_meta_dir=out_meta_dir,
                error=f"worker_exited_without_result:exitcode={process.exitcode}",
                tb="",
                elapsed_sec=elapsed,
            )

    if payload.get("ok"):
        row = payload.get("row") or {}
        if isinstance(row, dict):
            return row
        return build_failed_audit_row(
            pdf_path,
            out_text_dir=out_text_dir,
            out_meta_dir=out_meta_dir,
            error="worker_returned_invalid_row",
            tb="",
            elapsed_sec=elapsed,
        )

    return build_failed_audit_row(
        pdf_path,
        out_text_dir=out_text_dir,
        out_meta_dir=out_meta_dir,
        error=str(payload.get("error") or "worker_failed"),
        tb=str(payload.get("traceback") or ""),
        elapsed_sec=elapsed,
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "status",
        "file",
        "pages",
        "chars",
        "avg_score",
        "min_score",
        "problem_pages",
        "serious_pages",
        "review_pages",
        "informational_pages",
        "ordinary_ok_pages",
        "content_block_typing_issue_pages",
        "unknown_blocks_count",
        "misclassification_risk_blocks",
        "unknown_recovered_as_strong_type",
        "low_confidence_blocks",
        "ocr_pages_used",
        "ocr_pages_skipped",
        "ocr_pages_failed",
        "ocr_recommended_but_disabled",
        "ocr_avg_confidence",
        "ocr_engine_counts",
        "ocr_reason_counts",
        "ocr_quality_improved_pages",
        "ocr_quality_regressed_pages",
        "ocr_debug_artifacts_count",
        "ocr_debug_artifacts_truncated",
        "methods",
        "warnings",
        "suspicious_hits",
        "dangling_hyphen_breaks",
        "page_number_lines",
        "cid_tokens",
        "latexit_tokens",
        "private_use_glyphs",
        "watermark_tokens",
        "footnote_pages",
        "watermark_words_removed",
        "figure_heavy_pages",
        "figure_only_pages",
        "graph_axis_pages",
        "reference_pages",
        "formula_heavy_pages",
        "footnote_false_positive_candidates",
        "rejected_footnotes_graph_axis",
        "rejected_footnotes_reference",
        "rejected_footnotes_table",
        "rejected_footnotes_figure_label",
        "reference_context_footnotes_disabled_pages",
        "title_page_affiliation_footnotes",
        "graph_axis_informational_pages",
        "reference_informational_pages",
        "reference_continuation_pages",
        "figure_only_informational_pages",
        "formula_heavy_informational_pages",
        "clean_short_body_pages",
        "caption_continuation_blocks",
        "caption_continuation_lines",
        "title_pages",
        "page_profiles",
        "figure_plate_pages",
        "graph_heavy_pages",
        "arxiv_footer_lines_removed",
        "graph_axis_lines_removed",
        "page_number_lines_removed",
        "non_body_lines_removed",
        "math_microline_repairs",
        "content_block_count",
        "content_body_blocks",
        "content_caption_blocks",
        "content_formula_blocks",
        "content_table_blocks",
        "content_reference_blocks",
        "body_blocks_on_reference_pages",
        "body_blocks_on_formula_heavy_pages",
        "content_blocks_pua_after_cleanup",
        "content_blocks_cid_after_cleanup",
        "content_blocks_latexit_after_cleanup",
        "reference_pages_without_reference_blocks",
        "formula_heavy_pages_without_formula_blocks",
        "content_block_retyped_to_reference_count",
        "content_block_retyped_to_formula_count",
        "content_block_retyped_to_caption_count",
        "content_block_split_mixed_count",
        "content_block_dropped_noise_count",
        "line_type_body",
        "line_type_caption",
        "line_type_formula",
        "line_type_reference",
        "line_type_graph_axis",
        "line_type_arxiv_footer",
        "downstream_projection_issue_pages",
        "block_confusion_issue_pages",
        "block_confusion_issue_count",
        "reference_like_body_blocks",
        "formula_like_body_blocks",
        "table_like_body_blocks",
        "caption_like_body_blocks",
        "heading_like_body_blocks",
        "body_like_reference_blocks",
        "body_like_formula_blocks",
        "body_like_caption_blocks",
        "weak_table_blocks",
        "layout_issue_pages",
        "layout_issue_count",
        "two_column_pages",
        "word_layout_two_column_pages",
        "possible_column_mixing_pages",
        "short_line_heavy_pages",
        "orphan_line_heavy_pages",
        "low_text_density_pages",
        "axis_like_lines_not_marked_pages",
        "rotated_sidebar_noise_pages",
        "qwen_projection_chars",
        "embedding_projection_chars",
        "table_projection_chars",
        "formula_projection_chars",
        "reference_projection_chars",
        "qwen_projection_leakage_hits",
        "embedding_projection_leakage_hits",
        "embedding_reference_hits",
        "table_blocks_without_qwen_projection",
        "tables_detected_without_table_blocks",
        "table_blocks_validated_count",
        "table_blocks_unvalidated_count",
        "table_blocks_without_validation",
        "raw_content_block_count",
        "final_content_block_count",
        "raw_content_blocks_unavailable_pages",
        "content_sync_issue_pages",
        "content_sync_warning_pages",
        "content_sync_low_ratio_pages",
        "final_blocks_missing_pages",
        "final_block_text_not_in_page_pages",
        "final_header_footer_leftover_blocks",
        "final_text_blocks_sync_ratio_min",
        "final_block_type_counts",
        "domain_specific_matches",
        "domain_specific_generic_issue_pages",
        "domain_specific_top_terms",
        "ocr_unexplained_used_pages",
        "ocr_skipped_bad_text_layer_pages",
        "ocr_missing_reason_pages",
        "ocr_decision_issue_pages",
        "critical_diagnostic_pages",
        "warning_diagnostic_pages",
        "critical_diagnostic_count",
        "warning_diagnostic_count",
        "diagnostic_categories",
        "diagnostic_codes",
        "projection_input_block_count",
        "qwen_projection_block_count",
        "embedding_projection_block_count",
        "excluded_from_qwen_block_count",
        "excluded_from_embedding_block_count",
        "excluded_from_all_projection_block_count",
        "qwen_projection_type_counts",
        "embedding_projection_type_counts",
        "excluded_from_qwen_type_counts",
        "excluded_from_embedding_type_counts",
        "excluded_from_all_projection_type_counts",
        "content_noise_blocks",
        "table_candidates_raw_count",
        "table_candidates_accepted_count",
        "table_candidates_rejected_count",
        "table_candidates_rejected_plot_axis_grid",
        "table_candidates_rejected_no_table_semantics",
        "table_candidates_rejected_too_small",
        "elapsed_sec",
        "size_bytes",
        "sha1_12",
        "text_path",
        "meta_path",
        "error",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown_report(
    path: Path,
    *,
    rows: list[dict[str, Any]],
    problem_pages: list[dict[str, Any]],
    informational_pages: list[dict[str, Any]],
    content_block_issues: list[dict[str, Any]],
    block_confusion_items: list[dict[str, Any]],
    layout_issue_items: list[dict[str, Any]],
    quality_diagnostics: list[dict[str, Any]],
    regression_report: dict[str, Any] | None,
    pdf_dir: Path,
    out_dir: Path,
    args: argparse.Namespace,
    missing_sample_entries: int = 0,
    resolved_sample_entries: int = 0,
    ocr_runtime_ready: bool | None = None,
) -> None:
    status_counter = Counter(r["status"] for r in rows)
    method_counter: Counter[str] = Counter()
    warning_counter: Counter[str] = Counter()
    ocr_reason_counter: Counter[str] = Counter()
    for row in rows:
        for chunk in str(row.get("methods") or "").split(";"):
            if ":" in chunk:
                k, v = chunk.rsplit(":", 1)
                try:
                    method_counter[k] += int(v)
                except ValueError:
                    pass
        for chunk in str(row.get("warnings") or "").split(";"):
            if ":" in chunk:
                k, v = chunk.rsplit(":", 1)
                try:
                    warning_counter[k] += int(v)
                except ValueError:
                    pass
        ocr_reason_counter.update(parse_compact_counter(str(row.get("ocr_reason_counts") or "")))

    total_pages = sum(int(r.get("pages") or 0) for r in rows)
    total_chars = sum(int(r.get("chars") or 0) for r in rows)
    avg_scores = [float(r.get("avg_score") or 0) for r in rows if r.get("status") != "FAIL"]
    avg_score = statistics.mean(avg_scores) if avg_scores else 0.0
    ocr_required_docs: list[tuple[str, int, int, int]] = []
    for row in rows:
        reasons = 0
        reasons += int(row.get("ocr_recommended_but_disabled") or 0)
        reasons += int(row.get("ocr_skipped_bad_text_layer_pages") or 0)
        reasons += int(row.get("ocr_missing_reason_pages") or 0)
        file_value = str(row.get("file") or "-")
        file_name = Path(file_value).name.lower()
        forced_priority = file_name in OCR_PRIORITY_DOC_NAMES
        if reasons <= 0 and not forced_priority:
            continue
        if forced_priority and reasons <= 0:
            reasons = 1
        ocr_required_docs.append(
            (
                file_value,
                int(row.get("serious_pages") or 0),
                int(row.get("review_pages") or 0),
                int(reasons),
            )
        )
    ocr_required_docs.sort(key=lambda item: (item[1], item[2], item[3]), reverse=True)

    lines: list[str] = []
    lines.append("# Nickelfront PDF Parser Audit")
    lines.append("")
    lines.append(f"Generated: `{datetime.now().isoformat(timespec='seconds')}`")
    lines.append(f"Audit version: `{AUDIT_VERSION}`")
    lines.append(f"Audit script: `{Path(__file__).resolve()}`")
    lines.append(f"PDF dir: `{pdf_dir}`")
    lines.append(f"Output dir: `{out_dir}`")
    lines.append(
        f"Mode: `{args.mode}`; OCR: `{'enabled' if bool(args.ocr) else 'disabled'}`; "
        f"ocr_control_mode: `{args.ocr_control_mode}`; ocr_engine: `{args.ocr_engine}`; "
        f"ocr_merge_strategy: `{args.ocr_merge_strategy}`; "
        f"ocr_allow_paddle: `{bool(args.ocr_allow_paddle)}`; repair_cross_page: `{bool(args.repair_cross_page)}`"
    )
    lines.append("")
    lines.append("## Sample Source")
    lines.append("")
    lines.append(f"- sample_source: `{pdf_dir}`")
    lines.append(f"- sample_count: **{len(rows)}**")
    lines.append(f"- missing_sample_entries: **{int(missing_sample_entries or 0)}**")
    lines.append(f"- resolved_sample_entries: **{int(resolved_sample_entries or 0)}**")
    if ocr_runtime_ready is not None:
        lines.append(f"- ocr_runtime_ready: **{bool(ocr_runtime_ready)}**")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- PDFs processed: **{len(rows)}**")
    lines.append(f"- Pages: **{total_pages}**")
    lines.append(f"- Extracted chars: **{total_chars}**")
    lines.append(f"- Average document score: **{avg_score:.3f}**")
    lines.append(f"- Status counts: `{dict(status_counter)}`")
    lines.append(f"- Real review pages: **{len(problem_pages)}**")
    lines.append(f"- Special informational pages: **{len(informational_pages)}**")
    lines.append(f"- Ordinary OK pages: **{sum(int(r.get('ordinary_ok_pages') or 0) for r in rows)}**")
    lines.append(f"- Content-block typing issue pages: **{sum(int(r.get('content_block_typing_issue_pages') or 0) for r in rows)}**")
    lines.append(f"- Unknown blocks: **{sum(int(r.get('unknown_blocks_count') or 0) for r in rows)}**")
    lines.append(f"- Misclassification-risk blocks (low margin): **{sum(int(r.get('misclassification_risk_blocks') or 0) for r in rows)}**")
    lines.append(f"- Unknown recovered from strong tentative types: **{sum(int(r.get('unknown_recovered_as_strong_type') or 0) for r in rows)}**")
    lines.append(f"- Low-confidence blocks: **{sum(int(r.get('low_confidence_blocks') or 0) for r in rows)}**")
    lines.append(f"- OCR pages used: **{sum(int(r.get('ocr_pages_used') or 0) for r in rows)}**")
    lines.append(f"- OCR pages skipped: **{sum(int(r.get('ocr_pages_skipped') or 0) for r in rows)}**")
    lines.append(f"- OCR pages failed: **{sum(int(r.get('ocr_pages_failed') or 0) for r in rows)}**")
    lines.append(f"- OCR recommended but disabled: **{sum(int(r.get('ocr_recommended_but_disabled') or 0) for r in rows)}**")
    lines.append(f"- OCR quality improved pages: **{sum(int(r.get('ocr_quality_improved_pages') or 0) for r in rows)}**")
    lines.append(f"- OCR quality regressed pages: **{sum(int(r.get('ocr_quality_regressed_pages') or 0) for r in rows)}**")
    lines.append(f"- OCR debug artifacts: **{sum(int(r.get('ocr_debug_artifacts_count') or 0) for r in rows)}**")
    lines.append(f"- OCR debug artifacts truncated: **{sum(int(r.get('ocr_debug_artifacts_truncated') or 0) for r in rows)}**")
    lines.append(f"- OCR reason counts: `{dict(ocr_reason_counter.most_common())}`")
    unavailable_docs: list[tuple[str, int]] = []
    missing_docs: list[tuple[str, int]] = []
    for row in rows:
        rc = parse_compact_counter(str(row.get("ocr_reason_counts") or ""))
        if int(rc.get("engine_unavailable") or 0) > 0:
            unavailable_docs.append((str(row.get("file") or "-"), int(rc.get("engine_unavailable") or 0)))
        if int(rc.get("dependencies_missing") or 0) > 0:
            missing_docs.append((str(row.get("file") or "-"), int(rc.get("dependencies_missing") or 0)))
    unavailable_docs.sort(key=lambda item: item[1], reverse=True)
    missing_docs.sort(key=lambda item: item[1], reverse=True)
    lines.append(f"- Top engine_unavailable docs: `{unavailable_docs[:10]}`")
    lines.append(f"- Top dependencies_missing docs: `{missing_docs[:10]}`")
    lines.append(f"- Downstream projection issue pages: **{sum(int(r.get('downstream_projection_issue_pages') or 0) for r in rows)}**")
    lines.append(f"- Block confusion issue pages: **{sum(int(r.get('block_confusion_issue_pages') or 0) for r in rows)}**")
    lines.append(f"- Block confusion issue count: **{sum(int(r.get('block_confusion_issue_count') or 0) for r in rows)}**")
    lines.append(f"- Reference-like body blocks: **{sum(int(r.get('reference_like_body_blocks') or 0) for r in rows)}**")
    lines.append(f"- Formula-like body blocks: **{sum(int(r.get('formula_like_body_blocks') or 0) for r in rows)}**")
    lines.append(f"- Table-like body blocks: **{sum(int(r.get('table_like_body_blocks') or 0) for r in rows)}**")
    lines.append(f"- Caption-like body blocks: **{sum(int(r.get('caption_like_body_blocks') or 0) for r in rows)}**")
    lines.append(f"- Layout issue pages: **{sum(int(r.get('layout_issue_pages') or 0) for r in rows)}**")
    lines.append(f"- Two-column pages detected: **{sum(int(r.get('two_column_pages') or 0) for r in rows)}**")
    lines.append(f"- Possible column-mixing pages: **{sum(int(r.get('possible_column_mixing_pages') or 0) for r in rows)}**")
    lines.append(f"- Qwen projection chars: **{sum(int(r.get('qwen_projection_chars') or 0) for r in rows)}**")
    lines.append(f"- Embedding projection chars: **{sum(int(r.get('embedding_projection_chars') or 0) for r in rows)}**")
    lines.append(f"- Table projection chars: **{sum(int(r.get('table_projection_chars') or 0) for r in rows)}**")
    lines.append(f"- Validated table blocks: **{sum(int(r.get('table_blocks_validated_count') or 0) for r in rows)}**")
    lines.append(f"- Unvalidated table blocks: **{sum(int(r.get('table_blocks_unvalidated_count') or 0) for r in rows)}**")
    lines.append(f"- Pages with table blocks without validation: **{sum(int(r.get('table_blocks_without_validation') or 0) for r in rows)}**")
    lines.append(f"- Formula projection chars excluded from Qwen/embeddings: **{sum(int(r.get('formula_projection_chars') or 0) for r in rows)}**")
    lines.append(f"- Tables detected without final table blocks: **{sum(int(r.get('tables_detected_without_table_blocks') or 0) for r in rows)}**")
    lines.append(f"- Qwen projection leakage hits: **{sum(int(r.get('qwen_projection_leakage_hits') or 0) for r in rows)}**")
    lines.append(f"- Embedding projection leakage hits: **{sum(int(r.get('embedding_projection_leakage_hits') or 0) for r in rows)}**")
    lines.append(f"- Embedding reference hits: **{sum(int(r.get('embedding_reference_hits') or 0) for r in rows)}**")
    lines.append(f"- Raw table candidates: **{sum(int(r.get('table_candidates_raw_count') or 0) for r in rows)}**")
    lines.append(f"- Accepted table candidates: **{sum(int(r.get('table_candidates_accepted_count') or 0) for r in rows)}**")
    lines.append(f"- Rejected plot-axis table candidates: **{sum(int(r.get('table_candidates_rejected_plot_axis_grid') or 0) for r in rows)}**")
    lines.append(f"- Method counts: `{dict(method_counter.most_common())}`")
    lines.append(f"- Warning counts: `{dict(warning_counter.most_common())}`")
    diag_severity_counter = Counter(str(item.get("severity") or "WARNING").upper() for item in quality_diagnostics)
    diag_category_counter = Counter(str(item.get("category") or "unknown") for item in quality_diagnostics)
    diag_code_counter: Counter[str] = Counter()
    for item in quality_diagnostics:
        diag_code_counter.update(str(code) for code in (item.get("codes") or []))
    final_type_total = sum((parse_compact_counter(str(r.get("final_block_type_counts") or "")) for r in rows), Counter())
    qwen_type_total = sum((parse_compact_counter(str(r.get("qwen_projection_type_counts") or "")) for r in rows), Counter())
    embedding_type_total = sum((parse_compact_counter(str(r.get("embedding_projection_type_counts") or "")) for r in rows), Counter())
    excluded_embedding_type_total = sum((parse_compact_counter(str(r.get("excluded_from_embedding_type_counts") or "")) for r in rows), Counter())
    excluded_qwen_type_total = sum((parse_compact_counter(str(r.get("excluded_from_qwen_type_counts") or "")) for r in rows), Counter())
    excluded_all_type_total = sum((parse_compact_counter(str(r.get("excluded_from_all_projection_type_counts") or "")) for r in rows), Counter())
    lines.append(f"- Critical diagnostics: **{int(diag_severity_counter.get('CRITICAL') or 0)}**")
    lines.append(f"- Warning diagnostics: **{int(diag_severity_counter.get('WARNING') or 0)}**")
    lines.append(f"- Diagnostic categories: `{dict(diag_category_counter.most_common())}`")
    lines.append(f"- Diagnostic warning codes: `{dict(diag_code_counter.most_common())}`")
    lines.append(f"- Content sync issue pages: **{sum(int(r.get('content_sync_issue_pages') or 0) for r in rows)}**")
    lines.append(f"- Raw content blocks: **{sum(int(r.get('raw_content_block_count') or 0) for r in rows)}**")
    lines.append(f"- Final content blocks: **{sum(int(r.get('final_content_block_count') or 0) for r in rows)}**")
    min_sync = min((float(r.get('final_text_blocks_sync_ratio_min') or 1.0) for r in rows), default=1.0)
    lines.append(f"- Final text vs final blocks min sync ratio: **{min_sync:.4f}**")
    lines.append(f"- Final block type counts: `{dict(final_type_total.most_common())}`")
    lines.append(f"- Body/heading/abstract/table/caption/formula/reference/noise counts: `body={final_type_total.get('body', 0)}, heading={final_type_total.get('heading', 0)}, abstract={final_type_total.get('abstract', 0)}, table={final_type_total.get('table', 0)}, caption={final_type_total.get('caption', 0)}, formula={final_type_total.get('formula', 0)}, reference={final_type_total.get('reference', 0)}, noise={final_type_total.get('noise', 0)}, unknown={final_type_total.get('unknown', 0)}`")
    lines.append(f"- Raw content blocks unavailable pages: **{sum(int(r.get('raw_content_blocks_unavailable_pages') or 0) for r in rows)}**")
    lines.append(f"- Projection input blocks: **{sum(int(r.get('projection_input_block_count') or 0) for r in rows)}**")
    lines.append(f"- Blocks sent to RAG embeddings: **{sum(int(r.get('embedding_projection_block_count') or 0) for r in rows)}** `{dict(embedding_type_total.most_common())}`")
    lines.append(f"- Blocks sent to Qwen: **{sum(int(r.get('qwen_projection_block_count') or 0) for r in rows)}** `{dict(qwen_type_total.most_common())}`")
    lines.append(f"- Blocks excluded from embeddings: **{sum(int(r.get('excluded_from_embedding_block_count') or 0) for r in rows)}** `{dict(excluded_embedding_type_total.most_common())}`")
    lines.append(f"- Blocks excluded from Qwen: **{sum(int(r.get('excluded_from_qwen_block_count') or 0) for r in rows)}** `{dict(excluded_qwen_type_total.most_common())}`")
    lines.append(f"- Blocks excluded from all projections: **{sum(int(r.get('excluded_from_all_projection_block_count') or 0) for r in rows)}** `{dict(excluded_all_type_total.most_common())}`")
    lines.append(f"- Header/footer leftovers in final blocks: **{sum(int(r.get('final_header_footer_leftover_blocks') or 0) for r in rows)}**")
    lines.append(f"- OCR skipped on bad text-layer pages: **{sum(int(r.get('ocr_skipped_bad_text_layer_pages') or 0) for r in rows)}**")
    lines.append(f"- OCR used without clear reason pages: **{sum(int(r.get('ocr_unexplained_used_pages') or 0) for r in rows)}**")
    lines.append(f"- Domain-specific matches in generic-mode pages: **{sum(int(r.get('domain_specific_generic_issue_pages') or 0) for r in rows)}**")
    lines.append(f"- OCR-required docs: **{len(ocr_required_docs)}**")
    lines.append("")
    lines.append("Status meaning: `OK` = extraction looks usable; `WARN` = real review recommended; `BAD` = serious extraction risk; `FAIL` = exception. Special informational pages are reported separately and do not affect document status. Ordinary clean body/layout pages are counted but not expanded into snippets.")
    lines.append("")
    lines.append("## Documents")
    lines.append("")
    lines.append("| Status | Avg | Min | Pages | Review | Serious | Info | OrdinaryOK | BlockIssue | Profiles | CID | PUA | Latexit | WM | Foot | Fig | FigOnly | FigPlate | Axis | Ref | RefCont | Formula | FormulaInfo | CleanBody | CapCont | FootFP | RemovedAxis | ArxivRm | Blocks | BadRefBody | BadFormulaBody | PUAblk | RetypeRef | RetypeFormula | RetypeCaption | SplitMixed | DropNoise | Title | File | Methods | Warnings |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|")
    for row in sorted(rows, key=lambda r: (str(r.get("status")), -int(r.get("problem_pages") or 0), str(r.get("file")))):
        lines.append(
            f"| {row.get('status')} | {row.get('avg_score')} | {row.get('min_score')} | "
            f"{row.get('pages')} | {row.get('review_pages', row.get('problem_pages'))} | "
            f"{row.get('serious_pages', 0)} | {row.get('informational_pages', 0)} | "
            f"{row.get('ordinary_ok_pages', 0)} | {row.get('content_block_typing_issue_pages', 0)} | "
            f"`{row.get('page_profiles', '-')}` | "
            f"{row.get('cid_tokens', 0)} | {row.get('private_use_glyphs', 0)} | "
            f"{row.get('latexit_tokens', 0)} | {row.get('watermark_tokens', 0)} | "
            f"{row.get('footnote_pages', 0)} | {row.get('figure_heavy_pages', 0)} | "
            f"{row.get('figure_only_pages', 0)} | {row.get('figure_plate_pages', 0)} | "
            f"{row.get('graph_axis_pages', 0)} | {row.get('reference_pages', 0)} | "
            f"{row.get('reference_continuation_pages', 0)} | {row.get('formula_heavy_pages', 0)} | "
            f"{row.get('formula_heavy_informational_pages', 0)} | {row.get('clean_short_body_pages', 0)} | "
            f"{row.get('caption_continuation_blocks', 0)} | {row.get('footnote_false_positive_candidates', 0)} | "
            f"{row.get('graph_axis_lines_removed', 0)} | {row.get('arxiv_footer_lines_removed', 0)} | "
            f"{row.get('content_block_count', 0)} | {row.get('body_blocks_on_reference_pages', 0)} | "
            f"{row.get('body_blocks_on_formula_heavy_pages', 0)} | {row.get('content_blocks_pua_after_cleanup', 0)} | "
            f"{row.get('content_block_retyped_to_reference_count', 0)} | {row.get('content_block_retyped_to_formula_count', 0)} | "
            f"{row.get('content_block_retyped_to_caption_count', 0)} | {row.get('content_block_split_mixed_count', 0)} | "
            f"{row.get('content_block_dropped_noise_count', 0)} | {row.get('title_pages', 0)} | `{row.get('file')}` | "
            f"`{row.get('methods')}` | `{row.get('warnings')}` |"
        )
    lines.append("")
    lines.append("## OCR-required docs")
    lines.append("")
    if not ocr_required_docs:
        lines.append("No docs require OCR retry according to current diagnostics.")
    else:
        lines.append("| File | Serious | Review | OCR reasons |")
        lines.append("|---|---:|---:|---:|")
        for file_name, serious_pages, review_pages, reason_hits in ocr_required_docs[:40]:
            lines.append(f"| `{file_name}` | {serious_pages} | {review_pages} | {reason_hits} |")
    lines.append("")
    lines.append("## Critical / warning diagnostics")
    lines.append("")
    if not quality_diagnostics:
        lines.append("No critical/warning diagnostics detected by current audit heuristics.")
    else:
        for item in sorted(quality_diagnostics, key=lambda x: (0 if str(x.get('severity')).upper() == 'CRITICAL' else 1, str(x.get('category')), str(x.get('file')), int(x.get('page') or 0)))[:120]:
            lines.append(f"### `{item.get('file')}` page {item.get('page')} severity={item.get('severity')} category={item.get('category')} score={item.get('score')} method={item.get('method')}")
            lines.append(f"Issues: `{item.get('issues')}`")
            lines.append(f"Codes: `{item.get('codes')}`")
            lines.append(f"Owner: `{item.get('recommended_owner')}`")
            lines.append(f"Recommendation: {item.get('recommendation')}")
            lines.append(f"Metrics: `{item.get('metrics')}`")
            samples = item.get('samples') or []
            for sample in samples[:5]:
                lines.append(f"- sample: `{sample}`")
            lines.append("")
            lines.append("> " + str(item.get("snippet") or "").replace("\n", " "))
            lines.append("")
    lines.append("")
    lines.append("## Downstream projection issues / snippets")
    lines.append("")
    if not content_block_issues:
        lines.append("No downstream projection issues detected by current heuristics.")
    else:
        for item in content_block_issues[:80]:
            lines.append(f"### `{item['file']}` page {item['page']} severity={item.get('severity', 'DOWNSTREAM')}")
            lines.append(f"Projection issues: `{item.get('projection_issues')}`")
            lines.append(f"Projection audit: `{item.get('projection_audit')}`")
            proj_audit = item.get('projection_audit') or {}
            if isinstance(proj_audit, dict):
                lines.append(f"Projection decisions sample: `{proj_audit.get('projection_decision_samples', [])[:5]}`")
                lines.append(f"Projection excluded sample: `{proj_audit.get('projection_excluded_samples', [])[:5]}`")
            lines.append(f"Page profile: `{item.get('page_profile')}`; warnings: `{item.get('warnings')}`")
            lines.append("")
            lines.append("> " + str(item.get("snippet") or "").replace("\n", " "))
            lines.append("")
    lines.append("")
    lines.append("## Block confusion diagnostics / snippets")
    lines.append("")
    if not block_confusion_items:
        lines.append("No block confusion issues detected by current heuristics.")
    else:
        for item in block_confusion_items[:80]:
            lines.append(f"### `{item['file']}` page {item['page']} score={item.get('score')} method={item.get('method')}")
            lines.append(f"Page profile: `{item.get('page_profile')}`; warnings: `{item.get('warnings')}`")
            lines.append(f"Summary: `{item.get('summary')}`")
            lines.append(f"Block types: `{item.get('block_type_counts')}`")
            for sample in item.get("samples") or []:
                lines.append("")
                lines.append(f"- block #{sample.get('block_index')} type=`{sample.get('declared_type')}` issues=`{sample.get('issues')}` hints=`{sample.get('hints')}`")
                lines.append("  > " + str(sample.get("snippet") or "").replace("\n", " "))
            lines.append("")
    lines.append("")
    lines.append("## Layout diagnostics / snippets")
    lines.append("")
    if not layout_issue_items:
        lines.append("No layout issues detected by current heuristics.")
    else:
        for item in layout_issue_items[:80]:
            lines.append(f"### `{item['file']}` page {item['page']} score={item.get('score')} method={item.get('method')}")
            layout = item.get("layout") or {}
            lines.append(f"Page profile: `{item.get('page_profile')}`; warnings: `{item.get('warnings')}`")
            lines.append(f"Layout: issues=`{layout.get('issues')}` lines=`{layout.get('line_count')}` words=`{layout.get('word_count')}` avg_line=`{layout.get('avg_line_len')}` short_ratio=`{layout.get('short_line_ratio')}` orphan_ratio=`{layout.get('orphan_line_ratio')}`")
            lines.append("")
            lines.append("> " + str(item.get("snippet") or "").replace("\n", " "))
            lines.append("")
    if regression_report:
        lines.append("")
        lines.append("## Regression compare")
        lines.append("")
        lines.append(f"- Baseline docs: **{regression_report.get('baseline_docs', 0)}**")
        lines.append(f"- Current docs: **{regression_report.get('current_docs', 0)}**")
        lines.append(f"- Totals: `{regression_report.get('totals', {})}`")
        changed = [doc for doc in regression_report.get("documents", []) if doc.get("change") in {"regressed", "improved", "new", "missing"} or doc.get("metric_deltas")]
        if not changed:
            lines.append("No status or metric changes detected.")
        else:
            lines.append("")
            lines.append("| Change | Prev | Current | File | Metric deltas |")
            lines.append("|---|---|---|---|---|")
            for doc in changed[:100]:
                lines.append(
                    f"| {doc.get('change')} | {doc.get('previous_status', '-')} | {doc.get('current_status', '-')} | "
                    f"`{doc.get('file') or doc.get('identity')}` | `{doc.get('metric_deltas', {})}` |"
                )
        quality_gate = regression_report.get("quality_regression_gate") if isinstance(regression_report, dict) else None
        if isinstance(quality_gate, dict):
            lines.append("")
            lines.append("## Quality Regression Gate")
            lines.append("")
            lines.append(f"- Triggered: **{bool(quality_gate.get('triggered'))}**")
            lines.append(f"- Regressed docs: **{int(quality_gate.get('regressed_docs') or 0)}**")
            lines.append(f"- Metric hits: `{quality_gate.get('metric_hits', {})}`")
            docs = quality_gate.get("documents") or []
            if docs:
                lines.append("")
                lines.append("| File | Quality metric deltas |")
                lines.append("|---|---|")
                for doc in docs[:100]:
                    lines.append(f"| `{doc.get('file') or doc.get('identity')}` | `{doc.get('quality_metric_deltas', {})}` |")
        ocr_quality_gate = regression_report.get("ocr_quality_regression_gate") if isinstance(regression_report, dict) else None
        if isinstance(ocr_quality_gate, dict):
            lines.append("")
            lines.append("## OCR Quality Gate")
            lines.append("")
            lines.append(f"- Triggered: **{bool(ocr_quality_gate.get('triggered'))}**")
            lines.append(f"- Regressed docs: **{int(ocr_quality_gate.get('regressed_docs') or 0)}**")
            lines.append(f"- Metric hits: `{ocr_quality_gate.get('metric_hits', {})}`")
            lines.append(f"- Thresholds: `{OCR_QUALITY_GATE_THRESHOLDS}`")
            docs = ocr_quality_gate.get("documents") or []
            if docs:
                lines.append("")
                lines.append("| File | OCR quality metric deltas |")
                lines.append("|---|---|")
                for doc in docs[:100]:
                    lines.append(f"| `{doc.get('file') or doc.get('identity')}` | `{doc.get('ocr_quality_metric_deltas', {})}` |")
        lines.append("")
        lines.append("## Gate Decision Notes")
        lines.append("")
        gate_notes: list[tuple[str, str, dict[str, Any]]] = []
        if isinstance(quality_gate, dict):
            for doc in quality_gate.get("documents") or []:
                gate_notes.append(("quality", str(doc.get("file") or doc.get("identity") or "-"), dict(doc.get("quality_metric_deltas") or {})))
        if isinstance(ocr_quality_gate, dict):
            for doc in ocr_quality_gate.get("documents") or []:
                gate_notes.append(("ocr_quality", str(doc.get("file") or doc.get("identity") or "-"), dict(doc.get("ocr_quality_metric_deltas") or {})))
        if not gate_notes:
            lines.append("No gate triggers in compare.")
        else:
            lines.append("| Gate | File | Metric deltas |")
            lines.append("|---|---|---|")
            for gate_name, file_name, deltas in gate_notes[:120]:
                lines.append(f"| `{gate_name}` | `{file_name}` | `{deltas}` |")
    lines.append("")
    lines.append("## Special informational pages / snippets")
    lines.append("")
    if not informational_pages:
        lines.append("No special informational pages detected by current heuristics.")
    else:
        for item in informational_pages[:60]:
            lines.append(f"### `{item['file']}` page {item['page']} severity=INFO score={item['score']} method={item['method']}")
            lines.append(f"Warnings: `{item.get('warnings')}`")
            lines.append(f"Classes: `{item.get('classes', {})}`")
            lines.append("")
            lines.append("> " + str(item.get("snippet") or "").replace("\n", " "))
            lines.append("")
    lines.append("")
    lines.append("## Problem pages / snippets")
    lines.append("")
    if not problem_pages:
        lines.append("No problem pages detected by current heuristics.")
    else:
        for item in problem_pages[:80]:
            lines.append(f"### `{item['file']}` page {item['page']} severity={item.get('severity', 'REVIEW')} score={item['score']} method={item['method']}")
            lines.append(f"Warnings: `{item.get('warnings')}`")
            lines.append(f"Classes: `{item.get('classes', {})}`")
            lines.append(f"Suspicious: `{item.get('suspicious')}`")
            lines.append("")
            lines.append("> " + str(item.get("snippet") or "").replace("\n", " "))
            lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def make_share_zip(zip_path: Path, out_dir: Path) -> None:
    if zip_path.exists():
        try:
            zip_path.unlink()
        except OSError:



            pass
    include_names = {
        "REPORT.md",
        "summary.csv",
        "summary.json",
        "problem_pages.json",
        "informational_pages.json",
        "content_block_issues.json",
        "block_confusion_issues.json",
        "layout_issues.json",
        "quality_diagnostics.json",
        "ocr_debug_artifacts.json",
        "ocr_required_docs.json",
        "ocr_required_sample_list.txt",
        "regression_report.json",
        "run_info.json",
    }
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=8) as zf:
        for path in out_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(out_dir)
            rel_parts = rel.parts
            include = (
                rel.name in include_names
                or (rel_parts and rel_parts[0] in {"meta", "texts"})
            )
            if include:
                zf.write(path, arcname="/".join(rel_parts))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch audit raw PDF extraction on Nickelfront storage/papers_pdf")
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR, help="Directory with PDF files")
    parser.add_argument("--out-base", type=Path, default=DEFAULT_OUT_BASE, help="Base output directory")
    parser.add_argument("--mode", default="auto", choices=["auto", "layout", "simple", "columns", "ocr", "ai"], help="Legacy extraction strategy override; use --parser-mode auto for public mode")
    parser.add_argument("--parser-mode", default="auto", choices=["auto", "ai"], help="Public parser mode: auto or ai. In ai mode pages are treated as future page-image AI recognition inputs.")
    parser.add_argument("--force-strategy", default="", choices=["", "simple", "layout", "columns", "ocr", "ai"], help="Debug override for internal extraction strategy")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of PDFs, 0 = all")
    parser.add_argument("--per-pdf-timeout-sec", type=int, default=180, help="Max seconds for one PDF before marking it FAIL and continuing; 0 disables isolation/timeout")
    parser.add_argument("--glob", default="*.pdf", help="PDF glob pattern")
    parser.add_argument("--sample-list", type=Path, default=None, help="Path to fixed sample list (one PDF path per line)")
    parser.add_argument(
        "--sample-from-ocr-required",
        type=Path,
        default=None,
        help="Path to previous audit latest dir or ocr_required_sample_list.txt for targeted OCR fallback",
    )
    parser.add_argument("--write-sample-list", type=Path, default=None, help="Write resolved PDF sample list to path")
    recursive_group = parser.add_mutually_exclusive_group()
    recursive_group.add_argument("--recursive", dest="recursive", action="store_true", help="Search PDFs recursively")
    recursive_group.add_argument("--no-recursive", dest="recursive", action="store_false", help="Search only the top-level PDF directory")
    parser.set_defaults(recursive=True)
    parser.add_argument("--no-tables", action="store_true", help="Disable table markdown extraction")
    parser.add_argument("--keep-headers", action="store_true", help="Do not remove repeated headers/footers")
    parser.add_argument(
        "--repair-cross-page",
        action="store_true",
        help="Experimental: allow cross-page word continuation repair. Disabled by default.",
    )
    parser.add_argument(
        "--domain-profile",
        default="generic",
        choices=["generic", "materials", "patents"],
        help="Parser domain/profile option passed through public config",
    )
    parser.add_argument(
        "--content-blocks-mode",
        default="final",
        choices=["final", "raw"],
        help="Content block mode option passed through public config",
    )
    parser.add_argument(
        "--rebuild-content-blocks-from-final-text",
        dest="rebuild_content_blocks_from_final_text",
        action="store_true",
        help="Rebuild final content_blocks from final page.text (recommended default).",
    )
    parser.add_argument(
        "--no-rebuild-content-blocks-from-final-text",
        dest="rebuild_content_blocks_from_final_text",
        action="store_false",
        help="Disable final-text rebuild for diagnostics only.",
    )
    parser.set_defaults(rebuild_content_blocks_from_final_text=True)
    parser.add_argument(
        "--no-content-blocks",
        action="store_true",
        help="Disable content_blocks metadata emission",
    )
    parser.add_argument("--sample-chars", type=int, default=700, help="Snippet length for problem pages")
    parser.add_argument("--sample-blocks", type=int, default=8, help="Max suspicious block samples per page")
    parser.add_argument("--audit-domain-mode", default="generic", choices=["generic", "materials", "patents", "auto"], help="Audit-only profile for domain-specific heuristic warnings; does not change parser extraction")
    parser.add_argument("--ocr", dest="ocr", action="store_true", help="Enable OCR policy in parser options")
    parser.add_argument("--no-ocr", dest="ocr", action="store_false", help="Disable OCR policy in parser options")
    parser.set_defaults(ocr=False)
    parser.add_argument("--ocr-mode", default="auto", choices=["auto", "force", "off"], help="OCR strategy policy: auto, force or off")
    parser.add_argument("--ai-mode", default="off", choices=["off", "auto", "force"], help="AI page-image recognition placeholder policy. Stub only; no external call is performed.")
    parser.add_argument("--ai-enabled", action="store_true", help="Enable AI page-image recognition placeholder metadata")
    parser.add_argument("--ai-provider", default="", help="Future AI page recognizer provider name")
    parser.add_argument("--ai-model", default="", help="Future AI page recognizer model name")
    parser.add_argument("--ai-render-dpi", type=int, default=220, help="Future PDF page image render DPI for AI recognition")
    parser.add_argument("--ai-page-image-format", default="png", choices=["png", "jpg", "jpeg", "webp"], help="Future page image format for AI recognition")
    parser.add_argument("--ocr-control-mode", default="auto", choices=["auto", "selective", "manual"], help="OCR decision mode")
    parser.add_argument("--ocr-engine", default="auto", choices=["auto", "tesseract", "paddle", "ocrmypdf", "surya"], help="Primary OCR engine")
    parser.add_argument("--ocr-force", action="store_true", help="Force OCR for selected pages/mode")
    parser.add_argument("--ocr-skip", action="store_true", help="Keep OCR config visible but skip OCR execution")
    parser.add_argument("--ocr-pages", default="", help="Selected pages for selective mode, e.g. 1,2,5-8")
    parser.add_argument("--ocr-only-pages", default="", help="Alias for --ocr-pages in selective/manual OCR mode")
    parser.add_argument("--ocr-dpi", type=int, default=220, help="OCR DPI")
    parser.add_argument("--ocr-languages", default="eng+rus", help="OCR language pack string")
    parser.add_argument("--ocr-min-quality-score", type=float, default=0.45, help="Min page quality threshold for OCR replacement")
    parser.add_argument("--ocr-min-confidence", type=float, default=0.55, help="Min OCR confidence threshold")
    parser.add_argument("--ocr-min-text-chars", type=int, default=180, help="Auto OCR trigger: minimum extracted characters per page")
    parser.add_argument("--ocr-min-words", type=int, default=35, help="Auto OCR trigger: minimum extracted words per page")
    parser.add_argument("--ocr-min-text-density", type=float, default=0.35, help="Auto OCR trigger: minimum chars per 1000 page points")
    parser.add_argument("--ocr-broken-encoding-noise-ratio", type=float, default=0.02, help="Auto OCR trigger: max allowed noisy glyph ratio")
    parser.add_argument("--ocr-allow-paddle", action="store_true", help="Allow PaddleOCR as explicit/auto fallback when installed")
    parser.add_argument("--ocr-allow-ocrmypdf-page", action="store_true", help="Allow heavy OCRmyPDF page-level fallback when explicitly requested")
    parser.add_argument("--ocr-debug", action="store_true", help="Store OCR debug payloads in metadata/artifacts")
    parser.add_argument("--ocr-surya-experimental", action="store_true", help="Enable experimental Surya OCR engine path")
    parser.add_argument("--ocr-preflight", action="store_true", help="Print OCR engine availability before audit run")
    parser.add_argument("--ocr-preflight-only", action="store_true", help="Print OCR engine availability and exit without running audit")
    parser.add_argument(
        "--ocr-merge-strategy",
        default="replace_low_quality",
        choices=["replace_low_quality", "prefer_pdf_text", "prefer_ocr", "hybrid_lines", "diagnostics_only"],
        help="OCR merge strategy",
    )
    fresh_group = parser.add_mutually_exclusive_group()
    fresh_group.add_argument("--fresh", dest="fresh", action="store_true", help="Clear latest output dir before run")
    fresh_group.add_argument("--no-fresh", dest="fresh", action="store_false", help="Keep latest output dir and overwrite files in place")
    parser.set_defaults(fresh=True)
    parser.add_argument("--compare", type=Path, default=None, help="Previous summary.json, audit latest dir or audit zip to compare with")
    parser.add_argument("--fail-on-bad", action="store_true", help="Exit with code 2 when current audit contains BAD/FAIL documents")
    parser.add_argument("--fail-on-regression", action="store_true", help="Exit with code 3 when --compare finds status regressions")
    parser.add_argument("--fail-on-block-issues", action="store_true", help="Exit with code 4 when block confusion/layout/projection issues are detected")
    parser.add_argument("--fail-on-quality-regression", action="store_true", help="Exit with code 5 when --compare finds quality metric regressions")
    parser.add_argument("--fail-on-ocr-quality-regression", action="store_true", help="Exit with code 6 when --compare finds OCR-specific quality metric regressions")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.sample_list and args.sample_from_ocr_required:
        raise SystemExit("Use either --sample-list or --sample-from-ocr-required, not both.")
    preflight_data: dict[str, Any] = {"engines": {}}
    if args.ocr or args.ocr_preflight or args.ocr_preflight_only:
        preflight_data = detect_ocr_runtime_availability()
    if args.ocr_preflight or args.ocr_preflight_only:
        print(json.dumps(preflight_data, ensure_ascii=False, indent=2))
    if args.ocr_preflight_only:
        return 0
    pdf_dir = args.pdf_dir if args.pdf_dir.is_absolute() else (ROOT / args.pdf_dir)
    out_base = args.out_base if args.out_base.is_absolute() else (ROOT / args.out_base)
    out_dir = out_base / "latest"
    text_dir = out_dir / "texts"
    meta_dir = out_dir / "meta"

    if not pdf_dir.exists():
        raise SystemExit(f"PDF directory not found: {pdf_dir}")

    baseline_rows: list[dict[str, Any]] | None = None
    if args.compare:
        compare_path = args.compare if args.compare.is_absolute() else (ROOT / args.compare)
        baseline_rows = load_summary_rows(compare_path)

    if args.fresh and out_dir.exists():
        shutil.rmtree(out_dir)
    text_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    pattern_iter = pdf_dir.rglob(args.glob) if args.recursive else pdf_dir.glob(args.glob)
    discovered = sorted(p for p in pattern_iter if p.is_file() and p.suffix.lower() == ".pdf")
    missing_sample_entries = 0
    sample_source = str(pdf_dir)
    sample_list_input = args.sample_list
    if args.sample_from_ocr_required:
        ocr_required_src = args.sample_from_ocr_required if args.sample_from_ocr_required.is_absolute() else (ROOT / args.sample_from_ocr_required)
        sample_list_input = (ocr_required_src / "ocr_required_sample_list.txt") if ocr_required_src.is_dir() else ocr_required_src
        if not sample_list_input.exists():
            raise SystemExit(f"OCR-required sample list not found: {sample_list_input}")
        args.ocr = True
        if str(args.ocr_control_mode or "auto").strip().lower() == "auto":
            args.ocr_control_mode = "selective"
        print(f"Using OCR-required sample list: {sample_list_input}")

    if sample_list_input:
        sample_list_path = sample_list_input if sample_list_input.is_absolute() else (ROOT / sample_list_input)
        if not sample_list_path.exists():
            raise SystemExit(f"Sample list not found: {sample_list_path}")
        sample_source = str(sample_list_path)
        selected: list[Path] = []
        for raw_line in sample_list_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            candidate = Path(line)
            if not candidate.is_absolute():
                candidate = (ROOT / candidate).resolve()
            if not candidate.exists() or candidate.suffix.lower() != ".pdf":
                missing_sample_entries += 1
                continue
            selected.append(candidate)
        pdfs = sorted(dict.fromkeys(selected))
        resolved_sample_entries = len(pdfs)
        if resolved_sample_entries == 0:
            raise SystemExit("empty_resolved_sample_list")
    else:
        pdfs = discovered
        resolved_sample_entries = len(pdfs)
    if args.limit and args.limit > 0:
        pdfs = pdfs[: args.limit]

    if not pdfs:
        raise SystemExit(f"No PDFs found in {pdf_dir} with pattern {args.glob}")
    if args.write_sample_list:
        target = args.write_sample_list if args.write_sample_list.is_absolute() else (ROOT / args.write_sample_list)
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = [str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p) for p in pdfs]
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"PDF parser audit version: {AUDIT_VERSION}")
    print(f"PDF dir: {pdf_dir}")
    print(f"Found PDFs: {len(pdfs)}")
    if len(pdfs) < 30:
        print(f"WARN: only {len(pdfs)} real PDFs available (<30 target). Using all available PDFs.")
    if missing_sample_entries > 0:
        print(f"WARN: missing sample-list entries skipped: {missing_sample_entries}")
    print(f"Output: {out_dir}")
    print(f"Sample set hash: {sample_list_hash(pdfs, root=ROOT)}")

    parser = None if int(args.per_pdf_timeout_sec or 0) > 0 else PDFParser()
    rows: list[dict[str, Any]] = []
    problem_pages: list[dict[str, Any]] = []
    informational_pages: list[dict[str, Any]] = []
    content_block_issues: list[dict[str, Any]] = []
    block_confusion_items: list[dict[str, Any]] = []
    layout_issue_items: list[dict[str, Any]] = []
    quality_diagnostic_items: list[dict[str, Any]] = []
    ocr_debug_items: list[dict[str, Any]] = []
    started = time.perf_counter()

    for idx, pdf_path in enumerate(pdfs, start=1):
        print(f"[{idx}/{len(pdfs)}] {pdf_path.name} ...", flush=True)
        analyze_kwargs = {
            "pdf_path": pdf_path,
            "out_text_dir": text_dir,
            "out_meta_dir": meta_dir,
            "mode": args.mode,
            "parser_mode": str(args.parser_mode),
            "force_strategy": str(args.force_strategy or ""),
            "ocr_mode": str(args.ocr_mode),
            "extract_tables": not args.no_tables,
            "keep_headers": args.keep_headers,
            "repair_cross_page": args.repair_cross_page,
            "domain_profile": str(args.domain_profile),
            "content_blocks_mode": str(args.content_blocks_mode),
            "rebuild_content_blocks_from_final_text": bool(args.rebuild_content_blocks_from_final_text),
            "emit_content_blocks": not bool(args.no_content_blocks),
            "ocr_enabled": bool(args.ocr),
            "ocr_control_mode": str(args.ocr_control_mode),
            "ocr_engine": str(args.ocr_engine),
            "ocr_force": bool(args.ocr_force),
            "ocr_skip": bool(args.ocr_skip),
            "ocr_pages": str(args.ocr_only_pages or args.ocr_pages or ""),
            "ocr_dpi": int(args.ocr_dpi),
            "ocr_languages": str(args.ocr_languages),
            "ocr_merge_strategy": str(args.ocr_merge_strategy),
            "ocr_min_quality_score": float(args.ocr_min_quality_score),
            "ocr_min_confidence": float(args.ocr_min_confidence),
            "ocr_min_text_chars": int(args.ocr_min_text_chars),
            "ocr_min_words": int(args.ocr_min_words),
            "ocr_min_text_density": float(args.ocr_min_text_density),
            "ocr_broken_encoding_noise_ratio": float(args.ocr_broken_encoding_noise_ratio),
            "ocr_allow_paddle": bool(args.ocr_allow_paddle),
            "ocr_allow_ocrmypdf_page": bool(args.ocr_allow_ocrmypdf_page),
            "ocr_debug": bool(args.ocr_debug),
            "ocr_surya_experimental": bool(args.ocr_surya_experimental),
            "ai_mode": str(args.ai_mode),
            "ai_enabled": bool(args.ai_enabled),
            "ai_provider": str(args.ai_provider),
            "ai_model": str(args.ai_model),
            "ai_render_dpi": int(args.ai_render_dpi),
            "ai_page_image_format": str(args.ai_page_image_format),
            "audit_domain_mode": str(args.audit_domain_mode),
            "sample_chars": max(100, args.sample_chars),
            "sample_blocks": max(0, args.sample_blocks),
        }
        if int(args.per_pdf_timeout_sec or 0) > 0:
            row = analyze_pdf_with_timeout(analyze_kwargs, int(args.per_pdf_timeout_sec or 0))
        else:
            assert parser is not None
            row = analyze_pdf(parser, **analyze_kwargs)
        problem_pages.extend(row.pop("problem_page_items", []))
        informational_pages.extend(row.pop("informational_page_items", []))
        content_block_issues.extend(row.pop("content_block_issue_items", []))
        block_confusion_items.extend(row.pop("block_confusion_items", []))
        layout_issue_items.extend(row.pop("layout_issue_items", []))
        quality_diagnostic_items.extend(row.pop("quality_diagnostic_items", []))
        ocr_debug_items.extend(row.pop("ocr_debug_items", []))
        rows.append(row)
        print(
            f"  {row['status']} pages={row['pages']} chars={row['chars']} "
            f"avg={row['avg_score']} problems={row['problem_pages']} warnings={row['warnings']}"
        )

    elapsed = round(time.perf_counter() - started, 3)
    run_info = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "audit_version": AUDIT_VERSION,
        "script_path": str(Path(__file__).resolve()),
        "python_executable": sys.executable,
        "project_root": str(ROOT),
        "pdf_dir": str(pdf_dir),
        "out_dir": str(out_dir),
        "mode": args.mode,
        "parser_mode": str(args.parser_mode),
        "force_strategy": str(args.force_strategy or ""),
        "ocr_mode": str(args.ocr_mode),
        "ocr_enabled": bool(args.ocr),
        "ocr_control_mode": str(args.ocr_control_mode),
        "ocr_engine": str(args.ocr_engine),
        "ai_mode": str(args.ai_mode),
        "ai_enabled": bool(args.ai_enabled),
        "ai_provider": str(args.ai_provider),
        "ai_model": str(args.ai_model),
        "ocr_force": bool(args.ocr_force),
        "ocr_skip": bool(args.ocr_skip),
        "ocr_pages": str(args.ocr_only_pages or args.ocr_pages or ""),
        "ocr_dpi": int(args.ocr_dpi),
        "ocr_languages": str(args.ocr_languages),
        "ocr_merge_strategy": str(args.ocr_merge_strategy),
        "ocr_min_quality_score": float(args.ocr_min_quality_score),
        "ocr_min_confidence": float(args.ocr_min_confidence),
        "ocr_min_text_chars": int(args.ocr_min_text_chars),
        "ocr_min_words": int(args.ocr_min_words),
        "ocr_min_text_density": float(args.ocr_min_text_density),
        "ocr_broken_encoding_noise_ratio": float(args.ocr_broken_encoding_noise_ratio),
        "ocr_allow_paddle": bool(args.ocr_allow_paddle),
        "ocr_allow_ocrmypdf_page": bool(args.ocr_allow_ocrmypdf_page),
        "ocr_debug": bool(args.ocr_debug),
        "ocr_surya_experimental": bool(args.ocr_surya_experimental),
        "repair_cross_page_continuations": bool(args.repair_cross_page),
        "domain_profile": str(args.domain_profile),
        "content_blocks_mode": str(args.content_blocks_mode),
        "rebuild_content_blocks_from_final_text": bool(args.rebuild_content_blocks_from_final_text),
        "emit_content_blocks": not bool(args.no_content_blocks),
        "sample_blocks": int(args.sample_blocks),
        "audit_domain_mode": str(args.audit_domain_mode),
        "compare": str(args.compare) if args.compare else "",
        "fresh": bool(args.fresh),
        "pdf_count": len(rows),
        "sample_set_hash": sample_list_hash(pdfs, root=ROOT),
        "sample_list_path": str(args.sample_list) if args.sample_list else "",
        "sample_source": sample_source,
        "sample_count": len(pdfs),
        "missing_sample_entries": int(missing_sample_entries),
        "resolved_sample_entries": int(resolved_sample_entries),
        "preflight_only": False,
        "ocr_runtime_ready": bool((preflight_data.get("engines", {}).get("tesseract", {}) or {}).get("available") or (bool(args.ocr_allow_paddle) and (preflight_data.get("engines", {}).get("paddle", {}) or {}).get("available"))),
        "elapsed_sec": elapsed,
        "ocr_preflight": preflight_data if bool(args.ocr_preflight or args.ocr) else {},
    }

    regression_report: dict[str, Any] | None = None
    if baseline_rows is not None:
        regression_report = build_regression_report(rows, baseline_rows)
        regression_report["quality_regression_gate"] = build_quality_regression_summary(regression_report)
        regression_report["ocr_quality_regression_gate"] = build_ocr_quality_regression_summary(
            regression_report,
            ocr_enabled=bool(args.ocr),
        )

    (out_dir / "run_info.json").write_text(json.dumps(run_info, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "problem_pages.json").write_text(json.dumps(problem_pages, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "informational_pages.json").write_text(json.dumps(informational_pages, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "content_block_issues.json").write_text(json.dumps(content_block_issues, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "block_confusion_issues.json").write_text(json.dumps(block_confusion_items, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "layout_issues.json").write_text(json.dumps(layout_issue_items, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "quality_diagnostics.json").write_text(json.dumps(quality_diagnostic_items, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ocr_debug_artifacts.json").write_text(json.dumps(ocr_debug_items, ensure_ascii=False, indent=2), encoding="utf-8")
    ocr_required_docs = []
    for row in rows:
        reason_hits = (
            int(row.get("ocr_recommended_but_disabled") or 0)
            + int(row.get("ocr_skipped_bad_text_layer_pages") or 0)
            + int(row.get("ocr_missing_reason_pages") or 0)
        )
        file_value = str(row.get("file") or "").strip()
        file_name = Path(file_value).name.lower()
        forced_priority = file_name in OCR_PRIORITY_DOC_NAMES
        if reason_hits <= 0 and not forced_priority:
            continue
        if forced_priority and reason_hits <= 0:
            reason_hits = 1
        ocr_required_docs.append(
            (
                file_value,
                int(row.get("serious_pages") or 0),
                int(row.get("review_pages") or 0),
                int(reason_hits),
            )
        )
    ocr_required_docs.sort(key=lambda item: (item[1], item[2], item[3]), reverse=True)
    ocr_required_paths = [item[0] for item in ocr_required_docs if item[0]]
    (out_dir / "ocr_required_docs.json").write_text(
        json.dumps(
            [
                {"file": file_name, "serious_pages": serious_pages, "review_pages": review_pages, "reason_hits": reason_hits}
                for file_name, serious_pages, review_pages, reason_hits in ocr_required_docs
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "ocr_required_sample_list.txt").write_text(
        "\n".join(ocr_required_paths).strip() + ("\n" if ocr_required_paths else ""),
        encoding="utf-8",
    )
    if regression_report is not None:
        (out_dir / "regression_report.json").write_text(json.dumps(regression_report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(out_dir / "summary.csv", rows)
    write_markdown_report(
        out_dir / "REPORT.md",
        rows=rows,
        problem_pages=problem_pages,
        informational_pages=informational_pages,
        content_block_issues=content_block_issues,
        block_confusion_items=block_confusion_items,
        layout_issue_items=layout_issue_items,
        quality_diagnostics=quality_diagnostic_items,
        regression_report=regression_report,
        pdf_dir=pdf_dir,
        out_dir=out_dir,
        args=args,
        missing_sample_entries=missing_sample_entries,
        resolved_sample_entries=resolved_sample_entries,
        ocr_runtime_ready=bool((preflight_data.get("engines", {}).get("tesseract", {}) or {}).get("available") or (bool(args.ocr_allow_paddle) and (preflight_data.get("engines", {}).get("paddle", {}) or {}).get("available"))),
    )


    for old_zip in out_base.glob("pdf_parser_audit_report*.zip"):
        try:
            old_zip.unlink()
        except OSError:
            pass

    zip_path = out_base / f"pdf_parser_audit_report_{AUDIT_VERSION}.zip"
    make_share_zip(zip_path, out_dir)
    legacy_zip_path = out_base / "pdf_parser_audit_report.zip"
    make_share_zip(legacy_zip_path, out_dir)

    status_counter = Counter(r["status"] for r in rows)
    print("-" * 72)
    print(f"Done in {elapsed}s")
    print(f"Status counts: {dict(status_counter)}")
    print(f"Report: {out_dir / 'REPORT.md'}")
    print(f"Summary: {out_dir / 'summary.csv'}")
    if regression_report:
        print(f"Regression compare: {dict(regression_report.get('totals') or {})}")
        print(f"Regression report: {out_dir / 'regression_report.json'}")
    print(f"Share zip: {zip_path}")
    print(f"Legacy zip: {legacy_zip_path}")
    print("Upload the versioned zip above if you want me to inspect the batch results.")
    print(zip_path)

    if args.fail_on_bad and any(str(r.get("status")) in {"BAD", "FAIL"} for r in rows):
        return 2
    if args.fail_on_regression and regression_report and (
        int((regression_report.get("totals") or {}).get("regressed_docs") or 0) > 0
        or has_severe_metric_regression(regression_report)
    ):
        return 3
    if args.fail_on_block_issues:
        block_issue_total = sum(
            int(r.get("block_confusion_issue_pages") or 0)
            + int(r.get("layout_issue_pages") or 0)
            + int(r.get("downstream_projection_issue_pages") or 0)
            for r in rows
        )
        if block_issue_total > 0:
            return 4
    if args.fail_on_quality_regression and regression_report:
        quality_gate = regression_report.get("quality_regression_gate") if isinstance(regression_report, dict) else None
        if isinstance(quality_gate, dict) and bool(quality_gate.get("triggered")):
            return 5
    if args.fail_on_ocr_quality_regression and regression_report:
        ocr_quality_gate = regression_report.get("ocr_quality_regression_gate") if isinstance(regression_report, dict) else None
        if isinstance(ocr_quality_gate, dict) and bool(ocr_quality_gate.get("triggered")):
            return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

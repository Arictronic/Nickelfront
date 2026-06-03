from __future__ import annotations

import os
import py_compile
import re
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
PARSER_ALPHA = ROOT / "parser_alpha"
checks: list[tuple[str, bool, list[str]]] = []
runtime_checks: list[tuple[str, bool, str]] = []


def check(path: str, patterns: list[str]) -> None:
    p = ROOT / path
    ok_file = p.exists()
    text = p.read_text(encoding="utf-8", errors="replace") if ok_file else ""
    missing = [pat for pat in patterns if pat not in text]
    checks.append((path, ok_file and not missing, missing))


def run_python_check(name: str, code: str, *, cwd: Path | None = None) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(BACKEND), str(PARSER_ALPHA), env.get("PYTHONPATH", "")])
    try:
        proc = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(code)],
            cwd=str(cwd or ROOT),
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        runtime_checks.append((name, True, proc.stdout.strip()))
    except subprocess.CalledProcessError as exc:
        detail = (exc.stdout or "") + (exc.stderr or "")
        runtime_checks.append((name, False, detail.strip() or str(exc)))


check("backend/app/__init__.py", ["backend.app", "sys.modules.setdefault"])
check("backend/app/services/__init__.py", ["app.services", "backend.app.services", "sys.modules.setdefault"])
check("backend/app/services/pdf_content_parser.py", [
    "Public service entrypoint",
    "from .pdf_parser import",
    "PDFParser",
    "pdf_parser",
    "PdfExtractionError",
    "PdfPageExtraction",
    "RecursiveCharacterTextSplitter",
    "def parse_bytes",
    "def extract_content",
    "def parse_to_documents",
    "def parse_bytes_to_documents",
    "def extract_content_from_file",
])
check("backend/app/services/pdf_parser/__init__.py", [
    "from .pdf_content_parser import PDFParser, pdf_parser",
    "PdfExtractionError",
    "PdfPageExtraction",
    "def parse_bytes",
    "def extract_content",
    "def parse_bytes_to_documents",
    "def extract_content_from_file",
])
check("backend/app/services/pdf_parser/parser.py", [
    "Compatibility import for the PDF/content parser facade",
    "from .pdf_content_parser import PDFParser, pdf_parser",
    "def parse_bytes",
    "def extract_content",
    "def parse_bytes_to_documents",
])
check("backend/app/services/pdf_parser/config.py", [
    "DEFAULT_PARSER_OPTIONS",
    '"parser_mode": "auto"',
    '"domain_profile": "generic"',
    '"rebuild_content_blocks_from_final_text": True',
    '"ocr_enabled": True',
    '"ocr_mode": "auto"',
    '"force_strategy": ""',
    '"ocr_fallback_engines": ["tesseract"]',
    '"ocr_allow_paddle": False',
    '"ocr_allow_ocrmypdf_page": False',
    '"ai_enabled": False',
    '"ai_mode": "off"',
    "AI_MODE",
    "parser_env_options",
    "merge_parser_options",
    "normalize_parser_options",
    "NICKELFRONT_PDF_PARSER_",
    "PDF_PARSER_",
    "OCR_SKIP",
    "OCR_ONLY_PAGES",
])
check("backend/app/services/pdf_parser/pdf_content_parser.py", [
    "class PDFParser(",
    "AIPageRecognitionService",
    "def extract_pages_from_file",
    "def extract_pages_from_bytes",
    "def parse_bytes",
    "def extract_content",
    "def parse_to_structured_documents",
    "def parse_bytes_to_structured_documents",
    "_normalize_options",
    '"domain_profile": domain_profile',
    '"rebuild_content_blocks_from_final_text"',
    '"ocr_allow_paddle"',
    "def _extract_pdfplumber_page",
    "pdf_parser = PDFParser(chunk_size=1000, chunk_overlap=200)",
])
check("backend/app/services/pdf_parser/content_blocks.py", [
    "class PDFContentBlockMixin",
    "def _content_blocks_from_lines",
    "def _retype_content_blocks",
    "def _refresh_content_blocks_after_context",
    "body_blocks_on_reference_pages",
    "rebuild_content_blocks_from_final_text",
 ])
check("backend/app/services/pdf_parser/documents.py", [
    "class PDFDocumentMixin",
    "def _split_text_to_documents",
    "def _clean_text_for_embeddings",
    "def pages_to_content_parts",
    "def content_parts_to_documents",
    "def _summarize_parser_strategy_metadata",
    "_STRATEGY_METADATA_KEYS",
    "selected_strategies",
    "primary_selected_strategy",
    "ai_used_page_count",
    "embedding_enabled",
    "qwen_enabled",
    "final_content_blocks",
])
check("backend/app/services/pdf_parser/layout.py", [
    "class PDFLayoutMixin",
    "def _extract_words_layout_text",
    "def _extract_columns_text",
])
check("backend/app/services/pdf_parser/tables_ocr.py", [
    "class PDFTablesOcrMixin",
    "def _extract_tables_markdown",
])
check("backend/app/services/pdf_parser/profiles.py", [
    "generic",
    "materials",
    "patents",
])
check("backend/app/services/pdf_parser/ai.py", ["class AIPageRecognitionService", "class AIPageResult", "def run_page_stub"])
check("backend/app/services/pdf_parser/ocr/models.py", ["class OCRPageResult", "class OCRDecision", "class OCRConfig"])
check("backend/app/services/pdf_parser/ocr/detector.py", ["class OCRDetector", "def decide"])
check("backend/app/services/pdf_parser/ocr/service.py", ["class OCRService", "def build_config", "def merge_text"])
check("backend/scripts/pdf_parser_batch_audit.py", [
    'AUDIT_VERSION = "v47_parser_typing_stabilization_full"',
    "build_downstream_projection_audit",
    "build_content_sync_audit",
    "build_ocr_decision_risk_audit",
    "build_domain_specific_audit",
    "final_text_blocks_sync_ratio",
    "final_block_text_not_in_page_text",
    "references_in_body",
    "formulas_in_body",
    "table_markdown_in_body",
    "heading_lost_as_body",
    "caption_false_positive",
    "domain_terms_used_in_generic",
    "ocr_triggered_without_reason",
    "ocr_skipped_on_bad_text_layer",
    "two_column_interleaved_order",
    "duplicated_headers_footers",
    "qwen_projection_block_count",
    "embedding_projection_block_count",
    "recommended_owner",
    "--audit-domain-mode",
    "--parser-mode",
    "--force-strategy",
    "--ocr-mode",
    "--ai-mode",
    "--ai-enabled",
    "--ocr-preflight-only",
    "--fail-on-ocr-quality-regression",
])
check("parser_alpha/parsers_pkg/pdf_processor.py", [
    "CanonicalPDFParser",
    "thin adapter",
    "def extract_text_from_pdf",
    "def parse_bytes",
    "def extract_content",
])
print("Nickelfront PDF parser patch verification")
print("Expected version: v47_parser_typing_stabilization_full + post-merge invariants")
print("Project root:", ROOT)
failed = False
for path, ok, missing in checks:
    status = "OK" if ok else "FAIL"
    print(f"{status:4} {path}")
    if missing:
        failed = True
        for pat in missing:
            print(f"     missing: {pat}")

for rel in ["backend/app/services/pdf_parser/layout.py", "backend/app/services/pdf_parser/content_blocks.py"]:
    text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    if re.search(r"(?<!_)FIGURE_LABEL_LINE_RE\.match", text):
        failed = True
        print(f"FAIL {rel}")
        print("     found stale FIGURE_LABEL_LINE_RE.match; expected _FIGURE_LABEL_LINE_RE.match")

try:
    compile_targets = [
        "backend/app/__init__.py",
        "backend/app/services/__init__.py",
        "backend/app/services/pdf_content_parser.py",
        "backend/app/services/pdf_parser/__init__.py",
        "backend/app/services/pdf_parser/compat.py",
        "backend/app/services/pdf_parser/config.py",
        "backend/app/services/pdf_parser/models.py",
        "backend/app/services/pdf_parser/constants.py",
        "backend/app/services/pdf_parser/ai.py",
        "backend/app/services/pdf_parser/documents.py",
        "backend/app/services/pdf_parser/layout.py",
        "backend/app/services/pdf_parser/content_blocks.py",
        "backend/app/services/pdf_parser/text_cleaning.py",
        "backend/app/services/pdf_parser/document_context.py",
        "backend/app/services/pdf_parser/quality.py",
        "backend/app/services/pdf_parser/tables_ocr.py",
        "backend/app/services/pdf_parser/ocr/__init__.py",
        "backend/app/services/pdf_parser/ocr/models.py",
        "backend/app/services/pdf_parser/ocr/detector.py",
        "backend/app/services/pdf_parser/ocr/service.py",
        "backend/app/services/pdf_parser/ocr/engines/__init__.py",
        "backend/app/services/pdf_parser/ocr/engines/base.py",
        "backend/app/services/pdf_parser/ocr/engines/tesseract_engine.py",
        "backend/app/services/pdf_parser/ocr/engines/paddle_engine.py",
        "backend/app/services/pdf_parser/ocr/engines/ocrmypdf_engine.py",
        "backend/app/services/pdf_parser/ocr/engines/surya_engine.py",
        "backend/app/services/pdf_parser/utils.py",
        "backend/app/services/pdf_parser/parser.py",
        "backend/app/services/pdf_parser/pdf_content_parser.py",
        "backend/scripts/pdf_parser_batch_audit.py",
        "backend/scripts/debug_pdf_extract.py",
        "backend/scripts/verify_pdf_parser_patch.py",
        "parser_alpha/parsers_pkg/pdf_processor.py",
    ]
    for rel in compile_targets:
        py_compile.compile(str(ROOT / rel), doraise=True)
    print("OK   Python syntax compile")
except Exception as exc:
    failed = True
    print("FAIL Python syntax compile:", exc)

run_python_check(
    "public imports and default parser invariants",
    r'''
    from app.services.pdf_content_parser import PDFParser as PublicPDFParser, pdf_parser, PdfPageExtraction, PdfExtractionError
    from app.services.pdf_parser import PDFParser as PackagePDFParser
    from app.services.pdf_parser.parser import PDFParser as CompatPDFParser
    from app.services.pdf_parser.config import DEFAULT_PARSER_OPTIONS, normalize_parser_options, parser_env_options
    assert PublicPDFParser is PackagePDFParser is CompatPDFParser
    assert isinstance(pdf_parser, PublicPDFParser)
    assert hasattr(pdf_parser, "extract_pages_from_bytes")
    assert hasattr(pdf_parser, "parse_bytes")
    assert hasattr(pdf_parser, "extract_content")
    assert hasattr(pdf_parser, "parse_bytes_to_documents")
    assert DEFAULT_PARSER_OPTIONS["parser_mode"] == "auto"
    assert DEFAULT_PARSER_OPTIONS["domain_profile"] == "generic"
    assert DEFAULT_PARSER_OPTIONS["rebuild_content_blocks_from_final_text"] is True
    assert DEFAULT_PARSER_OPTIONS["ocr_enabled"] is True
    assert DEFAULT_PARSER_OPTIONS["ocr_mode"] == "auto"
    assert DEFAULT_PARSER_OPTIONS["ocr_fallback_engines"] == ["tesseract"]
    assert DEFAULT_PARSER_OPTIONS["ocr_allow_paddle"] is False
    assert DEFAULT_PARSER_OPTIONS["ai_enabled"] is False
    assert DEFAULT_PARSER_OPTIONS["ai_mode"] == "off"
    parser = PublicPDFParser()
    public_opts = normalize_parser_options({"parser_mode": "auto"})
    assert public_opts["parser_mode"] == "auto"
    public_ai_opts = normalize_parser_options({"parser_mode": "ai"})
    assert public_ai_opts["parser_mode"] == "ai"
    assert public_ai_opts["force_strategy"] == "ai"
    assert public_ai_opts["ai_mode"] == "force"
    assert public_ai_opts["ai_enabled"] is True
    opts = parser._normalize_options({})
    assert opts["parser_mode"] == "auto"
    assert opts["extraction_mode"] == "auto"
    assert opts["extraction_strategy"] == "auto"
    assert opts["force_strategy"] == ""
    assert opts["ocr_mode"] == "auto"
    assert opts["domain_profile"] == "generic"
    assert opts["rebuild_content_blocks_from_final_text"] is True
    assert opts["ocr_enabled"] is True
    assert opts["ocr_engine"] == "auto"
    assert opts["ocr_fallback_engines"] == ["tesseract"]
    assert opts["ocr_allow_paddle"] is False
    assert opts["ai_enabled"] is False
    assert opts["ai_mode"] == "off"
    forced_columns = parser._normalize_options({"parser_mode": "auto", "force_strategy": "columns"})
    assert forced_columns["parser_mode"] == "auto"
    assert forced_columns["extraction_mode"] == "columns"
    assert forced_columns["force_strategy"] == "columns"
    legacy_columns = parser._normalize_options({"extraction_mode": "columns"})
    assert legacy_columns["parser_mode"] == "auto"
    assert legacy_columns["extraction_mode"] == "columns"
    assert legacy_columns["force_strategy"] == "columns"
    legacy_ocr = parser._normalize_options({"mode": "ocr"})
    assert legacy_ocr["parser_mode"] == "auto"
    assert legacy_ocr["extraction_mode"] == "auto"
    assert legacy_ocr["force_strategy"] == "ocr"
    assert legacy_ocr["ocr_mode"] == "force"
    assert legacy_ocr["ocr_enabled"] is True
    assert legacy_ocr["ocr_engine"] == "tesseract"
    assert legacy_ocr["ocr_force"] is True
    ai_public = parser._normalize_options({"parser_mode": "ai"})
    assert ai_public["parser_mode"] == "ai"
    assert ai_public["force_strategy"] == "ai"
    assert ai_public["extraction_strategy"] == "ai"
    assert ai_public["ai_mode"] == "force"
    ai_legacy = parser._normalize_options({"extraction_mode": "ai"})
    assert ai_legacy["parser_mode"] == "ai"
    assert ai_legacy["force_strategy"] == "ai"
    ai_forced = parser._normalize_options({"force_strategy": "ai"})
    assert ai_forced["parser_mode"] == "auto"
    assert ai_forced["force_strategy"] == "ai"
    assert ai_forced["extraction_strategy"] == "ai"
    assert ai_forced["ai_mode"] == "force"
    assert ai_forced["ai_enabled"] is True
    ai_mode_forced = parser._normalize_options({"ai_mode": "force"})
    assert ai_mode_forced["force_strategy"] == "ai"
    assert ai_mode_forced["ai_enabled"] is True
    ocr_off = parser._normalize_options({"ocr_mode": "off"})
    assert ocr_off["ocr_enabled"] is False
    for bad_public_mode in ("simple", "layout", "columns", "ocr", "scripts"):
        try:
            parser._normalize_options({"parser_mode": bad_public_mode})
        except ValueError:
            pass
        else:
            raise AssertionError(f"parser_mode={bad_public_mode} must be rejected")
    env = parser_env_options({"NICKELFRONT_PDF_PARSER_OCR_SKIP": "true", "PDF_PARSER_DOMAIN_PROFILE": "materials", "PDF_PARSER_FORCE_STRATEGY": "columns", "PDF_PARSER_AI_MODE": "force"})
    assert env["ocr_skip"] is True
    assert env["domain_profile"] == "materials"
    assert env["force_strategy"] == "columns"
    assert env["ai_mode"] == "force"
    from backend.app.services.pdf_content_parser import PDFParser as BackendPDFParser, pdf_parser as backend_pdf_parser
    assert BackendPDFParser is PublicPDFParser
    assert backend_pdf_parser is pdf_parser
    print("OK")
    ''',
)

run_python_check(
    "parser_alpha safe import",
    r'''
    import parser_alpha.parsers_pkg as parsers_pkg
    from parser_alpha.parsers_pkg.pdf_processor import PDFProcessor, CanonicalPDFParser
    assert hasattr(parsers_pkg, "__all__")
    assert CanonicalPDFParser is not None
    processor = PDFProcessor()
    assert hasattr(processor, "parse_bytes")
    assert hasattr(processor, "extract_content")
    print("OK")
    ''',
)

run_python_check(
    "simple PDF parse smoke",
    r'''
    def minimal_pdf_bytes(text="Agent8 Smoke Test"):
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 18 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
        objects = [
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
            b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
            b"5 0 obj << /Length " + str(len(stream)).encode("ascii") + b" >> stream\n" + stream + b"\nendstream endobj\n",
        ]
        out = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for obj in objects:
            offsets.append(len(out))
            out += obj
        xref_pos = len(out)
        out += f"xref\n0 {len(offsets)}\n".encode("ascii")
        out += b"0000000000 65535 f \n"
        for off in offsets[1:]:
            out += f"{off:010d} 00000 n \n".encode("ascii")
        out += f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
        return bytes(out)
    from app.services.pdf_content_parser import PDFParser
    parser = PDFParser()
    content = parser.extract_content(
        file_bytes=minimal_pdf_bytes(),
        filename="agent8_smoke.pdf",
        options={"extract_tables": False, "ocr_enabled": False, "domain_profile": "generic"},
    )
    assert len(content.get("pages") or []) == 1
    assert "Agent8 Smoke Test" in str(content.get("legacy_text") or "")
    assert content.get("content_parts"), "structured content_parts must be emitted"
    assert content.get("documents"), "structured documents must be emitted"
    result_meta = content.get("metadata") or {}
    assert result_meta.get("parser_mode") == "auto"
    assert result_meta.get("primary_selected_strategy") in {"simple", "layout", "columns", "ocr", "ai", "auto"}
    assert isinstance(result_meta.get("selected_strategies"), list)
    first_part_meta = (content.get("content_parts") or [{}])[0].get("metadata") or {}
    assert first_part_meta.get("parser_mode") == "auto"
    assert first_part_meta.get("selected_strategy") in {"simple", "layout", "columns", "ocr", "ai", "auto"}
    first_doc_meta = content["documents"][0].metadata
    assert first_doc_meta.get("parser_mode") == "auto"
    assert first_doc_meta.get("selected_strategy") in {"simple", "layout", "columns", "ocr", "ai", "auto"}
    page = content["pages"][0]
    page_meta = page.get("metadata", {})
    assert page_meta.get("domain_profile") == "generic"
    assert page_meta.get("parser_mode") == "auto"
    assert page_meta.get("selected_strategy") in {"simple", "layout", "columns", "ocr", "ai", "auto"}
    final_blocks = page_meta.get("content_blocks") or []
    assert final_blocks, "content_blocks metadata must be present"
    assert "Agent8 Smoke Test" in " ".join(str(b.get("text") or "") for b in final_blocks)
    print("OK")
    ''',
)

run_python_check(
    "parser strategy metadata propagation",
    r'''
    def minimal_pdf_bytes(text="Strategy Metadata Smoke"):
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 18 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
        objects = [
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
            b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
            b"5 0 obj << /Length " + str(len(stream)).encode("ascii") + b" >> stream\n" + stream + b"\nendstream endobj\n",
        ]
        out = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for obj in objects:
            offsets.append(len(out))
            out += obj
        xref_pos = len(out)
        out += f"xref\n0 {len(offsets)}\n".encode("ascii")
        out += b"0000000000 65535 f \n"
        for off in offsets[1:]:
            out += f"{off:010d} 00000 n \n".encode("ascii")
        out += f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
        return bytes(out)
    from app.services.pdf_content_parser import PDFParser
    parser = PDFParser()
    content = parser.extract_content(
        file_bytes=minimal_pdf_bytes(),
        filename="strategy_smoke.pdf",
        options={"parser_mode": "auto", "force_strategy": "columns", "ocr_enabled": False, "extract_tables": False},
    )
    meta = content.get("metadata") or {}
    assert meta.get("parser_mode") == "auto"
    assert meta.get("force_strategy") == "columns"
    assert meta.get("primary_selected_strategy") in {"columns", "layout", "simple", "auto", "ocr"}
    assert isinstance(meta.get("selected_strategy_counts"), dict)
    assert meta.get("selected_strategy_counts")
    assert isinstance(meta.get("selected_strategies"), list)
    assert "ocr_used_page_count" in meta
    part_meta = content["content_parts"][0]["metadata"]
    assert part_meta.get("parser_mode") == "auto"
    assert part_meta.get("force_strategy") == "columns"
    assert part_meta.get("selected_strategy") in {"columns", "layout", "simple", "auto", "ocr"}
    doc_meta = content["documents"][0].metadata
    assert doc_meta.get("parser_mode") == "auto"
    assert doc_meta.get("force_strategy") == "columns"
    assert doc_meta.get("selected_strategy") in {"columns", "layout", "simple", "auto", "ocr"}
    print("OK")
    ''',
)


run_python_check(
    "AI page recognition placeholder metadata",
    r'''
    from app.services.pdf_content_parser import PDFParser
    parser = PDFParser()
    opts = parser._normalize_options({"parser_mode": "ai"})
    assert opts["parser_mode"] == "ai"
    assert opts["force_strategy"] == "ai"
    assert opts["extraction_strategy"] == "ai"
    assert opts["ai_mode"] == "force"
    assert opts["ai_enabled"] is True
    from app.services.pdf_parser.ai import AIPageRecognitionService
    result = AIPageRecognitionService().run_page_stub(page_number=1, opts=opts)
    assert result.text == ""
    assert result.status in {"not_configured", "disabled", "not_implemented"}
    assert result.metadata["ai_page_image_expected"] is True
    assert result.metadata["ai_external_call_performed"] is False
    print("OK")
    ''',
)

for name, ok, detail in runtime_checks:
    status = "OK" if ok else "FAIL"
    print(f"{status:4} {name}")
    if not ok:
        failed = True
        if detail:
            print(textwrap.indent(detail[-3000:], "     "))

if failed:
    raise SystemExit(1)
print("OK   pdf_content_parser imports")

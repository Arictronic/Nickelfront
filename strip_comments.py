from __future__ import annotations

import argparse
import ast
import io
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
from dataclasses import dataclass
from pathlib import Path
from tokenize import TokenInfo

CODE_EXTENSIONS = frozenset({
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".cjs",
    ".mjs",
    ".css",
    ".scss",
    ".less",
    ".html",
    ".htm",
    ".ps1",
    ".bat",
    ".cmd",
})

CONFIG_EXTENSIONS = frozenset({
    ".ini",
    ".toml",
    ".yml",
    ".yaml",
    ".conf",
})

EXCLUDE_DIRS = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "storage",
    "audit_out",
    "logs",
    ".next",
    ".nuxt",
})

SKIP_NAMES = frozenset({
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
})

REGEX_PREFIX_KEYWORDS = frozenset({
    "return",
    "throw",
    "case",
    "delete",
    "void",
    "typeof",
    "instanceof",
    "new",
    "in",
    "yield",
    "await",
    "else",
    "do",
})

REGEX_PREFIX_CHARS = frozenset("([{=:+-!*%&|^~?,;\n\r")
TS_DIRECTIVE_RE = re.compile(r"^\s*///\s*<(reference|amd|amd-module|lib|types|path)\b", re.IGNORECASE)
PY_ENCODING_RE = re.compile(r"coding[:=]\s*[-\w.]+")
VERSION = "5.0.0-safe-guard"
SCRIPT_MARKER = "strip-comments-safe-guard-20260603-a9f3d2-vite-jsx-regex"

@dataclass(frozen=True)
class FileResult:
    path: Path
    changed: bool
    error: str | None = None


def read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    return raw.decode(encoding), encoding


def write_text(path: Path, text: str, encoding: str) -> None:
    path.write_text(text, encoding=encoding, newline="")


def trim_trailing_space(text: str) -> str:
    lines = text.splitlines(keepends=True)
    cleaned: list[str] = []
    for line in lines:
        newline = ""
        body = line
        if line.endswith("\r\n"):
            body = line[:-2]
            newline = "\r\n"
        elif line.endswith("\n"):
            body = line[:-1]
            newline = "\n"
        elif line.endswith("\r"):
            body = line[:-1]
            newline = "\r"
        cleaned.append(body.rstrip() + newline)
    return "".join(cleaned)


def is_python_metadata_comment(token: TokenInfo, source_line: str) -> bool:
    line_no = token.start[0]
    text = token.string.strip()
    if line_no == 1 and text.startswith("#!"):
        return True
    if line_no <= 2 and PY_ENCODING_RE.search(text):
        return True
    return False


def strip_python(source: str) -> str:
    result: list[TokenInfo] = []
    lines = source.splitlines()
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                source_line = lines[token.start[0] - 1] if 0 <= token.start[0] - 1 < len(lines) else ""
                if is_python_metadata_comment(token, source_line):
                    result.append(token)
                continue
            result.append(token)
        cleaned = tokenize.untokenize(result)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source
    return trim_trailing_space(cleaned)


def last_word(text: str) -> str:
    i = len(text) - 1
    while i >= 0 and text[i].isspace():
        i -= 1
    end = i + 1
    while i >= 0 and (text[i].isalnum() or text[i] in "_$"):
        i -= 1
    return text[i + 1:end]


def previous_significant(out: list[str]) -> str:
    i = len(out) - 1
    while i >= 0 and out[i].isspace():
        i -= 1
    return out[i] if i >= 0 else ""


def previous_text(out: list[str], limit: int = 120) -> str:
    start = max(0, len(out) - limit)
    return "".join(out[start:])


def should_start_regex(out: list[str]) -> bool:
    prev = previous_significant(out)
    if not prev:
        return True
    if prev in REGEX_PREFIX_CHARS:
        return True
    word = last_word(previous_text(out))
    return word in REGEX_PREFIX_KEYWORDS


def current_line_prefix(out: list[str]) -> str:
    i = len(out) - 1
    while i >= 0 and out[i] not in "\r\n":
        i -= 1
    return "".join(out[i + 1:])


def starts_ts_directive(source: str, index: int, out: list[str]) -> bool:
    if not source.startswith("///", index):
        return False
    prefix = current_line_prefix(out)
    if prefix.strip():
        return False
    end = source.find("\n", index)
    if end == -1:
        end = len(source)
    line = prefix + source[index:end]
    return bool(TS_DIRECTIVE_RE.match(line))


def is_jsx_tag_start(source: str, index: int, out: list[str]) -> bool:
    if index + 1 >= len(source):
        return False
    nxt = source[index + 1]
    if nxt not in "/>ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
        return False
    prev = previous_significant(out)
    if not prev:
        return True
    if prev in "([{=,:;!?\n\r":
        return True
    word = last_word(previous_text(out))
    return word in {"return", "yield"}


def copy_line(source: str, index: int, out: list[str]) -> int:
    n = len(source)
    while index < n:
        out.append(source[index])
        if source[index] == "\n":
            return index + 1
        index += 1
    return index


def skip_line_comment(source: str, index: int) -> int:
    n = len(source)
    index += 2
    while index < n and source[index] not in "\r\n":
        index += 1
    return index


def skip_block_comment(source: str, index: int, out: list[str], compact_space: bool = True, jsx_comment: bool = False) -> int:
    n = len(source)
    if compact_space and out and not out[-1].isspace():
        out.append(" ")
    index += 2
    while index < n:
        if source[index] in "\r\n":
            out.append(source[index])
            if source[index] == "\r" and index + 1 < n and source[index + 1] == "\n":
                index += 1
                out.append(source[index])
        elif source[index] == "*" and index + 1 < n and source[index + 1] == "/":
            index += 2
            if jsx_comment:
                while index < n and source[index].isspace() and source[index] not in "\r\n":
                    index += 1
                if index < n and source[index] == "}":
                    index += 1
            return index
        index += 1
    return index


def strip_js_like_comments(source: str, jsx: bool) -> str:
    out: list[str] = []
    i = 0
    n = len(source)
    state = "normal"
    regex_class = False
    jsx_stack: list[tuple[str, int]] = []
    template_stack: list[int] = []
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if state == "normal":
            if jsx_stack and ch == "{":
                jsx_stack[-1] = (jsx_stack[-1][0], jsx_stack[-1][1] + 1)
                out.append(ch)
                i += 1
                continue
            if jsx_stack and ch == "}":
                return_state, depth = jsx_stack[-1]
                if depth <= 0:
                    out.append(ch)
                    jsx_stack.pop()
                    state = return_state
                    i += 1
                    continue
                jsx_stack[-1] = (return_state, depth - 1)
                out.append(ch)
                i += 1
                continue
            if template_stack and ch == "{":
                template_stack[-1] += 1
                out.append(ch)
                i += 1
                continue
            if template_stack and ch == "}":
                if template_stack[-1] <= 0:
                    out.append(ch)
                    template_stack.pop()
                    state = "template"
                    i += 1
                    continue
                template_stack[-1] -= 1
                out.append(ch)
                i += 1
                continue
            if jsx and ch == "<" and is_jsx_tag_start(source, i, out):
                out.append(ch)
                state = "jsx_tag"
                i += 1
                continue
            if ch == "'":
                out.append(ch)
                state = "single"
                i += 1
                continue
            if ch == '"':
                out.append(ch)
                state = "double"
                i += 1
                continue
            if ch == "`":
                out.append(ch)
                state = "template"
                i += 1
                continue
            if ch == "/" and should_start_regex(out) and nxt not in {"/", "*"}:
                out.append(ch)
                state = "regex"
                regex_class = False
                i += 1
                continue
            if ch == "/" and nxt == "/":
                if starts_ts_directive(source, i, out):
                    i = copy_line(source, i, out)
                else:
                    i = skip_line_comment(source, i)
                continue
            if ch == "/" and nxt == "*":
                i = skip_block_comment(source, i, out)
                continue
            out.append(ch)
            i += 1
            continue
        if state == "single":
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                i += 1
                out.append(source[i])
            elif ch == "'":
                state = "normal"
            i += 1
            continue
        if state == "double":
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                i += 1
                out.append(source[i])
            elif ch == '"':
                state = "normal"
            i += 1
            continue
        if state == "template":
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                i += 1
                out.append(source[i])
            elif ch == "`":
                state = "normal"
            elif ch == "$" and nxt == "{":
                i += 1
                out.append(source[i])
                template_stack.append(0)
                state = "normal"
            i += 1
            continue
        if state == "regex":
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                i += 1
                out.append(source[i])
            elif ch == "[":
                regex_class = True
            elif ch == "]":
                regex_class = False
            elif ch == "/" and not regex_class:
                state = "normal"
            i += 1
            continue
        if state == "jsx_tag":
            if ch == "'":
                out.append(ch)
                state = "jsx_single"
                i += 1
                continue
            if ch == '"':
                out.append(ch)
                state = "jsx_double"
                i += 1
                continue
            if ch == "{":
                out.append(ch)
                jsx_stack.append(("jsx_tag", 0))
                state = "normal"
                i += 1
                continue
            out.append(ch)
            if ch == ">":
                state = "jsx_text"
            i += 1
            continue
        if state == "jsx_text":
            if ch == "{" and nxt == "/" and i + 2 < n and source[i + 2] == "*":
                i = skip_block_comment(source, i + 1, out, compact_space=False, jsx_comment=True)
                continue
            if ch == "{":
                out.append(ch)
                jsx_stack.append(("jsx_text", 0))
                state = "normal"
                i += 1
                continue
            if ch == "<":
                out.append(ch)
                state = "jsx_tag"
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if state == "jsx_single":
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                i += 1
                out.append(source[i])
            elif ch == "'":
                state = "jsx_tag"
            i += 1
            continue
        if state == "jsx_double":
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                i += 1
                out.append(source[i])
            elif ch == '"':
                state = "jsx_tag"
            i += 1
            continue
    return trim_trailing_space("".join(out))


def strip_css_comments(source: str) -> str:
    out: list[str] = []
    i = 0
    n = len(source)
    state = "normal"
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if state == "normal":
            if ch in {"'", '"'}:
                out.append(ch)
                state = ch
                i += 1
                continue
            if ch == "/" and nxt == "*":
                i = skip_block_comment(source, i, out)
                continue
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        if ch == "\\" and i + 1 < n:
            i += 1
            out.append(source[i])
        elif ch == state:
            state = "normal"
        i += 1
    return trim_trailing_space("".join(out))


def strip_html_comments(source: str) -> str:
    out: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        if source.startswith("<!--", i):
            i += 4
            while i < n and not source.startswith("-->", i):
                if source[i] in "\r\n":
                    out.append(source[i])
                    if source[i] == "\r" and i + 1 < n and source[i + 1] == "\n":
                        i += 1
                        out.append(source[i])
                i += 1
            if i < n:
                i += 3
            continue
        out.append(source[i])
        i += 1
    return trim_trailing_space("".join(out))


def strip_powershell_comments(source: str) -> str:
    out: list[str] = []
    i = 0
    n = len(source)
    state = "normal"
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if state == "normal":
            if ch == "@" and nxt in {"'", '"'}:
                terminator = nxt + "@"
                out.append(ch)
                i += 1
                out.append(source[i])
                i += 1
                while i < n:
                    out.append(source[i])
                    if source.startswith(terminator, i):
                        if i == 0 or source[i - 1] in "\r\n":
                            i += 2
                            break
                    i += 1
                continue
            if ch == "'":
                out.append(ch)
                state = "single"
                i += 1
                continue
            if ch == '"':
                out.append(ch)
                state = "double"
                i += 1
                continue
            if ch == "<" and nxt == "#":
                i += 2
                while i < n:
                    if source[i] in "\r\n":
                        out.append(source[i])
                        if source[i] == "\r" and i + 1 < n and source[i + 1] == "\n":
                            i += 1
                            out.append(source[i])
                    elif source[i] == "#" and i + 1 < n and source[i + 1] == ">":
                        i += 2
                        break
                    i += 1
                continue
            if ch == "#":
                i += 1
                while i < n and source[i] not in "\r\n":
                    i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if state == "single":
            out.append(ch)
            if ch == "'":
                if i + 1 < n and source[i + 1] == "'":
                    i += 1
                    out.append(source[i])
                else:
                    state = "normal"
            i += 1
            continue
        out.append(ch)
        if ch == "`" and i + 1 < n:
            i += 1
            out.append(source[i])
        elif ch == '"':
            if i + 1 < n and source[i + 1] == '"':
                i += 1
                out.append(source[i])
            else:
                state = "normal"
        i += 1
    return trim_trailing_space("".join(out))


def strip_batch_comments(source: str) -> str:
    result: list[str] = []
    for line in source.splitlines(keepends=True):
        body = line.lstrip()
        probe = body[1:].lstrip() if body.startswith("@") else body
        low = probe.lower()
        newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        if low.startswith("::"):
            continue
        if low == "rem" or low.startswith("rem ") or low.startswith("rem\t"):
            continue
        result.append(line.rstrip() + newline)
    return "".join(result)


def strip_config_comments(source: str) -> str:
    out: list[str] = []
    for line in source.splitlines(keepends=True):
        stripped = line.lstrip()
        newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        if stripped.startswith("#") or stripped.startswith(";"):
            continue
        out.append(line.rstrip() + newline)
    return "".join(out)



def validate_known_javascript_damage(path: Path, text: str) -> str | None:
    if path.name.lower() == "vite.config.js" and re.search(r"/\^https\?:\\/\\\s*(?:\r?\n|$)", text):
        return "Known strip_comments regex damage detected in vite.config.js"
    return None


def validate_javascript_syntax(path: Path, text: str) -> str | None:
    known_damage = validate_known_javascript_damage(path, text)
    if known_damage:
        return known_damage
    if path.suffix.lower() not in {".js", ".cjs", ".mjs"}:
        return None
    node = shutil.which("node")
    if not node:
        return None
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=path.suffix.lower(), delete=False, newline="") as handle:
            handle.write(text)
            temp_path = Path(handle.name)
        result = subprocess.run([node, "--check", str(temp_path)], capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "JavaScript syntax validation failed").strip()
            return message.replace(str(temp_path), str(path))
    except Exception as exc:
        return f"JavaScript syntax validation error: {exc}"
    finally:
        if temp_path:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
    return None


def run_self_test() -> list[str]:
    errors: list[str] = []
    js_source = "function f(raw) {\n  if (/^https?:\\/\\//i.test(raw)) {\n    return raw; // comment\n  }\n}\n"
    js_expected = "function f(raw) {\n  if (/^https?:\\/\\//i.test(raw)) {\n    return raw;\n  }\n}\n"
    js_cleaned = strip_js_like_comments(js_source, jsx=False)
    if js_cleaned != js_expected:
        errors.append("JS regex self-test failed")
    vite_source = "try {\n  if (/^https?:\\/\\//i.test(raw)) { // keep regex, remove comment\n    return raw;\n  }\n} catch (error) {\n  return null;\n}\n"
    vite_cleaned = strip_js_like_comments(vite_source, jsx=False)
    if "/^https?:\\/\\//i.test(raw)" not in vite_cleaned or "remove comment" in vite_cleaned:
        errors.append("Vite regex self-test failed")
    vite_damage = validate_known_javascript_damage(Path("vite.config.js"), "if (/^https?:\\/\\\n")
    if not vite_damage:
        errors.append("Vite damage guard self-test failed")
    ts_source = "/// <reference types=\"vite/client\" />\nconst a = 1; // comment\n"
    ts_cleaned = strip_js_like_comments(ts_source, jsx=False)
    if "/// <reference types=\"vite/client\" />" not in ts_cleaned or "// comment" in ts_cleaned:
        errors.append("TypeScript directive self-test failed")
    tsx_source = "export function X(){\n  return <div>{/* remove */}<span>http://x // text</span></div>\n}\n"
    tsx_cleaned = strip_js_like_comments(tsx_source, jsx=True)
    if "{/* remove */}" in tsx_cleaned or "http://x // text" not in tsx_cleaned or "</div>" not in tsx_cleaned:
        errors.append("TSX JSX self-test failed")
    css_source = ".a { content: \"/* keep */\"; } /* remove */\n"
    css_cleaned = strip_css_comments(css_source)
    if "/* remove */" in css_cleaned or "/* keep */" not in css_cleaned:
        errors.append("CSS self-test failed")
    py_source = "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nx = '# keep' # remove\n"
    py_cleaned = strip_python(py_source)
    if "#!/usr/bin/env python3" not in py_cleaned or "coding: utf-8" not in py_cleaned or "# remove" in py_cleaned or "'# keep'" not in py_cleaned:
        errors.append("Python self-test failed")
    validation = validate_javascript_syntax(Path("vite.config.js"), js_cleaned)
    if validation:
        errors.append(f"JavaScript syntax self-test failed: {validation}")
    return errors


def strip_file_content(path: Path, source: str, include_config: bool) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix == ".py":
        return strip_python(source)
    if suffix in {".jsx", ".tsx"}:
        return strip_js_like_comments(source, jsx=True)
    if suffix in {".js", ".ts", ".cjs", ".mjs"}:
        return strip_js_like_comments(source, jsx=False)
    if suffix in {".css", ".scss", ".less"}:
        return strip_css_comments(source)
    if suffix == ".ps1":
        return strip_powershell_comments(source)
    if suffix in {".bat", ".cmd"}:
        return strip_batch_comments(source)
    if suffix in {".html", ".htm"}:
        return strip_html_comments(source)
    if include_config and (suffix in CONFIG_EXTENSIONS or name in {".env", ".env.example"}):
        return strip_config_comments(source)
    return source


def allowed_extensions(include_config: bool, extra_extensions: list[str]) -> set[str]:
    extensions = set(CODE_EXTENSIONS)
    if include_config:
        extensions.update(CONFIG_EXTENSIONS)
        extensions.add(".env")
    for extension in extra_extensions:
        normalized = extension if extension.startswith(".") else f".{extension}"
        extensions.add(normalized.lower())
    return extensions


def should_skip(path: Path, root: Path, extensions: set[str]) -> bool:
    if path.name in SKIP_NAMES:
        return True
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return True
    suffix = path.suffix.lower()
    if path.name.lower() in {".env", ".env.example"}:
        return ".env" not in extensions
    return suffix not in extensions


def iter_files(target: Path, extensions: set[str]) -> list[Path]:
    if target.is_file():
        return [target] if not should_skip(target, target.parent, extensions) else []
    return sorted(path for path in target.rglob("*") if path.is_file() and not should_skip(path, target, extensions))


def process_file(path: Path, include_config: bool, write: bool, backup: bool) -> FileResult:
    try:
        original, encoding = read_text(path)
    except Exception as exc:
        return FileResult(path=path, changed=False, error=str(exc))
    cleaned = strip_file_content(path, original, include_config=include_config)
    if cleaned != original:
        validation_error = validate_javascript_syntax(path, cleaned)
        if validation_error:
            return FileResult(path=path, changed=False, error=validation_error)
    if cleaned == original:
        return FileResult(path=path, changed=False)
    if write:
        try:
            if backup:
                backup_path = path.with_name(path.name + ".bak")
                backup_path.write_text(original, encoding=encoding, newline="")
            write_text(path, cleaned, encoding)
        except Exception as exc:
            return FileResult(path=path, changed=False, error=str(exc))
    return FileResult(path=path, changed=True)


def relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Безопасно удаляет комментарии из файлов кода, не трогая строки, UI-тексты, промпты, логи, regex, JSX text и TypeScript directives.")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--no-self-test", action="store_true")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--include-config", action="store_true")
    parser.add_argument("--ext", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.check and args.write:
        parser.error("--check нельзя использовать вместе с --write")
    if args.self_test:
        self_test_errors = run_self_test()
        if self_test_errors:
            for error in self_test_errors:
                print(f"self-test error: {error}")
            return 1
        print(f"strip_comments.py v{VERSION}: self-test ok")
        return 0
    if not args.no_self_test:
        self_test_errors = run_self_test()
        if self_test_errors:
            print(f"strip_comments.py v{VERSION}: встроенная проверка не прошла")
            for error in self_test_errors:
                print(f"self-test error: {error}")
            return 1
    root = Path(args.root).resolve()
    if not root.exists():
        print(f"Не найден путь: {root}")
        return 1
    extensions = allowed_extensions(include_config=args.include_config, extra_extensions=args.ext)
    files = iter_files(root, extensions)
    results = [process_file(path, include_config=args.include_config, write=args.write, backup=args.backup) for path in files]
    changed = [result.path for result in results if result.changed]
    errors = [result for result in results if result.error]
    mode = "write" if args.write else "dry-run"
    base = root if root.is_dir() else root.parent
    print(f"Версия: {VERSION}")
    print(f"Сигнатура: {SCRIPT_MARKER}")
    print(f"Режим: {mode}")
    print(f"Путь: {root}")
    print(f"Проверено файлов: {len(files)}")
    print(f"Файлов с изменениями: {len(changed)}")
    for path in changed:
        print(f"changed: {relative(path, base)}")
    for error in errors:
        print(f"error: {relative(error.path, base)}: {error.error}")
    if errors:
        return 1
    if args.check and changed:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


"""Удаляет все #-комментарии из Python-файлов в указанной директории."""

from __future__ import annotations

import argparse
import io
import sys
import tokenize
from pathlib import Path
from tokenize import TokenInfo

EXCLUDE_DIRS = frozenset({
    ".git", ".hg", ".svn",
    ".venv", "venv", "env",
    "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache",
    ".idea", ".vscode",
    "node_modules", "dist", "build",
    "storage", "audit_out", "logs",
})


def should_skip(path: Path, root: Path) -> bool:
    """Пропускает файлы в системных/зависимых папках."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part in EXCLUDE_DIRS for part in rel.parts)


def strip_comments(source: str) -> str:
    """Удаляет все #-комментарии, сохраняя структуру кода."""
    tokens: list[TokenInfo] = []
    try:
        stream = io.StringIO(source)
        for tok in tokenize.generate_tokens(stream.readline):
            if tok.type != tokenize.COMMENT:
                tokens.append(tok)
        cleaned = tokenize.untokenize(tokens)
    except tokenize.TokenError:

        return source


    lines = cleaned.splitlines(keepends=True)
    result: list[str] = []
    for line in lines:
        stripped = line.rstrip()
        result.append(f"{stripped}\n" if stripped else "\n")
    return "".join(result)


def process_file(filepath: Path, dry_run: bool = False) -> bool:
    """Обрабатывает один файл. Возвращает True, если были изменения."""
    try:
        raw = filepath.read_bytes()
        encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
        original = raw.decode(encoding)
    except Exception as e:
        print(f"❌ Ошибка чтения {filepath}: {e}")
        return False

    cleaned = strip_comments(original)
    if cleaned == original:
        return False

    if dry_run:
        return True

    try:
        filepath.write_text(cleaned, encoding=encoding)
        return True
    except Exception as e:
        print(f"❌ Ошибка записи {filepath}: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Удаляет все #-комментарии из .py файлов в директории."
    )
    parser.add_argument(
        "root", nargs="?", default=".",
        help="Корневая директория проекта (по умолчанию: текущая)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Только показать файлы, которые будут изменены (без записи)"
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"❌ Директория не найдена: {root}")
        return 1

    changed: list[Path] = []
    errors = 0

    print(f"🔍 Сканирование: {root}")
    for py_file in sorted(root.rglob("*.py")):
        if should_skip(py_file, root):
            continue
        if py_file.name.endswith((".bak", ".tmp", ".pyc")):
            continue

        try:
            was_modified = process_file(py_file, dry_run=args.dry_run)
        except Exception as e:
            print(f"⚠️ Пропуск {py_file}: {e}")
            errors += 1
            continue

        if was_modified:
            changed.append(py_file)
            rel = py_file.relative_to(root)
            status = "🔸 Будет изменён" if args.dry_run else "✅ Изменён"
            print(f"{status}: {rel}")

    print("\n" + "=" * 40)
    if args.dry_run:
        print(f"📋 Dry-run завершён. Файлов для изменения: {len(changed)}")
        if changed:
            print("👉 Запустите без --dry-run для фактического удаления комментариев.")
    else:
        print(f"🎯 Готово. Изменено файлов: {len(changed)}")
        if errors:
            print(f"⚠️ Пропущено файлов с ошибками: {errors}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

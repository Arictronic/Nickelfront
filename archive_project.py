#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
archive_project.py

Создаёт zip-архив проекта в папке archives/.

Что делает:
- архивы складываются в ./archives;
- папка archives не попадает внутрь архива;
- backend/app/db/models попадает в архив, даже если в .gitignore есть models/;
- requirements.txt, pyproject.toml, package.json, alembic, frontend/src и код проекта сохраняются;
- из markdown-документов в архив попадают только:
    - README.md в корне проекта;
    - все .md/.mdx/.markdown файлы внутри docs/;
- .env в корне проекта попадает в архив;
- .env.local, .env.production, ключи, pem, service-account.json и прочие секреты НЕ попадают;
- исключает мусор: .git, __pycache__, node_modules, venv, build/dist, кеши, логи, большие ML-веса;
- поддерживает dry-run и verbose.

Примеры:

    python archive_project.py

    python archive_project.py --dry-run --verbose

    python archive_project.py --output archives/Nickelfront.zip

    python archive_project.py --max-file-size-mb 25
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


# -----------------------------------------------------------------------------
# Настройки по умолчанию
# -----------------------------------------------------------------------------

DEFAULT_OUTPUT_PREFIX = "project_archive"
DEFAULT_MAX_FILE_SIZE_MB = 50


DEFAULT_EXCLUDE_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".nickelfront_setup_state",
    ".tmp_wheels",

    "archives",
    "chroma_db",

    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".coverage",
    "htmlcov",

    "node_modules",
    ".next",
    ".nuxt",
    ".svelte-kit",
    "dist",
    "build",
    "coverage",

    ".venv",
    "venv",
    "env",
    "ENV",
    "runtime",

    ".cache",
    "cache",
    "tmp",
    "temp",
    "logs",
    "log",
    "redis",
    "ml",
    "models",

    ".DS_Store",
}


DEFAULT_EXCLUDE_FILE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",

    ".coverage",
    "coverage.xml",

    ".env.local",
    ".env.development.local",
    ".env.test.local",
    ".env.production.local",
}


DEFAULT_EXCLUDE_PATTERNS = {
    # Python artifacts
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.egg-info",
    "*.egg",

    # JS artifacts
    "*.tsbuildinfo",

    # Logs / dumps / temp
    "*.log",
    "*.tmp",
    "*.temp",
    "*.bak",
    "*.swp",
    "*.swo",
    "*.orig",

    # Databases / binary local state
    "*.sqlite",
    "*.sqlite3",
    "*.db",

    # Archives
    "*.zip",
    "*.tar",
    "*.tar.gz",
    "*.tgz",
    "*.rar",
    "*.7z",

    # Large ML / model artifacts
    "*.pth",
    "*.pt",
    "*.onnx",
    "*.ckpt",
    "*.safetensors",
    "*.bin",

    # Media usually not needed for code review
    "*.mp4",
    "*.mov",
    "*.avi",
    "*.mkv",
    "*.mp3",
    "*.wav",
    "*.flac",

    # Office/PDF documents are excluded by default
    "*.pdf",
    "*.doc",
    "*.docx",
    "*.odt",
}


# Важные файлы, которые надо включать даже если .gitignore их игнорирует.
ALWAYS_INCLUDE_FILE_PATTERNS = {
    # Только README.md из корневых markdown-документов
    "README.md",
    "readme.md",

    # Разрешаем архивировать корневой .env
    ".env",

    "LICENSE",
    "LICENSE.*",

    "requirements.txt",
    "requirements-*.txt",
    "**/requirements.txt",
    "**/requirements-*.txt",

    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "poetry.lock",
    "uv.lock",
    "Pipfile",
    "Pipfile.lock",

    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",

    "tsconfig.json",
    "tsconfig.*.json",
    "vite.config.js",
    "vite.config.ts",
    "webpack.config.js",

    "Dockerfile",
    "Dockerfile.*",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",

    ".env.example",
    ".env.template",
    "example.env",

    "alembic.ini",
    "**/alembic.ini",

    # Markdown-документы только внутри docs/
    "docs/**/*.md",
    "docs/**/*.mdx",
    "docs/**/*.markdown",
    "docs/*.md",
    "docs/*.mdx",
    "docs/*.markdown",
}


# Важные директории, которые нельзя выкидывать из-за правил вроде models/.
ALWAYS_INCLUDE_DIR_PATTERNS = {
    "backend/app/db/models",
    "backend/app/db/models/**",

    "backend/alembic",
    "backend/alembic/**",
    "alembic",
    "alembic/**",

    ".github",
    ".github/**",

    # docs нужна, чтобы пройти внутрь и забрать markdown-файлы
    "docs",
    "docs/**",

    "tests",
    "tests/**",
    "backend/tests",
    "backend/tests/**",

    "frontend/src",
    "frontend/src/**",
}


# Опасные/мусорные директории, которые исключаем даже без .gitignore.
EXCLUDE_DIR_PATTERNS = {
    "**/__pycache__",
    "**/.pytest_cache",
    "**/.mypy_cache",
    "**/.ruff_cache",
    "**/node_modules",
    "**/.venv",
    "**/venv",
    "**/dist",
    "**/build",
    "**/coverage",
    "**/htmlcov",
    "**/.next",
    "**/.nuxt",

    "archives",
    "archives/**",
}


ROOT_EXCLUDE_DIR_NAMES = {
    "archives",
    "data",
    "storage",
    "uploads",
    "media",
    "checkpoints",
    "ml_models",
    "models_cache",
    ".tmp_wheels",
    "chroma_db",
    "redis",
    "runtime",
    "ml",
    "models",
    ".nickelfront_setup_state",
}


ROOT_EXCLUDE_DIR_GLOBS = {
    "venv_broken*",
}


# Секреты не включаем.
# Исключение: корневой .env включается отдельно.
SECRET_FILE_PATTERNS = {
    ".env.*",
    "**/.env.*",

    "*.pem",
    "*.key",
    "*.crt",
    "*.p12",
    "*.pfx",

    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "**/id_rsa",
    "**/id_dsa",
    "**/id_ecdsa",
    "**/id_ed25519",

    "secrets.json",
    "**/secrets.json",
    "service-account.json",
    "**/service-account.json",
}


MARKDOWN_EXTENSIONS = {
    ".md",
    ".mdx",
    ".markdown",
}


LLM_EXCLUDE_FILE_PATTERNS = {
    "*.har",
    "*.csv",
    "*.parquet",
    "*.rdb",
    "*.ipynb",
}


# -----------------------------------------------------------------------------
# Gitignore parser
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class IgnoreRule:
    pattern: str
    negated: bool
    directory_only: bool
    anchored: bool
    source: str


def normalize_rel(path: Path | str) -> str:
    return str(path).replace(os.sep, "/").strip("/")


def parse_gitignore_file(path: Path, root: Path) -> list[IgnoreRule]:
    rules: list[IgnoreRule] = []

    if not path.exists() or not path.is_file():
        return rules

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return rules

    base_dir = path.parent
    base_dir_rel = normalize_rel(base_dir.relative_to(root))

    for raw_line in lines:
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        negated = line.startswith("!")
        if negated:
            line = line[1:].strip()

        if not line:
            continue

        directory_only = line.endswith("/")
        if directory_only:
            line = line.rstrip("/")

        anchored = line.startswith("/")
        line = line.lstrip("/")

        if not line:
            continue

        rules.append(
            IgnoreRule(
                pattern=line,
                negated=negated,
                directory_only=directory_only,
                anchored=anchored,
                source=base_dir_rel,
            )
        )

    return rules


def _load_root_gitignore_rules(root: Path) -> list[IgnoreRule]:
    """
    Загружает только корневой .gitignore.
    """
    return parse_gitignore_file(root / ".gitignore", root)


def load_gitignore_rules(root: Path) -> list[IgnoreRule]:
    """
    Загружает все .gitignore внутри проекта, кроме жёстко исключённых директорий.
    """
    rules: list[IgnoreRule] = []

    for current_root, dir_names, file_names in os.walk(root):
        current_path = Path(current_root)

        kept_dirs: list[str] = []
        for dir_name in dir_names:
            abs_dir = current_path / dir_name
            rel_dir = normalize_rel(abs_dir.relative_to(root))

            if is_hard_excluded_dir(rel_dir, dir_name):
                continue

            kept_dirs.append(dir_name)

        dir_names[:] = kept_dirs

        if ".gitignore" in file_names:
            rules.extend(parse_gitignore_file(current_path / ".gitignore", root))

    return rules


def path_matches_pattern(rel_path: str, pattern: str) -> bool:
    rel_path = normalize_rel(rel_path)
    pattern = normalize_rel(pattern)

    if not rel_path:
        return False

    candidates = {
        rel_path,
        "/" + rel_path,
    }

    for candidate in candidates:
        if fnmatch.fnmatch(candidate, pattern):
            return True

    # Если паттерн без slash, он может совпадать с любым сегментом пути.
    if "/" not in pattern:
        parts = rel_path.split("/")
        if any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True

    # Паттерн директории/пути.
    if rel_path == pattern or rel_path.startswith(pattern.rstrip("/") + "/"):
        return True

    # Glob через **.
    if fnmatch.fnmatch(rel_path, pattern):
        return True

    return False


def match_gitignore_rule(rel_path: str, is_dir: bool, rule: IgnoreRule) -> bool:
    rel_path = normalize_rel(rel_path)
    rule_source = normalize_rel(rule.source)
    pattern = normalize_rel(rule.pattern)

    if rule_source:
        if rel_path == rule_source:
            scoped_path = ""
        elif rel_path.startswith(rule_source + "/"):
            scoped_path = rel_path[len(rule_source) + 1 :]
        else:
            return False
    else:
        scoped_path = rel_path

    if not scoped_path:
        return False

    if rule.anchored:
        matched = (
            scoped_path == pattern
            or scoped_path.startswith(pattern.rstrip("/") + "/")
            or fnmatch.fnmatch(scoped_path, pattern)
            or fnmatch.fnmatch("/" + scoped_path, "/" + pattern)
        )
    else:
        matched = path_matches_pattern(scoped_path, pattern)

    if matched:
        return True

    if not rule.directory_only:
        return False

    parent_candidates = list(Path(scoped_path).parents)
    if is_dir:
        parent_candidates.insert(0, Path(scoped_path))

    for parent in parent_candidates:
        parent_str = normalize_rel(parent)
        if not parent_str or parent_str == ".":
            continue

        if rule.anchored:
            if (
                parent_str == pattern
                or parent_str.startswith(pattern.rstrip("/") + "/")
                or fnmatch.fnmatch(parent_str, pattern)
            ):
                return True
        elif path_matches_pattern(parent_str, pattern):
            return True

    return False


def matches_any(rel_path: str, patterns: Iterable[str]) -> bool:
    return any(path_matches_pattern(rel_path, pattern) for pattern in patterns)


def name_matches_any(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def is_root_env_file(rel_path: str) -> bool:
    return normalize_rel(rel_path) == ".env"


def is_always_include_file(rel_path: str) -> bool:
    return matches_any(rel_path, ALWAYS_INCLUDE_FILE_PATTERNS)


def is_always_include_dir(rel_path: str) -> bool:
    return matches_any(rel_path, ALWAYS_INCLUDE_DIR_PATTERNS)


def is_inside_always_include_dir(rel_path: str) -> bool:
    """
    Проверяет, лежит ли файл/путь внутри важной директории.

    Нужно, чтобы правило .gitignore вроде:
        models/

    не выкинуло файлы:
        backend/app/db/models/user.py
        backend/app/db/models/paper.py
    """
    rel_path = normalize_rel(rel_path)

    if not rel_path:
        return False

    parts = rel_path.split("/")

    for index in range(1, len(parts)):
        parent = "/".join(parts[:index])
        if is_always_include_dir(parent):
            return True

    return False


def is_docs_markdown_file(rel_path: str) -> bool:
    rel_path = normalize_rel(rel_path)
    path = Path(rel_path)

    return (
        rel_path.startswith("docs/")
        and path.suffix.lower() in MARKDOWN_EXTENSIONS
    )


def is_root_readme_file(rel_path: str) -> bool:
    rel_path = normalize_rel(rel_path)
    return rel_path.lower() == "readme.md"


def is_markdown_file(rel_path: str) -> bool:
    return Path(normalize_rel(rel_path)).suffix.lower() in MARKDOWN_EXTENSIONS


def is_disallowed_markdown_file(rel_path: str, no_markdown: bool = False) -> bool:
    """
    В архиве из markdown должны остаться только:
    - README.md в корне;
    - .md/.mdx/.markdown внутри docs/.
    """
    if not is_markdown_file(rel_path):
        return False

    if no_markdown:
        return True

    if is_root_readme_file(rel_path):
        return False

    if is_docs_markdown_file(rel_path):
        return False

    return True


def is_secret_file(rel_path: str) -> bool:
    rel_path = normalize_rel(rel_path)

    # Пользователь явно попросил включать корневой .env.
    if is_root_env_file(rel_path):
        return False

    return matches_any(rel_path, SECRET_FILE_PATTERNS)


def is_inside_hard_excluded_dir(rel_path: str) -> bool:
    """Дополнительная защита: не включать файлы из мусорных директорий.

    os.walk обычно отсекает такие директории до обхода файлов, но эта проверка
    страхует архиватор от ошибок в allowlist/.gitignore и старых локальных артефактов.
    """
    rel_path = normalize_rel(rel_path)
    if not rel_path:
        return False

    parts = rel_path.split("/")
    for index, part in enumerate(parts[:-1]):
        parent = "/".join(parts[: index + 1])
        if is_always_include_dir(parent):
            continue

        if is_hard_excluded_dir(parent, part):
            return True

    return False


def is_hard_excluded_dir(rel_path: str, name: str) -> bool:
    nested_excluded_names = {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".coverage",
        "htmlcov",
        "node_modules",
        ".next",
        ".nuxt",
        ".svelte-kit",
        "dist",
        "build",
        "coverage",
        ".venv",
        "venv",
        "env",
        "ENV",
        ".cache",
        "cache",
        "tmp",
        "temp",
        "logs",
        "log",
    }

    if name in DEFAULT_EXCLUDE_DIR_NAMES:
        return True

    if name_matches_any(name, ROOT_EXCLUDE_DIR_GLOBS):
        return True

    normalized_rel_path = normalize_rel(rel_path)
    parts = normalized_rel_path.split("/")

    if parts and parts[0] in ROOT_EXCLUDE_DIR_NAMES:
        return True

    if any(part in nested_excluded_names for part in parts):
        return True

    return matches_any(normalized_rel_path, EXCLUDE_DIR_PATTERNS)


def is_hard_excluded_file(rel_path: str, name: str) -> bool:
    if name in DEFAULT_EXCLUDE_FILE_NAMES:
        return True

    if is_secret_file(rel_path):
        return True

    # Markdown вне README.md и docs/ не включаем.
    if is_disallowed_markdown_file(rel_path):
        return True

    if matches_any(rel_path, DEFAULT_EXCLUDE_PATTERNS):
        return True

    return False


def is_llm_excluded_file(rel_path: str) -> bool:
    return matches_any(rel_path, LLM_EXCLUDE_FILE_PATTERNS)


def is_ignored_by_gitignore(rel_path: str, is_dir: bool, rules: list[IgnoreRule]) -> bool:
    """
    Упрощённая, но практичная обработка .gitignore.
    """
    rel_path = normalize_rel(rel_path)
    ignored = False

    for rule in rules:
        matched = match_gitignore_rule(rel_path, is_dir=is_dir, rule=rule)

        if matched:
            ignored = not rule.negated

    return ignored


# -----------------------------------------------------------------------------
# Архивация
# -----------------------------------------------------------------------------

@dataclass
class ArchiveStats:
    included_files: int = 0
    skipped_files: int = 0
    skipped_dirs: int = 0
    included_bytes: int = 0


def should_include_dir(
    rel_dir: str,
    dir_name: str,
    gitignore_rules: list[IgnoreRule],
) -> tuple[bool, str]:
    rel_dir = normalize_rel(rel_dir)

    if not rel_dir:
        return True, "root"

    if is_always_include_dir(rel_dir):
        return True, "always-include-dir"

    # Жёсткие исключения первыми:
    # __pycache__, node_modules, archives и т.д.
    if is_hard_excluded_dir(rel_dir, dir_name):
        return False, "hard-excluded-dir"

    # Важные директории спасаем от .gitignore.
    if is_inside_always_include_dir(rel_dir):
        return True, "inside-always-include-dir"

    if is_ignored_by_gitignore(rel_dir, is_dir=True, rules=gitignore_rules):
        return False, "gitignore"

    return True, "included"


def should_include_file(
    rel_file: str,
    file_name: str,
    gitignore_rules: list[IgnoreRule],
    file_size: int,
    max_file_size_bytes: int,
    no_markdown: bool,
    llm_mode: bool,
) -> tuple[bool, str]:
    rel_file = normalize_rel(rel_file)

    # Корневой .env включаем, даже если он в .gitignore.
    if is_root_env_file(rel_file):
        return True, "root-env"

    if is_inside_hard_excluded_dir(rel_file):
        return False, "inside-hard-excluded-dir"

    # Секреты не включаем.
    if is_secret_file(rel_file):
        return False, "secret"

    # Жёсткий мусор не включаем.
    if is_hard_excluded_file(rel_file, file_name):
        return False, "hard-excluded-file"

    if is_disallowed_markdown_file(rel_file, no_markdown=no_markdown):
        return False, "disallowed-markdown"

    if llm_mode and is_llm_excluded_file(rel_file):
        return False, "llm-excluded-file"

    # Важные файлы включаем даже если .gitignore против.
    if is_always_include_file(rel_file):
        return True, "always-include-file"

    # Если файл лежит внутри allowlist-директории.
    if is_inside_always_include_dir(rel_file):
        # Но markdown внутри allowlist-директории всё равно фильтруем:
        # README.md или docs/*.md — да, остальное markdown — нет.
        if is_disallowed_markdown_file(rel_file, no_markdown=no_markdown):
            return False, "disallowed-markdown"

        # В docs/ включаем только markdown-файлы.
        if rel_file.startswith("docs/"):
            if no_markdown:
                return False, "markdown-disabled"

            if not is_docs_markdown_file(rel_file):
                return False, "docs-non-markdown"

        return True, "inside-always-include-dir"

    if file_size > max_file_size_bytes:
        return False, f"too-large>{max_file_size_bytes}B"

    if is_ignored_by_gitignore(rel_file, is_dir=False, rules=gitignore_rules):
        return False, "gitignore"

    return True, "included"


def iter_project_files(
    root: Path,
    gitignore_rules: list[IgnoreRule],
    max_file_size_bytes: int,
    no_markdown: bool,
    llm_mode: bool,
    verbose: bool = False,
) -> tuple[list[Path], ArchiveStats]:
    stats = ArchiveStats()
    included: list[Path] = []

    for current_root, dir_names, file_names in os.walk(root):
        current_path = Path(current_root)

        kept_dirs: list[str] = []

        for dir_name in sorted(dir_names):
            abs_dir = current_path / dir_name
            rel_dir = normalize_rel(abs_dir.relative_to(root))

            include, reason = should_include_dir(rel_dir, dir_name, gitignore_rules)

            if include:
                kept_dirs.append(dir_name)
            else:
                stats.skipped_dirs += 1
                if verbose:
                    print(f"SKIP DIR  [{reason:25}] {rel_dir}")

        dir_names[:] = kept_dirs

        for file_name in sorted(file_names):
            abs_file = current_path / file_name
            rel_file = normalize_rel(abs_file.relative_to(root))

            try:
                file_size = abs_file.stat().st_size
            except OSError:
                stats.skipped_files += 1
                if verbose:
                    print(f"SKIP FILE [stat-error               ] {rel_file}")
                continue

            include, reason = should_include_file(
                rel_file=rel_file,
                file_name=file_name,
                gitignore_rules=gitignore_rules,
                file_size=file_size,
                max_file_size_bytes=max_file_size_bytes,
                no_markdown=no_markdown,
                llm_mode=llm_mode,
            )

            if include:
                included.append(abs_file)
                stats.included_files += 1
                stats.included_bytes += file_size

                if verbose:
                    print(f"ADD       [{reason:25}] {rel_file}")
            else:
                stats.skipped_files += 1

                if verbose:
                    print(f"SKIP FILE [{reason:25}] {rel_file}")

    return included, stats


def make_zip(root: Path, output_path: Path, files: list[Path]) -> None:
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for abs_file in files:
            rel_file = normalize_rel(abs_file.relative_to(root))
            zf.write(abs_file, arcname=rel_file)


def format_size(num_bytes: int) -> str:
    value = float(num_bytes)

    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024

    return f"{value:.2f} GB"


def default_output_name(root: Path) -> str:
    project_name = root.name or DEFAULT_OUTPUT_PREFIX
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{project_name}_{timestamp}.zip"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Создать безопасный zip-архив проекта в папке archives/."
    )

    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Корень проекта. По умолчанию текущая директория.",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Путь к выходному zip-файлу. "
            "Если не указан, архив будет создан в ./archives/."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ничего не архивировать, только показать список файлов.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Подробно показать включённые и пропущенные файлы.",
    )

    parser.add_argument(
        "--max-file-size-mb",
        type=int,
        default=DEFAULT_MAX_FILE_SIZE_MB,
        help=f"Максимальный размер одного файла в МБ. По умолчанию {DEFAULT_MAX_FILE_SIZE_MB}.",
    )

    parser.add_argument(
        "--ignore-gitignore",
        action="store_true",
        help="Не учитывать .gitignore вообще. Жёсткие exclude/secret правила всё равно работают.",
    )

    parser.add_argument(
        "--no-markdown",
        action="store_true",
        help="Не включать в архив никакие markdown-файлы, включая README.md и docs/*.",
    )

    parser.add_argument(
        "--llm-mode",
        action="store_true",
        help="Архив для нейросети: только основной код и конфиги, без markdown и локальных артефактов, но с корневым .env.",
    )

    return parser.parse_args(argv)


def get_output_path(root: Path, output_arg: Path | None) -> Path:
    archives_dir = root / "archives"

    if output_arg is None:
        return archives_dir / default_output_name(root)

    output_path = output_arg

    # Если пользователь передал только имя файла, например:
    #   --output Nickelfront.zip
    # кладём его в ./archives/Nickelfront.zip.
    if not output_path.is_absolute() and output_path.parent == Path("."):
        return archives_dir / output_path.name

    # Если пользователь передал путь, уважаем его.
    return output_path.resolve()


def collect_existing_dirs(root: Path, files: list[Path]) -> set[str]:
    existing_dirs: set[str] = set()

    for file in files:
        rel = Path(normalize_rel(file.relative_to(root)))

        for parent in rel.parents:
            parent_str = normalize_rel(parent)

            if parent_str and parent_str != ".":
                existing_dirs.add(parent_str)

    return existing_dirs


def is_expected_missing_in_mode(check: str, llm_mode: bool, no_markdown: bool) -> bool:
    if (llm_mode or no_markdown) and check in {"README.md", "docs"}:
        return True

    return False


def should_prompt_for_mode(argv: list[str]) -> bool:
    if argv:
        return False

    if not sys.stdin or not sys.stdin.isatty():
        return False

    return True


def prompt_archive_mode() -> str:
    print()
    print("Выберите режим архивации:")
    print("1. Обычный режим")
    print("   Основной код и конфиги, корневой .env включается, README.md и docs/*.md остаются.")
    print("2. Без markdown")
    print("   То же самое, но без всех markdown-файлов, включая README.md и docs/*.")
    print("3. Режим для нейросети")
    print("   Только основной код и конфиги, без markdown и лишних локальных артефактов, но с корневым .env.")
    print()

    while True:
        choice = input("Введите 1, 2 или 3: ").strip()

        if choice in {"1", "2", "3"}:
            return choice

        print("Неверный выбор. Пожалуйста, введите 1, 2 или 3.")


def main(argv: list[str] | None = None) -> int:
    raw_argv = argv or sys.argv[1:]

    if should_prompt_for_mode(raw_argv):
        choice = prompt_archive_mode()
        if choice == "2":
            raw_argv = ["--no-markdown"]
        elif choice == "3":
            raw_argv = ["--llm-mode"]

    args = parse_args(raw_argv)
    llm_mode = args.llm_mode
    effective_no_markdown = args.no_markdown or llm_mode

    root = args.root.resolve()

    if not root.exists() or not root.is_dir():
        print(f"ERROR: root не существует или не является директорией: {root}", file=sys.stderr)
        return 2

    output_path = get_output_path(root=root, output_arg=args.output)
    archives_dir = root / "archives"

    max_file_size_bytes = args.max_file_size_mb * 1024 * 1024

    gitignore_rules: list[IgnoreRule] = []

    if not args.ignore_gitignore:
        gitignore_rules = load_gitignore_rules(root)

    files, stats = iter_project_files(
        root=root,
        gitignore_rules=gitignore_rules,
        max_file_size_bytes=max_file_size_bytes,
        no_markdown=effective_no_markdown,
        llm_mode=llm_mode,
        verbose=args.verbose,
    )

    output_path_resolved = output_path.resolve()

    # Финальная защита:
    # - не включаем сам выходной архив;
    # - не включаем папку archives.
    filtered_files: list[Path] = []

    for file in files:
        try:
            rel_parts = file.relative_to(root).parts
        except ValueError:
            continue

        if file.resolve() == output_path_resolved:
            continue

        if rel_parts and rel_parts[0] == "archives":
            continue

        filtered_files.append(file)

    files = filtered_files

    total_input_size = sum(file.stat().st_size for file in files if file.exists())

    print()
    print("Archive summary")
    print("---------------")
    print(f"Root:           {root}")
    print(f"Output:         {output_path}")
    print(f"Dry run:        {args.dry_run}")
    print(f"Mode:           {'llm' if llm_mode else 'default'}")
    print(f"Gitignore:      {'ignored' if args.ignore_gitignore else 'used'}")
    print(f"Markdown:       {'excluded' if effective_no_markdown else 'allowed (README/docs only)'}")
    print(f"Files included: {len(files)}")
    print(f"Files skipped:  {stats.skipped_files}")
    print(f"Dirs skipped:   {stats.skipped_dirs}")
    print(f"Input size:     {format_size(total_input_size)}")
    print()

    important_checks = [
        ".env",
        "README.md",
        "docs",
        "backend/app/db/models",
        "requirements.txt",
        "backend/requirements.txt",
        "pyproject.toml",
        "frontend/package.json",
        "frontend/tsconfig.json",
        "frontend/vite.config.js",
        ".github/workflows",
        "scripts/nf-server.ps1",
        "tests/conftest.py",
        "rag/app/main.py",
        "run_all.bat",
        "run_backend.bat",
        "run_worker.bat",
        "run_qwen_worker.bat",
        "run_frontend.bat",
        "parser_alpha/run_parser.py",
        "qwen_service/service.py",
        "rag/app",
        "alembic",
        "backend/alembic",
    ]

    existing_rel_paths = {normalize_rel(file.relative_to(root)) for file in files}
    existing_dirs = collect_existing_dirs(root=root, files=files)

    print("Important paths check")
    print("---------------------")

    for check in important_checks:
        exists = check in existing_rel_paths or check in existing_dirs
        if exists:
            marker = "OK "
        elif is_expected_missing_in_mode(check, llm_mode=llm_mode, no_markdown=effective_no_markdown):
            marker = "SKIP"
        else:
            marker = "MISS"
        print(f"{marker} {check}")

    accidental_artifacts = [
        rel_path
        for rel_path in sorted(existing_rel_paths)
        if "__pycache__/" in rel_path
        or rel_path.endswith(".pyc")
        or rel_path.endswith(".pyo")
    ]
    if accidental_artifacts:
        print()
        print("WARNING: Python cache artifacts would be archived:")
        for rel_path in accidental_artifacts[:20]:
            print(f"WARN {rel_path}")
        if len(accidental_artifacts) > 20:
            print(f"WARN ... and {len(accidental_artifacts) - 20} more")

    print()

    if args.dry_run:
        print("Dry-run finished. Archive was not created.")
        return 0

    try:
        archives_dir.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        make_zip(root=root, output_path=output_path, files=files)
    except OSError as exc:
        print(f"ERROR: не удалось создать архив: {exc}", file=sys.stderr)
        return 1

    print(f"Created: {output_path}")
    print(f"Zip size: {format_size(output_path.stat().st_size)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

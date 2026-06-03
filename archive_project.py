"""
archive_project.py

Создаёт zip-архив проекта Nickelfront в папке archives/.

Цель скрипта:
- собрать компактный архив кода для анализа человеком/нейросетью;
- сохранить важные исходники, конфиги, миграции, frontend/src, backend, parser/rag/qwen;
- намеренно включить КОРНЕВОЙ .env, потому что для этого проекта он нужен в AI-аудите;
- не тащить runtime-мусор, кеши, node_modules, venv, ChromaDB, дампы, логи, PDF/DOCX и большие ML-веса.

Важно по .env:
- .env в корне проекта включается всегда;
- вложенные backend/.env, frontend/.env, qwen_service/.env и т.п. по умолчанию НЕ включаются;
- если нужно включить все вложенные .env, используй --include-nested-env.

Примеры:

    python archive_project.py
    python archive_project.py --dry-run --verbose
    python archive_project.py --llm-mode
    python archive_project.py --output archives/Nickelfront.zip
    python archive_project.py --max-file-size-mb 25
    python archive_project.py --include-nested-env
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
    ".parcel-cache",
    ".ipynb_checkpoints",
    "archives",
    "chroma_db",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".pyre",
    ".pytype",
    ".hypothesis",
    ".tox",
    ".nox",
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
    "ml_models",
    "models_cache",
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
    ".nickelfront_setup_state",
}

ROOT_EXCLUDE_DIR_GLOBS = {
    "venv_broken*",
}

DEFAULT_EXCLUDE_FILE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    ".coverage",
    "coverage.xml",
    "debug_pdf_extract.txt",
    "debug_pdf_extract_meta.json",
    "celerybeat-schedule",
    "celerybeat-schedule.db",
    "npm-debug.log",
    "yarn-debug.log",
    "yarn-error.log",
    "pnpm-debug.log",
}

DEFAULT_EXCLUDE_PATTERNS = {

    "*.pyc",
    "*.pyc.*",
    "*.pyo",
    "*.pyd",
    "*.py[cod]",
    "*$py.class",
    "*.so",
    "*.dll",
    "*.dylib",
    "*.egg-info",
    "*.egg",

    "*.tsbuildinfo",
    "npm-debug.log*",
    "yarn-debug.log*",
    "yarn-error.log*",
    "pnpm-debug.log*",

    "*.log",
    "*.tmp",
    "*.temp",
    "*.bak",
    "*.bak_*",
    "*.swp",
    "*.swo",
    "*.orig",
    "*.old",
    "*.rej",

    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.db-journal",
    "*.db-wal",
    "*.db-shm",
    "*.sqlite-journal",
    "*.sqlite-wal",
    "*.sqlite-shm",
    "*.mdb",
    "*.accdb",
    "*.sql",
    "*.dump",
    "*.rdb",
    "*.har",
    "*.csv",
    "*.parquet",
    "*.jsonl",

    "*.zip",
    "*.tar",
    "*.tar.gz",
    "*.tgz",
    "*.rar",
    "*.7z",

    "*.pth",
    "*.pt",
    "*.onnx",
    "*.ckpt",
    "*.safetensors",
    "*.bin",

    "*.mp4",
    "*.mov",
    "*.avi",
    "*.mkv",
    "*.mp3",
    "*.wav",
    "*.flac",
    "*.pdf",
    "*.doc",
    "*.docx",
    "*.odt",
}


SECRET_FILE_PATTERNS = {
    ".env.*",
    "**/.env.*",
    "**/.env",
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
    ".rst",
}

ALWAYS_INCLUDE_FILE_PATTERNS = {
    "README.md",
    "readme.md",
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
    "docs/**/*.md",
    "docs/**/*.mdx",
    "docs/**/*.markdown",
    "docs/**/*.rst",
    "docs/*.md",
    "docs/*.mdx",
    "docs/*.markdown",
    "docs/*.rst",
}

ALWAYS_INCLUDE_DIR_PATTERNS = {
    "backend/app/db/models",
    "backend/app/db/models/**",
    "backend/alembic",
    "backend/alembic/**",
    "alembic",
    "alembic/**",
    ".github",
    ".github/**",
    "docs",
    "docs/**",
    "tests",
    "tests/**",
    "backend/tests",
    "backend/tests/**",
    "frontend/src",
    "frontend/src/**",
}

EXCLUDE_DIR_PATTERNS = {
    "**/__pycache__",
    "**/.pytest_cache",
    "**/.mypy_cache",
    "**/.ruff_cache",
    "**/.pyre",
    "**/.pytype",
    "**/.hypothesis",
    "**/.tox",
    "**/.nox",
    "**/node_modules",
    "**/.venv",
    "**/venv",
    "**/env",
    "**/dist",
    "**/build",
    "**/coverage",
    "**/htmlcov",
    "**/.next",
    "**/.nuxt",
    "**/.svelte-kit",
    "archives",
    "archives/**",
    "parser_alpha/data",
    "parser_alpha/data/**",
}



LLM_EXCLUDE_FILE_PATTERNS = {
    "*.har",
    "*.csv",
    "*.parquet",
    "*.rdb",
    "*.ipynb",
    "PATCH_NOTES.txt",
    "*_notes.txt",
    "*_session.txt",
    "*_debug.txt",
    "export_*.txt",
    "export_*.json",
    "debug_*.txt",
    "debug_*.json",
}

IMPORTANT_CHECKS = [
    ".env",
    "README.md",
    "docs",
    "backend/app/db/models",
    "requirements.txt",
    "pyproject.toml",
    "frontend/package.json",
    "frontend/tsconfig.json",
    "frontend/vite.config.js",
    ".github/workflows",
    "tests/backend/conftest.py",
    "run_all.bat",
    "scripts/run_backend.bat",
    "scripts/run_worker.bat",
    "scripts/run_qwen_worker.bat",
    "scripts/run_frontend.bat",
    "parser_alpha/run_parser.py",
    "qwen_service/service.py",
    "backend/alembic",
    "backend/alembic.ini",
]

OPTIONAL_CHECKS = {
    "README.md",
    "docs",
    "frontend/tsconfig.json",
    "frontend/vite.config.js",
    ".github/workflows",
    "tests/backend/conftest.py",
    "scripts/run_backend.bat",
    "scripts/run_worker.bat",
    "scripts/run_qwen_worker.bat",
    "scripts/run_frontend.bat",
}


@dataclass(frozen=True)
class IgnoreRule:
    pattern: str
    negated: bool
    directory_only: bool
    anchored: bool
    source: str


@dataclass
class ArchiveStats:
    included_files: int = 0
    skipped_files: int = 0
    skipped_dirs: int = 0
    included_bytes: int = 0


@dataclass
class ArchiveOptions:
    max_file_size_bytes: int
    no_markdown: bool
    llm_mode: bool
    include_nested_env: bool


def normalize_rel(path: Path | str) -> str:
    """Нормализует относительный путь под zip/.gitignore matching.

    В старой версии Path('.') превращался в '.', из-за чего корневой .gitignore
    применялся как будто он лежит в подпапке '.'. Это ломало правила вида *.txt.
    """
    value = str(path).replace(os.sep, "/").strip("/")
    if value in {"", "."}:
        return ""
    return value


def parse_gitignore_file(path: Path, root: Path) -> list[IgnoreRule]:
    rules: list[IgnoreRule] = []

    if not path.exists() or not path.is_file():
        return rules

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return rules

    base_dir = path.parent
    if base_dir.resolve() == root.resolve():
        base_dir_rel = ""
    else:
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


def load_gitignore_rules(root: Path) -> list[IgnoreRule]:
    """Загружает все .gitignore внутри проекта, кроме жёстко исключённых директорий."""
    rules: list[IgnoreRule] = []

    for current_root, dir_names, file_names in os.walk(root):
        current_path = Path(current_root)

        kept_dirs: list[str] = []
        for dir_name in sorted(dir_names):
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

    if not rel_path or not pattern:
        return False

    candidates = {
        rel_path,
        "/" + rel_path,
    }

    for candidate in candidates:
        if fnmatch.fnmatch(candidate, pattern):
            return True

    if "/" not in pattern:
        parts = rel_path.split("/")
        if any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True

    if rel_path == pattern or rel_path.startswith(pattern.rstrip("/") + "/"):
        return True

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
        if rule.directory_only and not is_dir:

            pass
        else:
            return True

    if not rule.directory_only:
        return False

    parent_candidates = list(Path(scoped_path).parents)
    if is_dir:
        parent_candidates.insert(0, Path(scoped_path))

    for parent in parent_candidates:
        parent_str = normalize_rel(parent)
        if not parent_str:
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


def is_runtime_cache_artifact(rel_path: str) -> bool:
    """Hard guard against Python/runtime cache files even inside allow-listed dirs."""
    rel_path = normalize_rel(rel_path)
    if not rel_path:
        return False
    path = Path(rel_path)
    parts = {part.lower() for part in path.parts}
    if "__pycache__" in parts:
        return True
    suffix = path.suffix.lower()
    return suffix in {".pyc", ".pyo"} or path.name.endswith((".pyc", ".pyo"))


def is_root_env_file(rel_path: str) -> bool:
    return normalize_rel(rel_path) == ".env"


def is_nested_env_file(rel_path: str) -> bool:
    rel_path = normalize_rel(rel_path)
    return rel_path.endswith("/.env") and not is_root_env_file(rel_path)


def is_always_include_file(rel_path: str) -> bool:
    return matches_any(rel_path, ALWAYS_INCLUDE_FILE_PATTERNS)


def is_always_include_dir(rel_path: str) -> bool:
    return matches_any(rel_path, ALWAYS_INCLUDE_DIR_PATTERNS)


def is_inside_always_include_dir(rel_path: str) -> bool:
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

    return rel_path.startswith("docs/") and path.suffix.lower() in MARKDOWN_EXTENSIONS


def is_root_readme_file(rel_path: str) -> bool:
    return normalize_rel(rel_path).lower() == "readme.md"


def is_markdown_file(rel_path: str) -> bool:
    return Path(normalize_rel(rel_path)).suffix.lower() in MARKDOWN_EXTENSIONS


def is_disallowed_markdown_file(rel_path: str, no_markdown: bool = False) -> bool:
    if not is_markdown_file(rel_path):
        return False

    if no_markdown:
        return True

    if is_root_readme_file(rel_path):
        return False

    if is_docs_markdown_file(rel_path):
        return False

    return True


def is_secret_file(rel_path: str, include_nested_env: bool = False) -> bool:
    rel_path = normalize_rel(rel_path)

    if is_root_env_file(rel_path):
        return False

    if include_nested_env and is_nested_env_file(rel_path):
        return False

    return matches_any(rel_path, SECRET_FILE_PATTERNS)


def is_hard_excluded_dir(rel_path: str, name: str) -> bool:
    if name in DEFAULT_EXCLUDE_DIR_NAMES:
        return True

    if name_matches_any(name, ROOT_EXCLUDE_DIR_GLOBS):
        return True

    normalized_rel_path = normalize_rel(rel_path)
    if not normalized_rel_path:
        return False

    parts = normalized_rel_path.split("/")

    if parts and parts[0] in ROOT_EXCLUDE_DIR_NAMES:
        return True

    if any(part in DEFAULT_EXCLUDE_DIR_NAMES for part in parts):
        return True

    return matches_any(normalized_rel_path, EXCLUDE_DIR_PATTERNS)


def is_inside_hard_excluded_dir(rel_path: str) -> bool:
    """Защита от always-include: мусорные директории нельзя протащить внутрь архива."""
    rel_path = normalize_rel(rel_path)
    if not rel_path:
        return False

    parts = rel_path.split("/")
    for index, part in enumerate(parts[:-1]):
        parent = "/".join(parts[: index + 1])
        if is_hard_excluded_dir(parent, part):
            return True

    return False


def is_hard_excluded_file(
    rel_path: str,
    name: str,
    *,
    no_markdown: bool,
    include_nested_env: bool,
) -> bool:
    if name in DEFAULT_EXCLUDE_FILE_NAMES:
        return True

    if is_secret_file(rel_path, include_nested_env=include_nested_env):
        return True

    if is_disallowed_markdown_file(rel_path, no_markdown=no_markdown):
        return True

    if matches_any(rel_path, DEFAULT_EXCLUDE_PATTERNS):
        return True

    return False


def is_llm_excluded_file(rel_path: str) -> bool:
    return matches_any(rel_path, LLM_EXCLUDE_FILE_PATTERNS)


def is_ignored_by_gitignore(rel_path: str, is_dir: bool, rules: list[IgnoreRule]) -> bool:
    rel_path = normalize_rel(rel_path)
    ignored = False

    for rule in rules:
        matched = match_gitignore_rule(rel_path, is_dir=is_dir, rule=rule)
        if matched:
            ignored = not rule.negated

    return ignored


def should_include_dir(
    rel_dir: str,
    dir_name: str,
    gitignore_rules: list[IgnoreRule],
) -> tuple[bool, str]:
    rel_dir = normalize_rel(rel_dir)

    if not rel_dir:
        return True, "root"



    if is_hard_excluded_dir(rel_dir, dir_name):
        return False, "hard-excluded-dir"

    if is_always_include_dir(rel_dir):
        return True, "always-include-dir"

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
    options: ArchiveOptions,
) -> tuple[bool, str]:
    rel_file = normalize_rel(rel_file)

    if is_runtime_cache_artifact(rel_file):
        return False, "runtime-cache"

    if is_root_env_file(rel_file):
        return True, "root-env"

    if is_inside_hard_excluded_dir(rel_file):
        return False, "inside-hard-excluded-dir"

    if is_secret_file(rel_file, include_nested_env=options.include_nested_env):
        return False, "secret"

    if is_hard_excluded_file(
        rel_file,
        file_name,
        no_markdown=options.no_markdown,
        include_nested_env=options.include_nested_env,
    ):
        return False, "hard-excluded-file"

    if options.llm_mode and is_llm_excluded_file(rel_file):
        return False, "llm-excluded-file"

    if is_always_include_file(rel_file):
        return True, "always-include-file"

    if is_inside_always_include_dir(rel_file):
        if rel_file.startswith("docs/"):
            if options.no_markdown:
                return False, "markdown-disabled"
            if not is_docs_markdown_file(rel_file):
                return False, "docs-non-markdown"

        return True, "inside-always-include-dir"

    if file_size > options.max_file_size_bytes:
        return False, f"too-large>{options.max_file_size_bytes}B"

    if is_ignored_by_gitignore(rel_file, is_dir=False, rules=gitignore_rules):
        return False, "gitignore"

    return True, "included"


def iter_project_files(
    root: Path,
    gitignore_rules: list[IgnoreRule],
    options: ArchiveOptions,
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
                options=options,
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
            if is_runtime_cache_artifact(rel_file):
                continue
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
        description="Создать zip-архив проекта Nickelfront в папке archives/."
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
        help="Путь к выходному zip-файлу. Если не указан, архив будет создан в ./archives/.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ничего не архивировать, только показать сводку и проверки.",
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
        help="Не учитывать .gitignore. Hard-exclude и secret-exclude всё равно работают.",
    )

    parser.add_argument(
        "--no-markdown",
        action="store_true",
        help="Не включать markdown/rst-файлы, включая README.md и docs/*.",
    )

    parser.add_argument(
        "--llm-mode",
        action="store_true",
        help="Архив для нейросети: без markdown и локальных артефактов, но с корневым .env.",
    )

    parser.add_argument(
        "--include-nested-env",
        action="store_true",
        help="Дополнительно включить вложенные */.env. По умолчанию включается только корневой .env.",
    )

    return parser.parse_args(argv)


def get_output_path(root: Path, output_arg: Path | None) -> Path:
    archives_dir = root / "archives"

    if output_arg is None:
        return archives_dir / default_output_name(root)

    output_path = output_arg

    if not output_path.is_absolute() and output_path.parent == Path("."):
        return archives_dir / output_path.name

    return output_path.resolve()


def collect_existing_dirs(root: Path, files: list[Path]) -> set[str]:
    existing_dirs: set[str] = set()

    for file in files:
        rel = Path(normalize_rel(file.relative_to(root)))

        for parent in rel.parents:
            parent_str = normalize_rel(parent)
            if parent_str:
                existing_dirs.add(parent_str)

    return existing_dirs


def is_expected_missing_in_mode(check: str, llm_mode: bool, no_markdown: bool) -> bool:
    if (llm_mode or no_markdown) and check in {"README.md", "docs"}:
        return True

    if check in OPTIONAL_CHECKS:
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
    print("   То же самое, но без всех markdown/rst-файлов, включая README.md и docs/*.")
    print("3. Режим для нейросети")
    print("   Только основной код и конфиги, без markdown и лишних локальных артефактов, но с корневым .env.")
    print()

    while True:
        choice = input("Введите 1, 2 или 3: ").strip()

        if choice in {"1", "2", "3"}:
            return choice

        print("Неверный выбор. Пожалуйста, введите 1, 2 или 3.")


def filter_output_and_archives(root: Path, output_path: Path, files: list[Path]) -> list[Path]:
    output_path_resolved = output_path.resolve()
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

    return filtered_files


def print_summary(
    *,
    root: Path,
    output_path: Path,
    dry_run: bool,
    llm_mode: bool,
    no_markdown: bool,
    ignore_gitignore: bool,
    include_nested_env: bool,
    files: list[Path],
    stats: ArchiveStats,
) -> None:
    total_input_size = sum(file.stat().st_size for file in files if file.exists())

    print()
    print("Archive summary")
    print("---------------")
    print(f"Root:           {root}")
    print(f"Output:         {output_path}")
    print(f"Dry run:        {dry_run}")
    print(f"Mode:           {'llm' if llm_mode else 'default'}")
    print(f"Gitignore:      {'ignored' if ignore_gitignore else 'used'}")
    print(f"Markdown:       {'excluded' if no_markdown else 'allowed (README/docs only)'}")
    print(f"Root .env:      included")
    print(f"Nested .env:    {'included' if include_nested_env else 'excluded'}")
    print(f"Files included: {len(files)}")
    print(f"Files skipped:  {stats.skipped_files}")
    print(f"Dirs skipped:   {stats.skipped_dirs}")
    print(f"Input size:     {format_size(total_input_size)}")
    print()


def print_important_checks(root: Path, files: list[Path], llm_mode: bool, no_markdown: bool) -> None:
    existing_rel_paths = {normalize_rel(file.relative_to(root)) for file in files}
    existing_dirs = collect_existing_dirs(root=root, files=files)

    print("Important paths check")
    print("---------------------")

    for check in IMPORTANT_CHECKS:
        exists = check in existing_rel_paths or check in existing_dirs
        if exists:
            marker = "OK  "
        elif is_expected_missing_in_mode(check, llm_mode=llm_mode, no_markdown=no_markdown):
            marker = "SKIP"
        else:
            marker = "MISS"
        print(f"{marker} {check}")

    accidental_artifacts = [
        rel_path
        for rel_path in sorted(existing_rel_paths)
        if "__pycache__/" in rel_path
        or rel_path.endswith(".pyc")
        or ".pyc." in rel_path
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
    max_file_size_bytes = args.max_file_size_mb * 1024 * 1024

    gitignore_rules: list[IgnoreRule] = []
    if not args.ignore_gitignore:
        gitignore_rules = load_gitignore_rules(root)

    options = ArchiveOptions(
        max_file_size_bytes=max_file_size_bytes,
        no_markdown=effective_no_markdown,
        llm_mode=llm_mode,
        include_nested_env=args.include_nested_env,
    )

    files, stats = iter_project_files(
        root=root,
        gitignore_rules=gitignore_rules,
        options=options,
        verbose=args.verbose,
    )

    files = filter_output_and_archives(root=root, output_path=output_path, files=files)

    print_summary(
        root=root,
        output_path=output_path,
        dry_run=args.dry_run,
        llm_mode=llm_mode,
        no_markdown=effective_no_markdown,
        ignore_gitignore=args.ignore_gitignore,
        include_nested_env=args.include_nested_env,
        files=files,
        stats=stats,
    )

    print_important_checks(
        root=root,
        files=files,
        llm_mode=llm_mode,
        no_markdown=effective_no_markdown,
    )

    if args.dry_run:
        print("Dry-run finished. Archive was not created.")
        return 0

    try:
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

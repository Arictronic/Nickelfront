"""Compatibility bridge to the canonical project-level :mod:`shared` package.

`parser_alpha` used to carry a private copy of `shared.schemas`.  That copy
can silently drift from the backend contract when the parser is started as a
subprocess from Windows scripts, because `parser_alpha` may appear before the
project root in `sys.path`.

Keep this package only as a bridge: even if Python resolves `shared` from
`parser_alpha/shared`, all submodules are loaded from `<project_root>/shared`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ROOT_SHARED_DIR = _PROJECT_ROOT / "shared"

if not _ROOT_SHARED_DIR.exists():
    raise ImportError(f"Canonical shared package not found: {_ROOT_SHARED_DIR}")

_project_root_str = str(_PROJECT_ROOT)
if _project_root_str in sys.path:
    sys.path.remove(_project_root_str)
sys.path.insert(0, _project_root_str)



__path__ = [str(_ROOT_SHARED_DIR)]
if __spec__ is not None:
    __spec__.submodule_search_locations = __path__

__nickelfront_canonical_shared__ = str(_ROOT_SHARED_DIR)
__all__: list[str] = []

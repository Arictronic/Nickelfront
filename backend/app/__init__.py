"""Backend application package.

Keep ``app`` and ``backend.app`` pointing to the same module object when
Nickelfront tools are launched from different working directories.  Windows
.bat scripts intentionally put both the project root and ``backend`` on
``PYTHONPATH``; without these aliases, importing ``backend.app`` first and
``app`` later can create broken parent-package state.
"""

from __future__ import annotations

import sys

for _alias in ("app", "backend.app"):
    sys.modules.setdefault(_alias, sys.modules[__name__])

__all__: list[str] = []

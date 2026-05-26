"""Backend services package with stable import aliases."""

from __future__ import annotations

import sys

for _alias in ("app.services", "backend.app.services"):
    sys.modules.setdefault(_alias, sys.modules[__name__])

__all__: list[str] = []

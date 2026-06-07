"""Quant Replay Collector desktop research application.

The v1.x codebase still supports script-style imports from inside
``quant_collector_app``. Keep the package directory importable when callers use
``python -m quant_collector_app...`` until the import tree is migrated fully.
"""

from __future__ import annotations

import sys
from pathlib import Path


_PACKAGE_DIR = Path(__file__).resolve().parent
if str(_PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_DIR))

__version__ = "1.4.1"

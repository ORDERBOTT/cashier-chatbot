"""Pytest hooks shared by all tests."""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_fixture = _ROOT / "fixtures" / "clover_menu_pricing.json"
os.environ.setdefault("CLOVER_MENU_JSON_PATH", str(_fixture))

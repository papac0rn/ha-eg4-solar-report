"""Make the integration's pure modules importable without Home Assistant.

Registers the integration folder as package `eg4sr` without running its __init__.py (which imports HA),
so analyzer.py, charts.py and codes.py load with their relative imports intact.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

PKG_DIR = Path(__file__).parents[1] / "custom_components" / "eg4_solar_report"

if "eg4sr" not in sys.modules:
    pkg = types.ModuleType("eg4sr")
    pkg.__path__ = [str(PKG_DIR)]
    sys.modules["eg4sr"] = pkg

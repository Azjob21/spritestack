from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[1] / "test_api.py"
sys.path.insert(0, str(_SOURCE.parent))
_SPEC = importlib.util.spec_from_file_location("legacy_api_tests", _SOURCE)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Could not load {_SOURCE}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

for _name in dir(_MODULE):
    if _name.startswith("Test") or _name.startswith("test_"):
        globals()[_name] = getattr(_MODULE, _name)

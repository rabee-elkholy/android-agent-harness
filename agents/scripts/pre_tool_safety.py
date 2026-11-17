"""Compatible facade for `pre_tool_safety.py` (implementation lives in `_safety`).
Includes HYDROGEN_ANTI_BURST_PACER (check_and_apply_hydrogen_burst_pacer) via _safety.audit_and_pacer.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _safety import engine as _engine

if __name__ == "__main__":
    _res = _engine.main()
    raise SystemExit(_res if isinstance(_res, int) else 0)
else:
    sys.modules[__name__] = _engine

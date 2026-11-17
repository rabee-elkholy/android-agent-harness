"""Compatible facade for `web_relay.py` (implementation lives in `_web_relay`).
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _web_relay import engine as _engine

if __name__ == "__main__":
    _res = _engine.main()
    raise SystemExit(_res if isinstance(_res, int) else 0)
else:
    sys.modules[__name__] = _engine

"""Compatible lifecycle entry point for planning, approval and task routing.

Implementation lives in _workflow. Imports retain the live engine namespace,
including private compatibility helpers and existing monkeypatch seams.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _workflow import engine as _engine

if __name__ == "__main__":
    raise SystemExit(_engine.main())
else:
    sys.modules[__name__] = _engine

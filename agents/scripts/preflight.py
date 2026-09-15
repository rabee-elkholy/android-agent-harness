"""Forwarding alias script for preflight_check.py.

Usage: python .agents/scripts/preflight.py [args...]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preflight_check

if __name__ == "__main__":
    raise SystemExit(preflight_check.main())

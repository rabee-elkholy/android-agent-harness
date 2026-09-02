"""Self-test for Maestro E2E test runner (run_e2e_qa.py).

Delegates to _maestro_selftest.py to ensure backwards compatibility.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _maestro_selftest import main as maestro_selftest_main  # noqa: E402

if __name__ == "__main__":
    sys.exit(maestro_selftest_main())

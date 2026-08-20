"""Run hook selftest when harness files change. Cached by content hash.

CLI:  python .agents/scripts/ensure_hook_selftest.py
Hook: PreInvocation — stdout is JSON only.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

AGENTS = Path(__file__).resolve().parent.parent
SCRIPTS = AGENTS / "scripts"
SELFTEST = SCRIPTS / "_hook_selftest.py"
CACHE = AGENTS / "state" / "hook_selftest.json"


def _iter_watched() -> list[Path]:
    files: list[Path] = []
    files.extend(sorted(SCRIPTS.glob("*.py")))
    files.extend(sorted((AGENTS / "subagents").glob("*.json")))
    for extra in (AGENTS / "hooks.json",):
        if extra.is_file():
            files.append(extra)
    return [p for p in files if p.is_file()]


def harness_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in _iter_watched():
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _read_cache() -> dict:
    try:
        if not CACHE.is_file():
            return {}
        data = json.loads(CACHE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_cache(fingerprint: str, ok: bool) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(
        json.dumps({"fingerprint": fingerprint, "ok": ok}, indent=2),
        encoding="utf-8",
    )


def cache_is_fresh(fingerprint: str) -> bool:
    cache = _read_cache()
    return cache.get("fingerprint") == fingerprint and cache.get("ok") is True


def run_selftest() -> tuple[bool, str]:
    env = os.environ.copy()
    env.pop("RASHAQA_HOOK_STATE", None)
    env.pop("RASHAQA_TRANSCRIPT_ROOT", None)
    proc = subprocess.run(
        [sys.executable, str(SELFTEST)],
        cwd=str(AGENTS.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output


def _is_hook_payload(raw: str) -> bool:
    if not raw.strip():
        return False
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    return any(
        key in payload
        for key in ("conversationId", "conversation_id", "invocationNum", "toolCall")
    )


def main() -> int:
    raw = ""
    if not sys.stdin.isatty():
        raw = sys.stdin.read()
    as_hook = _is_hook_payload(raw)

    fingerprint = harness_fingerprint()
    if cache_is_fresh(fingerprint):
        if as_hook:
            print("{}")
        else:
            print("[OK] Hook selftest cache is fresh.")
        return 0

    ok, output = run_selftest()
    _write_cache(fingerprint, ok)

    if as_hook:
        if ok:
            print("{}")
            return 0
        print(
            json.dumps(
                {
                    "injectSteps": [
                        {
                            "ephemeralMessage": (
                                "Rashaqa hook selftest FAILED after a harness change. "
                                "Do not assemble. Run `python .agents/scripts/_hook_selftest.py` "
                                "and fix the failures before delivery."
                            )
                        }
                    ]
                }
            )
        )
        return 0

    print(output.strip())
    if ok:
        print("[SUCCESS] Hook selftest passed; cache updated.")
        return 0
    print("[FAIL] Hook selftest failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

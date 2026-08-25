"""GitHub Copilot preToolUse bridge over the harness safety engine.

Copilot CLI and the Copilot Coding Agent enforce repository-level hooks
(`.github/hooks/*.json`) with a documented `preToolUse` event that accepts
`permissionDecision` allow/deny. This bridge adapts the documented payload
(camelCase `toolName`/`toolArgs`, plus the VS Code compatible snake_case
variant) into the kit's pre_tool_safety payload and maps the verdict back to
Copilot's decision JSON — the same engine-subprocess pattern used by
`cc_pre_tool_safety.py`.

Copilot treats a crash/non-zero exit of a command preToolUse hook as a denial
(fail-closed), so this script always exits 0 and encodes its decision in
stdout JSON. Hook timeouts on the Copilot side are fail-open, hence the
engine call is bounded and the registered hook carries a tight timeoutSec.

Install (written automatically by install_tool_adapters.py --copilot-hooks):
  .github/hooks/android-harness-pre-tool-use.json
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ENGINE = SCRIPTS / "pre_tool_safety.py"


def emit(decision: str, reason: str) -> None:
    print(
        json.dumps(
            {
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        )
    )


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        emit("deny", "android-harness bridge received unreadable hook input. Retry the tool.")
        return 0

    if not isinstance(payload, dict):
        payload = {}

    tool_name = str(payload.get("toolName") or payload.get("tool_name") or "").strip().lower()
    tool_args = payload.get("toolArgs") or payload.get("tool_input") or {}
    if isinstance(tool_args, str):
        try:
            tool_args = json.loads(tool_args)
        except json.JSONDecodeError:
            tool_args = {}
    if not isinstance(tool_args, dict):
        tool_args = {}

    command = str(
        tool_args.get("command")
        or tool_args.get("CommandLine")
        or tool_args.get("commandLine")
        or ""
    ).strip()

    if tool_name not in ("bash", "powershell") or not command:
        emit("allow", "Not a shell command; nothing for the harness gate to inspect.")
        return 0

    inner = {"toolCall": {"name": "run_command", "args": {"CommandLine": command}}}
    try:
        proc = subprocess.run(
            [sys.executable, str(ENGINE)],
            input=json.dumps(inner),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=20,
        )
        verdict = json.loads(proc.stdout or "{}")
        decision = str(verdict.get("decision") or "deny")
        reason = str(verdict.get("reason") or "No reason returned by safety engine.")
    except Exception as exc:
        emit("deny", f"android-harness gate error ({type(exc).__name__}). Fail-closed; retry the tool.")
        return 0

    copilot_decision = "deny" if decision == "deny" else "allow"
    prefix = "[android-harness] " if copilot_decision == "deny" else ""
    emit(copilot_decision, f"{prefix}{reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

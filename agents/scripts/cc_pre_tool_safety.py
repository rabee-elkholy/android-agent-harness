"""Claude Code PreToolUse bridge over the harness safety engine.

Translates the Claude Code hook protocol (JSON on stdin: tool_name/tool_input)
into the kit's pre_tool_safety payload, and maps the verdict back to Claude
Code's permissionDecision JSON. Deterministic git/adb/emulator denials now run
in Claude Code sessions exactly as they do in Antigravity.

Install (written automatically by install_tool_adapters.py --cc-hooks):
  .claude/settings.json -> hooks.PreToolUse -> matcher "Bash"

Exit code is always 0; the JSON decision carries the verdict.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ENGINE = SCRIPTS / "pre_tool_safety.py"


def emit(decision: str, reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload_in = json.loads(raw) if raw.strip() else {}
        tool_name = str(payload_in.get("tool_name") or payload_in.get("toolName") or "")
        tool_input = payload_in.get("tool_input") or payload_in.get("toolInput") or {}
        command = str(
            tool_input.get("command")
            or tool_input.get("CommandLine")
            or tool_input.get("commandLine")
            or ""
        )
    except Exception:
        emit("deny", "android-harness bridge received unreadable hook input. Retry the tool.")
        return 0

    if tool_name.lower() != "bash" or not command.strip():
        emit("allow", "Not a shell command; nothing for the harness gate to inspect.")
        return 0

    session_id = str(
        payload_in.get("session_id")
        or payload_in.get("sessionId")
        or os.environ.get("CLAUDE_SESSION_ID")
        or "claude-session"
    )
    inner = {
        "conversationId": session_id,
        "toolCall": {"name": "run_command", "args": {"CommandLine": command}},
    }
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

    cc_decision = "deny" if decision == "deny" else "allow"
    prefix = "[android-harness] " if cc_decision == "deny" else ""
    emit(cc_decision, f"{prefix}{reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

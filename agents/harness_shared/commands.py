"""Quote and inspect executable commands using the current platform's syntax."""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
import re
import shlex
import shutil
import subprocess
import sys


def split_command(command: str) -> list[str]:
    parts = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
        parts = [part[1:-1] if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'" else part for part in parts]
    return parts


def quote_executable(executable: str) -> str:
    return subprocess.list2cmdline([executable]) if os.name == "nt" else shlex.quote(executable)


def configured_python_command(command: str | None) -> str:
    """Preserve explicit interpreters; resolve missing generic aliases safely."""
    value = (command or "").strip()
    if not value:
        return quote_executable(sys.executable)
    # Setup may receive an unquoted absolute executable path with spaces.
    if Path(value).is_file() or (PureWindowsPath(value).is_absolute() and value.lower().endswith('.exe')):
        return quote_executable(value)
    parts = split_command(value)
    if not parts:
        raise ValueError("Python command is empty")
    if parts[0] in {"python", "python3"} and not shutil.which(parts[0]):
        return quote_executable(sys.executable) + (" " + " ".join(parts[1:]) if len(parts) > 1 else "")
    return value


def rewrite_python_hooks(data, python_command: str) -> bool:
    """Substitute only template interpreter aliases, preserving custom hooks."""
    changed = False
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "command" and isinstance(value, str):
                rewritten = re.sub(r"^python(?:\d+(?:\.\d+)*)?(?:\.exe)?(?=\s|$)",
                                   lambda _match: python_command, value, count=1)
                if rewritten != value:
                    data[key] = rewritten
                    changed = True
            else:
                changed = rewrite_python_hooks(value, python_command) or changed
    elif isinstance(data, list):
        for item in data:
            changed = rewrite_python_hooks(item, python_command) or changed
    return changed


def review_command(arguments: list[str]) -> tuple[str, list[str]]:
    """One dispatch contract for both public launchers."""
    forwarded = list(arguments)
    if forwarded[:1] == ["--"]:
        forwarded = forwarded[1:]
    subcommand = forwarded[0] if forwarded else ""
    dedicated = {"package": "review_package.py", "profile": "review_execution.py", "ingest": "record_review.py", "models": "review_models.py"}
    if subcommand in dedicated:
        return dedicated[subcommand], forwarded[1:]
    if subcommand in {"complete", "finalize", "dispatch", "dispatch-batch", "status"}:
        return "review_orchestrator.py", forwarded
    return "record_review.py", forwarded

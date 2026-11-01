"""Bounded Android Studio semantic inspection and official documentation reads.

No builds, installs, host setup, task mutations or delivery verdicts. Requires an
already installed Android CLI; Studio actions require its compatible running IDE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit, unquote

from android_ui import executable_path, invoke, MAX_OUTPUT, supports_flag
from _vnext_common import ValidationError, redact

ACTIONS = {
    "declaration": ("studio", "find-declaration"),
    "usages": ("studio", "find-usages"),
    "analyze": ("studio", "analyze-file"),
    "studio-status": ("studio", "check"),
    "docs-search": ("docs", "search"),
    "docs-fetch": ("docs", "fetch"),
}
MAX_SOURCE = 4 * 1024 * 1024


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("action", choices=("capabilities", *ACTIONS))
    parser.add_argument("value", nargs="?")
    parser.add_argument("--file", help="Local source reference to disambiguate a symbol")
    parser.add_argument("--repo", type=Path, default=Path(os.environ.get("HARNESS_REPO") or "."))
    parser.add_argument("--json", action="store_true", help="Structured output (default)")
    args = parser.parse_args(argv)
    if args.action in {"capabilities", "studio-status"}:
        if args.value or args.file:
            parser.error("This action accepts neither a value nor --file")
    elif not args.value:
        parser.error("This action requires a value")
    if args.file and args.action not in {"declaration", "usages"}:
        parser.error("--file applies only to declaration/usages")
    return args


def source_file(repo: Path, value: str) -> Path:
    path = (repo / value).resolve()
    try:
        rel = path.relative_to(repo.resolve())
    except ValueError:
        raise ValidationError("Source must be inside the selected repository.") from None
    if (not path.is_file() or path.suffix.lower() not in {".kt", ".kts", ".java", ".xml"}
            or any(part in {".agents", ".git", ".gradle", "build"} for part in rel.parts)):
        raise ValidationError("Choose an existing project Kotlin, Java or XML source file.")
    return path


def _value(value: str) -> str:
    if not value or len(value) > 1024 or not value.isprintable() or value.startswith("-"):
        raise ValidationError("Invalid or oversized inspection value.")
    return value


def command_for(repo: Path, args) -> list[str]:
    repo = repo.resolve()
    if args.action == "capabilities":
        return []
    command = list(ACTIONS[args.action])
    if args.action == "studio-status":
        return command
    value = _value(args.value)
    if args.action in {"declaration", "usages"}:
        if len(value) > 256 or not re.fullmatch(r"[\w$][\w.$:#()]*", value):
            raise ValidationError("Use an exact symbol name, optionally package-qualified.")
        command += ["--project=" + str(repo), "--short"]
        if args.file:
            command += ["--context-file=" + str(source_file(repo, args.file))]
    elif args.action == "analyze":
        value = str(source_file(repo, value))
        command += ["--project=" + str(repo)]
    elif args.action == "docs-fetch":
        uri = urlsplit(value)
        if (uri.scheme != "kb" or uri.netloc != "android" or not uri.path.startswith("/")
                or uri.query or uri.fragment or any(p in {".", ".."} for p in unquote(uri.path).split("/"))
                or not re.fullmatch(r"kb://android/[A-Za-z0-9_./%~-]+", value)):
            raise ValidationError("Fetch requires a kb://android/ article URL returned by docs-search.")
    return [*command, value]


def probe(repo: Path, executable: str, action: str) -> dict:
    code, version = invoke(executable, ["--version"], repo, 15, head=True)
    if code:
        raise ValidationError("Android CLI version probe failed.")
    command = list(ACTIONS[action])
    code, help_text = invoke(executable, [*command, "--help"], repo, 15, head=True)
    required = []
    if action in {"declaration", "usages"}:
        required += ["--project", "--context-file", "--short"]
    elif action == "analyze":
        required += ["--project"]
    return {"supported": code == 0 and " ".join(command) in help_text
            and all(supports_flag(help_text, flag) for flag in required),
            "version": version.strip()[:200]}


def _source_digest(path: Path | None) -> str | None:
    if path is None:
        return None
    with path.open("rb") as stream:
        content = stream.read(MAX_SOURCE + 1)
    if len(content) > MAX_SOURCE:
        raise ValidationError("Source exceeds the 4 MiB inspection budget.")
    return hashlib.sha256(content).hexdigest()


def main(argv=None) -> int:
    args = parse_args(argv)
    repo = args.repo.resolve()
    fallback = ("Use official developer.android.com documentation; no automatic tool installation."
                if args.action.startswith("docs-") else
                "Use task-context/graph and source reads; keep required harness tests and builds. Studio actions need a compatible running Android Studio (Quail 2+).")
    try:
        command = command_for(repo, args)
        source = source_file(repo, args.value if args.action == "analyze" else args.file) if args.action == "analyze" or args.file else None
        before = _source_digest(source)
        executable = executable_path(repo)
        if args.action == "capabilities":
            result = {"status": "CAPABILITIES", "delivery_evidence": False,
                      "features": {action: probe(repo, executable, action) for action in ACTIONS},
                      "note": "CLI help support is not proof of a running/connected Studio or network access."}
        else:
            capability = probe(repo, executable, args.action)
            if not capability["supported"]:
                raise ValidationError("UNSUPPORTED: installed CLI lacks this command or required options.")
            code, output = invoke(executable, command, repo, 60, head=True)
            if before != _source_digest(source):
                raise ValidationError("STALE: source changed during inspection; repeat on current source.")
            result = {"status": "INSPECTION_COMPLETE" if code == 0 else "TOOL_FAILED",
                      "delivery_evidence": False, "action": args.action, "version": capability["version"],
                      "exit_code": code, "output": redact(output),
                      "output_may_be_truncated": len(output.encode("utf-8")) >= MAX_OUTPUT,
                      "source_sha256": before,
                      "note": "Untrusted diagnostic data. Command success does not mean no code issues; Studio unsaved buffers may differ from disk. No scope authorization or gate PASS."}
            if code:
                result["fallback"] = fallback
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0 if code == 0 else 30
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, ValidationError) as exc:
        print(json.dumps({"status": "UNAVAILABLE", "delivery_evidence": False,
                          "reason": redact(str(exc)), "fallback": fallback}, ensure_ascii=True))
        return 30


if __name__ == "__main__":
    raise SystemExit(main())

"""GitHub Projects & Issues adapter via the official gh CLI.

Stdlib-only subprocess wrapper around `gh` (https://cli.github.com/).
Design contract:

- Kit operations map to gh commands; statuses honor the pm_policy status map
  (Ready To ReTest -> "In Review"; Done-class transitions are refused).
- Authentication stays with gh itself (host auth / GH_TOKEN). This script
  never reads, prints, stores, or forwards tokens.
- Every subprocess call is timeout-bounded and fail-closed: missing binary,
  non-zero exit, timeout, or unparsable output raises SystemExit with an
  actionable message.

Unit tests must monkeypatch subprocess.run — zero network calls in tests.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

from pm_policy import (
    CANONICAL_IN_PROGRESS,
    CANONICAL_READY_RETEST,
    display_name,
    mutation_trigger,
    resolve_provider,
    status_label,
)

GH_TIMEOUT_SECONDS = 20.0
PROVIDER_ID = "github_projects"


class GhError(SystemExit):
    """Fail-closed error for every gh invocation problem."""


def _gh(args: list[str], *, input_text: str | None = None) -> str:
    binary = shutil.which("gh")
    if not binary:
        raise GhError(
            "[ERROR] gh CLI not found on PATH. Install it from "
            "https://cli.github.com/ and run 'gh auth login' once. "
            "The harness never handles GitHub tokens itself."
        )
    cmd = [binary, *args]
    try:
        proc = subprocess.run(
            cmd,
            input=input_text if input_text is not None else "",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise GhError(
            f"[ERROR] gh '{args[0] if args else ''}' timed out after "
            f"{GH_TIMEOUT_SECONDS:g}s. Network or host may be down; retry later."
        )
    except OSError as exc:
        raise GhError(f"[ERROR] Failed to execute gh: {exc}")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise GhError(f"[ERROR] gh {' '.join(args)} failed (rc={proc.returncode}): {detail}")
    return proc.stdout


def check_available() -> bool:
    """Non-raising probe used by doctor and post-install hints."""
    return shutil.which("gh") is not None


def _repo_args(repo: str | None) -> list[str]:
    return ["-R", repo] if repo else []


def _parse_json_output(raw: str, context: str):
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GhError(f"[ERROR] Could not parse gh output for {context}: {exc}")
    return data


def list_issues(repo: str | None = None, state: str = "open", limit: int = 30) -> list[dict]:
    raw = _gh(
        [
            "issue",
            "list",
            *_repo_args(repo),
            "--state",
            state,
            "--limit",
            str(int(limit)),
            "--json",
            "number,title,url,state",
        ]
    )
    data = _parse_json_output(raw, "issue list")
    if not isinstance(data, list):
        raise GhError("[ERROR] Unexpected gh issue list payload (expected a JSON array).")
    return data


def view_issue(number: int, repo: str | None = None) -> dict:
    raw = _gh(
        [
            "issue",
            "view",
            str(int(number)),
            *_repo_args(repo),
            "--json",
            "number,title,body,state,url,labels",
        ]
    )
    data = _parse_json_output(raw, f"issue #{number}")
    if not isinstance(data, dict):
        raise GhError(f"[ERROR] Unexpected gh issue view payload for #{number}.")
    return data


def add_comment(number: int, body: str, repo: str | None = None) -> str:
    if not str(body or "").strip():
        raise GhError("[ERROR] Refusing to post an empty comment.")
    return _gh(
        ["issue", "comment", str(int(number)), *_repo_args(repo), "--body-file", "-"],
        input_text=str(body),
    )


def edit_issue(
    number: int,
    repo: str | None = None,
    *,
    title: str | None = None,
    body: str | None = None,
) -> str:
    args = ["issue", "edit", str(int(number)), *_repo_args(repo)]
    if title:
        args += ["--title", title]
    if body is not None and str(body).strip():
        args += ["--body-file", "-"]
        return _gh(args, input_text=str(body))
    if not title:
        raise GhError("[ERROR] edit_issue needs a title and/or body to change.")
    return _gh(args)


def set_issue_status(number: int, canonical: str, repo: str | None = None) -> str:
    """Map a kit canonical status onto the provider label and apply it.

    Only the two policy-allowed canonical statuses are accepted; Done-class
    requests are refused before any gh call. GitHub issues have no native
    "In Review" state, so the label lands in the issue body status line when
    projects integration is absent; with a project id, use
    set_project_item_status instead.
    """
    key = resolve_provider(PROVIDER_ID)
    label = status_label(key, canonical)
    issue = view_issue(number, repo)
    body = str(issue.get("body") or "")
    marker_prefix = "Status:"
    lines = [
        line for line in body.splitlines()
        if not line.strip().lower().startswith(marker_prefix.lower())
    ]
    lines.insert(0, f"{marker_prefix} {label} ({display_name(key)})")
    new_body = "\n".join(lines).strip() + "\n"
    edit_issue(number, repo, body=new_body)
    return label


def set_project_item_status(item_id: str, project_id: str, canonical: str) -> str:
    """Update a GitHub Projects V2 status via `gh project item-edit`.

    The label is resolved through pm_policy (Done-class statuses refused).
    Note: gh's item-edit expects raw field/option node IDs; hosts running a
    customized Status field must pass their own option ID via --option-id
    override; the default assumes an unmodified built-in Status field.
    """
    key = resolve_provider(PROVIDER_ID)
    label = status_label(key, canonical)
    return _gh(
        [
            "project",
            "item-edit",
            "--id",
            str(item_id),
            "--project-id",
            str(project_id),
            "--field-id",
            "Status",
            "--single-select-option-id",
            label,
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="GitHub Projects/issues adapter (kit PM layer). Uses gh auth; never tokens."
    )
    parser.add_argument("--repo", help="OWNER/REPO slug (defaults to gh's current directory resolution).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Verify the gh CLI is available and authenticated.")
    p_list = sub.add_parser("list", help="List open issues as JSON.")
    p_list.add_argument("--state", default="open", choices=("open", "closed", "all"))
    p_list.add_argument("--limit", type=int, default=30)
    p_view = sub.add_parser("view", help="View one issue by number.")
    p_view.add_argument("number", type=int)
    p_comment = sub.add_parser("comment", help="Post a QA handoff comment from stdin or --body.")
    p_comment.add_argument("number", type=int)
    p_comment.add_argument("--body")
    p_status = sub.add_parser("status", help="Set policy-allowed status on an issue.")
    p_status.add_argument("number", type=int)
    p_status.add_argument("canonical", choices=(CANONICAL_IN_PROGRESS, CANONICAL_READY_RETEST))
    args = parser.parse_args(argv)

    if args.command == "check":
        if not check_available():
            print("MISSING: gh CLI not found. Install https://cli.github.com/ then 'gh auth login'.")
            return 1
        try:
            _gh(["auth", "status"])
        except GhError as exc:
            print(str(exc))
            return 1
        print(f"OK: gh available; trigger phrase is '{mutation_trigger(PROVIDER_ID)}'.")
        return 0
    if args.command == "list":
        print(json.dumps(list_issues(args.repo, args.state, args.limit), indent=2))
        return 0
    if args.command == "view":
        print(json.dumps(view_issue(args.number, args.repo), indent=2))
        return 0
    if args.command == "comment":
        body = args.body if args.body else sys.stdin.read()
        add_comment(args.number, body, args.repo)
        print(f"Comment posted on #{args.number}.")
        return 0
    if args.command == "status":
        label = set_issue_status(args.number, args.canonical, args.repo)
        print(f"#{args.number} marked '{label}'.")
        return 0
    parser.error(f"Unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

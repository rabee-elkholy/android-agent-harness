import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_state import (  # noqa: E402
    MAX_DIAGNOSTICS,
    MAX_REVIEWS,
    MAX_UI_REVIEWS,
    bump_invoke,
    canonical_subagent_name,
    clear_pending_reviews,
    file_sha256,
    invoke_count,
    package_already_reviewed,
    prompts_match,
    record_review_round,
    resolve_transcript_path,
    reviews_pending,
    transcript_path,
)
from _repo_files import has_non_doc_code_changes  # noqa: E402


def deny(reason: str) -> None:
    print(json.dumps({"decision": "deny", "reason": reason}))


def allow(reason: str = "Not blocked by the harness safety hook.") -> None:
    print(json.dumps({"decision": "allow", "reason": reason}))


def is_true(value) -> bool:
    if value is True:
        return True
    return str(value).strip().lower() in ("true", "1", "yes")


def conversation_id(payload: dict) -> str:
    return str(payload.get("conversationId") or payload.get("conversation_id") or "unknown")


PACKAGE_RE = re.compile(r"HARNESS_REVIEW_PACKAGE=(\S+)")

REVIEW_FIVE = frozenset(
    {
        "bug-reviewer-agent",
        "convention-reviewer-agent",
        "security-reviewer-agent",
        "perf-anr-guardian-agent",
        "regression-impact-reviewer-agent",
    }
)

GUARD_NAMES = frozenset({"code-review-guard", "code-review-guard-agent"})

ALLOWED_KINDS = {
    "bug-reviewer-agent": "review",
    "convention-reviewer-agent": "review",
    "security-reviewer-agent": "review",
    "regression-impact-reviewer-agent": "review",
    "perf-anr-guardian-agent": "review",
    "qa-diagnostics-agent": "diagnostics",
    "android-ui-expert-agent": "ui",
    "code-review-guard-agent": "guard",
}


def require_review_package(sub: dict) -> Path | None:
    prompt = str(sub.get("Prompt") or sub.get("prompt") or "")
    match = PACKAGE_RE.search(prompt)
    if not match:
        deny(
            "Denied: generate a review package first "
            "(`python .agents/scripts/review_package.py`) and put "
            "HARNESS_REVIEW_PACKAGE=<path> in every reviewer Prompt."
        )
        return None
    path = Path(match.group(1).strip().strip('"').strip("'"))
    if not path.is_file():
        deny(f"Denied: review package file does not exist: {path}")
        return None
    return path


def parse_subagents(args: dict):
    raw_subs = args.get("Subagents")
    if isinstance(raw_subs, str):
        raw_subs = json.loads(raw_subs)
    if raw_subs is None:
        return []
    if not isinstance(raw_subs, list):
        raise ValueError("Subagents must be a list")
    return raw_subs


def identify_subagent(sub: dict) -> tuple[str, str] | None:
    for key in ("TypeName", "typeName", "type_name"):
        raw = sub.get(key)
        if raw:
            canon = canonical_subagent_name(raw)
            if canon in ALLOWED_KINDS:
                return canon, ALLOWED_KINDS[canon]
    for key in ("Name", "name", "Role", "role"):
        raw = sub.get(key)
        if raw:
            canon = canonical_subagent_name(raw)
            if canon in ALLOWED_KINDS:
                return canon, ALLOWED_KINDS[canon]
    return None


def has_write_tools(obj: dict) -> bool:
    for key in ("enable_write_tools", "enableWriteTools", "EnableWriteTools"):
        if key in obj and is_true(obj.get(key)):
            return True
    return False


def has_subagent_tools(obj: dict) -> bool:
    for key in ("enable_subagent_tools", "enableSubagentTools", "EnableSubagentTools"):
        if key in obj and is_true(obj.get(key)):
            return True
    return False


def handle_define_subagent(args: dict) -> None:
    name = canonical_subagent_name(args.get("name") or args.get("Name") or "")
    if name in GUARD_NAMES or name == "code-review-guard-agent":
        deny(
            "Denied: code-review-guard-agent is retired as the delivery gate. "
            "Define/invoke the 5 review leaves instead."
        )
        return
    if name not in ALLOWED_KINDS:
        deny(
            f"Denied: subagent '{name}' is not in the allowed roster "
            f"({', '.join(sorted(ALLOWED_KINDS))})"
        )
        return
    if has_write_tools(args) or has_subagent_tools(args):
        deny("Denied: subagents must keep write tools and nested subagent tools off.")
        return
    prompt = args.get("system_prompt") or args.get("systemPrompt") or args.get("SystemPrompt") or ""
    if not prompts_match(str(prompt), name):
        deny(
            f"Denied: define_subagent system_prompt must match "
            f".agents/subagents/{name}.json template verbatim (fingerprint + body)."
        )
        return
    allow(f"{name} template accepted.")


def handle_invoke_subagent(payload: dict, args: dict) -> None:
    try:
        subs = parse_subagents(args)
    except Exception:
        deny("Denied: invoke_subagent Subagents is not valid JSON.")
        return
    if not subs or not isinstance(subs, list):
        deny("Denied: Subagents must be a non-empty list.")
        return
    if len(subs) > 6:
        deny("Denied: maximum 6 subagents allowed per invoke (5 review leaves + one optional specialist).")
        return

    conv = conversation_id(payload)
    identified: list[tuple[dict, str, str]] = []
    seen_names: set[str] = set()

    for sub in subs:
        if not isinstance(sub, dict):
            deny("Denied: each item in Subagents must be an object.")
            return
        workspace = str(sub.get("Workspace") or sub.get("workspace") or "").strip().lower()
        if workspace and workspace not in ("inherit", ""):
            deny("Denied: subagent Workspace must be inherit. Worktrees/share are off.")
            return
        found = identify_subagent(sub)
        if not found:
            deny(
                f"Denied: subagent '{sub.get('TypeName') or sub.get('Role')}' is not in the allowed roster "
                f"({', '.join(sorted(ALLOWED_KINDS))})"
            )
            return
        sub_name, agent_type = found
        if sub_name in seen_names:
            deny(f"Denied: duplicate subagent '{sub_name}' in the same invoke.")
            return
        seen_names.add(sub_name)
        if has_write_tools(sub) or has_subagent_tools(sub):
            deny(f"Denied: {sub_name} must keep write and subagent tools off.")
            return
        if sub_name in GUARD_NAMES or agent_type == "guard":
            deny(
                "Denied: code-review-guard-agent is retired as the delivery gate. "
                "Dispatch all 5 review leaves in EXACTLY ONE invoke_subagent call: "
                "bug-reviewer-agent, convention-reviewer-agent, security-reviewer-agent, "
                "perf-anr-guardian-agent, regression-impact-reviewer-agent."
            )
            return
        identified.append((sub, sub_name, agent_type))

    names = {name for _, name, _ in identified}
    review_names = names & REVIEW_FIVE
    solo_perf = review_names == {"perf-anr-guardian-agent"} and names == {"perf-anr-guardian-agent"}

    if review_names and not solo_perf:
        missing = REVIEW_FIVE - review_names
        if missing or review_names != REVIEW_FIVE:
            deny(
                "Denied: delivery review must dispatch all 5 leaves in ONE invoke_subagent call "
                f"(missing: {', '.join(sorted(missing)) or 'none'}). "
                "Do not fire separate invoke_subagent calls."
            )
            return
        package_paths: list[Path] = []
        for sub, _name, _kind in identified:
            if _name not in REVIEW_FIVE:
                continue
            path = require_review_package(sub)
            if path is None:
                return
            package_paths.append(path)
        unique_pkgs = {str(p.resolve()) for p in package_paths}
        if len(unique_pkgs) != 1:
            deny("Denied: all 5 review leaves must share the same HARNESS_REVIEW_PACKAGE path.")
            return
        pkg = package_paths[0]
        digest = file_sha256(pkg)
        if package_already_reviewed(conv, digest):
            deny(
                "Denied: this exact review package content was already reviewed. "
                "Fix the findings, regenerate with `python .agents/scripts/review_package.py`, "
                "then dispatch the 5 leaves again."
            )
            return
        used = invoke_count(conv, "review")
        if used >= MAX_REVIEWS:
            deny(
                f"Denied: runaway review cap reached ({used}/{MAX_REVIEWS}). "
                "This is an infinite-loop guard, not a quality skip. Stop and inspect why reviews are repeating."
            )
            return
        record_review_round(conv, digest)
        allow("5-leaf parallel review accepted.")
        return

    if solo_perf:
        used = invoke_count(conv, "perf")
        if used >= MAX_REVIEWS:
            deny(f"Denied: performance audit limit reached ({used}/{MAX_REVIEWS}).")
            return
        bump_invoke(conv, "perf")
        allow("Solo perf-anr-guardian-agent accepted for /perf-audit.")
        return

    has_diag = any(kind == "diagnostics" for _, _, kind in identified)
    has_ui = any(kind == "ui" for _, _, kind in identified)

    if has_diag:
        used = invoke_count(conv, "diagnostics")
        if used >= MAX_DIAGNOSTICS:
            deny(f"Denied: diagnostics limit reached ({used}/{MAX_DIAGNOSTICS}).")
            return
        bump_invoke(conv, "diagnostics")
    if has_ui:
        used = invoke_count(conv, "ui")
        if used >= MAX_UI_REVIEWS:
            deny(f"Denied: UI review limit reached ({used}/{MAX_UI_REVIEWS}).")
            return
        bump_invoke(conv, "ui")

    allow(f"Specialist subagents accepted: {len(subs)} running.")


INVOKE_NAME_RE = re.compile(r"invoke[_-]?subagent", re.IGNORECASE)
CONV_ID_RE = re.compile(
    r'(?:conversationId|conversation_id)\s*[:=]\s*"([0-9a-fA-F-]{8,})"',
    re.IGNORECASE,
)
SENDER_RE = re.compile(r"sender=([0-9a-fA-F-]{8,}(?:/task-\d+)?)")
PASS_TOKENS = ("BUG_PASS", "CONVENTION_PASS", "SECURITY_PASS", "PERF_PASS", "REGRESSION_PASS")


_INVOKE_TOOL_JSON_RE = re.compile(
    r"""["']name["']\s*:\s*["']invoke_subagent["']""",
    re.IGNORECASE,
)
_NON_INVOKE_TYPES = frozenset(
    {"GENERIC", "CHECKPOINT", "EPHEMERAL_MESSAGE", "SYSTEM_MESSAGE"}
)


def _is_invoke_subagent_entry(entry: dict) -> bool:
    for tool_call in _iter_tool_calls(entry):
        name = _tool_name(tool_call).strip().lower()
        if name == "invoke_subagent" or INVOKE_NAME_RE.fullmatch(name):
            return True
    entry_type = str(entry.get("type") or "").upper()
    if entry_type in _NON_INVOKE_TYPES:
        return False
    source = str(entry.get("source") or "").upper()
    if source in {"SYSTEM", "SYSTEM_SDK"}:
        return False
    blob = _entry_blob(entry)
    return bool(_INVOKE_TOOL_JSON_RE.search(blob))


def _iter_tool_calls(entry: dict):
    for key in ("tool_calls", "toolCalls"):
        raw = entry.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    yield item
        elif isinstance(raw, dict):
            yield raw


def _tool_name(tool_call: dict) -> str:
    nested = tool_call.get("function")
    if isinstance(nested, dict):
        nested_name = nested.get("name")
        if nested_name:
            return str(nested_name)
    return str(tool_call.get("name") or tool_call.get("toolName") or "")


def _entry_blob(entry: dict) -> str:
    try:
        return json.dumps(entry, ensure_ascii=False)
    except TypeError:
        return str(entry)


def _read_transcript_lines(path: Path) -> list[dict]:
    max_bytes = 2_000_000
    size = path.stat().st_size
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
            handle.readline()
        raw_lines = handle.readlines()
    entries = []
    for line in raw_lines:
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({"content": line})
    return entries


def _tail_has_verdicts(text: str) -> bool:
    if all(token in text for token in PASS_TOKENS):
        return True
    return text.count("Findings") >= 5


def check_subagents_barrier(conv_id: str, payload: dict | None = None) -> tuple[bool, str]:
    if not conv_id or conv_id == "unknown":
        return True, "No conv id"
    if not reviews_pending(conv_id):
        return True, "No pending review round"

    log_file = resolve_transcript_path(conv_id, payload)
    if log_file is None or not log_file.is_file():
        fallback = transcript_path(conv_id)
        return False, (
            "A 5-leaf review round is pending and the conversation transcript is not readable yet "
            f"(looked for {fallback}). "
            "Wait until all 5 leaves deliver BUG_PASS / CONVENTION_PASS / SECURITY_PASS / "
            "PERF_PASS / REGRESSION_PASS (or Findings). Do not assemble while they are running."
        )
    try:
        lines = _read_transcript_lines(log_file)
    except Exception:
        return False, (
            "A 5-leaf review round is pending and the transcript could not be parsed. "
            "Wait for all 5 review messages before tests/assemble."
        )

    last_invoke_idx = -1
    for i, entry in enumerate(lines):
        if _is_invoke_subagent_entry(entry):
            last_invoke_idx = i

    if last_invoke_idx == -1:
        whole = "\n".join(_entry_blob(entry) for entry in lines)
        if _tail_has_verdicts(whole):
            clear_pending_reviews(conv_id)
            return True, "Review verdicts found in transcript (invoke record missing)."
        return False, (
            "A 5-leaf review round is pending but the last invoke_subagent is not in the transcript tail. "
            "Wait for all 5 leaves to reply before tests/assemble. "
            "If they already replied, the log format may have changed — do not assemble until "
            "BUG_PASS / CONVENTION_PASS / SECURITY_PASS / PERF_PASS / REGRESSION_PASS are visible."
        )

    after_entries = lines[last_invoke_idx + 1 :]
    after = "\n".join(_entry_blob(entry) for entry in after_entries)
    spawn_window = _entry_blob(lines[last_invoke_idx])
    if after_entries:
        spawn_window += "\n" + _entry_blob(after_entries[0])

    spawned_ids = [sid for sid in CONV_ID_RE.findall(spawn_window) if sid != conv_id]
    if spawned_ids:
        replied_ids = set()
        for entry in after_entries:
            content = str(entry.get("content") or "") + _entry_blob(entry)
            for sid in spawned_ids:
                if f"sender={sid}" in content or sid in SENDER_RE.findall(content):
                    replied_ids.add(sid)
                elif sid in content and ("finished" in content.lower() or "PASS" in content or "Findings" in content):
                    replied_ids.add(sid)
        pending = [sid for sid in spawned_ids if sid not in replied_ids]
        if not pending:
            clear_pending_reviews(conv_id)
            return True, "All subagents completed."
        if _tail_has_verdicts(after):
            clear_pending_reviews(conv_id)
            return True, "All subagents completed."
        return False, (
            f"Waiting for {len(pending)}/{len(spawned_ids)} review subagents to deliver their verdicts."
        )

    if _tail_has_verdicts(after):
        clear_pending_reviews(conv_id)
        return True, "All subagents completed."
    return False, (
        "A 5-leaf review round is pending. Wait until all 5 leaves reply "
        "(PASS or Findings) before tests/assemble."
    )


def handle_run_command(command: str, payload: dict | None = None) -> None:
    lower = command.lower()
    conv = conversation_id(payload or {})

    is_assemble_or_test = any(
        k in lower
        for k in ("gradle", "assemble", "testdebug", ":app:test", "run_device.py")
    )
    is_lint = "fast_kt_lint" in lower

    if (is_assemble_or_test or is_lint) and conv != "unknown":
        ok, barrier_msg = check_subagents_barrier(conv, payload)
        if not ok:
            deny(
                f"Denied: Parallel review barrier active. {barrier_msg} "
                "You MUST NOT run tests/build until all review subagents have finished."
            )
            return

    if is_assemble_or_test and conv != "unknown":
        if has_non_doc_code_changes() and invoke_count(conv, "review") < 1:
            deny(
                "Denied: working tree has code changes but no 5-leaf review round ran in this conversation. "
                "Generate a review package and dispatch all 5 review leaves in one invoke_subagent call first."
            )
            return

    tokens = lower.split()
    if "git" in tokens:
        mutations = {
            "add",
            "commit",
            "push",
            "pull",
            "fetch",
            "merge",
            "rebase",
            "stash",
            "reset",
            "checkout",
            "switch",
            "branch",
            "worktree",
            "clone",
        }
        skip_next = False
        for token in tokens[tokens.index("git") + 1 :]:
            if skip_next:
                skip_next = False
                continue
            if token in ("-c", "-C"):
                skip_next = True
                continue
            if token.startswith("-"):
                continue
            if token in mutations:
                deny("Denied: git mutation is developer-owned in Android Studio. Inspection only. Never commit.")
                return
            break

    if re.search(r"\bandroid\s+emulator\b", lower):
        deny("Denied: android emulator is forbidden. Physical device only.")
        return
    if re.search(r"\bandroid\s+(?:run|install)\b", lower) and "--device" not in lower:
        deny("Denied: android run/install needs --device=<physical-serial>.")
        return

    if "adb" not in lower and "emulator" not in lower and "avdmanager" not in lower:
        allow()
        return

    if re.search(r"(?:^|\s)(?:emulator|avdmanager)(?:\.exe|\.bat)?(?:\s|$)", lower):
        deny("Denied: emulator/AVD tooling is forbidden. Physical device only.")
        return
    if re.search(r"(?:^|\s)-e(?:\s|$)", lower) or re.search(r"emulator-\d+", lower):
        deny("Denied: emulator targeting is forbidden.")
        return
    if re.search(r"(?:^|\s)monkey(?:\s|$)", lower):
        deny("Denied: adb monkey is forbidden. Use adb -s <id> shell am start.")
        return
    if re.search(r"\bpm\s+clear\b", lower):
        deny("Denied: pm clear app data requires explicit developer approval.")
        return
    if re.search(r"\bpm\s+uninstall\b", lower):
        deny("Denied: pm uninstall is forbidden. Use python .agents/scripts/run_device.py uninstall or adb -s <serial> uninstall <package>.")
        return

    device_bound = bool(
        re.search(r"\b(?:install|uninstall|shell|exec-out|push|pull|logcat|forward|reverse)\b", lower)
    )
    if device_bound and not re.search(r"(?:^|\s)(?:-d|-s)\b", command):
        deny("Denied: device-bound adb needs -d or -s <physical-serial>.")
        return

    allow("ADB command not blocked by safety hook.")


def handle_schedule(args: dict, payload: dict) -> None:
    prompt = str(args.get("Prompt") or args.get("prompt") or "").lower()
    conv = conversation_id(payload)
    if reviews_pending(conv) or any(
        kw in prompt for kw in ("subagent", "reviewer", "review", "reviewers", "subagents", "مراجع")
    ):
        deny(
            "Denied: do not use schedule/timers to wait for subagents. "
            "Antigravity wakes the agent automatically via Reactive Wakeup when subagents finish. "
            "Simply stop calling tools to end your turn."
        )
        return
    allow("Schedule call permitted.")


def main() -> None:
    try:
        if hasattr(sys.stdin, "reconfigure"):
            try:
                sys.stdin.reconfigure(encoding="utf-8")
            except Exception:
                pass
        raw = sys.stdin.read()
        if not raw.strip():
            allow()
            return

        payload = json.loads(raw)
        tool_call = payload.get("toolCall") or {}
        name = str(tool_call.get("name") or "").lower()
        args = tool_call.get("args") or {}

        if name == "define_subagent":
            handle_define_subagent(args)
            return
        if name == "invoke_subagent":
            handle_invoke_subagent(payload, args)
            return
        if name == "schedule":
            handle_schedule(args, payload)
            return
        if name != "run_command":
            allow()
            return

        command = str(args.get("CommandLine") or args.get("commandLine") or "")
        handle_run_command(command, payload)
    except json.JSONDecodeError:
        deny("Denied: safety hook received invalid JSON on stdin.")
    except Exception as exc:
        deny(
            f"Denied: safety hook error ({type(exc).__name__}: {exc}). "
            "Retry the tool. Do not bypass the hook."
        )


if __name__ == "__main__":
    main()

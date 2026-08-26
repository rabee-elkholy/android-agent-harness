import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_state import (  # noqa: E402
    MAX_DIAGNOSTICS,
    MAX_REVIEWS,
    MAX_TEST_REVIEWS,
    MAX_UI_REVIEWS,
    active_package_hash,
    adjudicate_review_findings,
    bump_invoke,
    canonical_subagent_name,
    clear_pending_reviews,
    file_sha256,
    invoke_count,
    package_already_reviewed,
    pending_since,
    prompts_match,
    read_verdict_record,
    record_review_round,
    record_subagent_defined,
    record_subagents_poll,
    record_task_poll,
    resolve_transcript_path,
    reviews_pending,
    transcript_path,
    write_verdict_record,
)
from _repo_files import REPO, has_non_doc_code_changes  # noqa: E402
from policy_vocab import (  # noqa: E402
    DEVICE_BOUND_ADB,
    DENIED_PM_OPS,
    GIT_MUTATIONS,
    SHELL_INDIRECTION_PATTERNS,
    classify_reason,
    emulator_match,
    normalize_command,
    reason_short,
)


_CONTEXT = {"tool": "", "command": ""}

AUDIT_MAX_RECORDS = 1000


def _audit_path() -> Path:
    override = os.environ.get("HARNESS_HOOK_STATE")
    base = (
        Path(override)
        if override
        else Path(__file__).resolve().parent.parent / "state" / "review-invokes.json"
    )
    return base.with_name("audit_log.jsonl")


def _cmd_sha256_12(command: str) -> str:
    if not command:
        return ""
    return hashlib.sha256(command.encode("utf-8", errors="replace")).hexdigest()[:12]


def write_audit(decision: str, reason: str) -> None:
    """Append one sanitized decision record to the JSONL audit log.

    Never writes raw commands or payload content: only a 12-hex command digest,
    a truncated conversation hint, and the classified reason.
    """
    try:
        conv = conversation_id(_CONTEXT.get("payload") or {})
        record = {
            "ts": round(time.time(), 3),
            "decision": decision,
            "tool": _CONTEXT.get("tool") or "run_command",
            "reason_code": classify_reason(reason),
            "reason_short": reason_short(reason),
            "cmd_sha256_12": _cmd_sha256_12(_CONTEXT.get("command") or ""),
            "conv_hint": (conv if conv and conv != "unknown" else "")[:16],
        }
        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if path.stat().st_size > 0:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
            if len(lines) > AUDIT_MAX_RECORDS:
                from _hook_state import state_lock

                with state_lock():
                    kept = lines[-AUDIT_MAX_RECORDS:]
                    temp_file = tempfile.NamedTemporaryFile(
                        mode="w",
                        encoding="utf-8",
                        dir=str(path.parent),
                        delete=False,
                        suffix=".tmp",
                    )
                    temp_file.writelines(kept)
                    temp_file.flush()
                    temp_file.close()
                    os.replace(temp_file.name, path)
    except Exception:
        pass  # Auditing must never alter a safety decision.


def deny(reason: str) -> None:
    write_audit("deny", reason)
    print(json.dumps({"decision": "deny", "reason": reason}))


def allow(reason: str = "Not blocked by the harness safety hook.") -> None:
    write_audit("allow", reason)
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
    "test-quality-reviewer-agent": "test",
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
    raw_path = match.group(1).strip().strip('"').strip("'")
    path = Path(raw_path)
    if not path.is_file():
        deny(f"Denied: review package file does not exist: {path}")
        return None
    _WARNED_LEGACY: set[str] = getattr(require_review_package, "_warned", set())
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2000]
    except Exception:
        head = ""
    if "HARNESS_PACKAGE_HEADER v2" not in head and str(path) not in _WARNED_LEGACY:
        _WARNED_LEGACY.add(str(path))
        setattr(require_review_package, "_warned", _WARNED_LEGACY)
        print(
            f"[WARN] review package {path.name} predates the v2 evidence header "
            "(no PACKAGE_SHA256/GIT_SHA); accepted this migration window, regenerate soon.",
            file=sys.stderr,
        )
    try:
        resolved = path.resolve()
        repo_resolved = REPO.resolve()
        temp_dir = Path(tempfile.gettempdir()).resolve()
        is_inside_repo = resolved == repo_resolved or repo_resolved in resolved.parents
        is_inside_temp = "HARNESS_HOOK_STATE" in os.environ and (resolved == temp_dir or temp_dir in resolved.parents)
        if not (is_inside_repo or is_inside_temp):
            deny(f"Denied: review package must reside inside the repository: {path}")
            return None
    except Exception:
        deny(f"Denied: invalid review package path: {path}")
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


def handle_define_subagent(args: dict, payload: dict | None = None) -> None:
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
    conv = conversation_id(payload) if payload else ""
    if conv and conv != "unknown":
        record_subagent_defined(conv, name)
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
    has_test = any(kind == "test" for _, _, kind in identified)

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
    if has_test:
        used = invoke_count(conv, "test")
        if used >= MAX_TEST_REVIEWS:
            deny(f"Denied: test quality review limit reached ({used}/{MAX_TEST_REVIEWS}).")
            return
        bump_invoke(conv, "test")

    allow(f"Specialist subagents accepted: {len(subs)} running.")


INVOKE_NAME_RE = re.compile(r"invoke[_-]?subagent", re.IGNORECASE)
CONV_ID_RE = re.compile(
    r'(?:conversationId|conversation_id)\s*[:=]\s*"([0-9a-fA-F-]{8,})"',
    re.IGNORECASE,
)
SENDER_RE = re.compile(r"sender=([0-9a-fA-F-]{8,}(?:/task-\d+)?)")
PASS_TOKENS = ("BUG_PASS", "CONVENTION_PASS", "SECURITY_PASS", "PERF_PASS", "REGRESSION_PASS")
EVIDENCE_RE = re.compile(r"EVIDENCE\s+pkg=([0-9a-fA-F]{12})\s+cites=(\d+)\b")


def _record_verdict(
    conv_id: str,
    active_pkg12: str,
    verdict: str,
    reason: str,
    chunks: list[str] | None = None,
) -> None:
    """Best-effort completion record for the machine-readable verdict artifact.

    Strictly additive: never raises and never alters the allow/deny decision.
    """
    try:
        if not active_pkg12:
            return
        record = read_verdict_record(active_pkg12) or {
            "schema_version": 1,
            "task_id": "",
            "git_sha": "",
            "package": {"path": "", "sha256": "", "sha256_12": active_pkg12},
            "tree_fingerprint": None,
            "files": {},
            "dispatched_at": None,
        }
        record["verdict"] = verdict
        record["completed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        record["completed_reason"] = reason[:400]
        leaves: dict[str, dict] = {}
        findings: list[str] = []
        for chunk in chunks or []:
            for token in PASS_TOKENS:
                if token in chunk:
                    leaf = token.split("_")[0].lower()
                    evidence = EVIDENCE_RE.search(chunk)
                    leaves.setdefault(
                        leaf,
                        {
                            "token": token,
                            "evidence": {
                                "pkg": evidence.group(1) if evidence else "",
                                "cites": int(evidence.group(2)) if evidence else 0,
                                "valid": bool(evidence)
                                and evidence.group(1).lower() == active_pkg12.lower(),
                            },
                        },
                    )
            if "Findings" in chunk:
                findings.append(chunk[:2000])
        record["leaves"] = leaves
        record["findings"] = findings[:50]
        record["adjudication"] = adjudicate_review_findings(findings)
        write_verdict_record(active_pkg12, record)
    except Exception:
        pass


def _evidence_mode() -> str:
    raw = os.environ.get("HARNESS_EVIDENCE_MODE", "strict").strip().lower()
    return "legacy" if raw == "legacy" else "strict"


def _valid_evidence_footer(text: str, active_pkg12: str) -> bool:
    if not active_pkg12:
        return False
    return any(pkg.lower() == active_pkg12.lower() for pkg, _cites in EVIDENCE_RE.findall(text))


def _evidenced_verdict_count(chunks: list[str], active_pkg12: str) -> int:
    """Count distinct leaves whose verdict chunk carries a valid evidence footer.

    A chunk satisfies one leaf when it contains the leaf's PASS token or a
    Findings marker AND at least one EVIDENCE footer whose pkg matches the
    active review package hash.
    """
    satisfied_tokens: set[str] = set()
    findings_leaves = 0
    for chunk in chunks:
        footer_ok = _valid_evidence_footer(chunk, active_pkg12)
        if not footer_ok:
            continue
        tokens = {token for token in PASS_TOKENS if token in chunk}
        satisfied_tokens |= tokens
        if not tokens and "Findings" in chunk:
            findings_leaves += 1
    return len(satisfied_tokens) + min(findings_leaves, max(0, 5 - len(satisfied_tokens)))


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

    evidence_mode = _evidence_mode()
    active_pkg12 = active_package_hash(conv_id)[:12]
    if evidence_mode == "strict" and not active_pkg12:
        return False, (
            "A 5-leaf review round is pending but the active review package hash is unknown. "
            "Regenerate with `python .agents/scripts/review_package.py` and re-dispatch the 5 leaves; "
            "verdicts are only accepted with an EVIDENCE footer citing that package."
        )

    def strict_shortfall(chunks: list[str]) -> bool:
        if evidence_mode != "strict":
            return False
        return _evidenced_verdict_count(chunks, active_pkg12) < 5

    try:
        barrier_ttl = float(os.environ.get("HARNESS_BARRIER_TTL", "21600"))
    except (TypeError, ValueError):
        barrier_ttl = 21600.0
    since = pending_since(conv_id)
    if barrier_ttl > 0 and since is not None and time.time() - since > barrier_ttl:
        clear_pending_reviews(conv_id)
        _record_verdict(conv_id, active_pkg12, "EXPIRED", "Review round expired after the barrier TTL.")
        return True, (
            f"Pending review round expired after {int(barrier_ttl)}s barrier TTL. "
            "Re-run the 5 review leaves if the code changed."
        )

    log_file = resolve_transcript_path(conv_id, payload)
    if log_file is None or not log_file.is_file():
        fallback = transcript_path(conv_id)
        if evidence_mode == "legacy":
            return False, (
                "A 5-leaf review round is pending and the conversation transcript is not readable yet "
                f"(looked for {fallback}). "
                "Wait until all 5 leaves deliver BUG_PASS / CONVENTION_PASS / SECURITY_PASS / "
                "PERF_PASS / REGRESSION_PASS (or Findings). Do not assemble while they are running."
            )
        return False, (
            "A 5-leaf review round is pending and the conversation transcript is not readable yet "
            f"(looked for {fallback}). In strict evidence mode each leaf must end its reply with "
            "`EVIDENCE pkg=<sha256_12> cites=<n>` matching the dispatched package "
            f"(active package: pkg={active_pkg12}). Do not assemble while they are running."
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
        if _tail_has_verdicts(whole) and not strict_shortfall([whole]):
            clear_pending_reviews(conv_id)
            _record_verdict(
                conv_id, active_pkg12, "PASS",
                "Review verdicts found in transcript (invoke record missing).", [whole],
            )
            return True, "Review verdicts found in transcript (invoke record missing)."
        if evidence_mode == "strict" and _tail_has_verdicts(whole):
            missing = _evidenced_verdict_count([whole], active_pkg12)
            _record_verdict(
                conv_id, active_pkg12, "FAIL",
                f"Only {missing}/5 verdicts carried a valid EVIDENCE footer.", [whole],
            )
            return False, (
                f"PASS/Findings tokens found for {missing}/5 leaves but EVIDENCE footers are missing "
                f"or cite the wrong package (expected pkg={active_pkg12}). "
                "Verdicts without a valid evidence footer do not count; ask the leaves to re-reply."
            )
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
            chunks = [str(entry.get("content") or "") + _entry_blob(entry) for entry in after_entries]
            if strict_shortfall(chunks):
                evidenced = _evidenced_verdict_count(chunks, active_pkg12)
                _record_verdict(
                    conv_id, active_pkg12, "FAIL",
                    f"All subagent senders replied, but only {evidenced}/5 verdicts carried a valid EVIDENCE footer.",
                    chunks,
                )
                return False, (
                    f"All subagent senders replied, but only {evidenced}/5 verdicts carry a valid "
                    f"EVIDENCE footer (expected pkg={active_pkg12}). "
                    "Forged, missing, or mismatched footers keep the barrier up; re-request the replies."
                )
            clear_pending_reviews(conv_id)
            _record_verdict(conv_id, active_pkg12, "PASS", "All subagents completed.", chunks)
            return True, "All subagents completed."
        return False, (
            f"Waiting for {len(pending)}/{len(spawned_ids)} review subagents to deliver their verdicts."
        )

    chunks = [str(entry.get("content") or "") + _entry_blob(entry) for entry in after_entries]
    if _tail_has_verdicts(after) and not strict_shortfall(chunks):
        clear_pending_reviews(conv_id)
        _record_verdict(conv_id, active_pkg12, "PASS", "All subagents completed.", chunks)
        return True, "All subagents completed."
    if evidence_mode == "strict" and _tail_has_verdicts(after):
        evidenced = _evidenced_verdict_count(chunks, active_pkg12)
        _record_verdict(
            conv_id, active_pkg12, "FAIL",
            f"A 5-leaf review round is pending: only {evidenced}/5 verdicts carried a valid EVIDENCE footer.",
            chunks,
        )
        return False, (
            f"A 5-leaf review round is pending: {evidenced}/5 verdicts carry a valid EVIDENCE footer "
            f"(expected pkg={active_pkg12}). Tokens alone no longer clear the barrier — "
            "each leaf reply must include `EVIDENCE pkg=<sha256_12> cites=<n>`."
        )
    return False, (
        "A 5-leaf review round is pending. Wait until all 5 leaves reply "
        "(PASS or Findings) before tests/assemble."
    )


def handle_run_command(command: str, payload: dict | None = None) -> None:
    lower = command.lower()
    lower_norm = re.sub(r"[\\]", "", lower)
    conv = conversation_id(payload or {})
    is_setup_script = any(
        s in lower_norm
        for s in (
            "install_tool_adapters",
            "setup_wizard",
            "install_zoho_mcp",
            "check_kit_update",
            "review_package",
        )
    )
    is_assemble_or_test = not is_setup_script and any(
        k in lower_norm
        for k in ("gradle", "assemble", "testdebug", ":app:test", "run_device.py")
    )
    is_lint = not is_setup_script and "fast_kt_lint" in lower_norm

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

    git_mutation_pat = re.compile(
        r'(?:^|[;&|`\s\'"]|(?:\b(?:cmd|powershell|pwsh|bash|sh|zsh|env)\b[^\n\r]*?))'
        r'(?:[a-zA-Z0-9_./\\:-]*[/\\])?git(?:\.exe)?[\'"]?\s+(.+)$',
        re.IGNORECASE | re.DOTALL,
    )
    indirection_res = tuple(re.compile(p, re.IGNORECASE) for p in SHELL_INDIRECTION_PATTERNS)
    # Scan each shell-chained segment separately so a leading inspection
    # command cannot mask a chained mutation ("git status && git push").
    segments = [s for s in re.split(r"&&|\|\||;|\||\r?\n", command) if s.strip()] or [command]
    for segment in segments:
        normalized_segment = normalize_command(segment)
        lower_norm_segment = normalized_segment.lower()
        for pattern in indirection_res:
            if pattern.search(lower_norm_segment):
                deny(
                    "Denied: encoded or piped shell indirection is fail-closed denied. "
                    "Run the plain command directly; do not wrap payloads through sh/base64/eval."
                )
                return
        for m in git_mutation_pat.finditer(normalized_segment):
            rest = m.group(1).strip()
            rest_tokens = rest.split()
            skip_next = False
            for tok in rest_tokens:
                cleaned_tok = tok.strip("'\"").strip()
                if skip_next:
                    skip_next = False
                    continue
                if cleaned_tok in ("-c", "-C", "--git-dir", "--work-tree"):
                    skip_next = True
                    continue
                if cleaned_tok.startswith("-"):
                    continue
                if cleaned_tok.lower() in GIT_MUTATIONS:
                    deny("Denied: git mutation is developer-owned in Android Studio. Inspection only. Never commit.")
                    return
                break

    if emulator_match(lower) and emulator_match(lower)[0] == "android_emulator":
        deny("Denied: android emulator is forbidden. Physical device only.")
        return

    if re.search(r"\bandroid\s+(?:run|install)\b", lower) and "--device" not in lower:
        deny("Denied: android run/install needs --device=<physical-serial>.")
        return

    if "adb" not in lower and "emulator" not in lower and "avdmanager" not in lower:
        allow()
        return

    emulator_hit = emulator_match(lower)
    if emulator_hit:
        name, _match = emulator_hit
        if name == "monkey":
            deny("Denied: adb monkey is forbidden. Use adb -s <id> shell am start.")
            return
        if name == "standalone_tool":
            deny("Denied: emulator/AVD tooling is forbidden. Physical device only.")
            return
        deny("Denied: emulator targeting is forbidden.")
        return

    pm_messages = {
        "clear": "Denied: pm clear app data requires explicit developer approval.",
        "uninstall": "Denied: pm uninstall is forbidden. Use python .agents/scripts/run_device.py uninstall or adb -s <serial> uninstall <package>.",
    }
    for op in sorted(DENIED_PM_OPS):
        # Also cover the `cmd package clear|uninstall <pkg>` laundering path:
        # it performs the same data wipe as `pm <op>` and must deny identically.
        if re.search(rf"\b(?:pm\s+|cmd\s+package\s+){re.escape(op)}\b", lower):
            deny(pm_messages[op])
            return

    device_bound_pat = r"\b(?:" + "|".join(sorted(DEVICE_BOUND_ADB)) + r")\b"
    device_bound = bool(re.search(device_bound_pat, lower))
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


def handle_manage_task(args: dict, payload: dict) -> None:
    action = str(args.get("Action") or args.get("action") or "").lower()
    task_id = str(args.get("TaskId") or args.get("taskId") or "")
    conv = conversation_id(payload)
    if action == "status" and conv != "unknown" and task_id:
        count = record_task_poll(conv, task_id)
        if count > 2:
            deny(
                "Denied: Busy polling on background task status is forbidden. "
                "Antigravity automatically notifies you with a message when the background command finishes. "
                "You MUST stop calling tools immediately to end your turn and wait for the completion notification."
            )
            return
    allow("manage_task permitted.")


def handle_manage_subagents(args: dict, payload: dict) -> None:
    action = str(args.get("Action") or args.get("action") or "").lower()
    conv = conversation_id(payload)
    if action == "list" and conv != "unknown" and reviews_pending(conv):
        count = record_subagents_poll(conv)
        if count > 2:
            deny(
                "Denied: Busy polling on active subagents via manage_subagents(list) is forbidden. "
                "Antigravity automatically delivers subagent responses via Reactive Wakeup. "
                "You MUST stop calling tools immediately to end your turn."
            )
            return
    allow("manage_subagents permitted.")


MAX_STDIN_BYTES = 5 * 1024 * 1024


def main() -> None:
    try:
        if hasattr(sys.stdin, "reconfigure"):
            try:
                sys.stdin.reconfigure(encoding="utf-8")
            except Exception:
                pass
        raw = sys.stdin.read()
        if len(raw.encode("utf-8", errors="replace")) > MAX_STDIN_BYTES:
            deny(
                "Denied: hook payload too large "
                f"(>{MAX_STDIN_BYTES} bytes). Retry with a smaller tool input."
            )
            return
        if not raw.strip():
            allow()
            return

        payload = json.loads(raw)
        tool_call = payload.get("toolCall") or {}
        name = str(tool_call.get("name") or "").lower()
        args = tool_call.get("args") or {}
        _CONTEXT["tool"] = name or "run_command"
        _CONTEXT["command"] = str(args.get("CommandLine") or args.get("commandLine") or "")
        _CONTEXT["payload"] = payload if isinstance(payload, dict) else {}

        if name == "define_subagent":
            handle_define_subagent(args, payload)
            return
        if name == "invoke_subagent":
            handle_invoke_subagent(payload, args)
            return
        if name == "manage_subagents":
            handle_manage_subagents(args, payload)
            return
        if name == "manage_task":
            handle_manage_task(args, payload)
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

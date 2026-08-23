"""Shared review-round state and subagent template validator for this app hooks."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

MAX_REVIEWS = int(os.environ.get("HARNESS_MAX_REVIEWS", "20"))
MAX_DIAGNOSTICS = int(os.environ.get("HARNESS_MAX_DIAGNOSTICS", "10"))
MAX_UI_REVIEWS = int(os.environ.get("HARNESS_MAX_UI_REVIEWS", "10"))

STATE_EXPIRY_SECONDS = 7 * 24 * 3600

SUBAGENTS_DIR = Path(__file__).resolve().parent.parent / "subagents"

_FINGERPRINT_RE = re.compile(r"HARNESS_\w+_FINGERPRINT=(\S+)")

TEMPLATE_ALIASES = {
    "compose-ui-expert": "android-ui-expert-agent",
    "compose-ui-expert-agent": "android-ui-expert-agent",
    "android-ui-expert": "android-ui-expert-agent",
    "qa-diagnostics": "qa-diagnostics-agent",
    "bug-reviewer": "bug-reviewer-agent",
    "convention-reviewer": "convention-reviewer-agent",
    "security-reviewer": "security-reviewer-agent",
    "regression-impact-reviewer": "regression-impact-reviewer-agent",
    "perf-anr-guardian": "perf-anr-guardian-agent",
    "perf-guardian": "perf-anr-guardian-agent",
    "code-review-guard": "code-review-guard-agent",
}


def state_path() -> Path:
    override = os.environ.get("HARNESS_HOOK_STATE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "state" / "review-invokes.json"


def transcript_path(conversation_id: str) -> Path:
    override = os.environ.get("HARNESS_TRANSCRIPT_ROOT")
    if override:
        return Path(override) / conversation_id / "transcript.jsonl"
    return (
        Path.home()
        / ".gemini"
        / "antigravity"
        / "brain"
        / conversation_id
        / ".system_generated"
        / "logs"
        / "transcript.jsonl"
    )


def resolve_transcript_path(conversation_id: str, payload: dict | None = None) -> Path | None:
    """Find the conversation transcript even if Antigravity moves the log path."""
    candidates: list[Path] = []
    if payload:
        for key in ("transcriptPath", "transcript_path"):
            raw = payload.get(key)
            if raw:
                candidates.append(Path(str(raw)))
    candidates.append(transcript_path(conversation_id))
    brain_logs = (
        Path.home()
        / ".gemini"
        / "antigravity"
        / "brain"
        / conversation_id
        / ".system_generated"
        / "logs"
    )
    candidates.extend(
        [
            brain_logs / "transcript.jsonl",
            brain_logs / "transcript_full.jsonl",
        ]
    )
    seen: set[str] = set()
    ordered: list[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(path)
        if path.is_file():
            return path
        if path.is_dir():
            jsonl = sorted(path.glob("*.jsonl"))
            if jsonl:
                return jsonl[-1]
    if brain_logs.is_dir():
        found = list(brain_logs.rglob("transcript*.jsonl"))
        if found:
            return max(found, key=lambda item: item.stat().st_mtime)
    return None


def normalize_prompt(text: str) -> str:
    cleaned = str(text).replace("\r\n", "\n").replace("\u00e2\u20ac\u201c", "-").replace("\u2014", "-")
    lines = [line.strip() for line in cleaned.split("\n")]
    return "\n".join(line for line in lines if line)


def _extract_fingerprint(text: str) -> str | None:
    match = _FINGERPRINT_RE.search(text)
    return match.group(1) if match else None


def canonical_subagent_name(subagent_name: str) -> str:
    norm = re.sub(r"[^a-z0-9]+", "-", str(subagent_name).lower()).strip("-")
    return TEMPLATE_ALIASES.get(norm, norm)


def get_template_path(subagent_name: str) -> Path | None:
    norm = canonical_subagent_name(subagent_name)
    candidates = [
        SUBAGENTS_DIR / f"{norm}.json",
        SUBAGENTS_DIR / f"{norm}-agent.json",
    ]
    if norm.endswith("-agent"):
        candidates.append(SUBAGENTS_DIR / f"{norm[:-6]}.json")
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def template_system_prompt(subagent_name: str = "bug-reviewer-agent") -> str:
    path = get_template_path(subagent_name)
    if not path or not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("system_prompt") or "")
    except Exception:
        return ""


def prompts_match(incoming: str, subagent_name: str = "bug-reviewer-agent") -> bool:
    """Incoming system_prompt must match the template verbatim (normalized).

    Fingerprint equality alone is not enough — both the fingerprint and the
    normalized body must match so a token cannot launder a different prompt.
    """
    template_prompt = template_system_prompt(subagent_name)
    if not template_prompt:
        return False
    if normalize_prompt(incoming) != normalize_prompt(template_prompt):
        return False
    template_fp = _extract_fingerprint(template_prompt)
    incoming_fp = _extract_fingerprint(incoming)
    if template_fp or incoming_fp:
        return template_fp == incoming_fp
    return True


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _prune_expired(state: dict) -> dict:
    now = time.time()
    pruned = {}
    for conv_id, rec in state.items():
        ts = rec.get("_last_used", 0)
        try:
            ts_val = float(ts)
        except (TypeError, ValueError):
            ts_val = 0.0
        if now - ts_val < STATE_EXPIRY_SECONDS:
            pruned[conv_id] = rec
    return pruned


def load_state() -> dict:
    path = state_path()
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = _prune_expired(state)
    payload = json.dumps(cleaned, indent=2)
    try:
        temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            delete=False,
            suffix=".tmp",
        )
        temp_file.write(payload)
        temp_file.flush()
        temp_file.close()
        os.replace(temp_file.name, path)
    except Exception:
        path.write_text(payload, encoding="utf-8")


def _record(conversation_id: str) -> dict:
    return load_state().get(conversation_id) or {}


def invoke_count(conversation_id: str, agent_type: str = "review") -> int:
    rec = _record(conversation_id)
    try:
        if agent_type == "review":
            return int(rec.get("invokes") or rec.get("review_invokes") or 0)
        return int(rec.get(f"{agent_type}_invokes") or 0)
    except (TypeError, ValueError):
        return 0


def bump_invoke(conversation_id: str, agent_type: str = "review") -> int:
    state = load_state()
    rec = state.get(conversation_id) or {}
    key = "invokes" if agent_type == "review" else f"{agent_type}_invokes"
    n = invoke_count(conversation_id, agent_type) + 1
    rec[key] = n
    if agent_type == "review":
        rec["review_invokes"] = n
    rec["_last_used"] = time.time()
    state[conversation_id] = rec
    save_state(state)
    return n


def package_already_reviewed(conversation_id: str, package_hash: str) -> bool:
    rec = _record(conversation_id)
    hashes = rec.get("package_hashes") or []
    return package_hash in hashes


def record_review_round(conversation_id: str, package_hash: str) -> int:
    state = load_state()
    rec = state.get(conversation_id) or {}
    hashes = list(rec.get("package_hashes") or [])
    if package_hash not in hashes:
        hashes.append(package_hash)
    rec["package_hashes"] = hashes[-40:]
    rec["last_package_hash"] = package_hash
    rec["pending_reviews"] = True
    rec["pending_since"] = time.time()
    n = int(rec.get("review_invokes") or rec.get("invokes") or 0) + 1
    rec["invokes"] = n
    rec["review_invokes"] = n
    rec["_last_used"] = time.time()
    state[conversation_id] = rec
    save_state(state)
    return n


def reviews_pending(conversation_id: str) -> bool:
    return bool(_record(conversation_id).get("pending_reviews"))


def pending_since(conversation_id: str) -> float | None:
    rec = _record(conversation_id)
    if not rec.get("pending_reviews"):
        return None
    try:
        return float(rec.get("pending_since") or 0) or None
    except (TypeError, ValueError):
        return None


def clear_pending_reviews(conversation_id: str) -> None:
    state = load_state()
    rec = state.get(conversation_id) or {}
    if not rec:
        return
    rec["pending_reviews"] = False
    rec["_last_used"] = time.time()
    state[conversation_id] = rec
    save_state(state)

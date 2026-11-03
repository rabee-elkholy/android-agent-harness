"""Short-lived PM & Zoho write grants from the developer's explicit update order.

Supports both Zoho Sprints (`update zoho` / `حدث زوهو`) and any Project Management
MCP installed in Antigravity (`update pm` / `حدث التاسك` / `update jira` /
`update linear` / `update monday` / `update github` / etc.), plus explicit
developer orders to close a task (`close task` / `mark done` / `اقفل التاسك`).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

GRANT_FILE = "zoho-write-grant.json"
GRANT_TTL_SECONDS = 30 * 60
TRIGGER = "update zoho"

_ARABIC_MARKS = re.compile("[ً-ْـ]")  # harakat, shadda and tatweel
_ARABIC_UPDATE = ("حدث", "تحديث", "حدثه", "حدثها", "عدل", "تعديل")
_ZOHO_WORDS = ("zoho", "زوهو", "بروجكتس")
_PM_TARGET_WORDS = (
    "zoho", "زوهو", "بروجكتس",
    "jira", "جيرا", "atlassian", "اتلاسيان",
    "linear", "لينير",
    "monday", "مانداي",
    "github", "جيتهاب",
    "clickup", "كليك",
    "asana", "اسانا",
    "trello", "تريلو",
    "pm", "tracker", "task", "issue", "ticket",
    "التاسك", "تاسك", "المهمة", "المهمه", "البورد",
)
_EN_PM_TRIGGERS = (
    "update zoho",
    "update pm",
    "update tracker",
    "update task",
    "update issue",
    "update jira",
    "update atlassian",
    "update linear",
    "update monday",
    "update github",
    "update clickup",
    "update asana",
    "update trello",
)
_CLOSE_EN_PHRASES = (
    "close task",
    "close the task",
    "close issue",
    "close the issue",
    "mark done",
    "mark as done",
    "mark completed",
    "mark as completed",
    "set status to done",
    "set to done",
    "move to done",
)
_ARABIC_CLOSE_VERBS = ("اقفل", "إقفل", "اغلق", "أغلق", "اقفله", "اقفلها", "اغلقه", "اغلقها", "انهي", "أنهي")


def is_explicit_close_order(text: str) -> bool:
    """True when the developer explicitly ordered closing/completing the tracker item."""
    plain = _ARABIC_MARKS.sub("", " ".join(str(text or "").split())).lower()
    if any(phrase in plain for phrase in _CLOSE_EN_PHRASES):
        return True
    words = re.findall(r"[\w؀-ۿ]+", plain)
    for index, word in enumerate(words):
        w_clean = word[1:] if word.startswith("و") and len(word) > 3 else word
        if w_clean in _ARABIC_CLOSE_VERBS:
            window = " ".join(words[index + 1:index + 4])
            if any(target in window for target in _PM_TARGET_WORDS) or w_clean in ("اقفله", "اقفلها", "اغلقه", "اغلقها"):
                return True
        if w_clean in ("خليها", "خليه", "حولها", "حوله") and index + 1 < len(words):
            window = " ".join(words[index + 1:index + 4])
            if any(st in window for st in ("done", "closed", "completed", "solved", "مكتمل", "مغلق")):
                return True
    return False


def is_update_zoho(text: str) -> bool:
    """The developer's explicit order: `update zoho` / `update pm`, or Arabic (حدث زوهو / حدث التاسك)."""
    plain = _ARABIC_MARKS.sub("", " ".join(str(text or "").split())).lower()
    if TRIGGER in plain or "update pm" in plain:
        return True
    words = re.findall(r"[\w؀-ۿ]+", plain)
    for index, word in enumerate(words):
        if word in _ARABIC_UPDATE or (word.startswith("و") and word[1:] in _ARABIC_UPDATE):
            if any(zoho in " ".join(words[index + 1:index + 3]) for zoho in _ZOHO_WORDS):
                return True
    return False


def is_update_pm(text: str, provider: str | None = None, *, allow_close: bool = False) -> bool:
    """True when `text` contains a valid developer PM update or close order."""
    if allow_close or is_update_zoho(text) or is_explicit_close_order(text):
        return True
    plain = _ARABIC_MARKS.sub("", " ".join(str(text or "").split())).lower()
    if any(trig in plain for trig in _EN_PM_TRIGGERS):
        return True
    prov_clean = (provider or "").strip().lower().replace("_", " ").replace("-", " ")
    if prov_clean and prov_clean not in ("all", "auto", "*", "pm", "any") and f"update {prov_clean}" in plain:
        return True
    words = re.findall(r"[\w؀-ۿ]+", plain)
    for index, word in enumerate(words):
        if word in _ARABIC_UPDATE or (word.startswith("و") and word[1:] in _ARABIC_UPDATE):
            window = " ".join(words[index + 1:index + 4])
            if any(target in window for target in _PM_TARGET_WORDS):
                return True
    return False


def _matched_providers_from_text(text: str, explicit_provider: str = "all") -> list[str]:
    if explicit_provider and explicit_provider not in ("all", "auto", "*"):
        return [explicit_provider.lower()]
    plain = _ARABIC_MARKS.sub("", " ".join(str(text or "").split())).lower()
    matched: list[str] = []
    if any(w in plain for w in ("zoho", "زوهو", "بروجكتس")):
        matched.extend(["zoho_sprints", "zoho_projects"])
    if any(w in plain for w in ("jira", "جيرا", "atlassian", "اتلاسيان")):
        matched.append("jira")
    if any(w in plain for w in ("linear", "لينير")):
        matched.append("linear")
    if any(w in plain for w in ("monday", "مانداي")):
        matched.append("monday")
    if any(w in plain for w in ("github", "جيتهاب")):
        matched.append("github_projects")
    if any(w in plain for w in ("clickup", "كليك")):
        matched.append("clickup")
    if any(w in plain for w in ("asana", "اسانا")):
        matched.append("asana")
    if any(w in plain for w in ("trello", "تريلو")):
        matched.append("trello")
    if not matched or any(w in plain for w in ("update pm", "update tracker", "update task", "التاسك", "المهمة", "المهمه")):
        return ["all"]
    return sorted(set(matched))


def _state(repo: Path) -> Path:
    for candidate in (repo / ".agents" / "state", repo / "agents" / "state"):
        if candidate.parent.is_dir():
            return candidate
    return repo / ".agents" / "state"


def record_grant(repo: Path, proof_reference: str, source: str = "conversation") -> dict:
    """Record a Zoho/PM grant; proof must be the developer's message ordering `update zoho` / `حدث زوهو`."""
    from _vnext_common import ValidationError, atomic_write_json, utc_now

    proof = " ".join(str(proof_reference or "").split())
    if not is_update_zoho(proof):
        raise ValidationError(
            f"ZOHO_GRANT_NEEDS_UPDATE_ZOHO: the proof must be the developer's message ordering it (`{TRIGGER}`, or حدث زوهو); "
            "show the developer what will be written first and wait for it."
        )
    grant = {
        "schema_version": 1,
        "source": source,
        "proof_reference": proof[:500],
        "providers": ["zoho_sprints", "zoho_projects", "all"],
        "allow_close": is_explicit_close_order(proof),
        "granted_at": utc_now(),
        "granted_epoch": time.time(),
        "expires_epoch": time.time() + GRANT_TTL_SECONDS,
    }
    state = _state(repo)
    state.mkdir(parents=True, exist_ok=True)
    atomic_write_json(state / GRANT_FILE, grant)
    return grant


def record_pm_grant(
    repo: Path,
    proof_reference: str,
    provider: str = "all",
    source: str = "conversation",
    *,
    allow_close: bool = False,
) -> dict:
    """Record a universal PM write grant for any installed PM MCP."""
    from _vnext_common import ValidationError, atomic_write_json, utc_now

    # Support legacy positional call pattern: record_pm_grant(repo, "conversation", "حدث التاسك")
    if proof_reference in ("conversation", "developer_terminal") and provider not in ("all", "auto", "*") and is_update_pm(provider):
        source, proof_reference, provider = proof_reference, provider, "all"

    proof = " ".join(str(proof_reference or "").split())
    if not is_update_pm(proof, provider=provider, allow_close=allow_close):
        raise ValidationError(
            "PM_GRANT_NEEDS_UPDATE_ORDER: the proof must be the developer's message ordering the tracker update "
            "(`update pm`, `update zoho`, `update jira`, `حدث التاسك`, `حدث زوهو`, etc.); "
            "show the developer what will be written first and wait for their confirmation."
        )
    providers = _matched_providers_from_text(proof, explicit_provider=provider)
    grant = {
        "schema_version": 1,
        "source": source,
        "proof_reference": proof[:500],
        "providers": providers,
        "allow_close": bool(allow_close or is_explicit_close_order(proof)),
        "granted_at": utc_now(),
        "granted_epoch": time.time(),
        "expires_epoch": time.time() + GRANT_TTL_SECONDS,
    }
    state = _state(repo)
    state.mkdir(parents=True, exist_ok=True)
    atomic_write_json(state / GRANT_FILE, grant)
    return grant


def active_grant(repo: Path) -> dict | None:
    """The unexpired Zoho grant, or None."""
    try:
        data = json.loads((_state(repo) / GRANT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        if float(data.get("expires_epoch") or 0) <= time.time():
            return None
        if float(data.get("expires_epoch") or 0) - float(data.get("granted_epoch") or 0) > GRANT_TTL_SECONDS + 1:
            return None
    except (TypeError, ValueError):
        return None
    proof = str(data.get("proof_reference") or "")
    if not (is_update_zoho(proof) or is_update_pm(proof)):
        return None
    return data


def active_pm_grant(repo: Path, provider: str | None = None) -> dict | None:
    """Return the active PM write grant if unexpired and matching `provider` (or `'all'`)."""
    data = active_grant(repo)
    if not data:
        return None
    if not provider:
        return data
    allowed_providers = data.get("providers") or ["all"]
    if "all" in allowed_providers or provider.lower() in allowed_providers:
        return data
    return None


def authorize_command() -> str:
    return 'python .agents/harness.py zoho authorize --proof-reference "<the developer\'s message with update zoho>"'


def pm_authorize_command(provider: str = "pm") -> str:
    return f'python .agents/harness.py pm authorize --proof-reference "<the developer\'s message with update {provider} or حدث التاسك>"'

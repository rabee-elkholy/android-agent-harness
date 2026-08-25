"""Provider-agnostic project-management (PM) policy engine.

Deterministic, offline, stdlib-only. Generalizes the Zoho Sprints policy
(rules section 5 + workflows/zoho-sprints.md) to GitHub Projects, Jira, and
Linear without changing any default behavior:

- Absent/empty PM_PROVIDER resolves to "zoho_sprints" (the historical default).
- "update zoho" remains the mutation trigger for zoho_sprints; other providers
  get "update <provider>".
- Handoff validation recognizes the bilingual header mapping table documented
  in workflows/zoho-sprints.md per ZOHO_LANGUAGE mode.

No network I/O anywhere in this module. Adapters live in separate scripts
(see pm_github.py) or upstream MCP servers (see agents/pm/*.md).
"""
from __future__ import annotations

DEFAULT_PROVIDER = "zoho_sprints"

CANONICAL_IN_PROGRESS = "in_progress"
CANONICAL_READY_RETEST = "ready_to_retest"
CANONICAL_STATUSES = (CANONICAL_IN_PROGRESS, CANONICAL_READY_RETEST)

LANG_MODES = ("en_titles_ar_comments", "all_en", "all_ar")
AR_MODES = ("en_titles_ar_comments", "all_ar")

PROVIDERS: dict[str, dict] = {
    "zoho_sprints": {
        "display": "Zoho Sprints",
        "status_map": {
            CANONICAL_IN_PROGRESS: "In progress",
            CANONICAL_READY_RETEST: "Ready To ReTest",
        },
        "denied_status_labels": {"done", "solved", "completed", "closed"},
        "trigger": "update zoho",
        "config_file": "zoho_sprints.json",
    },
    "github_projects": {
        "display": "GitHub Projects",
        "status_map": {
            CANONICAL_IN_PROGRESS: "In Progress",
            CANONICAL_READY_RETEST: "In Review",
        },
        "denied_status_labels": {"done", "shipped"},
        "trigger": "update github",
        "config_file": "github_projects.json",
    },
    "jira": {
        "display": "Jira",
        "status_map": {
            CANONICAL_IN_PROGRESS: "In Progress",
            CANONICAL_READY_RETEST: "Ready for Testing",
        },
        "denied_status_labels": {"done", "resolved", "closed"},
        "trigger": "update jira",
        "config_file": "jira.json",
    },
    "linear": {
        "display": "Linear",
        "status_map": {
            CANONICAL_IN_PROGRESS: "In Progress",
            CANONICAL_READY_RETEST: "In Review",
        },
        "denied_status_labels": {"done", "canceled", "cancelled"},
        "trigger": "update linear",
        "config_file": "linear.json",
    },
}

WIZARD_PROVIDER_IDS = ("zoho_sprints", "github_projects", "jira_mcp", "linear_mcp", "none")

# Bilingual handoff header aliases per workflows/zoho-sprints.md. Each section
# accepts any alias of its comment-language group (all_en -> EN, otherwise AR).
SECTIONS: tuple[dict, ...] = (
    {
        "key": "root_cause_or_objective",
        "en": ("Root Cause:", "Objective:", "Feature & Objective:"),
        "ar": (
            "سبب المشكلة:",
            "الهدف من المهمة:",
            "الميزة والهدف منها:",
            "الهدف من التعديل:",
        ),
    },
    {
        "key": "solution_or_what_changed",
        "en": ("Solution:", "What Changed:", "Implementation & Entry Points:"),
        "ar": ("الحل المطبق:", "ما تم تنفيذه:"),
    },
    {
        "key": "impact_area_blast_radius",
        "en": ("Impact Area (Blast Radius):",),
        "ar": ("نطاق التأثير (Impact Area):",),
    },
    {
        "key": "test_cases_verification_steps",
        "en": ("Test Cases & Verification Steps:",),
        "ar": ("خطوات الفحص وحالات الاختبار (Test Cases):",),
    },
)

_COMMIT_LINE_RE = None
_STATUS_DECLINE_RE = None


def _commit_line_re():
    global _COMMIT_LINE_RE
    if _COMMIT_LINE_RE is None:
        import re

        _COMMIT_LINE_RE = re.compile(r"^Commit:\s*\S+", re.IGNORECASE)
    return _COMMIT_LINE_RE


def _status_decline_re():
    global _STATUS_DECLINE_RE
    if _STATUS_DECLINE_RE is None:
        import re

        _STATUS_DECLINE_RE = re.compile(
            r"\bstatus\b\s*(?::|=|->|\bto\b)\s*(\S[^\n]*)", re.IGNORECASE
        )
    return _STATUS_DECLINE_RE


def resolve_provider(raw: str | None) -> str:
    """Resolve a configured provider id to a registry key.

    Accepts wizard ids (jira_mcp -> jira, linear_mcp -> linear). Empty or
    absent values fall back to DEFAULT_PROVIDER for backward compatibility.
    Unknown values raise SystemExit with an actionable message (fail closed).
    """
    value = str(raw or "").strip()
    if not value:
        return DEFAULT_PROVIDER
    alias = {
        "zoho": "zoho_sprints",
        "zoho_mcp": "zoho_sprints",
        "github": "github_projects",
        "gh": "github_projects",
        "jira_mcp": "jira",
        "linear_mcp": "linear",
    }
    key = alias.get(value.lower(), value.lower())
    if key == "none":
        return "none"
    if key not in PROVIDERS:
        known = ", ".join(WIZARD_PROVIDER_IDS)
        raise SystemExit(
            f"[ERROR] Unknown project tracker '{raw}'. Expected one of: {known}. "
            f"Fix PM_PROVIDER in _product.py (or .harness-setup/answers.json)."
        )
    return key


def active_provider() -> str:
    """Read PM_PROVIDER from _product.py; absent field keeps Zoho behavior."""
    try:
        from _product import PM_PROVIDER  # type: ignore
    except ImportError:
        return DEFAULT_PROVIDER
    return resolve_provider(PM_PROVIDER)


def display_name(provider: str | None = None) -> str:
    key = resolve_provider(provider)
    if key == "none":
        return "None (local-only delivery)"
    return str(PROVIDERS[key]["display"])


def mutation_trigger(provider: str | None = None) -> str:
    """Explicit chat phrase required before any provider mutation."""
    key = resolve_provider(provider)
    if key == "none":
        return ""
    return str(PROVIDERS[key]["trigger"])


def status_label(provider: str | None, canonical: str) -> str:
    """Kit canonical status -> provider label. Fails closed on unknown."""
    key = resolve_provider(provider)
    if key == "none":
        raise SystemExit(
            "[ERROR] No project tracker is configured (PM_PROVIDER=none); "
            "there is no provider status to map."
        )
    canon = str(canonical or "").strip().lower().replace("-", "_").replace(" ", "_")
    label = PROVIDERS[key]["status_map"].get(canon)
    if not label:
        allowed = ", ".join(PROVIDERS[key]["status_map"])
        raise SystemExit(
            f"[ERROR] Unknown canonical status '{canonical}' for {display_name(key)}. "
            f"Allowed kit statuses: {allowed}."
        )
    return str(label)


def normalize_status(provider: str | None, label: str) -> str:
    """Provider status label -> kit canonical status (case-insensitive).

    Raises SystemExit on unknown labels with the accepted alternatives listed.
    """
    key = resolve_provider(provider)
    if key == "none":
        raise SystemExit(
            "[ERROR] No project tracker is configured (PM_PROVIDER=none); "
            "cannot normalize a provider status."
        )
    raw = str(label or "").strip()
    lowered = raw.lower()
    reverse = {str(v).lower(): k for k, v in PROVIDERS[key]["status_map"].items()}
    if lowered in reverse:
        return reverse[lowered]
    denied = PROVIDERS[key]["denied_status_labels"]
    if lowered in denied:
        raise SystemExit(
            f"[ERROR] Status '{raw}' is forbidden by harness policy for "
            f"{display_name(key)} (rules section 5). Allowed: only "
            "'In progress' when started and 'Ready To ReTest' when verified."
        )
    allowed = ", ".join(str(v) for v in PROVIDERS[key]["status_map"].values())
    raise SystemExit(
        f"[ERROR] Unknown status '{raw}' for {display_name(key)}. "
        f"Allowed labels: {allowed}."
    )


def _section_aliases(section: dict, lang_mode: str) -> tuple[str, ...]:
    group = "en" if lang_mode == "all_en" else "ar"
    return tuple(str(a) for a in section[group])


def _contains_header(line_lower: str, header: str) -> bool:
    needle = header.lower().rstrip(":").strip()
    hay = line_lower.strip()
    if hay.startswith("#"):
        hay = hay.lstrip("#").strip()
    if hay[:2] in ("- ", "* "):
        hay = hay[2:].strip()
    elif len(hay) > 2 and hay[0].isdigit() and hay[1] in ".),":
        hay = hay[2:].lstrip(".) ").strip()
    elif len(hay) > 3 and hay[:2].isdigit() and hay[2] in ".)":
        hay = hay[3:].lstrip(".) ").strip()
    return hay.startswith(needle)


def validate_handoff(
    text: str,
    lang_mode: str = "en_titles_ar_comments",
    provider: str | None = DEFAULT_PROVIDER,
) -> list[str]:
    """Validate a QA handoff text against rules section 5.

    Returns a list of human-readable violations; empty list means valid.
    Checks: Commit first line, every mandatory section header (bilingual,
    resolved by lang_mode), and forbidden provider-Done status declarations.
    """
    violations: list[str] = []
    mode = str(lang_mode or "").strip()
    if mode not in LANG_MODES:
        raise SystemExit(
            f"[ERROR] Unknown language mode '{lang_mode}'. "
            f"Expected one of: {', '.join(LANG_MODES)}."
        )
    body = str(text or "").replace("\r\n", "\n")
    lines = body.split("\n")
    first_nonempty = next((l for l in lines if l.strip()), "")
    if not _commit_line_re().match(first_nonempty.strip()):
        violations.append(
            "Missing 'Commit: <hash>' as the first line "
            "(retrieve via git log -1 --format=%h; never invent one)."
        )

    for section in SECTIONS:
        aliases = _section_aliases(section, mode)
        found = any(
            _contains_header(line.lower(), alias) for line in lines for alias in aliases
        )
        if not found:
            violations.append(
                f"Missing mandatory section header ({aliases[0].rstrip(':')}) — "
                "see workflows/zoho-sprints.md templates."
            )

    key = resolve_provider(provider)
    if key != "none":
        denied = {str(d) for d in PROVIDERS[key]["denied_status_labels"]}
        for match in _status_decline_re().finditer(body):
            label = match.group(1).strip().strip("*_\"'").split()[0].rstrip(".:,") if match.group(1).strip() else ""
            if label.lower() in denied:
                violations.append(
                    f"Forbidden status declaration '{label}' for {display_name(key)} "
                    "(never Done/Solved-class statuses; use Ready To ReTest)."
                )
                break
    return violations

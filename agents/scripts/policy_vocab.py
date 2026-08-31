"""Canonical safety vocabulary for the Android Agent Harness.

Single source of truth for every deny class the pre-tool safety hook enforces.
pre_tool_safety.py imports these frozensets instead of redeclaring literals;
the selftest proves the shipped grants example never contradicts them.

Also hosts the static REASON_CODES map used by `android-harness explain` to
render audit-log entries in human-readable form.
"""
from __future__ import annotations

import re

# Verbs that mutate git state. Inspection verbs (status/diff/log/rev-parse...)
# are deliberately absent: they stay allowed.
GIT_MUTATIONS = frozenset(
    {
        "add",
        "branch",
        "checkout",
        "clone",
        "commit",
        "fetch",
        "merge",
        "pull",
        "push",
        "rebase",
        "reset",
        "stash",
        "switch",
        "worktree",
    }
)

# adb verbs that touch a device and therefore require -d / -s <serial>.
# Privilege/data-exfil verbs (root, remount, backup, reboot, sync) are
# deliberately included so they cannot run without an explicit device binding.
DEVICE_BOUND_ADB = frozenset(
    {
        "backup",
        "exec-out",
        "forward",
        "install",
        "logcat",
        "pull",
        "push",
        "reboot",
        "remount",
        "reverse",
        "root",
        "shell",
        "sync",
        "uninstall",
    }
)

# Regex fragments identifying forbidden emulator tooling. Names preserve the
# distinct deny message each pattern produced before the vocabulary existed.
EMULATOR_PATTERNS = (
    ("android_emulator", r"\bandroid\s+emulator\b"),
    ("standalone_tool", r"(?:^|\s)(?:emulator|avdmanager)(?:\.exe|\.bat)?(?:\s|$)"),
    ("targeting_flag", r"(?:^|\s)-e(?:\s|$)"),
    ("emulator_port", r"emulator-\d+"),
    # Only monkey launched through adb is denied; a bare word mention
    # (e.g. `git log --grep monkey`) must not trip the deny.
    ("monkey", r"(?:^|\s)adb(?:\s+[^\n]*)?\bmonkey\b"),
)
_EMULATOR_RES = tuple((name, re.compile(p, re.IGNORECASE)) for name, p in EMULATOR_PATTERNS)


def emulator_match(text: str) -> tuple[str, re.Match] | None:
    for name, pattern in _EMULATOR_RES:
        match = pattern.search(text)
        if match:
            return name, match
    return None


# `pm <op>` package-manager operations that are denied outright.
DENIED_PM_OPS = frozenset({"clear", "uninstall"})


# Standalone tools that must never be invoked in a harness session.
FORBIDDEN_TOOLS = frozenset({"android emulator", "avdmanager", "emulator", "monkey"})

# Shell-indirection shapes (encoded payloads, pipe-to-shell) that are denied
# outright regardless of the decoded content.
SHELL_INDIRECTION_PATTERNS = (
    r"\|\s*(?:ba|z|da|k)?sh\b",
    r"\b(?:ba|z|da|k)?sh\s+-[a-z]*c\b",
    r"\bbase64\b[^|\n]*\|\s*(?:ba|z|da|k)?sh\b",
    r"\beval\b\s*\$\(",
    r"\bbase64\s+(?:--decode|-d)\b",
)

# Homoglyph fold map applied before git scanning so 'gıt' / 'git.exe' lookalike
# variants cannot launder a mutation past the scanner (B1 adversarial suite).
CONFUSABLES_MAP = {
    "\u0131": "i",  # dotless i
    "\u0456": "i",  # cyrillic byelorussian-ukrainian i
    "\u03b9": "i",  # greek iota
    "\u1d96": "i",
    "\u0262": "g",  # small capital g
    "\u01f5": "g",
    "\u0581": "g",
    "\u0433": "r",  # cyrillic ge resembles r-ish glyphs in some fonts
    "\uff47": "g",  # fullwidth g
    "\uff49": "i",  # fullwidth i
    "\uff54": "t",  # fullwidth t
    "\u2013": "-",
    "\u2014": "-",
    "\u00ad": "",  # soft hyphen
    "\u200b": "",
    "\u200c": "",
    "\u200d": "",
    "\u2060": "",
    "\ufeff": "",
}


def fold_confusables(text: str) -> str:
    translated = str(text).translate(str.maketrans(CONFUSABLES_MAP))
    import unicodedata

    return unicodedata.normalize("NFKC", translated)


def normalize_command(command: str) -> str:
    """Deterministic normalization used by the git scanner: confusable fold,
    whitespace collapse, backslash unification."""
    folded = fold_confusables(str(command)).replace("\\\\", "/").replace("\\", "/")
    return re.sub(r"[ \t]+", " ", folded)


# Static, human-readable mapping printed by `android-harness explain`.
REASON_CODES = {
    "ALREADY_REVIEWED": "This exact review package content was already reviewed.",
    "BARRIER_ACTIVE": "Parallel review barrier active; subagents have not all replied.",
    "CAP_REACHED": "Runaway invocation cap reached for this subagent class.",
    "DEVICE_BINDING_REQUIRED": "Device-bound adb command missing -d/-s <physical-serial>.",
    "DEVICE_TARGETING_REQUIRED": "android run/install without an explicit --device target.",
    "DUPLICATE_SUBAGENT": "The same subagent was listed twice in one invoke.",
    "EMULATOR_DENIED": "Emulator/AVD tooling is forbidden; physical device only.",
    "GUARD_RETIRED": "code-review-guard-agent is retired; dispatch the 5 review leaves.",
    "HOOK_ERROR": "Safety hook raised while inspecting the payload; fail-closed.",
    "INVOKE_LIMIT": "Too many subagents in one invoke_subagent call.",
    "MONKEY_DENIED": "adb monkey is forbidden; use adb shell am start.",
    "PACKAGE_MISMATCH": "Review leaves referenced different review packages.",
    "PACKAGE_MISSING": "Referenced HARNESS_REVIEW_PACKAGE file does not exist.",
    "PACKAGE_PATH_ESCAPE": "Review package path escapes the repository sandbox.",
    "PACKAGE_PATH_INVALID": "Review package path could not be resolved safely.",
    "PAYLOAD_MALFORMED": "Hook payload was not valid JSON or had an invalid shape.",
    "PAYLOAD_OVERSIZE": "Hook payload exceeded the accepted stdin size cap.",
    "POLL_DENIED": "Busy polling on tasks/subagents is forbidden; stop calling tools.",
    "PM_CLEAR_DENIED": "pm clear app data requires explicit developer approval.",
    "PM_UNINSTALL_DENIED": "pm uninstall is forbidden via pm; use uninstall helpers.",
    "REGISTRY_DENIED": "Command matches a denied registry mutation pattern.",
    "REVIEW_DISPATCH_INCOMPLETE": "Delivery review must dispatch all 5 leaves in ONE invoke.",
    "REVIEW_PACKAGE_REQUIRED": "A review package must be generated before dispatching leaves.",
    "REVIEW_REQUIRED_FIRST": "Code changes exist but no 5-leaf review round ran yet.",
    "ROSTER_DENIED": "Subagent name is not in the allowed roster.",
    "SCHEDULE_DENIED": "Timers must not be used to wait for subagents.",
    "GIT_MUTATION_DENIED": "git mutations are developer-owned; inspection only.",
    "SHELL_INDIRECTION_DENIED": "Encoded/piped shell indirection is fail-closed denied.",
    "ADB_ALLOW": "adb command passed every device-safety rule.",
    "DEFAULT_ALLOW": "Tool call not covered by any harness deny rule.",
    "SUBAGENT_TOOLS_OFF": "Subagents must keep write and nested-subagent tools off.",
    "TEMPLATE_MISMATCH": "define_subagent prompt does not match the shipped template.",
    "WORKSPACE_NOT_INHERIT": "Subagent workspace must be inherit; worktrees are off.",
    "UNKNOWN": "Decision recorded without a classified reason code.",
}

_CLASSIFIERS: tuple[tuple[str, str], ...] = (
    ("GIT_MUTATION_DENIED", r"git mutation"),
    ("REVIEW_PACKAGE_REQUIRED", r"generate a review package first"),
    ("PACKAGE_MISSING", r"package file does not exist"),
    ("PACKAGE_PATH_ESCAPE", r"must reside inside the repository"),
    ("PACKAGE_PATH_INVALID", r"invalid review package path"),
    ("PACKAGE_MISMATCH", r"same HARNESS_REVIEW_PACKAGE"),
    ("ALREADY_REVIEWED", r"already reviewed"),
    ("REVIEW_DISPATCH_INCOMPLETE", r"all 5 leaves"),
    ("REVIEW_REQUIRED_FIRST", r"no 5-leaf review round ran"),
    ("BARRIER_ACTIVE", r"review barrier active|Waiting for \d+/\d+ review|round is pending|transcript"),
    ("GUARD_RETIRED", r"retired as the delivery gate"),
    ("ROSTER_DENIED", r"not in the allowed roster"),
    ("SUBAGENT_TOOLS_OFF", r"write tools and nested subagent tools off|keep write and subagent tools off"),
    ("TEMPLATE_MISMATCH", r"template verbatim"),
    ("WORKSPACE_NOT_INHERIT", r"Workspace must be inherit"),
    ("DUPLICATE_SUBAGENT", r"duplicate subagent"),
    ("INVOKE_LIMIT", r"maximum 6 subagents"),
    ("CAP_REACHED", r"cap reached|limit reached"),
    ("MONKEY_DENIED", r"monkey is forbidden"),
    ("PM_CLEAR_DENIED", r"pm clear app data"),
    ("PM_UNINSTALL_DENIED", r"pm uninstall is forbidden"),
    ("EMULATOR_DENIED", r"emulator"),
    ("DEVICE_TARGETING_REQUIRED", r"--device=<physical-serial>"),
    ("DEVICE_BINDING_REQUIRED", r"-d or -s <physical-serial>"),
    ("SCHEDULE_DENIED", r"schedule/timers"),
    ("POLL_DENIED", r"polling on"),
    ("SHELL_INDIRECTION_DENIED", r"shell indirection|encoded payload"),
    ("ADB_ALLOW", r"ADB command not blocked"),
    ("DEFAULT_ALLOW", r"not blocked by the harness safety hook"),
    ("PAYLOAD_OVERSIZE", r"payload too large"),
    ("PAYLOAD_MALFORMED", r"invalid JSON"),
    ("HOOK_ERROR", r"safety hook error"),
)

_CLASSIFIER_RES = tuple((code, re.compile(pat, re.IGNORECASE)) for code, pat in _CLASSIFIERS)


def classify_reason(text: str) -> str:
    cleaned = fold_confusables(str(text))
    for code, pattern in _CLASSIFIER_RES:
        if pattern.search(cleaned):
            return code
    return "UNKNOWN"


def reason_short(text: str, limit: int = 160) -> str:
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    if cleaned.lower().startswith("denied:"):
        cleaned = cleaned[len("denied:") :].strip()
    head = cleaned.split(". ")[0].strip()
    if len(head) > limit:
        head = head[: limit - 1].rstrip() + "\u2026"
    return head

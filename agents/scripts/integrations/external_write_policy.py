"""Developer-confirmed external writes, independent of the code task plan.

Real app: the developer asked the agent to upload an RTL formatting file to Google Drive. The
upload was refused with "command is not allowed while plan status is AWAITING_DEVELOPER_APPROVAL",
because every external write was tied to the Android code plan. A plain upload the developer asked
for has nothing to do with that plan, so external writes now ask the developer through the host's
own permission prompt instead:

- reads are allowed;
- ordinary writes (upload, create, rename, comment) return ``ask``;
- high-impact writes (delete, trash, share, permission changes, moves, publish, send, opaque batch
  operations, and anything that cannot be classified) return ``force_ask`` so every call is
  confirmed again;
- writes that carry a credential or signing file (``.env``, keystores, ``local.properties``,
  ``google-services.json``, private keys) are denied outright;
- unknown shell network tools (curl, rclone, scp) are not recognized here and stay denied by the
  command guard.

Hosts that cannot show a permission prompt translate ``ask``/``force_ask`` to ``deny`` in their
bridge; nothing here may turn into a silent allow. Zoho keeps its own `update zoho` grant.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable

ALLOW = "allow"
ASK = "ask"
FORCE_ASK = "force_ask"
DENY = "deny"

# Decisions that a host must turn into a developer prompt (or a denial when it has no prompt).
PROMPT_DECISIONS = frozenset({ASK, FORCE_ASK})

# Google Workspace CLIs shipped as agent skills. Each splits its commands into a `readonly` and a
# `mutate` namespace so the namespace alone decides read versus write.
WORKSPACE_CLIS = frozenset({"gdrive", "gdocs", "gsheets", "gslides", "gcalendar"})
WORKSPACE_CLI_SUFFIXES = (".cmd", ".exe", ".bat", ".ps1")

# Readonly subcommands that still write a local file (download/export destinations).
LOCAL_WRITE_READ_TOKENS = frozenset({"download", "export", "extract"})

# Mutate subcommand tokens that are one-way doors or widen access.
HIGH_IMPACT_TOKENS = frozenset({
    "delete", "remove", "trash", "empty", "purge", "destroy", "drop",
    "share", "unshare", "permission", "permissions", "revoke",
    "mv", "move", "publish", "send", "clear", "protect",
    "batch", "raw",
})

INFO_FLAGS = frozenset({"--help", "-h", "--version"})
INFO_SUBCOMMANDS = frozenset({"help", "version"})
INFO_ARGS = INFO_FLAGS | INFO_SUBCOMMANDS

GLOBAL_BOOL_FLAGS = frozenset({
    "--verbose", "-v", "--quiet", "-q", "--debug", "--json", "--no-color",
    "--help", "-h", "--version",
})
LOCAL_OUTPUT_FLAGS = frozenset({
    "--output", "--out", "-o", "--dest", "--destination", "--file", "--path",
})
PROTECTED_DOWNLOAD_PREFIXES = (
    ".agents/", "agents/scripts/", "agents/state/", "agents/project-context/",
    ".harness-setup/", ".android-harness/", ".git/", ".github/workflows/",
    "gradle/wrapper/",
)
PROTECTED_DOWNLOAD_BASENAMES = frozenset({
    "gradlew", "gradlew.bat", "agents.md", "gemini.md", "claude.md",
    ".cursorrules", ".windsurfrules", ".clinerules", "copilot-instructions.md", "hooks.json",
})

SENSITIVE_BASENAMES = frozenset({
    ".env", "local.properties", "key.properties", "keystore.properties", "signing.properties",
    "google-services.json", "googleservice-info.plist", "credentials.json", "client_secret.json",
    ".netrc", ".npmrc", ".pypirc", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
})
SENSITIVE_SUFFIXES = (".jks", ".keystore", ".pem", ".p12", ".pfx", ".key", ".p8", ".mobileprovision")
SENSITIVE_PATTERNS = (
    re.compile(r"^\.env(?:\.[\w.-]+)?$", re.I),
    re.compile(r"^service[-_]?account.*\.json$", re.I),
    re.compile(r"^id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?$", re.I),
)
PATH_VALUE_MAX = 1024


def _basename(value: str) -> str:
    text = str(value or "").strip().strip("\"'")
    if not text:
        return ""
    if "=" in text and text.startswith("-"):
        text = text.split("=", 1)[1]
    name = PureWindowsPath(text).name if "\\" in text else PurePosixPath(text).name
    return name.lower()


def is_sensitive_path(value: str) -> bool:
    """True when the value names a credential, signing or secret file."""
    text = str(value or "")
    if not text or len(text) > PATH_VALUE_MAX or "\n" in text:
        return False
    name = _basename(text)
    if not name:
        return False
    if name in SENSITIVE_BASENAMES or name.endswith(SENSITIVE_SUFFIXES):
        return True
    return any(pattern.match(name) for pattern in SENSITIVE_PATTERNS)


_INLINE_SECRET_VALUE_RE = re.compile(
    r"(?:\b(?:ghp|gho|ghu|ghs|ghr|pat|sec)_[A-Za-z0-9_]{16,}\b"
    r"|\bAIza[0-9A-Za-z_-]{20,}\b"
    r"|\bsk-[A-Za-z0-9_-]{20,}\b"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
    r"|\b(?:storePassword|keyPassword|client_secret|access_token|refresh_token)\s*[:=]\s*[\x27\"]?[A-Za-z0-9_./+-]{8,})",
    re.IGNORECASE,
)
_FLAG_OR_FIELD_PATH_RE = re.compile(
    r"(?:--?[A-Za-z0-9_-]+=|\b(?:file|path|attach(?:ment)?|upload|bundle|keystore|cert|key_file)\s*[:=]\s*|(?<=\s)@|^@)"
    r"([\x27\"]?[^\s\x27\",;{}()<>]+[\x27\"]?)",
    re.IGNORECASE,
)


def sensitive_values(values: Iterable[Any]) -> list[str]:
    """Every string (searched recursively through lists and mappings) that names or leaks a secret."""
    found: list[str] = []

    def visit(item: Any, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(item, str):
            if is_sensitive_path(item):
                found.append(item)
                return
            s_trim = item.strip()
            if s_trim.startswith(("{", "[")):
                for q1, q2 in re.findall(r'"((?:\\.|[^"\\])*)"|\x27((?:\\.|[^\x27\\])*)\x27', s_trim):
                    cand = q1 or q2
                    if cand and is_sensitive_path(cand):
                        found.append(cand)
            for m_flag in _FLAG_OR_FIELD_PATH_RE.finditer(item):
                cand = m_flag.group(1).strip("\"\x27")
                if cand and is_sensitive_path(cand):
                    found.append(cand)
            m_sec = _INLINE_SECRET_VALUE_RE.search(item)
            if m_sec:
                found.append("[REDACTED_SECRET_VALUE]")
        elif isinstance(item, dict):
            for nested in item.values():
                visit(nested, depth + 1)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested, depth + 1)

    for value in values:
        visit(value)
    return found


def _workspace_cli_name(token: str) -> str:
    name = _basename(token)
    for suffix in WORKSPACE_CLI_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name if name in WORKSPACE_CLIS else ""


def _strip_call_operator(segment: str) -> str:
    """PowerShell runs a quoted executable path through `&`; that one leading operator is allowed."""
    stripped = segment.strip()
    if stripped.startswith("&") and not stripped.startswith("&&"):
        return stripped[1:].lstrip()
    return stripped


def workspace_cli_tokens(command: str) -> list[str] | None:
    """Tokens of a single, operator-free Workspace CLI invocation, or None for anything else.

    Chained, piped, redirected or substituted commands are never recognized, so an allowed `readonly`
    call cannot carry a second command along with it.
    """
    from mutation_guard import SHELL_LAUNDERING, _operator_text_any_shell, _split_segments, _tokens

    segments = _split_segments(str(command or ""))
    if not segments or len(segments) != 1:
        return None
    segment = _strip_call_operator(segments[0])
    unquoted = _operator_text_any_shell(segment)
    if unquoted is None or SHELL_LAUNDERING.search(unquoted):
        return None
    tokens = _tokens(segment)
    if not tokens or not _workspace_cli_name(tokens[0]):
        return None
    return tokens


def _extract_workspace_positionals(args: list[str]) -> list[str]:
    """Extract positional tokens while skipping values of leading global options before the namespace."""
    positional: list[str] = []
    idx = 0
    n = len(args)
    while idx < n:
        tok = args[idx]
        if tok.startswith("-"):
            if not positional and "=" not in tok and tok.lower() not in GLOBAL_BOOL_FLAGS:
                if idx + 1 < n and not args[idx + 1].startswith("-"):
                    idx += 2
                    continue
            idx += 1
            continue
        positional.append(tok)
        idx += 1
    return positional


def _has_standalone_info_flag(args: list[str]) -> bool:
    for idx, tok in enumerate(args):
        low = tok.lower()
        if low in INFO_FLAGS:
            if idx > 0 and args[idx - 1].startswith("-") and "=" not in args[idx - 1] and args[idx - 1].lower() not in GLOBAL_BOOL_FLAGS:
                continue
            return True
    return False


def _extract_local_output_targets(args: list[str], positional: list[str]) -> list[str]:
    targets: list[str] = []
    idx = 0
    n = len(args)
    while idx < n:
        tok = args[idx]
        low = tok.lower()
        if "=" in tok and tok.startswith("-"):
            k, v = tok.split("=", 1)
            if k.lower() in LOCAL_OUTPUT_FLAGS and v.strip():
                targets.append(v.strip().strip("\"\x27"))
        elif low in LOCAL_OUTPUT_FLAGS and idx + 1 < n:
            targets.append(args[idx + 1].strip().strip("\"\x27"))
            idx += 2
            continue
        idx += 1
    if len(positional) >= 4:
        targets.extend(t.strip().strip("\"\x27") for t in positional[3:] if t.strip())
    return targets


def _is_protected_download_target(raw_target: str) -> bool:
    import posixpath
    norm = str(raw_target or "").strip().strip("\"\x27").replace("\\", "/")
    if not norm:
        return False
    if is_sensitive_path(norm):
        return True
    collapsed = posixpath.normpath(re.sub(r"^(?:\./)+", "", norm)).replace("\\", "/")
    low = re.sub(r"^(?:\./)+", "", collapsed.lower())
    base = _basename(collapsed)
    if base in PROTECTED_DOWNLOAD_BASENAMES:
        return True
    if low == ".." or low.startswith("../"):
        return True
    for pref in PROTECTED_DOWNLOAD_PREFIXES:
        p_clean = pref.rstrip("/")
        if low == p_clean or low.startswith(pref) or f"/{pref}" in low or low.endswith(f"/{p_clean}"):
            return True
    return False


def classify_workspace_cli(tokens: list[str]) -> tuple[str, str, str]:
    """(decision, reason, reason_code) for a Workspace CLI invocation."""
    cli = _workspace_cli_name(tokens[0])
    args = [token for token in tokens[1:] if token]
    positional = _extract_workspace_positionals(args)
    namespace = positional[0].lower() if positional else ""
    subcommand = positional[1].lower() if len(positional) > 1 else ""
    _resource_nouns = {
        "files", "permissions", "comments", "revisions", "drives", "folders",
        "sheets", "spreadsheets", "documents", "presentations", "events", "calendars",
    }
    if namespace == "readonly" and subcommand == "mutate":
        namespace = "mutate"
        subcommand = positional[2].lower() if len(positional) > 2 else ""
    elif namespace in {"readonly", "mutate"} and subcommand in _resource_nouns and len(positional) > 2:
        subcommand = f"{subcommand}-{positional[2].lower()}"
    label = " ".join(part for part in (cli, namespace, subcommand) if part)

    if not args or all(token.lower() in INFO_ARGS for token in args) or (namespace in INFO_SUBCOMMANDS and not sensitive_values(args)):
        return ALLOW, f"{cli} help/version output is read-only.", "WORKSPACE_CLI_READ"
    if namespace == "auth":
        if subcommand in {"status", ""}:
            return ALLOW, f"{label} only reports the login state.", "WORKSPACE_CLI_READ"
        return ASK, f"{label} changes the {cli} login; confirm it.", "WORKSPACE_CLI_AUTH"

    if namespace == "readonly":
        sub_tokens = set(re.split(r"[-_]+", subcommand))
        if sub_tokens & LOCAL_WRITE_READ_TOKENS:
            for out_tgt in _extract_local_output_targets(args, positional):
                if _is_protected_download_target(out_tgt):
                    return (
                        DENY,
                        f"{label} cannot overwrite protected harness, wrapper, or credential path '{out_tgt}'.",
                        "PROTECTED_PATH",
                    )
        if _has_standalone_info_flag(args):
            return ALLOW, f"{label} help is read-only.", "WORKSPACE_CLI_READ"
        if sub_tokens & LOCAL_WRITE_READ_TOKENS:
            return ASK, f"{label} writes a local file; confirm the destination.", "WORKSPACE_CLI_LOCAL_WRITE"
        return ALLOW, f"{label} is a read-only Workspace command.", "WORKSPACE_CLI_READ"

    if namespace == "mutate":
        secrets = sensitive_values(args)
        if secrets:
            return (
                DENY,
                f"{label} would send a credential or signing file ({', '.join(sorted(set(secrets)))}) outside "
                "this machine. Upload a copy without secrets instead.",
                "SENSITIVE_EXTERNAL_UPLOAD",
            )
        if _has_standalone_info_flag(args):
            return ALLOW, f"{label} help is read-only.", "WORKSPACE_CLI_READ"
        sub_tokens = set(re.split(r"[-_]+", subcommand)) if subcommand else set()
        if not subcommand or sub_tokens & HIGH_IMPACT_TOKENS:
            return (
                FORCE_ASK,
                f"{label} is a high-impact external change (delete, share, move or bulk edit); confirm this call.",
                "EXTERNAL_HIGH_IMPACT_CONFIRM",
            )
        return ASK, f"{label} changes external {cli} data; confirm it.", "EXTERNAL_WRITE_CONFIRM"

    return (
        FORCE_ASK,
        f"{label or cli} is not a recognized readonly/mutate {cli} command; confirm this call.",
        "EXTERNAL_HIGH_IMPACT_CONFIRM",
    )


def generic_mcp_prompt(tool_class: str, server: str, tool_name: str, scope_reason: str) -> tuple[str, str]:
    """The prompt decision and reason for a generic MCP write the approved plan does not cover."""
    hint = f" ({scope_reason})" if scope_reason else ""
    if tool_class == "WRITE":
        return ASK, f"External MCP write '{tool_name}' on '{server}' needs your confirmation{hint}."
    return FORCE_ASK, f"High-impact or unclassified MCP operation '{tool_name}' on '{server}' needs your confirmation for this call{hint}."

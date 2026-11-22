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

import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

ALLOW = "allow"
ASK = "ask"
FORCE_ASK = "force_ask"
DENY = "deny"

# Decisions that a host must turn into a developer prompt (or a denial when it has no prompt).
PROMPT_DECISIONS = frozenset({ASK, FORCE_ASK})

# Google Workspace CLIs shipped as agent skills. Each splits its commands into a `readonly` and a
# `mutate` namespace so the namespace alone decides read versus write.
WORKSPACE_CLIS = frozenset({"gdrive", "gdocs", "gsheets", "gslides", "gcalendar", "gmail"})
WORKSPACE_CLI_SUFFIXES = (".cmd", ".exe", ".bat", ".ps1")

# Known first-class external service CLIs where read-only verbs are allowed and writes prompt via ask/force_ask.
KNOWN_EXTERNAL_SERVICE_CLIS = frozenset({
    "twg", "gh", "firebase", "gcloud", "postman", "wrangler",
    "supabase", "vercel", "netlify", "linear", "clickup",
})

# Built-in read/harness/VCS/Android executables already governed by mutation_guard / command_policy.
_GUARDED_BUILTIN_OR_HARNESS_EXES = frozenset({
    "git", "rg", "grep", "head", "tail", "ls", "dir", "pwd", "wc", "cat",
    "test", "[", "xcrun", "xcodebuild", "swift", "jar", "javap", "tar",
    "android-harness", "adb", "fastboot", "android", "emulator", "sdkmanager", "avdmanager",
    "gradlew", "gradle", "get-childitem", "gci", "get-content", "gc",
    "select-string", "sls", "test-path", "get-location", "get-item", "gi",
    "type", "more", "less", "nl", "findstr",
})

# Executables that MUST NEVER be routed to allow or `ask` via external CLI policy (always fall through to DENY).
HARD_DENIED_SHELL_EXES = frozenset({
    # Shells, interpreters, evaluators & script runners
    "sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh",
    "cmd", "powershell", "pwsh", "python", "python3", "py", "node", "deno", "bun",
    "perl", "ruby", "php", "lua", "tclsh", "awk", "gawk", "sed", "jq",
    "xargs", "env", "command", "exec", "eval", "source", "export", "set", "unset", "alias",
    "sudo", "su", "runas", "doas", "start", "start-process", "saps", "nohup",
    "wscript", "cscript", "mshta", "rundll32", "regsvr32", "schtasks", "at",
    "reg", "regedit", "sc", "net", "netsh", "icacls", "takeown", "attrib",
    "chmod", "chown", "chgrp", "ln", "mklink", "echo", "printf", "base64", "certutil", "bitsadmin",
    # Raw network & transfer tools
    "curl", "wget", "rclone", "scp", "sftp", "rsync", "ssh", "ftp", "tftp",
    "nc", "ncat", "netcat", "socat", "telnet", "invoke-webrequest", "iwr", "invoke-restmethod", "irm",
    # Filesystem mutators
    "rm", "del", "erase", "rmdir", "rd", "mv", "move", "ren", "rename", "cp", "copy", "xcopy", "robocopy",
    "touch", "mkdir", "md", "tee", "truncate", "dd", "shred", "unlink",
    "remove-item", "ri", "set-content", "add-content", "out-file", "new-item",
    "move-item", "copy-item", "rename-item", "clear-content",
    # Local build / package / VCS / harness-sensitive tools
    "agy", "antigravity", "keytool", "apksigner", "jarsigner", "bundletool",
    "npm", "npx", "yarn", "pnpm", "pip", "pip3", "uv", "poetry", "pipx",
    "cargo", "rustc", "go", "mvn", "gradle", "gradlew", "ant", "make", "cmake", "ninja", "bazel",
    "pod", "gem", "brew", "winget", "choco", "scoop", "apt", "apt-get", "dnf", "yum", "pacman",
    "docker", "podman", "kubectl", "helm", "terraform", "tofu", "pulumi", "find",
})

_NON_PLUGIN_SCRIPT_SUFFIXES = frozenset({".py", ".sh", ".ps1", ".vbs", ".js", ".mjs", ".cjs"})

_TWG_GLOBAL_VALUE_FLAGS = frozenset({
    "-u", "--user", "-s", "--site", "-p", "--profile", "-o", "--output",
    "--api-version", "--timeout-ms", "--agent-fields", "--select", "--output-shape", "--mode",
})
_TWG_FORMAT_VALUES = frozenset({"text", "json", "jsonl", "yaml", "table", "markdown", "csv"})
_TWG_READONLY_TOP = frozenset({
    "collaborators", "user", "user-search", "people", "resolve", "recently-viewed",
    "org-tree", "pr-tree", "pull-requests-tree", "workitem-tree", "issue-tree",
    "work-tree", "status-rollup", "focus-areas-tree", "context", "responsibility",
    "ownership", "subgraph", "search-code", "rovo", "insights", "talent", "teams",
    "goals", "projects", "focus-areas", "csm", "notifications", "commits",
    "deployments", "docs", "videos", "meetings", "spaces", "pull-requests", "prs", "work",
})
_TWG_INFO_COMMANDS = frozenset({"help", "help-map", "version", "doctor", "whoami", "access", "capabilities", "env"})
_EXTERNAL_READ_VERBS = frozenset({
    "get", "list", "ls", "search", "query", "find", "show", "view", "read", "describe",
    "inspect", "status", "count", "check", "checks", "diff", "logs", "info", "whoami",
    "doctor", "help", "version", "discover-skills", "export-schema",
})
_EXTERNAL_WRITE_VERBS = frozenset({
    "create", "add", "update", "edit", "set", "put", "patch", "transition", "comment",
    "reply", "link", "unlink", "assign", "unassign", "label", "unlabel", "archive",
    "close", "reopen", "merge", "approve", "reject", "decline", "cancel", "raise",
    "start", "complete", "trigger", "run", "login", "setup", "upgrade", "consent",
    "upkeep", "install", "restore", "upload", "post", "import", "sync", "write",
})
_EXTERNAL_HIGH_IMPACT_VERBS = frozenset({
    "delete", "remove", "trash", "empty", "purge", "destroy", "drop",
    "share", "unshare", "permission", "permissions", "revoke",
    "mv", "move", "publish", "send", "clear", "protect",
    "batch", "raw", "logout", "uninstall", "deploy", "reset", "wipe", "force-push",
})
_PLUGIN_CLI_CACHE: dict[str, Any] = {"root": None, "names": frozenset()}

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


def _installed_plugin_cli_names() -> frozenset[str]:
    """Best-effort discovery of external CLIs shipped by installed host plugins (cached read-only)."""
    plugins_root = Path.home() / ".gemini" / "config" / "plugins"
    key = str(plugins_root)
    if _PLUGIN_CLI_CACHE["root"] == key:
        return _PLUGIN_CLI_CACHE["names"]
    found: set[str] = set()
    try:
        if plugins_root.is_dir():
            for plugin_dir in plugins_root.iterdir():
                if not plugin_dir.is_dir():
                    continue
                for pattern in ("skills/*/scripts/*", "bin/*"):
                    for cand in plugin_dir.glob(pattern):
                        if not cand.is_file():
                            continue
                        stem = cand.stem.lower()
                        if (
                            re.fullmatch(r"[a-z][a-z0-9._-]{1,63}", stem)
                            and stem not in HARD_DENIED_SHELL_EXES
                            and stem not in _GUARDED_BUILTIN_OR_HARNESS_EXES
                        ):
                            found.add(stem)
    except OSError:
        pass
    frozen = frozenset(found)
    _PLUGIN_CLI_CACHE["root"] = key
    _PLUGIN_CLI_CACHE["names"] = frozen
    return frozen


def _cli_stem(token: str) -> str:
    name = _basename(token)
    for suffix in WORKSPACE_CLI_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def _workspace_cli_name(token: str) -> str:
    name = _cli_stem(token)
    return name if name in WORKSPACE_CLIS else ""


def _strip_call_operator(segment: str) -> str:
    """PowerShell runs a quoted executable path through `&`; that one leading operator is allowed."""
    stripped = segment.strip()
    if stripped.startswith("&") and not stripped.startswith("&&"):
        return stripped[1:].lstrip()
    return stripped


def external_cli_tokens(command: str, repo: Path | None = None) -> tuple[str, list[str]] | None:
    """Classify a single, operator-free external/plugin CLI call into `(kind, tokens)`.

    Kinds returned: `"workspace"`, `"twg"`, `"service"`, `"unknown_external"`, or `None` when the
    command contains shell operators, invokes a repo-local script/binary, or hits any built-in /
    hard-denied executable.
    """
    from mutation_guard import SHELL_LAUNDERING, _operator_text_any_shell, _split_segments, _tokens

    segments = _split_segments(str(command or ""))
    if not segments or len(segments) != 1:
        return None
    segment = _strip_call_operator(segments[0])
    unquoted = _operator_text_any_shell(segment)
    if unquoted is None or SHELL_LAUNDERING.search(unquoted) or re.search(r"[;&\n(){}]", unquoted):
        return None
    tokens = _tokens(segment)
    if not tokens:
        return None
    raw_exe = str(tokens[0]).strip().strip("\"'")
    if not raw_exe or raw_exe.startswith("."):
        return None
    if "/" in raw_exe or "\\" in raw_exe:
        exe_path = Path(raw_exe).expanduser()
        if not exe_path.is_absolute():
            return None
        if repo is not None:
            try:
                if exe_path.resolve().is_relative_to(Path(repo).resolve()):
                    return None
            except OSError:
                return None

    stem = _cli_stem(raw_exe)
    if not stem or stem in HARD_DENIED_SHELL_EXES or stem in _GUARDED_BUILTIN_OR_HARNESS_EXES:
        return None
    if stem in WORKSPACE_CLIS:
        return "workspace", tokens
    if stem == "twg":
        return "twg", tokens
    if stem in KNOWN_EXTERNAL_SERVICE_CLIS or stem in _installed_plugin_cli_names():
        return "service", tokens
    raw_low = raw_exe.lower()
    if any(raw_low.endswith(ext) for ext in _NON_PLUGIN_SCRIPT_SUFFIXES):
        return None
    if re.fullmatch(r"[a-z][a-z0-9._-]{1,63}", stem):
        return "unknown_external", tokens
    return None


def workspace_cli_tokens(command: str) -> list[str] | None:
    """Tokens of a single, operator-free Workspace CLI invocation, or None for anything else."""
    classified = external_cli_tokens(command)
    if classified and classified[0] == "workspace":
        return classified[1]
    return None


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
        "messages", "threads", "drafts", "labels",
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


def _extract_twg_positionals(args: list[str]) -> list[str]:
    positional: list[str] = []
    idx = 0
    n = len(args)
    while idx < n:
        tok = args[idx]
        low = tok.lower()
        if tok == "--":
            positional.extend(args[idx + 1:])
            break
        if tok.startswith("-"):
            if "=" not in tok and low in _TWG_GLOBAL_VALUE_FLAGS and idx + 1 < n and not args[idx + 1].startswith("-"):
                idx += 2
                continue
            if "=" not in tok and low == "--output-summary" and idx + 1 < n and args[idx + 1].lower() in {"none", "stats", "auto", "inline"}:
                idx += 2
                continue
            idx += 1
            continue
        positional.append(tok)
        idx += 1
    return positional


def _check_external_protected_outputs(args: list[str], *, allow_format_values: bool = False) -> str:
    """Return protected target string if output/download flags aim at sensitive or repo-protected files."""
    idx = 0
    n = len(args)
    while idx < n:
        tok = args[idx]
        low = tok.lower()
        val = ""
        is_output_flag = False
        if "=" in tok and tok.startswith("-"):
            k, v = tok.split("=", 1)
            k_low = k.lower()
            if k_low in LOCAL_OUTPUT_FLAGS or k_low == "--output-file":
                is_output_flag = True
                val = v.strip().strip("\"\x27")
        elif low in LOCAL_OUTPUT_FLAGS or low == "--output-file":
            if idx + 1 < n:
                is_output_flag = True
                val = args[idx + 1].strip().strip("\"\x27")
                idx += 1
        if is_output_flag and val:
            if allow_format_values and low in {"-o", "--output"} and val.lower() in _TWG_FORMAT_VALUES:
                pass
            elif _is_protected_download_target(val):
                return val
        idx += 1
    return ""


def _verb_parts(tokens: list[str]) -> list[str]:
    parts: list[str] = []
    for tok in tokens[:3]:
        if any(ch in tok for ch in (" ", "\t", "=", "~", "<", ">")):
            continue
        low = tok.lower()
        parts.append(low)
        parts.extend(p for p in re.split(r"[-_]+", low) if p and p != low)
    return parts


def classify_external_cli(kind: str, tokens: list[str], *, plan_status: str = "") -> tuple[str, str, str] | None:
    """Return `(decision, reason, reason_code)` for an external CLI call, or `None` to fall back to guard."""
    if kind == "workspace":
        return classify_workspace_cli(tokens)

    cli = _cli_stem(tokens[0])
    args = [t for t in tokens[1:] if t]

    if kind == "unknown_external":
        if str(plan_status or "").upper() == "IMPLEMENTING":
            return None
        secrets = sensitive_values(args)
        if secrets:
            return (
                DENY,
                f"{cli} would reference a credential or signing file ({', '.join(sorted(set(secrets)))}).",
                "SENSITIVE_EXTERNAL_UPLOAD",
            )
        return (
            ASK,
            f"External CLI '{cli}' is not in the built-in read-only allowlist; confirm this command.",
            "EXTERNAL_CLI_CONFIRM",
        )

    secrets = sensitive_values(args)
    if secrets:
        return (
            DENY,
            f"{cli} would send a credential or signing file ({', '.join(sorted(set(secrets)))}) outside "
            "this machine. Remove secrets before proceeding.",
            "SENSITIVE_EXTERNAL_UPLOAD",
        )
    prot = _check_external_protected_outputs(args, allow_format_values=(kind == "twg"))
    if prot:
        return (
            DENY,
            f"{cli} cannot write to protected harness, wrapper, or credential path '{prot}'.",
            "PROTECTED_PATH",
        )

    if kind == "twg":
        if not args or all(tok.lower() in INFO_FLAGS or tok.lower() == "-v" for tok in args):
            return ALLOW, "twg help/version output is read-only.", "EXTERNAL_CLI_READ"
        positional = _extract_twg_positionals(args)
        if not positional:
            return ALLOW, "twg diagnostic invocation is read-only.", "EXTERNAL_CLI_READ"
        top = positional[0].lower()
        if top in _TWG_INFO_COMMANDS or _has_standalone_info_flag(args):
            return ALLOW, f"twg {top} is a read-only diagnostic/help command.", "EXTERNAL_CLI_READ"
        verbs = _verb_parts(positional)
        if any(v in _EXTERNAL_HIGH_IMPACT_VERBS for v in verbs):
            return (
                FORCE_ASK,
                f"twg {' '.join(positional[:2])} is a high-impact external change; confirm this call.",
                "EXTERNAL_HIGH_IMPACT_CONFIRM",
            )
        if any(v in _EXTERNAL_WRITE_VERBS for v in verbs):
            return (
                ASK,
                f"twg {' '.join(positional[:2])} modifies or configures external Atlassian/plugin data; confirm it.",
                "EXTERNAL_WRITE_CONFIRM",
            )
        if top in _TWG_READONLY_TOP or any(v in _EXTERNAL_READ_VERBS for v in verbs):
            return ALLOW, f"twg {' '.join(positional[:2])} is a read-only Atlassian query.", "EXTERNAL_CLI_READ"
        return (
            FORCE_ASK,
            f"twg {' '.join(positional[:2])} is not recognized as read-only; confirm this external call.",
            "EXTERNAL_HIGH_IMPACT_CONFIRM",
        )

    # `kind == "service"` (known service CLIs like `gh`, `firebase`, `gcloud`, `postman`, or installed plugin CLIs)
    if not args or all(tok.lower() in INFO_FLAGS for tok in args) or _has_standalone_info_flag(args):
        return ALLOW, f"{cli} help/version output is read-only.", "EXTERNAL_CLI_READ"
    positional = _extract_workspace_positionals(args)
    if not positional:
        return ALLOW, f"{cli} diagnostic output is read-only.", "EXTERNAL_CLI_READ"
    if positional[0].lower() in {"help", "version", "doctor", "whoami", "status"}:
        return ALLOW, f"{cli} {positional[0]} is read-only.", "EXTERNAL_CLI_READ"
    verbs = _verb_parts(positional)
    # Non-GET HTTP methods in `gh api` / similar generic service callers must always prompt.
    non_get_method = False
    for idx, tok in enumerate(args):
        low = tok.lower()
        if low in {"-x", "--method"} and idx + 1 < len(args) and args[idx + 1].upper() != "GET":
            non_get_method = True
        elif low.startswith("--method=") and low.split("=", 1)[1].upper() != "GET":
            non_get_method = True
    if any(v in _EXTERNAL_HIGH_IMPACT_VERBS for v in verbs):
        return (
            FORCE_ASK,
            f"{cli} {' '.join(positional[:2])} is a high-impact external change; confirm this call.",
            "EXTERNAL_HIGH_IMPACT_CONFIRM",
        )
    if non_get_method or any(v in _EXTERNAL_WRITE_VERBS for v in verbs):
        return (
            ASK,
            f"{cli} {' '.join(positional[:2])} modifies external state or configuration; confirm it.",
            "EXTERNAL_WRITE_CONFIRM",
        )
    if any(v in _EXTERNAL_READ_VERBS for v in verbs):
        return ALLOW, f"{cli} {' '.join(positional[:2])} is a read-only query.", "EXTERNAL_CLI_READ"
    return (
        ASK,
        f"External service CLI '{cli} {' '.join(positional[:2])}' needs confirmation.",
        "EXTERNAL_CLI_CONFIRM",
    )


def generic_mcp_prompt(tool_class: str, server: str, tool_name: str, scope_reason: str) -> tuple[str, str]:
    """The prompt decision and reason for a generic MCP write the approved plan does not cover."""
    hint = f" ({scope_reason})" if scope_reason else ""
    if tool_class == "WRITE":
        return ASK, f"External MCP write '{tool_name}' on '{server}' needs your confirmation{hint}."
    return FORCE_ASK, f"High-impact or unclassified MCP operation '{tool_name}' on '{server}' needs your confirmation for this call{hint}."

"""Authoritative owner of Google Antigravity runtime-root and transcript resolution."""
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from _vnext_common import ValidationError, canonical_sha256


def candidate_runtime_roots() -> tuple[Path, ...]:
    """Returns candidate runtime roots in precedence order.
    
    1. explicit ANTIGRAVITY_APP_DATA environment variable when present;
    2. ~/.gemini/antigravity;
    3. ~/.gemini/antigravity-cli;
    4. ~/.gemini/antigravity-ide.
    """
    roots: list[Path] = []
    override = os.environ.get("ANTIGRAVITY_APP_DATA")
    if override and override.strip():
        try:
            resolved_override = Path(override.strip()).expanduser().resolve()
            roots.append(resolved_override)
        except (OSError, ValueError, RuntimeError):
            pass

    home = Path.home().resolve()
    for suffix in ("antigravity", "antigravity-cli", "antigravity-ide", "jetski"):
        standard = (home / ".gemini" / suffix).resolve()
        if standard not in roots:
            roots.append(standard)

    return tuple(roots)


def candidate_brain_roots() -> tuple[Path, ...]:
    """Returns candidate brain roots corresponding to candidate runtime roots."""
    return tuple((root / "brain").resolve() for root in candidate_runtime_roots())


def is_trusted_antigravity_path(path: Path | str) -> bool:
    """Checks whether the given path resolves within any trusted brain root."""
    try:
        resolved = Path(path).expanduser().resolve()
        brain_roots = candidate_brain_roots()
        for brain_root in brain_roots:
            if resolved == brain_root or brain_root in resolved.parents:
                return True
        return False
    except Exception:
        return False


_JETSKI_HIERARCHICAL_ID_RE = re.compile(
    r"^v\d+/[A-Za-z0-9_-]{1,64}/(?:jetski[A-Za-z0-9_-]*|remote_agents[A-Za-z0-9_-]*)/[A-Za-z0-9_-]{4,128}$"
)


def _is_invalid_conversation_id(conversation_id: str) -> bool:
    if not conversation_id or not isinstance(conversation_id, str):
        return True
    if "\0" in conversation_id or any(ord(ch) < 32 for ch in conversation_id):
        return True
    cid = conversation_id.strip().strip("'\"")
    if not cid or len(cid) > 255:
        return True
    if "\\" in cid or ".." in cid or ":" in cid or cid.startswith("file:"):
        return True
    if "/" in cid:
        if not _JETSKI_HIERARCHICAL_ID_RE.fullmatch(cid):
            return True
        if any(seg in {"", ".", ".."} for seg in cid.split("/")):
            return True
    try:
        if Path(cid).is_absolute():
            return True
    except Exception:
        return True
    return False


def iter_recent_brain_conversations(
    brain_root: Path,
    *,
    limit: int = 32,
    max_depth: int = 5,
) -> list[tuple[str, Path]]:
    """Return `(conversation_id, directory)` sorted newest-first across flat and Jetski brain trees."""
    if not brain_root.is_dir():
        return []
    marker_names = ("transcript.jsonl", "transcript_full.jsonl", "task.md", "implementation_plan.md", "walkthrough.md")
    discovered: dict[str, tuple[int, Path]] = {}

    def _mtime_ns(p: Path) -> int:
        try:
            return int(p.stat().st_mtime_ns)
        except OSError:
            return 0

    def _scan(cur: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            children = [c for c in cur.iterdir() if c.is_dir() and not c.is_symlink()]
        except OSError:
            return
        for child in children:
            try:
                rel_id = child.relative_to(brain_root).as_posix()
            except ValueError:
                continue
            has_markers = (child / ".system_generated").is_dir() or any((child / m).is_file() for m in marker_names)
            if depth == 1 and not rel_id.startswith("v"):
                discovered[rel_id] = (_mtime_ns(child), child)
                continue
            if has_markers and not _is_invalid_conversation_id(rel_id):
                discovered[rel_id] = (_mtime_ns(child), child)
                continue
            if depth == 1 and not has_markers and not re.fullmatch(r"v\d+", rel_id) and not _is_invalid_conversation_id(rel_id):
                discovered[rel_id] = (_mtime_ns(child), child)
            if depth < max_depth and (rel_id.startswith("v") or not has_markers):
                _scan(child, depth + 1)

    _scan(brain_root, 1)
    ranked = sorted(discovered.items(), key=lambda kv: kv[1][0], reverse=True)
    return [(cid, info[1]) for cid, info in ranked[: max(1, limit)]]


ACCEPTED_SYSTEM_SOURCES = frozenset({"SYSTEM", "SYSTEM_SDK"})


def prefer_full_transcript(path: Path | None) -> Path | None:
    """Upgrade `transcript.jsonl` to `transcript_full.jsonl` when present for untruncated content.

    Antigravity truncates `content` fields >4 KB inside `transcript.jsonl` (`truncated_fields=['content']`),
    which cuts off long dispatch briefs and `HARNESS_REVIEW_RESULT_V2` blocks. `resolve_transcript()` keeps
    returning `transcript.jsonl` as the canonical identity path while content readers call this helper.
    """
    if path is None:
        return None
    if path.name == "transcript.jsonl":
        full_cand = path.with_name("transcript_full.jsonl")
        try:
            if full_cand.is_file() and not full_cand.is_symlink():
                return full_cand
        except OSError:
            pass
    return path


def resolve_transcript(conversation_id: str) -> Path | None:
    """Resolves a trusted subagent transcript for conversation_id.
    
    Rejects path traversal, slashes, colons, absolute paths, and URIs.
    Checks candidate brain roots in precedence order for:
      - <root>/brain/<id>/.system_generated/logs/transcript.jsonl
      - <root>/brain/<id>/transcript.jsonl
    """
    if _is_invalid_conversation_id(conversation_id):
        return None

    clean_id = conversation_id.strip().strip("'\"")
    brain_roots = candidate_brain_roots()

    for brain_root in brain_roots:
        candidates = [
            brain_root / clean_id / ".system_generated" / "logs" / "transcript.jsonl",
            brain_root / clean_id / ".system_generated" / "logs" / "transcript_full.jsonl",
            brain_root / clean_id / "transcript.jsonl",
            brain_root / clean_id / "transcript_full.jsonl",
        ]
        for cand in candidates:
            try:
                resolved = cand.resolve()
                if brain_root in resolved.parents and resolved.is_file():
                    return resolved
            except Exception:
                continue

    return None


def _protobuf_fields(data: bytes) -> dict[int, list]:
    """Read only protobuf wire types; never deserialize or execute host payloads."""
    fields: dict[int, list] = {}
    offset = 0

    def integer() -> int:
        nonlocal offset
        value = 0
        for shift in range(0, 70, 7):
            if offset >= len(data):
                raise ValueError("truncated native metadata")
            byte = data[offset]
            offset += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError("invalid native metadata varint")

    while offset < len(data):
        tag = integer()
        field, wire = tag >> 3, tag & 7
        if not field:
            raise ValueError("invalid native metadata field")
        if wire == 0:
            value = integer()
        elif wire in (1, 2, 5):
            length = integer() if wire == 2 else (8 if wire == 1 else 4)
            if length > len(data) - offset:
                raise ValueError("truncated native metadata field")
            value = data[offset:offset + length]
            offset += length
        else:
            raise ValueError("unsupported native metadata wire type")
        fields.setdefault(field, []).append(value)
    return fields


def _native_model_field(blob: bytes, path: tuple[int, ...]) -> str | None:
    value = blob
    for field in path:
        values = _protobuf_fields(value).get(field, [])
        if not values:
            return None
        if len(values) != 1 or not isinstance(values[0], bytes):
            raise ValueError("ambiguous native model metadata")
        value = values[0]
    model = value.decode("ascii").strip()
    if model.startswith("models/"):
        model = model[7:]
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{1,127}", model):
        raise ValueError("invalid native model identifier")
    return model


def native_model_metadata(transcript: Path) -> dict:
    """Read observed Antigravity model fields from this execution's native DB.

    Known field paths are intentionally explicit. An unknown schema produces no
    model proof; prompt text and reviewer claims are never searched for models.
    """
    resolved = Path(transcript).resolve()
    root = next((p for p in candidate_brain_roots() if p in resolved.parents), None)
    if root is None:
        raise ValidationError("REVIEW_MODEL_UNVERIFIED: transcript is outside trusted Antigravity storage")
    parts = resolved.relative_to(root).parts
    if ".system_generated" in parts:
        conv_parts = parts[: parts.index(".system_generated")]
    elif parts and parts[-1] in {"transcript.jsonl", "transcript_full.jsonl"}:
        conv_parts = parts[:-1]
    else:
        conv_parts = parts[:1]
    execution_id = "/".join(conv_parts) if conv_parts else (parts[0] if parts else "")
    canonical = resolve_transcript(execution_id)
    if canonical is None or canonical.resolve() != resolved:
        raise ValidationError("REVIEW_MODEL_UNVERIFIED: model proof requires the canonical execution transcript")
    db_candidates = [root.parent / "conversations" / f"{execution_id}.db"]
    if "/" in execution_id:
        db_candidates.append(root.parent / "conversations" / f"{execution_id.rsplit('/', 1)[-1]}.db")
    database: Path | None = None
    for db_cand in db_candidates:
        try:
            if not db_cand.is_symlink() and db_cand.resolve().is_relative_to(root.parent.resolve()) and db_cand.is_file():
                database = db_cand
                break
        except OSError:
            continue
    if database is None:
        return {}
    def _fetch_rows(db_path: Path) -> tuple[list, list]:
        base_uri = db_path.resolve().as_uri()
        try:
            with closing(sqlite3.connect(base_uri + "?mode=ro", uri=True, timeout=1)) as connection:
                cfg = connection.execute("SELECT data FROM executor_metadata WHERE idx = 0").fetchall()
                gen = connection.execute("SELECT data FROM gen_metadata ORDER BY idx LIMIT 4097").fetchall()
                return cfg, gen
        except sqlite3.OperationalError:
            # Terminal Sandbox or read-only parent directories cannot create WAL -shm files under ?mode=ro.
            try:
                with closing(sqlite3.connect(base_uri + "?mode=ro&immutable=1", uri=True, timeout=1)) as connection:
                    cfg = connection.execute("SELECT data FROM executor_metadata WHERE idx = 0").fetchall()
                    gen = connection.execute("SELECT data FROM gen_metadata ORDER BY idx LIMIT 4097").fetchall()
                    return cfg, gen
            except sqlite3.OperationalError:
                if db_path.stat().st_size > 32 * 1024 * 1024:
                    raise
                import tempfile
                with tempfile.TemporaryDirectory(prefix="ag_meta_ro_") as tmp_dir:
                    snap_db = Path(tmp_dir) / "conv.db"
                    snap_db.write_bytes(db_path.read_bytes())
                    for suffix in ("-wal", "-shm"):
                        side = db_path.with_name(db_path.name + suffix)
                        if side.is_file() and not side.is_symlink() and side.stat().st_size <= 32 * 1024 * 1024:
                            (Path(tmp_dir) / f"conv.db{suffix}").write_bytes(side.read_bytes())
                    with closing(sqlite3.connect(snap_db.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as connection:
                        cfg = connection.execute("SELECT data FROM executor_metadata WHERE idx = 0").fetchall()
                        gen = connection.execute("SELECT data FROM gen_metadata ORDER BY idx LIMIT 4097").fetchall()
                        return cfg, gen

    try:
        configured_rows, generation_rows = _fetch_rows(database)
        if len(generation_rows) > 4096 or any(not isinstance(r[0], bytes) or len(r[0]) > 32 * 1024 * 1024 for r in configured_rows + generation_rows):
            raise ValueError("native metadata exceeds inspection limits")
        configured = {_native_model_field(r[0], (10, 1, 28)) for r in configured_rows} - {None}
        observed = {_native_model_field(r[0], (1, 19)) for r in generation_rows} - {None}
        if len(configured) != 1 or not observed:
            return {}
        result = {"execution_id": execution_id, "host_configured_model": next(iter(configured)),
                  "host_reported_models": sorted(observed), "native_metadata_source": "antigravity_execution_database"}
        result["native_metadata_sha256"] = canonical_sha256(result)
        return result
    except (sqlite3.Error, OSError, ValueError, UnicodeError) as exc:
        raise ValidationError(f"REVIEW_MODEL_UNVERIFIED: native model metadata is unavailable or unsupported: {type(exc).__name__}") from exc


# ---------------------------------------------------------------------------
# Antigravity Runtime Hazard Detectors (#198819 Remote Quota Leak, #198689 Log Bloat, #199301 Windows stdio MCP)
# ---------------------------------------------------------------------------
LANGUAGE_SERVER_LOG_WARN_BYTES = 500 * 1024 * 1024  # 500 MB
LANGUAGE_SERVER_VCS_LOOP_MIN_BYTES = 10 * 1024 * 1024  # 10 MB


def detect_antigravity_remote_mode(env: dict[str, str] | None = None) -> tuple[bool, list[str]]:
    """Detect whether Antigravity is running in Remote Mode (`agy --remote-agent`, Web, or Remote Control).

    In Remote Mode with a `Gemini 4 Argon` parent session, Antigravity ignores `Model: "flash"`
    on `invoke_subagent` and bills all subagent tokens directly to the `Argon` weekly quota (#198819).
    """
    environ = env if env is not None else os.environ
    signals: list[str] = []
    truthy = {"1", "true", "yes", "on", "remote"}
    for key in (
        "ANTIGRAVITY_REMOTE_AGENT",
        "AGY_REMOTE_AGENT",
        "ANTIGRAVITY_REMOTE",
        "AGY_REMOTE",
        "ANTIGRAVITY_REMOTE_CONTROL",
        "HARNESS_SIMULATE_REMOTE_MODE",
    ):
        val = str(environ.get(key) or "").strip().lower()
        if val in truthy:
            signals.append(f"{key}={environ.get(key)}")
    for mode_key in ("ANTIGRAVITY_MODE", "AGY_MODE", "ANTIGRAVITY_SESSION_MODE"):
        val = str(environ.get(mode_key) or "").strip().lower()
        if val in {"remote", "remote-agent", "remote_agent", "web"}:
            signals.append(f"{mode_key}={environ.get(mode_key)}")
    for args_key in ("AGY_ARGS", "ANTIGRAVITY_CLI_ARGS", "ANTIGRAVITY_LAUNCH_ARGS"):
        raw_args = str(environ.get(args_key) or "").strip()
        if "--remote-agent" in raw_args or re.search(r"(?:^|\s)--remote(?:\s|$)", raw_args):
            signals.append(f"{args_key} contains --remote-agent")
    return (bool(signals), signals)


def is_jetski_cloud_environment(env: dict[str, str] | None = None) -> bool:
    """Return True when running natively inside an Antigravity Cloud / Jetski container."""
    environ = env if env is not None else os.environ
    mode_vals = {
        str(environ.get(k) or "").strip().lower()
        for k in ("ANTIGRAVITY_MODE", "AGY_MODE", "ANTIGRAVITY_SESSION_MODE")
    }
    if mode_vals & {"jetski", "cloud"}:
        return True
    if str(environ.get("JETSKI_AGENT") or environ.get("ANTIGRAVITY_CLOUD") or "").strip().lower() in {"1", "true", "yes"}:
        return True
    try:
        home = Path.home()
        if (home / ".gemini" / "jetski").is_dir() and not (home / ".gemini" / "antigravity-ide").is_dir():
            return True
    except OSError:
        pass
    return False


def remote_subagents_explicitly_allowed(env: dict[str, str] | None = None) -> bool:
    environ = env if env is not None else os.environ
    return str(environ.get("HARNESS_ALLOW_REMOTE_SUBAGENTS") or "").strip().lower() in {"1", "true", "yes"}


def inspect_language_server_logs(env: dict[str, str] | None = None) -> dict[str, object]:
    """Inspect Antigravity `language_server.log` files in O(1) time for #198689 WatchVersionControlState bloat."""
    environ = env if env is not None else os.environ
    candidates: list[Path] = []

    def _add(cand: Path) -> None:
        try:
            resolved = cand.expanduser().resolve()
            if resolved not in candidates:
                candidates.append(resolved)
        except (OSError, RuntimeError, ValueError):
            pass

    log_override = str(environ.get("ANTIGRAVITY_LOG_DIR") or "").strip()
    if log_override:
        _add(Path(log_override) / "language_server.log")

    app_data_override = str(environ.get("ANTIGRAVITY_APP_DATA") or "").strip()
    if app_data_override:
        _add(Path(app_data_override) / "logs" / "language_server.log")
        _add(Path(app_data_override) / "language_server.log")

    for win_key in ("LOCALAPPDATA", "APPDATA"):
        win_base = str(environ.get(win_key) or "").strip()
        if win_base:
            _add(Path(win_base) / "Antigravity" / "logs" / "language_server.log")

    home = Path.home()
    _add(home / "Library" / "Logs" / "Antigravity" / "language_server.log")
    _add(home / ".gemini" / "antigravity" / "logs" / "language_server.log")
    _add(home / ".gemini" / "jetski" / "logs" / "language_server.log")
    _add(home / ".antigravity" / "logs" / "language_server.log")
    _add(home / ".config" / "Antigravity" / "logs" / "language_server.log")

    checked: list[str] = []
    bloated: list[dict[str, object]] = []
    for log_path in candidates:
        try:
            if not log_path.is_file() or log_path.is_symlink():
                continue
            size_bytes = log_path.stat().st_size
            checked.append(str(log_path))
            tail_text = ""
            if size_bytes > 0:
                with log_path.open("rb") as fh:
                    fh.seek(max(0, size_bytes - 16384))
                    tail_text = fh.read(16384).decode("utf-8", errors="replace")
            vcs_hits = tail_text.count("WatchVersionControlState")
            is_spin_loop = vcs_hits >= 20 or (size_bytes >= LANGUAGE_SERVER_VCS_LOOP_MIN_BYTES and vcs_hits >= 8)
            if size_bytes >= LANGUAGE_SERVER_LOG_WARN_BYTES or is_spin_loop:
                bloated.append({
                    "path": str(log_path),
                    "size_bytes": size_bytes,
                    "size_mb": round(size_bytes / (1024 * 1024), 1),
                    "vcs_spin_loop": is_spin_loop,
                    "vcs_hits_in_tail": vcs_hits,
                })
        except OSError:
            continue
    return {"checked_paths": checked, "bloated_logs": bloated}


def _parse_semver_prefix(raw: str) -> tuple[int, int, int] | None:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(raw or ""))
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


LATEST_KNOWN_ANTIGRAVITY_VERSIONS: dict[str, str] = {
    "app_version": "2.33.0",
    "ide_version": "2.8.0",
    "cli_version": "1.5.14",
    "vscode_extension_version": "1.13.0",
}


def detect_antigravity_versions(env: dict[str, str] | None = None) -> dict[str, str]:
    """Read declared Antigravity App, CLI, IDE, and VS Code extension versions from environment metadata when present."""
    environ = env if env is not None else os.environ
    return {
        "app_version": str(environ.get("ANTIGRAVITY_APP_VERSION") or environ.get("AGY_APP_VERSION") or "").strip(),
        "cli_version": str(environ.get("ANTIGRAVITY_CLI_VERSION") or environ.get("AGY_CLI_VERSION") or "").strip(),
        "ide_version": str(environ.get("ANTIGRAVITY_IDE_VERSION") or environ.get("AGY_IDE_VERSION") or "").strip(),
        "vscode_extension_version": str(
            environ.get("ANTIGRAVITY_VSCODE_VERSION") or environ.get("AGY_VSCODE_VERSION") or ""
        ).strip(),
    }


def inspect_windows_stdio_mcp_risk(repo: Path, env: dict[str, str] | None = None) -> dict[str, object]:
    """Detect multi-server stdio MCP setups on Windows susceptible to #199301 AcceptEx pipe-handle aborts."""
    import json as _json
    environ = env if env is not None else os.environ
    is_win = os.name == "nt" or str(environ.get("HARNESS_SIMULATE_WINDOWS_MCP") or "").strip().lower() in {"1", "true", "yes"}
    if not is_win:
        return {"applicable": False, "at_risk": False, "stdio_servers": [], "config_paths": []}

    mcp_files: list[Path] = [
        repo / ".agents" / "mcp_config.json",
        repo / ".agents" / "mcp.json",
        repo / "mcp_config.json",
        repo / ".mcp.json",
    ]
    app_data_override = str(environ.get("ANTIGRAVITY_APP_DATA") or "").strip()
    if app_data_override:
        mcp_files.append(Path(app_data_override) / "mcp_config.json")
    else:
        mcp_files.append(Path.home() / ".gemini" / "antigravity" / "mcp_config.json")
        appdata = str(environ.get("APPDATA") or "").strip()
        if appdata:
            mcp_files.append(Path(appdata) / "Antigravity" / "User" / "mcp.json")

    stdio_servers: list[str] = []
    inspected: list[str] = []
    seen_files: set[Path] = set()
    for cfg in mcp_files:
        try:
            resolved = cfg.expanduser().resolve()
            if resolved in seen_files or not resolved.is_file() or resolved.is_symlink():
                continue
            seen_files.add(resolved)
            data = _json.loads(resolved.read_text(encoding="utf-8-sig", errors="replace"))
            if not isinstance(data, dict):
                continue
            servers = data.get("mcpServers") or data.get("servers") or {}
            if not isinstance(servers, dict):
                continue
            inspected.append(str(resolved))
            for name, spec in servers.items():
                if not isinstance(spec, dict) or spec.get("disabled") is True:
                    continue
                has_cmd = bool(str(spec.get("command") or "").strip())
                has_http = bool(str(spec.get("url") or spec.get("serverUrl") or spec.get("httpUrl") or "").strip())
                transport = str(spec.get("transport") or spec.get("type") or "").strip().lower()
                if has_cmd and not has_http and transport not in {"http", "sse", "streamable-http"}:
                    if str(name) not in stdio_servers:
                        stdio_servers.append(str(name))
        except (OSError, ValueError, TypeError):
            continue

    vers = detect_antigravity_versions(environ)
    cli_v = _parse_semver_prefix(vers["cli_version"])
    app_v = _parse_semver_prefix(vers["app_version"])
    mitigated_upstream = bool(
        (cli_v is not None and cli_v >= (1, 5, 10))
        or (app_v is not None and app_v >= (2, 33, 0))
    )
    return {
        "applicable": True,
        "at_risk": (len(stdio_servers) >= 2) and not mitigated_upstream,
        "mitigated_upstream": mitigated_upstream,
        "stdio_servers": stdio_servers,
        "config_paths": inspected,
    }


def should_normalize_crlf_for_edit(repo: Path | None = None, env: dict[str, str] | None = None) -> bool:
    """Return True only on legacy (<1.5.1) or unknown Antigravity CLI versions when `#crlf-edit` is not disabled."""
    from platform_quirks import is_quirk_enabled
    return is_quirk_enabled(
        "AGY_WIN_CRLF_EDIT_NORMALIZATION",
        repo=repo,
        env=env,
        respect_upstream=True,
    )


def inspect_legacy_cli_quote_bom_and_crlf_guards(repo: Path, env: dict[str, str] | None = None) -> dict[str, object]:
    """Inspect hooks.json / plugin.json quote & UTF-8 BOM compatibility gated to Antigravity CLI <1.5.8 / <1.5.11."""
    import json as _json
    from platform_quirks import is_quirk_enabled

    environ = env if env is not None else os.environ
    vers = detect_antigravity_versions(dict(environ))
    cli_v = _parse_semver_prefix(vers["cli_version"])
    app_v = _parse_semver_prefix(vers["app_version"])
    ide_v = _parse_semver_prefix(vers["ide_version"])

    is_win = (
        os.name == "nt"
        or str(environ.get("HARNESS_SIMULATE_PLATFORM") or "").strip().lower().startswith("win")
        or str(environ.get("HARNESS_SIMULATE_WINDOWS_MCP") or "").strip().lower() in {"1", "true", "yes"}
    )

    crlf_mitigated = bool(
        (cli_v is not None and cli_v >= (1, 5, 1))
        or (app_v is not None and app_v >= (2, 33, 0))
        or (ide_v is not None and ide_v >= (2, 7, 1))
    )
    hooks_158_mitigated = bool(
        (cli_v is not None and cli_v >= (1, 5, 8))
        or (app_v is not None and app_v >= (2, 33, 0))
    )
    plugin_1511_mitigated = bool(
        (cli_v is not None and cli_v >= (1, 5, 11))
        or (app_v is not None and app_v >= (2, 33, 0))
    )

    hooks_file = (repo / ".agents" / "hooks.json") if (repo / ".agents" / "hooks.json").is_file() else (repo / "agents" / "hooks.json")
    plugin_file = repo / ".antigravity-plugin" / "plugin.json"

    hooks_has_bom = False
    quoted_commands: list[str] = []
    if hooks_file.is_file():
        try:
            raw_h = hooks_file.read_bytes()
            hooks_has_bom = raw_h.startswith(b"\xef\xbb\xbf")
            h_doc = _json.loads(raw_h.decode("utf-8-sig", errors="replace"))
            if isinstance(h_doc, dict):
                for grp in h_doc.values():
                    if not isinstance(grp, dict):
                        continue
                    for hook_list in grp.values():
                        if not isinstance(hook_list, list):
                            continue
                        for entry in hook_list:
                            if not isinstance(entry, dict):
                                continue
                            sub = entry.get("hooks") if isinstance(entry.get("hooks"), list) else [entry]
                            for sh in sub:
                                if isinstance(sh, dict):
                                    cmd = str(sh.get("command") or "").strip()
                                    if '"' in cmd and cmd not in quoted_commands:
                                        quoted_commands.append(cmd)
        except (OSError, ValueError):
            pass

    plugin_has_bom = False
    if plugin_file.is_file():
        try:
            plugin_has_bom = plugin_file.read_bytes().startswith(b"\xef\xbb\xbf")
        except OSError:
            plugin_has_bom = False

    quote_bom_quirk_on = is_quirk_enabled("AGY_WIN_HOOK_QUOTE_AND_BOM", repo=repo, env=environ)
    crlf_active = should_normalize_crlf_for_edit(repo=repo, env=dict(environ))

    hooks_quote_risk = bool(quote_bom_quirk_on and is_win and quoted_commands and not hooks_158_mitigated)
    hooks_bom_risk = bool(quote_bom_quirk_on and hooks_has_bom and not hooks_158_mitigated)
    plugin_bom_risk = bool(quote_bom_quirk_on and plugin_has_bom and not plugin_1511_mitigated)
    at_risk = hooks_quote_risk or hooks_bom_risk or plugin_bom_risk

    return {
        "at_risk": at_risk,
        "cli_version": vers["cli_version"],
        "app_version": vers["app_version"],
        "crlf_normalization_active": crlf_active,
        "crlf_mitigated_upstream": crlf_mitigated,
        "hooks_158_mitigated_upstream": hooks_158_mitigated,
        "plugin_1511_mitigated_upstream": plugin_1511_mitigated,
        "mitigated_upstream": bool(crlf_mitigated and hooks_158_mitigated),
        "hooks_has_bom": hooks_has_bom,
        "plugin_has_bom": plugin_has_bom,
        "quoted_hook_commands": quoted_commands,
        "hooks_quote_risk": hooks_quote_risk,
        "hooks_bom_risk": hooks_bom_risk,
        "plugin_bom_risk": plugin_bom_risk,
    }


ZOMBIE_WAKEUP_GAP_SECONDS = 7200  # 2h+ gap inside a subagent transcript flags #199713 255.3m reactive wakeup


def classify_antigravity_quota_or_capacity_error(err_text: str) -> dict[str, str] | None:
    """Classify Nov 2026 Antigravity platform quota/capacity/ban/cache hazards (#200029/#199971, #200026, #199769/#199770, #198333, Hydrogen rollout & Orchestrator)."""
    low = str(err_text or "").strip().lower()
    if not low:
        return None
    if (
        "tos_violation" in low
        or (("403" in low or "permission_denied" in low) and any(k in low for k in ("suspended", "flagged", "tos", "appeal")))
    ):
        return {
            "code": "HYDROGEN_403_TOS_FALSE_POSITIVE",
            "issue": "#200029/#199971",
            "remedy": (
                "False-positive 403 PERMISSION_DENIED (TOS_VIOLATION) triggered by high-velocity sequential tool bursts "
                "during Gemini 4 Hydrogen / Orchestrator plan execution (#200029/#199971). Keep Harness PreToolUse "
                "HYDROGEN_ANTI_BURST_PACER enabled, never select Antigravity's built-in Orchestrator mode, batch 4-8 "
                "parallel view_file calls per turn, and submit the official one-time Antigravity account appeal if suspended."
            ),
        }
    if "cachedcontenttokencount" in low or ("+701" in low and "turn" in low) or "multi-shard" in low:
        return {
            "code": "GEMINI4_TURN3_CACHE_DROP_ANOMALY",
            "issue": "#200026",
            "remedy": (
                "Server-side Gemini 4 Turn-3 +701 token injection / cachedContentTokenCount=0 drop or multi-shard KV split "
                "detected on daily-cloudcode-pa (#200026). Prefer pure agy CLI (3.41% regression) over ACP IDE extensions (5.86%), "
                "keep V2 reviewers Zero-Hop (1-2 turns, completing before Turn 3), and optionally switch multi-turn Scout sweeps "
                "to safe-cache-project (3.8 Flash Scout = 0 cache drops)."
            ),
        }
    if "orchestrator" in low and ("effort isn't adjustable" in low or "effort is not adjustable" in low or "double" in low or "re-plan" in low):
        return {
            "code": "ORCHESTRATOR_DOUBLE_PLANNING_HAZARD",
            "issue": "Orchestrator+Harness",
            "remedy": (
                "Antigravity built-in Orchestrator runs its own internal Carbon<->Hydrogen planning/handoff loop, "
                "which conflicts with Harness PreToolUse gates. Select explicit 'Gemini 4 Carbon (Medium)' or 'Gemini 4 Neon (High)' (or Hydrogen High/Claude 5.5) "
                "on the main chat and let 'hydrogen-dynamic-project' govern subagents."
            ),
        }
    if (
        ("invalid model" in low or "unsupported model" in low or "model_id" in low or "not a valid model" in low)
        and any(tok in low for tok in ("gemini-4-", "hydrogen", "argon", "carbon", "neon", "inherit", "flash", "flash_lite"))
    ) or ("expected" in low and "'inherit'" in low and "'flash'" in low):
        return {
            "code": "AGY_CLI_SUBAGENT_MODEL_ID_UNSUPPORTED",
            "issue": "#200144",
            "remedy": (
                "Antigravity CLI (agy v1.5.8-v1.5.12) rejected an explicit model ID in subagent frontmatter (#200144 — CLI schema only accepts "
                "inherit|flash|pro|flash_lite). Run in Antigravity Desktop App v2.33.0+, or switch subagents to inherit for CLI sessions via: "
                "python .agents/harness.py review models set --choice inherit-task --source conversation --proof-reference 'CLI inherit fallback (#200144)'"
            ),
        }
    if (
        ("0 thinking tokens" in low or "thinking_tokens=0" in low or "thinking_tokens: 0" in low or "thoughtstokencount=0" in low or "zero thinking tokens" in low)
        and "hydrogen" in low
    ):
        return {
            "code": "HYDROGEN_MEDIUM_ZERO_THINKING_AFTER_TOOL",
            "issue": "#1649/#201731",
            "remedy": (
                "Gemini 4 Hydrogen (Medium) on Windows can drop thinking_tokens to 0 on turns following workspace file-read tool calls "
                "(#1649/#201731). Switch the selector to 'Gemini 4 Hydrogen (High)' (same 1.00x quota cost, immune to #1649), and prefer "
                "'python .agents/harness.py symbol outline/read' or 'task-context' over raw read_file sweeps."
            ),
        }
    if (
        ("marked unavailable" in low or "shows unavailable" in low or "model unavailable" in low or "is unavailable" in low or "entitlement" in low)
        and any(tok in low for tok in ("hydrogen", "argon", "neon", "gemini 4", "gemini-4"))
        and "503" not in low
    ):
        return {
            "code": "GEMINI4_ENTITLEMENT_DESYNC_UNAVAILABLE",
            "issue": "#200147/#199992",
            "remedy": (
                "Account entitlement desync marked Gemini 4 Hydrogen/Neon/Argon as Unavailable (#200147/#199992). "
                "Run 'Antigravity: Reset Onboarding' (or sign out and back in), or unblock this task immediately via "
                "'python .agents/harness.py task heal --task-id <id>' followed by '--choice inherit-once' or '--choice flash-project'."
            ),
        }
    is_429 = "429" in low or "resource_exhausted" in low or "quota" in low
    is_entitlement_or_missing = (
        "not available on your plan" in low
        or "not supported for your account" in low
        or "model_not_found" in low
        or "model not found" in low
        or ("permission_denied" in low and "hydrogen" in low)
        or ("404" in low and "hydrogen" in low)
    )
    if "hydrogen" in low and (is_entitlement_or_missing or (is_429 and ("limit: 0" in low or "limit:0" in low))):
        return {
            "code": "HYDROGEN_ROLLOUT_ENTITLEMENT_BLOCK",
            "issue": "Hydrogen-Rollout",
            "remedy": (
                "Gemini 4 Hydrogen is not yet active or entitled on this account/region. "
                "Fall back cleanly to Flash + Argon Low (or Pure Flash) via: "
                "python .agents/harness.py review models set --choice flash-argon-project --source conversation "
                "--proof-reference \"Fallback to Flash+Argon while Hydrogen rolls out\""
            ),
        }
    is_zero_limit = (
        "limit: 0" in low
        or "limit:0" in low
        or "0 requests per day" in low
        or "0 input tokens per minute" in low
        or "antigravity-preview-09-2026" in low
        or ("carbon" in low and ("ultra" in low or "entitle" in low or "tier" in low))
        or ("neon" in low and ("pro" in low or "ultra" in low or "entitle" in low or "tier" in low))
    )
    if is_429 and is_zero_limit:
        return {
            "code": "MANAGED_AGENT_ZERO_QUOTA_429",
            "issue": "#199769/#199770",
            "remedy": (
                "Managed Agent API / tier returned zero Argon/Carbon/Neon quota (limit: 0). "
                "Switch subagents immediately to 100% Pure Gemini 4 Hydrogen (zero Argon/Carbon quota) via: "
                "python .agents/harness.py review models set --choice hydrogen-dynamic-project --source conversation "
                "--proof-reference \"Switch to Pure Hydrogen (#199769)\" "
                "(or --choice flash-project if Hydrogen is not yet rolled out on your tier)."
            ),
        }
    is_503 = "503" in low or "service unavailable" in low or ("unavailable" in low and ("capacity" in low or "overloaded" in low or "backoff" in low))
    if is_503:
        return {
            "code": "FLASH_503_CAPACITY_BACKOFF",
            "issue": "#198333",
            "remedy": (
                "Regional capacity retries (4s-24s HTTP 503 backoff) detected (#198333). "
                "Upgrade subagents from legacy 3.8 Flash to Gemini 4 Hydrogen via: "
                "python .agents/harness.py review models set --choice hydrogen-dynamic-project --source conversation "
                "--proof-reference \"Upgrade to Pure Hydrogen (#198333)\" and batch 4-8 parallel view_file reads per turn."
            ),
        }
    return None


def inspect_zombie_subagent_and_schedule_risks(repo: Path, env: dict[str, str] | None = None) -> dict[str, object]:
    """Detect #199713 Zombie Subagent schedule-permission injection in .agents and >=2h reactive wakeup spikes."""
    import json as _json
    from datetime import datetime as _dt

    environ = env if env is not None else os.environ
    schedule_injected_files: list[str] = []

    agent_md_dirs = [repo / ".agents" / "agents", repo / "agents" / "subagents"]
    for base in agent_md_dirs:
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix not in {".md", ".json"}:
                continue
            try:
                raw = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if f.suffix == ".md" and raw.startswith("---"):
                end = raw.find("\n---", 3)
                front = raw[: end if end > 0 else 600].lower()
                if re.search(r"""(?:^|\n)\s*-\s*["']?schedules?(?::|["']|\s|$)""", front):
                    schedule_injected_files.append(str(f.relative_to(repo) if f.is_relative_to(repo) else f))
            elif f.suffix == ".json":
                try:
                    spec = _json.loads(raw)
                except ValueError:
                    continue
                tools = spec.get("tools") if isinstance(spec, dict) else None
                if isinstance(tools, list) and any(str(t).strip().lower().startswith("schedule") for t in tools):
                    schedule_injected_files.append(str(f.relative_to(repo) if f.is_relative_to(repo) else f))

    settings_candidates = [repo / ".agents" / "settings.json", repo / "agents" / "settings.json"]
    for sf in settings_candidates:
        if sf.is_file():
            try:
                stxt = sf.read_text(encoding="utf-8", errors="replace").lower()
                if '"schedule"' in stxt or '"schedules:' in stxt:
                    schedule_injected_files.append(str(sf.relative_to(repo) if sf.is_relative_to(repo) else sf))
            except OSError:
                continue

    brain_roots: list[Path] = []
    brain_override = str(environ.get("ANTIGRAVITY_BRAIN_ROOT") or "").strip()
    if brain_override:
        try:
            brain_roots.append(Path(brain_override).expanduser().resolve())
        except (OSError, RuntimeError, ValueError):
            pass
    else:
        brain_roots.extend(candidate_brain_roots())

    wakeup_spikes: list[dict[str, object]] = []
    iso_re = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)")
    for broot in brain_roots:
        if not broot.is_dir():
            continue
        for conv_id, child_dir in iter_recent_brain_conversations(broot, limit=16):
            tx = prefer_full_transcript(child_dir / ".system_generated" / "logs" / "transcript.jsonl")
            if tx is None or not tx.is_file():
                tx = prefer_full_transcript(child_dir / "transcript.jsonl")
            if tx is None or not tx.is_file():
                for fb_tx in (
                    child_dir / ".system_generated" / "logs" / "transcript_full.jsonl",
                    child_dir / "transcript_full.jsonl",
                ):
                    if fb_tx.is_file() and not fb_tx.is_symlink():
                        tx = fb_tx
                        break
            if tx is None or not tx.is_file():
                continue
            try:
                size = tx.stat().st_size
                with tx.open("rb") as fh:
                    if size > 32768:
                        fh.seek(size - 32768)
                    tail = fh.read(32768).decode("utf-8", errors="replace")
            except OSError:
                continue
            if "HARNESS_" not in tail and "REVIEWER_FINGERPRINT" not in tail and "subagent" not in tail.lower():
                continue
            stamps: list[float] = []
            for ln in tail.splitlines():
                if not ln.strip():
                    continue
                try:
                    obj = _json.loads(ln) if ln.strip().startswith("{") else {}
                except ValueError:
                    obj = {}
                ts_val = obj.get("timestamp") or obj.get("ts") or obj.get("created_at")
                if isinstance(ts_val, (int, float)) and ts_val > 1_000_000_000:
                    stamps.append(float(ts_val))
                    continue
                m_iso = iso_re.search(str(ts_val or "") or ln)
                if m_iso:
                    try:
                        stamps.append(_dt.fromisoformat(m_iso.group(1).replace("Z", "+00:00")).timestamp())
                    except ValueError:
                        continue
            for prev_t, cur_t in zip(stamps, stamps[1:]):
                gap = cur_t - prev_t
                if gap >= ZOMBIE_WAKEUP_GAP_SECONDS:
                    wakeup_spikes.append({
                        "conversation_id": conv_id,
                        "gap_minutes": round(gap / 60.0, 1),
                        "transcript": str(tx),
                    })
                    break

    return {
        "at_risk": bool(schedule_injected_files or wakeup_spikes),
        "schedule_injected_files": schedule_injected_files,
        "wakeup_spikes": wakeup_spikes,
    }


def inspect_windows_smart_app_control_4551_risk(
    env: dict[str, str] | None = None,
    installer_dirs: list[Path] | None = None,
) -> dict[str, object]:
    """Detect Windows 11 Smart App Control Error 4551 blocking unsigned Antigravity IDE v2.7.0 / v2.8.0 (#200037/#203416)."""
    import sys as _sys
    environ = env if env is not None else os.environ
    sim_plat = str(environ.get("HARNESS_SIMULATE_PLATFORM") or "").strip().lower()
    is_win = sim_plat == "win32" or (not sim_plat and _sys.platform == "win32")
    if not is_win:
        return {"applicable": False, "at_risk": False, "flagged_artifacts": [], "ide_version": ""}

    ide_ver = str(environ.get("ANTIGRAVITY_IDE_VERSION") or environ.get("AGY_IDE_VERSION") or "").strip()
    sac_err = str(environ.get("ANTIGRAVITY_INSTALLER_ERROR") or "").strip()
    sac_err_low = sac_err.lower()
    flagged: list[str] = []

    if re.search(r"(?:^|[^0-9])2\.[78]\.0(?:$|[^0-9])", ide_ver):
        flagged.append(f"ANTIGRAVITY_IDE_VERSION={ide_ver}")
    if (
        "4551" in sac_err
        or "smart app control" in sac_err_low
        or ("3077" in sac_err and "notsigned" in sac_err_low)
    ):
        flagged.append(f"installer_error={sac_err[:120]}")

    dirs_to_scan: list[Path] = []
    if installer_dirs is not None:
        dirs_to_scan.extend(installer_dirs)
    else:
        home = Path.home()
        for d in (home / "Downloads", Path(environ.get("TEMP") or "") if environ.get("TEMP") else None):
            if d is not None and d.is_dir():
                dirs_to_scan.append(d)

    unsigned_ide_re = re.compile(r"antigravity.*2[._-][78][._-]0.*\.(?:exe|msi)$", re.IGNORECASE)
    for d in dirs_to_scan:
        if not d.is_dir():
            continue
        try:
            for child in d.iterdir():
                if child.is_file() and unsigned_ide_re.search(child.name):
                    flagged.append(str(child))
        except OSError:
            continue

    return {
        "applicable": True,
        "at_risk": bool(flagged),
        "flagged_artifacts": flagged[:8],
        "ide_version": ide_ver,
    }


def extract_lead_candidates_from_state(state_dir: Path) -> list[str]:
    """Return ordered candidate parent/Lead conversation IDs from active-conversation and hook-conversations files.

    Supports both `active-conversation.json` (`{"conversation_id": ...}`) and `cache/hook-conversations.json`
    (flat `{cid: epoch_float}` written by `pre_tool_safety.py`, as well as legacy `{"last_lead_conversation_id": ..., "conversations": {...}}`).
    """
    import json as _json
    candidates: list[str] = []
    if not isinstance(state_dir, Path) or not state_dir.is_dir():
        return candidates

    active_conv = state_dir / "active-conversation.json"
    if active_conv.is_file():
        try:
            doc = _json.loads(active_conv.read_text(encoding="utf-8-sig", errors="replace"))
            if isinstance(doc, dict):
                cid = str(doc.get("conversation_id") or "").strip()
                if cid and not _is_invalid_conversation_id(cid) and cid not in candidates:
                    candidates.append(cid)
        except (OSError, ValueError):
            pass

    for hc_path in (state_dir / "cache" / "hook-conversations.json", state_dir / "hook-conversations.json"):
        if not hc_path.is_file():
            continue
        try:
            doc = _json.loads(hc_path.read_text(encoding="utf-8-sig", errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        explicit_last = str(doc.get("last_lead_conversation_id") or "").strip()
        if explicit_last and not _is_invalid_conversation_id(explicit_last) and explicit_last not in candidates:
            candidates.append(explicit_last)
        nested = doc.get("conversations")
        if isinstance(nested, dict):
            ranked_nested: list[tuple[float, str]] = []
            for k, v in nested.items():
                ks = str(k).strip()
                if not ks or _is_invalid_conversation_id(ks):
                    continue
                ts = float(v) if isinstance(v, (int, float)) else 0.0
                ranked_nested.append((ts, ks))
            for _, ks in sorted(ranked_nested, key=lambda item: item[0], reverse=True):
                if ks not in candidates:
                    candidates.append(ks)
        ranked_flat: list[tuple[float, str]] = []
        for k, v in doc.items():
            if k in {"last_lead_conversation_id", "conversations", "schema_version"}:
                continue
            ks = str(k).strip()
            if not ks or _is_invalid_conversation_id(ks):
                continue
            if isinstance(v, (int, float)):
                ranked_flat.append((float(v), ks))
        for _, ks in sorted(ranked_flat, key=lambda item: item[0], reverse=True):
            if ks not in candidates:
                candidates.append(ks)
    return candidates


def is_likely_subagent_transcript(transcript: Path | None) -> bool:
    """Return True if bounded transcript head shows subagent dispatch markers without USER_EXPLICIT input."""
    read_p = prefer_full_transcript(transcript) or transcript
    if read_p is None or not read_p.is_file():
        return False
    try:
        head = read_p.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return False
    if '"USER_EXPLICIT"' in head:
        return False
    return (
        "MESSAGE_PRIORITY_HIGH" in head
        or "HARNESS_SCOUT_FINGERPRINT=" in head
        or "HARNESS_WORKER_FINGERPRINT=" in head
        or "REVIEWER_FINGERPRINT=" in head
    )


def inspect_nov15_antigravity_hazards(
    repo: Path,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    """Inspect Nov 15, 2026 Antigravity hazards (#200467 Hydrogen Extra Argon quota leak & #200619 autoAcceptOnChat / Inline Diff)."""
    import json as _json
    environ = env if env is not None else os.environ
    state_dir = (repo / ".agents" / "state") if (repo / ".agents" / "state").is_dir() else (repo / "agents" / "state")

    cand_cids: list[str] = []
    env_cid = str(environ.get("HARNESS_CONVERSATION_ID") or "").strip()
    if env_cid and not _is_invalid_conversation_id(env_cid):
        cand_cids.append(env_cid)
    for scid in extract_lead_candidates_from_state(state_dir):
        if scid not in cand_cids:
            cand_cids.append(scid)

    active_lead_cid = ""
    active_lead_model = str(environ.get("ANTIGRAVITY_ACTIVE_MODEL") or "").strip()
    for cid in cand_cids[:6]:
        tx = resolve_transcript(cid)
        if tx is None or is_likely_subagent_transcript(tx):
            continue
        try:
            meta = native_model_metadata(tx)
        except Exception:
            continue
        if isinstance(meta, dict):
            cfg = str(meta.get("host_configured_model") or "").strip()
            rep_list = [str(m).strip() for m in (meta.get("host_reported_models") or []) if str(m).strip()]
            chosen = cfg or (rep_list[-1] if rep_list else "")
            if chosen:
                active_lead_cid = cid
                active_lead_model = chosen
                break

    import sys as _sys
    norm_model = re.sub(r"[\s()]+", "-", active_lead_model.lower().removeprefix("models/")).strip("-")
    hydrogen_extra_leak_active = bool(
        re.search(r"gemini-4-hydrogen-(?:tiered-)?(?:extra|xhigh)\b|hydrogen@(?:extra|xhigh)\b", norm_model)
    )
    sim_plat = str(environ.get("HARNESS_SIMULATE_PLATFORM") or "").strip().lower()
    is_win_host = sim_plat == "win32" or (not sim_plat and _sys.platform == "win32")
    quirk_1649_on = True
    try:
        from platform_quirks import is_quirk_enabled
        quirk_1649_on = is_quirk_enabled("1649", repo=repo, env=environ)
    except ImportError:
        quirk_1649_on = True
    hydrogen_medium_win_tool_risk = bool(
        is_win_host
        and quirk_1649_on
        and re.search(r"gemini-4-hydrogen-(?:tiered-)?medium\b|hydrogen@medium\b", norm_model)
    )
    quirk_1720_on = True
    try:
        from platform_quirks import is_quirk_enabled
        quirk_1720_on = is_quirk_enabled("1720", repo=repo, env=environ)
    except ImportError:
        quirk_1720_on = True
    neon_xhigh_cache_collapse_risk = bool(
        quirk_1720_on
        and re.search(r"gemini-4-neon-(?:tiered-)?(?:extra|xhigh)\b|neon@(?:extra|xhigh)\b", norm_model)
    )

    auto_accept_state = "no_vscode_settings"
    auto_accept_at_risk = False
    vscode_settings = repo / ".vscode" / "settings.json"
    user_settings_raw = str(environ.get("ANTIGRAVITY_USER_SETTINGS_PATH") or "").strip()
    settings_files: list[Path] = []
    if vscode_settings.is_file():
        settings_files.append(vscode_settings)
    if user_settings_raw:
        up = Path(user_settings_raw).expanduser()
        if up.is_file():
            settings_files.append(up)

    for sf in settings_files:
        try:
            raw = sf.read_text(encoding="utf-8", errors="ignore")
            cleaned = re.sub(r"//.*?$", "", raw, flags=re.MULTILINE)
            cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
            parsed = _json.loads(cleaned)
        except Exception:
            continue
        if isinstance(parsed, dict):
            if "antigravity.autoAcceptOnChat" in parsed:
                val = parsed["antigravity.autoAcceptOnChat"]
                if val is True:
                    auto_accept_state = "explicit_true"
                    auto_accept_at_risk = True
                    break
                if val is False:
                    auto_accept_state = "explicit_false"
            elif auto_accept_state == "no_vscode_settings":
                auto_accept_state = "unset_default_true"

    return {
        "hydrogen_extra_leak_active": hydrogen_extra_leak_active,
        "hydrogen_medium_win_tool_risk": hydrogen_medium_win_tool_risk,
        "neon_xhigh_cache_collapse_risk": neon_xhigh_cache_collapse_risk,
        "active_lead_model": active_lead_model,
        "active_lead_conversation_id": active_lead_cid,
        "auto_accept_on_chat_state": auto_accept_state,
        "auto_accept_at_risk": auto_accept_at_risk,
    }


def inspect_language_server_acceptex_crashes(
    env: dict[str, str] | None = None,
    log_dirs: list[Path] | None = None,
    crash_dirs: list[Path] | None = None,
) -> dict[str, object]:
    """Detect Windows `language_server.exe` Exit Code 2 AcceptEx (Win32 Error 995) crash loops (#200687/#199301/#200763)
    even after Electron wipes `language_server.log` within 2s, by correlating `main.log` (`exited with code 2` +
    `[Auto-Restart] Port changed!`) and 0-byte `crash_*.log` files under `.gemini/antigravity/crashes/`.
    """
    environ = env if env is not None else os.environ
    main_log_candidates: list[Path] = []
    explicit_main = str(environ.get("ANTIGRAVITY_MAIN_LOG") or "").strip()
    if explicit_main:
        p_exp = Path(explicit_main).expanduser()
        if p_exp.is_file():
            main_log_candidates.append(p_exp)

    search_roots: list[Path] = []
    if log_dirs is not None:
        search_roots.extend(log_dirs)
    else:
        app_data_ovr = str(environ.get("ANTIGRAVITY_APP_DATA") or "").strip()
        if app_data_ovr:
            search_roots.append(Path(app_data_ovr).expanduser())
        else:
            for env_key in ("APPDATA", "LOCALAPPDATA"):
                raw_v = str(environ.get(env_key) or "").strip()
                if raw_v:
                    search_roots.append(Path(raw_v) / "Antigravity" / "logs")
            search_roots.append(Path.home() / ".gemini" / "antigravity" / "logs")
            search_roots.append(Path.home() / ".gemini" / "antigravity")

    seen_logs: set[Path] = set()
    for root in search_roots:
        if not root.is_dir():
            continue
        direct_main = root / "main.log"
        if direct_main.is_file():
            main_log_candidates.append(direct_main)
        logs_sub = root / "logs" if (root / "logs").is_dir() else root
        try:
            subdirs = sorted(
                [d for d in logs_sub.iterdir() if d.is_dir()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:6]
            for sd in subdirs:
                cand_m = sd / "main.log"
                if cand_m.is_file():
                    main_log_candidates.append(cand_m)
                for nested in sd.glob("*/main.log"):
                    if nested.is_file():
                        main_log_candidates.append(nested)
        except OSError:
            continue

    code2_crashes = 0
    port_restarts = 0
    acceptex_hits = 0
    matched_logs: list[str] = []
    code2_re = re.compile(r"language[_\s-]*server[^\n]*exited with code 2\b", re.IGNORECASE)
    acceptex_re = re.compile(r"acceptex:\s*the i/o operation has been aborted|server_common\.go:(?:58|98)\b", re.IGNORECASE)

    for ml in main_log_candidates[:8]:
        try:
            resolved = ml.resolve()
            if resolved in seen_logs or not resolved.is_file() or resolved.is_symlink():
                continue
            seen_logs.add(resolved)
            sz = resolved.stat().st_size
            if sz <= 0:
                continue
            with resolved.open("rb") as fh:
                fh.seek(max(0, sz - 65536))
                tail = fh.read(65536).decode("utf-8", errors="replace")
        except OSError:
            continue
        c2 = len(code2_re.findall(tail))
        pr = tail.count("[Auto-Restart] Port changed!")
        ax = len(acceptex_re.findall(tail))
        if c2 or pr or ax:
            code2_crashes += c2
            port_restarts += pr
            acceptex_hits += ax
            matched_logs.append(str(resolved))

    c_dirs: list[Path] = []
    if crash_dirs is not None:
        c_dirs.extend(crash_dirs)
    else:
        explicit_cdir = str(environ.get("ANTIGRAVITY_CRASH_DIR") or "").strip()
        if explicit_cdir:
            c_dirs.append(Path(explicit_cdir).expanduser())
        app_data_ovr = str(environ.get("ANTIGRAVITY_APP_DATA") or "").strip()
        if app_data_ovr:
            c_dirs.append(Path(app_data_ovr).expanduser() / "crashes")
        else:
            c_dirs.append(Path.home() / ".gemini" / "antigravity" / "crashes")

    zero_byte_crash_logs = 0
    seen_cdirs: set[Path] = set()
    for cd in c_dirs:
        try:
            if not cd.is_dir():
                continue
            rcd = cd.resolve()
            if rcd in seen_cdirs:
                continue
            seen_cdirs.add(rcd)
            for cf in rcd.glob("crash_*.log"):
                if cf.is_file() and not cf.is_symlink() and cf.stat().st_size == 0:
                    zero_byte_crash_logs += 1
        except OSError:
            continue

    crash_loop_detected = bool(
        acceptex_hits > 0
        or (code2_crashes > 0 and (port_restarts > 0 or zero_byte_crash_logs > 0))
    )
    return {
        "crash_loop_detected": crash_loop_detected,
        "code2_crashes": code2_crashes,
        "port_restarts": port_restarts,
        "acceptex_hits": acceptex_hits,
        "zero_byte_crash_logs": zero_byte_crash_logs,
        "matched_logs": matched_logs,
    }


def inspect_windows_go_gc_and_handle_risk(
    repo: Path,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    """Check Windows 11 `GOMEMLIMIT` / `GOGC` tuning (#200687), `stdio` MCP count (#199301), and pre-IDE-2.8.0 `AcceptEx` post-wipe crash loops (#200763)."""
    import sys as _sys
    environ = env if env is not None else os.environ
    try:
        from platform_quirks import is_quirk_enabled
        if not is_quirk_enabled("200687", repo=repo, env=environ):
            return {"applicable": False, "at_risk": False, "gc_tuned": True, "quirk_disabled": True}
    except ImportError:
        pass
    sim_plat = str(environ.get("HARNESS_SIMULATE_PLATFORM") or "").strip().lower()
    sim_mcp = str(environ.get("HARNESS_SIMULATE_WINDOWS_MCP") or "").strip().lower() in {"1", "true", "yes"}
    is_win = sim_plat == "win32" or sim_mcp or (not sim_plat and _sys.platform == "win32")
    if not is_win:
        return {"applicable": False, "at_risk": False, "gc_tuned": True}

    gogc = str(environ.get("GOGC") or "").strip()
    gomemlimit = str(environ.get("GOMEMLIMIT") or "").strip()
    gogc_low = gogc.lower()
    gogc_off_without_memlimit = (gogc_low == "off" and not gomemlimit)
    gogc_relaxed = gogc_low == "off" or (gogc.isdigit() and int(gogc) >= 150)
    gc_tuned = bool(gomemlimit) and gogc_relaxed and not gogc_off_without_memlimit

    mcp_env = dict(environ)
    if sim_plat == "win32" and "HARNESS_SIMULATE_WINDOWS_MCP" not in mcp_env:
        mcp_env["HARNESS_SIMULATE_WINDOWS_MCP"] = "1"
    mcp_rep = inspect_windows_stdio_mcp_risk(repo, env=mcp_env)
    stdio_servers = list(mcp_rep.get("stdio_servers") or [])

    vers = detect_antigravity_versions(dict(environ))
    ide_v = _parse_semver_prefix(vers["ide_version"])
    post_wipe_mitigated = bool(ide_v is not None and ide_v >= (2, 8, 0))
    if post_wipe_mitigated:
        crash_rep: dict[str, object] = {
            "applicable": False,
            "crash_loop_detected": False,
            "mitigated_upstream": True,
            "code2_crashes": 0,
            "port_restarts": 0,
            "zero_byte_crash_logs": 0,
            "matched_logs": [],
        }
        crash_loop = False
    else:
        crash_rep = inspect_language_server_acceptex_crashes(env=environ)
        crash_loop = bool(crash_rep.get("crash_loop_detected"))

    at_risk = bool(
        gogc_off_without_memlimit
        or crash_loop
        or (not gc_tuned and len(stdio_servers) >= 2)
    )
    return {
        "applicable": True,
        "at_risk": at_risk,
        "gc_tuned": gc_tuned,
        "gogc": gogc,
        "gomemlimit": gomemlimit,
        "gogc_off_without_memlimit": gogc_off_without_memlimit,
        "stdio_servers": stdio_servers,
        "post_wipe_recovery_mitigated_upstream": post_wipe_mitigated,
        "crash_report": crash_rep,
    }


def inspect_cli_model_steering_risk(
    repo: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    """Check `~/.gemini/antigravity-cli/settings.json` for `experimental.modelSteering: true` (#1697).

    In Antigravity CLI v1.5.13, background command completion notifications can inject an unclosed
    `<SYSTEM_MESSAGE>` into active streaming output when `modelSteering` is enabled, triggering
    runaway 166k-token EOS separator loops.
    """
    import json as _json

    environ = env if env is not None else os.environ
    try:
        from platform_quirks import is_quirk_enabled
        if not is_quirk_enabled("1697", repo=repo, env=environ):
            return {
                "applicable": False,
                "at_risk": False,
                "model_steering_enabled": False,
                "path": "",
                "cli_version": "",
                "quirk_disabled": True,
            }
    except ImportError:
        pass

    vers = detect_antigravity_versions(dict(environ))
    candidates: list[Path] = []
    explicit_file = str(environ.get("ANTIGRAVITY_CLI_SETTINGS_JSON") or "").strip()
    app_data_ovr = str(environ.get("ANTIGRAVITY_APP_DATA") or "").strip()
    if explicit_file:
        candidates.append(Path(explicit_file).expanduser())
    elif app_data_ovr:
        ap = Path(app_data_ovr).expanduser()
        candidates.append(ap / "settings.json")
        candidates.append(ap.parent / "antigravity-cli" / "settings.json")
    else:
        candidates.append(Path.home() / ".gemini" / "antigravity-cli" / "settings.json")

    target_file: Path | None = None
    for cand in candidates:
        try:
            if cand.is_file() and not cand.is_symlink():
                target_file = cand.resolve()
                break
        except OSError:
            continue

    if target_file is None:
        return {
            "applicable": True,
            "at_risk": False,
            "model_steering_enabled": False,
            "path": "",
            "cli_version": vers["cli_version"],
        }

    enabled = False
    try:
        doc = _json.loads(target_file.read_text(encoding="utf-8-sig", errors="replace"))
        if isinstance(doc, dict):
            exp = doc.get("experimental")
            if isinstance(exp, dict) and exp.get("modelSteering") is True:
                enabled = True
            elif doc.get("modelSteering") is True:
                enabled = True
    except (OSError, ValueError, TypeError):
        enabled = False

    return {
        "applicable": True,
        "at_risk": bool(enabled),
        "model_steering_enabled": bool(enabled),
        "path": str(target_file),
        "cli_version": vers["cli_version"],
    }


_BROAD_CLI_PERMISSION_RE = re.compile(
    r"(?:\*|(?:^|[:_./\s(-])(?:bash|sh|zsh|pwsh|powershell|cmd|run_command|run_terminal_cmd|shell|exec|"
    r"write_file|edit_file|replace_file_content|multi_replace_file_content|delete_file|write|edit|"
    r"call_mcp_tool|mcp|fetch|http|curl|git)(?:$|[:_./\s(-]))",
    re.IGNORECASE,
)


def inspect_default_cli_project_permissions(
    repo: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    """Check `~/.gemini/config/projects/default-cli-project.json` for leaked `/permissions` Project-scope
    `allow` rules that silently apply across non-Git or `--project`-omitted directories (#1618 / #548).
    """
    import json as _json

    environ = env if env is not None else os.environ
    try:
        from platform_quirks import is_quirk_enabled
        if not is_quirk_enabled("1618", repo=repo, env=environ):
            return {
                "applicable": False,
                "at_risk": False,
                "path": "",
                "allow_rules": [],
                "broad_allow_rules": [],
                "quirk_disabled": True,
            }
    except ImportError:
        pass

    candidates: list[Path] = []
    explicit_file = str(environ.get("ANTIGRAVITY_DEFAULT_CLI_PROJECT_JSON") or "").strip()
    cfg_root_ovr = str(environ.get("ANTIGRAVITY_CONFIG_ROOT") or "").strip()
    app_data_ovr = str(environ.get("ANTIGRAVITY_APP_DATA") or "").strip()
    if explicit_file:
        candidates.append(Path(explicit_file).expanduser())
    elif cfg_root_ovr:
        candidates.append(Path(cfg_root_ovr).expanduser() / "projects" / "default-cli-project.json")
    elif app_data_ovr:
        ap = Path(app_data_ovr).expanduser()
        candidates.append(ap / "config" / "projects" / "default-cli-project.json")
        candidates.append(ap.parent / "config" / "projects" / "default-cli-project.json")
    else:
        candidates.append(Path.home() / ".gemini" / "config" / "projects" / "default-cli-project.json")

    target_file: Path | None = None
    for cand in candidates:
        try:
            if cand.is_file() and not cand.is_symlink():
                target_file = cand.resolve()
                break
        except OSError:
            continue

    if target_file is None:
        return {
            "applicable": True,
            "at_risk": False,
            "exists": False,
            "path": "",
            "allow_rules": [],
            "broad_allow_rules": [],
        }

    try:
        raw = target_file.read_text(encoding="utf-8", errors="replace")
        cleaned = re.sub(r"//.*?$", "", raw, flags=re.MULTILINE)
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        data = _json.loads(cleaned) if cleaned.strip() else {}
    except (OSError, ValueError):
        return {
            "applicable": True,
            "at_risk": False,
            "exists": True,
            "path": str(target_file),
            "allow_rules": [],
            "broad_allow_rules": [],
            "parse_error": True,
        }

    allow_rules: list[str] = []
    seen_rules: set[str] = set()

    def _add_rule(val: object) -> None:
        s = str(val or "").strip()
        if s and s not in seen_rules:
            seen_rules.add(s)
            allow_rules.append(s)

    allow_list_keys = {"allow", "alwaysallow", "always_allow", "allowed", "allowedtools", "allowed_tools"}
    allow_decisions = {"allow", "always", "always_allow", "auto_approve", "approved"}
    container_keys = {"permissions", "tools", "toolpermissions", "tool_permissions", "rules", "policies"}

    def _walk(node: object, *, in_allow_map: bool = False) -> None:
        if isinstance(node, dict):
            decision = str(
                node.get("action") or node.get("decision") or node.get("policy") or node.get("permission") or ""
            ).strip().lower()
            if decision in allow_decisions:
                target = (
                    node.get("tool")
                    or node.get("pattern")
                    or node.get("rule")
                    or node.get("command")
                    or node.get("name")
                    or "*"
                )
                if isinstance(target, list):
                    for item in target:
                        _add_rule(item)
                else:
                    _add_rule(target)
            for k, v in node.items():
                kl = str(k).strip().lower()
                if kl in allow_list_keys:
                    if isinstance(v, list):
                        for item in v:
                            if isinstance(item, (str, int, float)):
                                _add_rule(item)
                            elif isinstance(item, dict):
                                _walk(item, in_allow_map=True)
                    elif isinstance(v, dict):
                        _walk(v, in_allow_map=True)
                    elif isinstance(v, str):
                        _add_rule(v)
                elif kl in container_keys:
                    _walk(v, in_allow_map=(kl in {"tools", "toolpermissions", "tool_permissions"}))
                elif in_allow_map:
                    if isinstance(v, str) and v.strip().lower() in allow_decisions:
                        _add_rule(k)
                    elif v is True:
                        _add_rule(k)
        elif isinstance(node, list):
            for item in node:
                _walk(item, in_allow_map=in_allow_map)

    _walk(data)
    broad_allow_rules = [r for r in allow_rules if _BROAD_CLI_PERMISSION_RE.search(r)]
    return {
        "applicable": True,
        "at_risk": bool(broad_allow_rules),
        "exists": True,
        "path": str(target_file),
        "allow_rules": allow_rules,
        "broad_allow_rules": broad_allow_rules,
    }

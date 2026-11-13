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
    for suffix in ("antigravity", "antigravity-cli", "antigravity-ide"):
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


def _is_invalid_conversation_id(conversation_id: str) -> bool:
    if not conversation_id or not isinstance(conversation_id, str):
        return True
    if "\0" in conversation_id:
        return True
    cid = conversation_id.strip().strip("'\"")
    if not cid or len(cid) > 255:
        return True
    if "/" in cid or "\\" in cid or ".." in cid or ":" in cid or cid.startswith("file:"):
        return True
    try:
        if Path(cid).is_absolute():
            return True
    except Exception:
        return True
    return False


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
    execution_id = parts[0]
    canonical = resolve_transcript(execution_id)
    if canonical is None or canonical.resolve() != resolved:
        raise ValidationError("REVIEW_MODEL_UNVERIFIED: model proof requires the canonical execution transcript")
    database = root.parent / "conversations" / f"{execution_id}.db"
    if database.is_symlink() or not database.resolve().is_relative_to(root.parent.resolve()) or not database.is_file():
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
        if val in {"remote", "remote-agent", "remote_agent", "web", "cloud"}:
            signals.append(f"{mode_key}={environ.get(mode_key)}")
    for args_key in ("AGY_ARGS", "ANTIGRAVITY_CLI_ARGS", "ANTIGRAVITY_LAUNCH_ARGS"):
        raw_args = str(environ.get(args_key) or "").strip()
        if "--remote-agent" in raw_args or re.search(r"(?:^|\s)--remote(?:\s|$)", raw_args):
            signals.append(f"{args_key} contains --remote-agent")
    return (bool(signals), signals)


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


def inspect_windows_stdio_mcp_risk(repo: Path, env: dict[str, str] | None = None) -> dict[str, object]:
    """Detect multi-server stdio MCP setups on Windows susceptible to #199301 AcceptEx pipe-handle aborts."""
    import json as _json
    environ = env if env is not None else os.environ
    is_win = os.name == "nt" or str(environ.get("HARNESS_SIMULATE_WINDOWS_MCP") or "").strip().lower() in {"1", "true", "yes"}
    if not is_win:
        return {"applicable": False, "at_risk": False, "stdio_servers": [], "config_paths": []}

    mcp_files: list[Path] = [
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
            data = _json.loads(resolved.read_text(encoding="utf-8", errors="replace"))
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

    return {
        "applicable": True,
        "at_risk": len(stdio_servers) >= 2,
        "stdio_servers": stdio_servers,
        "config_paths": inspected,
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
                "which conflicts with Harness PreToolUse gates. Select explicit 'Gemini 4 Carbon (Medium)' (or Argon/Claude 5.5) "
                "on the main chat and let 'hydrogen-argon-project' govern subagents."
            ),
        }
    if (
        ("invalid model" in low or "unsupported model" in low or "model_id" in low or "not a valid model" in low)
        and any(tok in low for tok in ("gemini-4-", "hydrogen", "argon", "carbon", "inherit", "flash", "flash_lite"))
    ) or ("expected" in low and "'inherit'" in low and "'flash'" in low):
        return {
            "code": "AGY_CLI_SUBAGENT_MODEL_ID_UNSUPPORTED",
            "issue": "#200144",
            "remedy": (
                "Antigravity CLI (agy v1.5.8) rejected an explicit model ID in subagent frontmatter (#200144 — CLI schema only accepts "
                "inherit|flash|pro|flash_lite). Run in Antigravity Desktop App v2.31.2, or switch subagents to inherit for CLI sessions via: "
                "python .agents/harness.py review models set --choice inherit-task --source conversation --proof-reference 'CLI inherit fallback (#200144)'"
            ),
        }
    if (
        ("marked unavailable" in low or "shows unavailable" in low or "model unavailable" in low or "is unavailable" in low or "entitlement" in low)
        and any(tok in low for tok in ("hydrogen", "argon", "gemini 4", "gemini-4"))
        and "503" not in low
    ):
        return {
            "code": "GEMINI4_ENTITLEMENT_DESYNC_UNAVAILABLE",
            "issue": "#200147/#199992",
            "remedy": (
                "Account entitlement desync marked Gemini 4 Hydrogen/Argon as Unavailable (#200147/#199992). "
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
    )
    if is_429 and is_zero_limit:
        return {
            "code": "MANAGED_AGENT_ZERO_QUOTA_429",
            "issue": "#199769/#199770",
            "remedy": (
                "Managed Agent API / tier returned zero Argon/Carbon quota (limit: 0). "
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
                "python .agents/harness.py review models set --choice hydrogen-argon-project --source conversation "
                "--proof-reference \"Upgrade to Hydrogen+Argon (#198333)\" and batch 4-8 parallel view_file reads per turn."
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
        try:
            entries = [e for e in broot.iterdir() if e.is_dir() and not e.is_symlink()]
        except OSError:
            continue
        entries.sort(key=lambda e: e.stat().st_mtime if e.exists() else 0.0, reverse=True)
        for child_dir in entries[:16]:
            tx = prefer_full_transcript(child_dir / ".system_generated" / "logs" / "transcript.jsonl")
            if tx is None or not tx.is_file():
                tx = child_dir / "transcript.jsonl"
            if not tx.is_file():
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
                        "conversation_id": child_dir.name,
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
    """Detect Windows 11 Smart App Control Error 4551 blocking Antigravity IDE v2.7.0 installer (#200037)."""
    import sys as _sys
    environ = env if env is not None else os.environ
    sim_plat = str(environ.get("HARNESS_SIMULATE_PLATFORM") or "").strip().lower()
    is_win = sim_plat == "win32" or (not sim_plat and _sys.platform == "win32")
    if not is_win:
        return {"applicable": False, "at_risk": False, "flagged_artifacts": [], "ide_version": ""}

    ide_ver = str(environ.get("ANTIGRAVITY_IDE_VERSION") or environ.get("AGY_IDE_VERSION") or "").strip()
    sac_err = str(environ.get("ANTIGRAVITY_INSTALLER_ERROR") or "").strip()
    flagged: list[str] = []

    if re.search(r"(?:^|[^0-9])2\.7\.0(?:$|[^0-9])", ide_ver):
        flagged.append(f"ANTIGRAVITY_IDE_VERSION={ide_ver}")
    if "4551" in sac_err or "smart app control" in sac_err.lower():
        flagged.append(f"installer_error={sac_err[:120]}")

    dirs_to_scan: list[Path] = []
    if installer_dirs is not None:
        dirs_to_scan.extend(installer_dirs)
    else:
        home = Path.home()
        for d in (home / "Downloads", Path(environ.get("TEMP") or "") if environ.get("TEMP") else None):
            if d is not None and d.is_dir():
                dirs_to_scan.append(d)

    v270_re = re.compile(r"antigravity.*2[._-]7[._-]0.*\.(?:exe|msi)$", re.IGNORECASE)
    for d in dirs_to_scan:
        if not d.is_dir():
            continue
        try:
            for child in d.iterdir():
                if child.is_file() and v270_re.search(child.name):
                    flagged.append(str(child))
        except OSError:
            continue

    return {
        "applicable": True,
        "at_risk": bool(flagged),
        "flagged_artifacts": flagged[:8],
        "ide_version": ide_ver,
    }

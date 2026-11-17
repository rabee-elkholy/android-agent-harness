"""Write entry files for Google Antigravity and the universal AGENTS.md fallback.

Canonical rules stay in `.agents/rules/harness-rules.md`. This script writes
`AGENTS.md`, `GEMINI.md` (when Antigravity/Gemini is selected), `.agents/agents/*/agent.md`,
and syncs `.agents/hooks.json` with the configured Python interpreter. Legacy managed
files from pre-v1.4 multi-host installs are pruned automatically on update.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _live_process import enable_line_buffered_stdio  # noqa: E402
from _repo_files import ensure_local_git_privacy  # noqa: E402
from harness_shared.commands import configured_python_command  # noqa: E402
from policy_vocab import (  # noqa: E402
    ANTIGRAVITY_REVIEWER_TOOLS,
    ANTIGRAVITY_SCOUT_TOOLS,
    CORE_ROUTED_REVIEWERS,
    CORE_UTILITY_AGENTS,
    ON_DEMAND_SPECIALIST_AGENTS,
)


AGENTS_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = AGENTS_DIR / "tool-adapters"
MANAGED = "<!-- managed-by: android-agent-harness -->\n"
MANAGED_START = "<!-- BEGIN ANDROID-HARNESS MANAGED BLOCK -->"
MANAGED_END = "<!-- END ANDROID-HARNESS MANAGED BLOCK -->"

DEVICE_TEXT = {
    "allow": (
        "Physical device or emulator. Automatically resolved by `run_device.py`. "
        "Prefer a physical device when both are connected. Never hardcode a serial."
    ),
    "physical-only": (
        "Physical device only. Do not use an emulator serial. "
        "Automatically resolved by `run_device.py`. Never hardcode a serial."
    ),
    "emulator-only": (
        "Emulator only. Do not use a physical-device serial. "
        "Automatically resolved by `run_device.py`. Never hardcode a serial."
    ),
}

GIT_TEXT = {
    "never": (
        "The agent must not run `git add`, `commit`, `push`, merge, rebase, stash, or reset. "
        "Leave changes unstaged. Draft a Conventional Commit message only. The developer commits."
    ),
    "agent-may-commit": (
        "The agent may commit when the developer explicitly asks in this chat. "
        "Follow Conventional Commits. Never force-push to main/master."
    ),
}

TOOL_ALIASES = {
    "google-antigravity": "antigravity",
}

# Supported host targets: Antigravity (primary) and Standard AGENTS.md CLI fallback.
TOOL_FILES: dict[str, tuple[str, ...]] = {
    "antigravity": ("GEMINI.md",),
    "gemini": ("GEMINI.md",),
    "generic": (),
}

KNOWN_TOOLS = tuple(TOOL_FILES)

# Legacy pre-v1.4 multi-host tool IDs mapped gracefully to `generic` (`AGENTS.md` only)
# so upgrading an older client checkout never crashes on historical `answers.json` values
# and automatically prunes retired vendor-specific adapter files.
_RETIRED_TOOL_IDS = frozenset({
    "cursor", "claude", "codex", "qwen", "copilot", "vscode", "github-copilot",
    "windsurf", "cline", "roo", "amazonq", "amazon-q", "q", "continue", "junie", "kilo", "goose",
})

LEGACY_PRUNABLE_ADAPTER_PATHS = (
    "CLAUDE.md",
    "CODEX.md",
    "QWEN.md",
    ".cursor/rules/android-harness.mdc",
    ".github/copilot-instructions.md",
    ".github/instructions/android-harness.instructions.md",
    ".github/hooks/android-harness-pre-tool-use.json",
    ".windsurf/rules/android-harness.md",
    ".windsurfrules",
    ".clinerules",
    ".roo/rules/android-harness.md",
    ".amazonq/rules/android-harness.md",
    ".continue/rules/android-harness.md",
    ".junie/guidelines.md",
    ".kilocode/rules/android-harness.md",
    ".goosehints",
)

EMPTY_DIR_CANDIDATES = (
    ".agents/agents/bug-test-reviewer-agent",
    ".agents/agents/security-perf-reviewer-agent",
    ".agents/agents/arch-regression-reviewer-agent",
    ".agents/agents/spec-compliance-agent",
    ".agents/agents/qa-diagnostics-agent",
    ".agents/agents/android-ui-expert-agent",
    ".agents/agents/harness-scout-agent",
    ".agents/agents/harness-worker-agent",
    ".agents/agents",
    ".amazonq/rules",
    ".amazonq",
    ".claude/agents",
    ".claude/commands",
    ".claude",
    ".codex/prompts",
    ".codex",
    ".continue/rules",
    ".continue",
    ".junie",
    ".kilocode/rules",
    ".kilocode",
    ".roo/rules",
    ".roo",
    ".windsurf/rules",
    ".windsurf",
    ".github/instructions",
    ".github/prompts",
    ".github/hooks",
    ".github",
    ".cursor/rules",
    ".cursor",
)

_PM_TRIGGERS = {
    "zoho_sprints": "update zoho",
    "github_projects": "update github",
    "jira_mcp": "update jira",
    "linear_mcp": "update linear",
    "none": "(no tracker — mutations disabled)",
}

_PM_LANG_NOTES = {
    "en_titles_ar_comments": "English task titles, Arabic descriptions/comments.",
    "all_en": "English task titles, descriptions, and comments.",
    "all_ar": "Arabic task titles, descriptions, and comments.",
}


def fill(text: str, mapping: dict[str, str]) -> str:
    out = text
    for key, value in mapping.items():
        out = out.replace("{{" + key + "}}", value)
    leftover = []
    start = 0
    while True:
        i = out.find("{{", start)
        if i < 0:
            break
        j = out.find("}}", i + 2)
        if j < 0:
            break
        leftover.append(out[i : j + 2])
        start = j + 2
    if leftover:
        raise SystemExit(f"Unfilled placeholders: {', '.join(sorted(set(leftover)))}")
    return out


def read_template(name: str) -> str:
    path = TEMPLATES_DIR / name
    if not path.is_file():
        raise SystemExit(f"Missing template: {path}")
    return path.read_text(encoding="utf-8")


def with_managed_marker(body: str) -> str:
    marker = MANAGED.strip()
    if marker in body:
        text = body
    elif body.startswith("---"):
        end = body.find("\n---", 3)
        if end >= 0:
            insert_at = end + len("\n---")
            text = body[:insert_at] + "\n" + MANAGED + body[insert_at:].lstrip("\n")
        else:
            text = MANAGED + body
    else:
        text = MANAGED + body
    if not text.endswith("\n"):
        text += "\n"
    return text


def merge_managed_content(existing_text: str, new_body: str) -> str:
    """Preserve existing user content outside managed markers."""
    harness_block = f"{MANAGED_START}\n{with_managed_marker(new_body).strip()}\n{MANAGED_END}\n"
    if MANAGED_START in existing_text and MANAGED_END in existing_text:
        start_idx = existing_text.find(MANAGED_START)
        end_idx = existing_text.find(MANAGED_END) + len(MANAGED_END)
        prefix = existing_text[:start_idx]
        suffix = existing_text[end_idx:].lstrip("\n")
        combined = prefix.rstrip() + ("\n\n" if prefix.strip() else "") + harness_block
        if suffix:
            combined += "\n" + suffix
        return combined
    legacy_markers = (
        MANAGED.strip(),
        "<!-- managed-by: android-harness-kit -->",
        "<!-- managed-by: android-agent-harness -->",
    )
    if any(marker in existing_text for marker in legacy_markers):
        return with_managed_marker(new_body)
    clean_existing = existing_text.rstrip()
    return f"{clean_existing}\n\n{harness_block}" if clean_existing else with_managed_marker(new_body)


def rel_of(path: Path, repo: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return path.as_posix()


def write_file(path: Path, body: str, *, dry_run: bool, repo: Path, merge_existing: bool = True) -> str:
    if path.is_file() and merge_existing:
        try:
            existing = path.read_text(encoding="utf-8")
            text = merge_managed_content(existing, body)
        except OSError:
            text = with_managed_marker(body)
    else:
        text = with_managed_marker(body)
    rel = rel_of(path, repo)
    if dry_run:
        return f"dry-run {rel} ({len(text)} bytes)"
    encoded = text.encode("utf-8")
    try:
        current_bytes = path.read_bytes() if path.is_file() else None
    except OSError:
        current_bytes = None
    if current_bytes != encoded:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
    return f"wrote {rel}"


def is_managed_file(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        content = path.read_text(encoding="utf-8")
        return (
            MANAGED.strip() in content
            or "<!-- managed-by: android-harness-kit -->" in content
            or MANAGED_START in content
        )
    except OSError:
        return False


def has_legacy_harness_claude_hook(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict):
        return False
    raw = json.dumps(data.get("hooks"))
    return '"_harnessManaged": true' in raw or "cc_pre_tool_safety.py" in raw


def parse_tools(raw: str) -> set[str]:
    parts = [p.strip().lower().replace("_", "-") for p in raw.split(",") if p.strip()]
    if not parts:
        raise SystemExit("Pass --tools with at least one id, or --tools all.")
    if "all" in parts:
        return {"antigravity"}
    selected: set[str] = set()
    unknown: list[str] = []
    for part in parts:
        name = TOOL_ALIASES.get(part, part)
        if name in TOOL_FILES:
            selected.add(name)
        elif name in _RETIRED_TOOL_IDS:
            selected.add("generic")
        else:
            unknown.append(part)
    if unknown:
        known = ", ".join(KNOWN_TOOLS)
        raise SystemExit(f"Unknown --tools: {', '.join(unknown)}. Known: {known}, all")
    return selected


def find_repo(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    candidate = AGENTS_DIR.parent
    if AGENTS_DIR.name in {".agents", "agents"} and (
        (candidate / "gradlew").is_file() or (candidate / "gradlew.bat").is_file()
    ):
        return candidate
    raise SystemExit("Pass --repo <android-checkout> (this script is not inside an app .agents folder).")


def subagents_dir(repo: Path) -> Path:
    local = repo / ".agents" / "subagents"
    if local.is_dir():
        return local
    kit = AGENTS_DIR / "subagents"
    if kit.is_dir():
        return kit
    raise SystemExit("No .agents/subagents (or kit agents/subagents) found.")


def antigravity_agent_markdown(data: dict, *, model: str | None = None) -> str:
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("Custom agent name cannot be empty.")
    description = str(data.get("description") or name).strip()
    prompt = str(data.get("system_prompt") or "").strip()
    if not prompt:
        raise ValueError(f"Custom agent '{name}' system_prompt cannot be empty.")

    name_yaml = json.dumps(name, ensure_ascii=False)
    description_yaml = json.dumps(description, ensure_ascii=False)
    tools_block = "\n".join(f"  - {t}" for t in ANTIGRAVITY_REVIEWER_TOOLS)
    _ = model
    return (
        f"---\n"
        f"name: {name_yaml}\n"
        f"description: {description_yaml}\n"
        f"mainAgent: false\n"
        f"subagent: true\n"
        f"tools:\n"
        f"{tools_block}\n"
        f"---\n\n"
        f"{prompt}\n"
        "\nReviewer fast-execution contract: Blast-radius topology and callers are pre-computed in your review brief/package. "
        "Use at most ONE batched parallel `view_file` turn (4-8 files/ranges, max 2 hops) only when needed to verify a concrete claim, "
        "then emit `HARNESS_REVIEW_RESULT_V2` immediately. Never run shell commands, builds, tests, writes, or sequential single-file reads.\n"
    )


def generate_antigravity_agents(repo: Path, *, dry_run: bool) -> list[str]:
    logs: list[str] = []
    src = subagents_dir(repo)
    for role in CORE_ROUTED_REVIEWERS:
        json_path = src / f"{role}.json"
        if not json_path.is_file():
            raise RuntimeError(f"Missing core subagent source definition: {json_path}")
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Malformed subagent source JSON at {json_path}: {exc}")
        source_name = str(data.get("name") or "").strip()
        if source_name != role:
            raise RuntimeError(f"Subagent source name mismatch in {json_path}: expected '{role}', got '{source_name}'")
        dest = repo / ".agents" / "agents" / role / "agent.md"
        configured_model = None
        try:
            from review_models import compute_task_complexity_tier, frozen_models, load_policy, resolve_antigravity_model
            from reviewer_host import active_reviews
            from workflow import state_root
            from _vnext_common import read_json
            found_active_run = False
            for run, _ in active_reviews(repo):
                if run.get("review_host") == "antigravity":
                    sel = frozen_models(run).get(role, {})
                    if sel:
                        found_active_run = True
                        fm = sel.get("agent_frontmatter_model") or sel.get("resolved_model")
                        if fm and fm != "inherit":
                            configured_model = fm
                        break
            if not found_active_run and configured_model is None:
                active_f = state_root(repo) / "active-task.json"
                active_tid = None
                if active_f.is_file():
                    active_tid = str(read_json(active_f).get("task_id") or "").strip() or None
                pol, src_scope = load_policy(repo, active_tid)
                if src_scope != "default":
                    req_m = pol.get("overrides", {}).get(role, pol.get("default", "inherit"))
                    if req_m and req_m != "inherit":
                        c_tier = compute_task_complexity_tier(repo, active_tid) if active_tid else "SIMPLE"
                        eff = "NORMAL" if req_m in ("hydrogen-argon-hybrid", "safe-cache-hybrid", "hydrogen-dynamic", "flash-argon-hybrid") else ("DEEP" if role == "security-perf-reviewer-agent" else "NORMAL")
                        configured_model, _ = resolve_antigravity_model(req_m, role, eff, complexity_tier=c_tier)
        except Exception:
            configured_model = None
        logs.append(
            write_file(
                dest,
                antigravity_agent_markdown(data, model=configured_model),
                dry_run=dry_run,
                repo=repo,
                merge_existing=False,
            )
        )
    for sp_role in ON_DEMAND_SPECIALIST_AGENTS:
        sp_json = src / f"{sp_role}.json"
        if sp_json.is_file():
            sp_data = json.loads(sp_json.read_text(encoding="utf-8"))
            sp_name = json.dumps(sp_role, ensure_ascii=False)
            sp_desc = json.dumps(str(sp_data.get("description") or sp_role).strip(), ensure_ascii=False)
            sp_tools = "\n".join(f"  - {t}" for t in ANTIGRAVITY_SCOUT_TOOLS)
            sp_prompt = str(sp_data.get("system_prompt") or "").strip()
            sp_md = (
                f"---\nname: {sp_name}\ndescription: {sp_desc}\nmainAgent: false\nsubagent: true\n"
                f"tools:\n{sp_tools}\n---\n\n{sp_prompt}\n"
            )
            logs.append(write_file(repo / ".agents" / "agents" / sp_role / "agent.md", sp_md, dry_run=dry_run, repo=repo, merge_existing=False))
    from delegation_policy import SCOUT_AGENT, render_utility_agent_markdown, resolve_utility_scout_model
    for u_role in CORE_UTILITY_AGENTS:
        u_dest = repo / ".agents" / "agents" / u_role / "agent.md"
        u_model = None
        try:
            if u_role == SCOUT_AGENT:
                u_model = resolve_utility_scout_model(repo)
        except (ImportError, OSError, ValueError, RuntimeError, KeyError, TypeError):
            u_model = None
        logs.append(
            write_file(
                u_dest,
                render_utility_agent_markdown(u_role, model=u_model),
                dry_run=dry_run,
                repo=repo,
                merge_existing=False,
            )
        )
    return logs


def keep_set(selected: set[str]) -> set[str]:
    keep = {"AGENTS.md"}
    for tool in selected:
        keep.update(TOOL_FILES.get(tool, ()))
    if {"antigravity", "gemini"} & set(selected):
        for r in (*CORE_ROUTED_REVIEWERS, *ON_DEMAND_SPECIALIST_AGENTS, *CORE_UTILITY_AGENTS):
            keep.add(f".agents/agents/{r}/agent.md")
    return keep


def _strip_or_delete_managed_file(path: Path, repo: Path, *, dry_run: bool) -> str | None:
    if not is_managed_file(path):
        return None
    rel_s = rel_of(path, repo)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    whole_file_markers = (MANAGED.strip(), "<!-- managed-by: android-harness-kit -->")
    if (
        MANAGED_START in content
        and MANAGED_END in content
        and not content.lstrip().startswith(whole_file_markers)
    ):
        start_idx = content.find(MANAGED_START)
        end_idx = content.find(MANAGED_END) + len(MANAGED_END)
        prefix = content[:start_idx].rstrip()
        suffix = content[end_idx:].strip()
        remaining = (prefix + ("\n\n" if prefix and suffix else "") + suffix).strip()
        if remaining:
            if dry_run:
                return f"dry-run strip-managed-block {rel_s}"
            path.write_bytes((remaining + "\n").encode("utf-8"))
            return f"stripped managed block from {rel_s}"
    if dry_run:
        return f"dry-run delete {rel_s}"
    path.unlink()
    return f"deleted {rel_s}"


def _prune_legacy_claude_settings(repo: Path, *, dry_run: bool) -> str | None:
    settings_path = repo / ".claude" / "settings.json"
    if not has_legacy_harness_claude_hook(settings_path):
        return None
    rel_s = rel_of(settings_path, repo)
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return None
    changed = False
    for event_name in list(hooks.keys()):
        entries = hooks.get(event_name)
        if not isinstance(entries, list):
            continue
        kept = []
        for entry in entries:
            if isinstance(entry, dict) and (
                entry.get("_harnessManaged") is True
                or "cc_pre_tool_safety.py" in json.dumps(entry)
            ):
                changed = True
                continue
            kept.append(entry)
        if kept:
            hooks[event_name] = kept
        else:
            hooks.pop(event_name, None)
    if not changed:
        return None
    if not hooks:
        data.pop("hooks", None)
    if not data:
        if dry_run:
            return f"dry-run delete {rel_s}"
        settings_path.unlink()
        return f"deleted {rel_s}"
    if dry_run:
        return f"dry-run prune-hooks {rel_s}"
    settings_path.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
    return f"pruned legacy hooks from {rel_s}"


def prune_unselected(repo: Path, keep: set[str], selected: set[str], *, dry_run: bool) -> list[str]:
    logs: list[str] = []
    catalog = {"AGENTS.md", "GEMINI.md", *LEGACY_PRUNABLE_ADAPTER_PATHS, ".cursorrules", ".cursor/mcp.json"}
    for rel in sorted(catalog):
        if rel in keep:
            continue
        msg = _strip_or_delete_managed_file(repo / rel, repo, dry_run=dry_run)
        if msg:
            logs.append(msg)
    for legacy_glob in (".claude/agents/*.md", ".claude/commands/*.md", ".github/prompts/*.prompt.md", ".codex/prompts/*.md"):
        for path in sorted(repo.glob(legacy_glob)):
            msg = _strip_or_delete_managed_file(path, repo, dry_run=dry_run)
            if msg:
                logs.append(msg)
    claude_msg = _prune_legacy_claude_settings(repo, dry_run=dry_run)
    if claude_msg:
        logs.append(claude_msg)
    ag_agents_dir = repo / ".agents" / "agents"
    if not ({"antigravity", "gemini"} & set(selected)):
        for r in (*CORE_ROUTED_REVIEWERS, *ON_DEMAND_SPECIALIST_AGENTS, *CORE_UTILITY_AGENTS):
            msg = _strip_or_delete_managed_file(ag_agents_dir / r / "agent.md", repo, dry_run=dry_run)
            if msg:
                logs.append(msg)
    if ag_agents_dir.is_dir():
        for child in sorted(ag_agents_dir.iterdir()):
            if not child.is_dir():
                continue
            if ({"antigravity", "gemini"} & set(selected)) and child.name in (*CORE_ROUTED_REVIEWERS, *ON_DEMAND_SPECIALIST_AGENTS, *CORE_UTILITY_AGENTS):
                continue
            msg = _strip_or_delete_managed_file(child / "agent.md", repo, dry_run=dry_run)
            if msg:
                logs.append(msg)
            if not dry_run and child.is_dir() and not any(child.iterdir()):
                child.rmdir()
                logs.append(f"removed empty {rel_of(child, repo)}")
    if dry_run:
        return logs
    for rel in EMPTY_DIR_CANDIDATES:
        path = repo / rel
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            logs.append(f"removed empty {rel}")
    return logs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    cleaned_argv: list[str] = []
    i = 0
    while i < len(raw_argv):
        arg = raw_argv[i]
        if arg == "--git-gate" and i + 1 < len(raw_argv) and raw_argv[i + 1].lower() in {"yes", "no", "true", "false", "1", "0"}:
            val = raw_argv[i + 1].lower()
            cleaned_argv.append("--git-gate" if val in {"yes", "true", "1"} else "--no-git-gate")
            i += 2
            continue
        if arg.startswith("--git-gate="):
            val = arg.split("=", 1)[1].lower()
            cleaned_argv.append("--git-gate" if val in {"yes", "true", "1"} else "--no-git-gate")
            i += 1
            continue
        cleaned_argv.append(arg)
        i += 1

    known = ", ".join(KNOWN_TOOLS)
    p = argparse.ArgumentParser(description="Install Android Agent Harness entry files for Antigravity and AGENTS.md.")
    p.add_argument("--repo", help="Android checkout root. Default: parent of .agents when installed.")
    p.add_argument("--product", required=True, help="Product display name (e.g. MyApp).")
    p.add_argument("--py", required=True, help="Python command that actually runs here (python or python3).")
    p.add_argument("--assemble", required=True, help="Gradle assemble task (e.g. :composeApp:assembleDebug).")
    p.add_argument("--unit-test", help="Gradle unit-test task. Default: derived from --assemble.")
    p.add_argument("--pm-provider", choices=sorted(_PM_TRIGGERS), default="zoho_sprints")
    p.add_argument("--tracker-language", choices=sorted(_PM_LANG_NOTES), default="en_titles_ar_comments")
    p.add_argument("--tools", default="antigravity", help=f"Comma-separated tool ids or 'all'. Known: {known}")
    p.add_argument("--device-policy", choices=sorted(DEVICE_TEXT), default="allow")
    p.add_argument("--git-policy", choices=sorted(GIT_TEXT), default="never")
    p.add_argument("--device-text", help="Override the generated device-policy sentence.")
    p.add_argument("--git-text", help="Override the generated git-policy sentence.")
    p.add_argument("--dry-run", action="store_true", help="Print paths without writing.")
    p.add_argument("--keep-extra-adapters", action="store_true", help="Do not delete managed legacy adapters.")
    p.add_argument("--git-gate", action=argparse.BooleanOptionalAction, default=False, help=argparse.SUPPRESS)
    return p.parse_args(cleaned_argv)


def _derive_unit_test(assemble: str) -> str:
    task = str(assemble or "").strip()
    if "assemble" not in task:
        return task
    derived = task.replace("assemble", "test", 1)
    if "UnitTest" not in derived:
        derived = re.sub(r"(Debug|Release)$", r"\1UnitTest", derived)
    return derived


def mapping_from_args(args: argparse.Namespace) -> dict[str, str]:
    unit_test = (args.unit_test or "").strip() or _derive_unit_test(args.assemble)
    provider = str(getattr(args, "pm_provider", "zoho_sprints") or "zoho_sprints").strip()
    tracker_lang = str(getattr(args, "tracker_language", "en_titles_ar_comments") or "en_titles_ar_comments").strip()
    if provider not in _PM_TRIGGERS:
        provider = "zoho_sprints"
    if tracker_lang not in _PM_LANG_NOTES:
        tracker_lang = "en_titles_ar_comments"
    pm_language_note = "No tracker integration is configured." if provider == "none" else _PM_LANG_NOTES[tracker_lang]
    return {
        "PRODUCT": args.product.strip(),
        "PY": configured_python_command(args.py),
        "ASSEMBLE": args.assemble.strip(),
        "UNIT_TEST": unit_test,
        "DEVICE_POLICY": (args.device_text or DEVICE_TEXT[args.device_policy]).strip(),
        "GIT_POLICY": (args.git_text or GIT_TEXT[args.git_policy]).strip(),
        "PM_TRIGGER": _PM_TRIGGERS[provider],
        "PM_LANG_NOTE": pm_language_note,
    }


def cleanup_legacy_git_gate(repo: Path, *, dry_run: bool = False) -> list[str]:
    logs: list[str] = []
    githooks_dir = repo / ".githooks"
    marker_tokens = ("managed-by: android-agent-harness", "managed-by: android-harness-kit")
    removable: list[Path] = []
    preserved: list[Path] = []
    if githooks_dir.is_dir():
        for hook in sorted(path for path in githooks_dir.rglob("*") if path.is_file()):
            try:
                head = hook.read_text(encoding="utf-8", errors="replace")[:4096].lower()
            except OSError:
                preserved.append(hook)
                continue
            (removable if any(token in head for token in marker_tokens) else preserved).append(hook)

    for hook in removable:
        rel = rel_of(hook, repo)
        if dry_run:
            logs.append(f"dry-run remove harness-owned legacy hook {rel}")
        else:
            hook.unlink(missing_ok=True)
            logs.append(f"removed harness-owned legacy hook {rel}")

    if preserved:
        logs.append(f"preserved {len(preserved)} project-owned .githooks file(s)")

    remaining_files = preserved
    proc = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip() in (".githooks", ".githooks/") and not remaining_files:
        if dry_run:
            logs.append("dry-run git config --unset core.hooksPath")
        else:
            subprocess.run(["git", "config", "--unset", "core.hooksPath"], cwd=str(repo), capture_output=True, check=False)
            logs.append("unset git core.hooksPath")

    if githooks_dir.is_dir() and not remaining_files:
        if dry_run:
            logs.append(f"dry-run remove empty {rel_of(githooks_dir, repo)}")
        else:
            try:
                githooks_dir.rmdir()
                logs.append(f"removed empty legacy {rel_of(githooks_dir, repo)}")
            except Exception as e:
                logs.append(f"warning: could not remove {githooks_dir}: {e}")

    logs.extend(ensure_local_git_privacy(repo))
    return logs


def sync_hooks_json(repo: Path, py: str, *, dry_run: bool) -> list[str]:
    """Apply the configured interpreter to managed hook templates."""
    from harness_shared.commands import rewrite_python_hooks
    hooks_path = repo / ".agents" / "hooks.json"
    if not hooks_path.is_file():
        return []
    data = json.loads(hooks_path.read_text(encoding="utf-8"))
    if not rewrite_python_hooks(data, configured_python_command(py)):
        return []
    if dry_run:
        return ["dry-run rewrite .agents/hooks.json commands with the configured python"]
    hooks_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    return ["rewrote .agents/hooks.json commands to use the configured python"]


def install(args: argparse.Namespace) -> list[str]:
    if not TEMPLATES_DIR.is_dir():
        raise SystemExit(f"Templates missing: {TEMPLATES_DIR}")
    selected = parse_tools(args.tools)
    repo = find_repo(args.repo)
    mapping = mapping_from_args(args)
    logs: list[str] = []

    keep = keep_set(selected)
    if not args.keep_extra_adapters:
        prune_logs = prune_unselected(repo, keep, selected, dry_run=args.dry_run)
        logs.extend(prune_logs)
        deleted = [x for x in prune_logs if x.startswith(("deleted ", "removed "))]
        if deleted:
            logs.append(
                f"pruned {len(deleted)} managed adapter file(s) for unselected tools "
                "(re-run with --keep-extra-adapters to retain them)."
            )

    logs.append(
        write_file(
            repo / "AGENTS.md",
            fill(read_template("AGENTS.md.template"), mapping),
            dry_run=args.dry_run,
            repo=repo,
        )
    )
    logs.extend(sync_hooks_json(repo, mapping["PY"], dry_run=args.dry_run))
    if {"antigravity", "gemini"} & set(selected):
        logs.append(
            write_file(
                repo / "GEMINI.md",
                fill(read_template("GEMINI.md.template"), mapping),
                dry_run=args.dry_run,
                repo=repo,
            )
        )
        logs.extend(generate_antigravity_agents(repo, dry_run=args.dry_run))
    logs.extend(cleanup_legacy_git_gate(repo, dry_run=args.dry_run))
    logs.append(f"tools: {', '.join(sorted(selected))}")
    return logs


def main(argv: list[str] | None = None) -> int:
    enable_line_buffered_stdio()
    args = parse_args(argv)
    logs = install(args)
    for line in logs:
        print(line)
    print(f"adapter files: {len([x for x in logs if x.startswith(('wrote ', 'dry-run '))])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Write entry files for the coding agents the developer actually uses.

Canonical rules stay in `.agents/rules/harness-rules.md`. This script writes thin
adapters only for `--tools` (and always `AGENTS.md`). Re-run with a new list to
add a tool. Managed files for tools that were not selected are removed.

Usage (from an installed app checkout):

    python .agents/scripts/install_tool_adapters.py --product MyApp --py python --assemble :app:assembleDebug --tools cursor,gemini

Usage (from the kit, targeting an app):

    python agents/scripts/install_tool_adapters.py --repo /path/to/app --product MyApp --py python3 --assemble :<module>:assembleDebug --tools all
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = AGENTS_DIR / "tool-adapters"
COMMAND_PACKS_DIR = AGENTS_DIR / "command-packs"
MANAGED = "<!-- managed-by: android-harness-kit -->\n"
SKIP_SUBAGENTS = {
    "code-review-guard-agent",
    "review-prompt",
    "re-review-prompt",
}

DEVICE_TEXT = {
    "allow": (
        "Physical device or emulator. Resolve the serial with `adb devices`. "
        "Prefer a physical device when both are connected. Never hardcode a serial."
    ),
    "physical-only": (
        "Physical device only. Do not use an emulator serial. "
        "Resolve the serial with `adb devices`. Never hardcode a serial."
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

CLAUDE_READ_TOOLS = "Read, Grep, Glob"

TOOL_ALIASES = {
    "antigravity": "gemini",
    "google-antigravity": "gemini",
    "vscode": "copilot",
    "github-copilot": "copilot",
    "amazon-q": "amazonq",
    "q": "amazonq",
}

# Files the installer may create. Shared AGENTS.md is always kept when any tool is selected.
TOOL_FILES: dict[str, tuple[str, ...]] = {
    "cursor": (".cursor/rules/android-harness.mdc",),
    "claude": ("CLAUDE.md",),
    "gemini": ("GEMINI.md",),
    "codex": ("CODEX.md",),
    "qwen": ("QWEN.md",),
    "copilot": (
        ".github/copilot-instructions.md",
        ".github/instructions/android-harness.instructions.md",
        ".github/hooks/android-harness-pre-tool-use.json",
    ),
    "windsurf": (".windsurf/rules/android-harness.md", ".windsurfrules"),
    "cline": (".clinerules",),
    "roo": (".roo/rules/android-harness.md",),
    "amazonq": (".amazonq/rules/android-harness.md",),
    "continue": (".continue/rules/android-harness.md",),
    "junie": (".junie/guidelines.md",),
    "kilo": (".kilocode/rules/android-harness.md",),
    "goose": (".goosehints",),
}

KNOWN_TOOLS = tuple(TOOL_FILES)

COMMAND_DIRS: dict[str, tuple[str, str]] = {
    "claude": (".claude/commands", "{}.md"),
    "copilot": (".github/prompts", "{}.prompt.md"),
    "codex": (".codex/prompts", "{}.md"),
}

EMPTY_DIR_CANDIDATES = (
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
    ".github",
    ".cursor/rules",
    ".cursor",
)


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


def _pack_name(tmpl: Path) -> str:
    name = tmpl.name
    return name[: -len(".md.template")] if name.endswith(".md.template") else tmpl.stem


def command_pack_templates() -> list[Path]:
    if not COMMAND_PACKS_DIR.is_dir():
        return []
    return sorted(COMMAND_PACKS_DIR.glob("*.template"))


def command_pack_rels(tool: str) -> list[str]:
    spec = COMMAND_DIRS.get(tool)
    if not spec:
        return []
    base, pattern = spec
    return [f"{base}/{pattern.format(_pack_name(tmpl))}" for tmpl in command_pack_templates()]


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            return text[end + 4 :].lstrip("\n")
    return text


def generate_command_packs(repo: Path, tool: str, mapping: dict[str, str], *, dry_run: bool) -> list[str]:
    logs: list[str] = []
    for tmpl in command_pack_templates():
        text = tmpl.read_text(encoding="utf-8")
        if tool == "codex":
            text = strip_frontmatter(text)
        base, pattern = COMMAND_DIRS[tool]
        rel = f"{base}/{pattern.format(_pack_name(tmpl))}"
        logs.append(write_file(repo / rel, fill(text, mapping), dry_run=dry_run, repo=repo))
    return logs


MANAGED_START = "<!-- BEGIN ANDROID-HARNESS MANAGED BLOCK -->"
MANAGED_END = "<!-- END ANDROID-HARNESS MANAGED BLOCK -->"


def with_managed_marker(body: str) -> str:
    """Keep YAML frontmatter first; keep @imports first (Claude / Qwen)."""
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
    elif body.startswith("@"):
        nl = body.find("\n")
        if nl >= 0:
            rest = body[nl + 1 :].lstrip("\n")
            text = body[: nl + 1] + MANAGED + rest
        else:
            text = body + "\n" + MANAGED
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
    if MANAGED.strip() in existing_text:
        return with_managed_marker(new_body)
    clean_existing = existing_text.rstrip()
    return f"{clean_existing}\n\n{harness_block}" if clean_existing else with_managed_marker(new_body)


def rel_of(path: Path, repo: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return path.as_posix()


def write_file(path: Path, body: str, *, dry_run: bool, repo: Path) -> str:
    if path.is_file():
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return f"wrote {rel}"


def is_managed_file(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        content = path.read_text(encoding="utf-8")
        return MANAGED.strip() in content or MANAGED_START in content
    except OSError:
        return False


def parse_tools(raw: str) -> set[str]:
    parts = [p.strip().lower().replace("_", "-") for p in raw.split(",") if p.strip()]
    if not parts:
        raise SystemExit("Pass --tools with at least one id, or --tools all.")
    if "all" in parts:
        return set(KNOWN_TOOLS)
    selected: set[str] = set()
    unknown: list[str] = []
    for part in parts:
        name = TOOL_ALIASES.get(part, part)
        if name not in TOOL_FILES:
            unknown.append(part)
            continue
        selected.add(name)
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


def claude_agent_markdown(data: dict) -> str:
    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or name).strip()
    prompt = str(data.get("system_prompt") or "").strip()
    tools = CLAUDE_READ_TOOLS
    if data.get("enable_write_tools"):
        tools = f"{CLAUDE_READ_TOOLS}, Edit, Write"
    model = str(data.get("model") or "inherit").strip() or "inherit"
    return (
        f"---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"tools: {tools}\n"
        f"model: {model}\n"
        f"---\n\n"
        f"{prompt}\n"
    )


def generate_claude_agents(repo: Path, *, dry_run: bool) -> list[str]:
    logs: list[str] = []
    src = subagents_dir(repo)
    dest = repo / ".claude" / "agents"
    for json_path in sorted(src.glob("*.json")):
        stem = json_path.stem
        if stem in SKIP_SUBAGENTS:
            continue
        data = json.loads(json_path.read_text(encoding="utf-8"))
        name = str(data.get("name") or stem).strip()
        if name in SKIP_SUBAGENTS:
            continue
        if not data.get("system_prompt"):
            logs.append(f"skip {json_path.name} (no system_prompt)")
            continue
        logs.append(
            write_file(dest / f"{name}.md", claude_agent_markdown(data), dry_run=dry_run, repo=repo)
        )
    return logs


def bodies_for_tool(tool: str, mapping: dict[str, str], pointer: str) -> dict[str, str]:
    if tool == "cursor":
        return {
            ".cursor/rules/android-harness.mdc": fill(
                read_template("cursor-android-harness.mdc.template"), mapping
            )
        }
    if tool == "claude":
        return {"CLAUDE.md": fill(read_template("CLAUDE.md.template"), mapping)}
    if tool == "gemini":
        return {"GEMINI.md": fill(read_template("GEMINI.md.template"), mapping)}
    if tool == "codex":
        return {"CODEX.md": fill(read_template("CODEX.md.template"), mapping)}
    if tool == "qwen":
        return {"QWEN.md": fill(read_template("QWEN.md.template"), mapping)}
    if tool == "copilot":
        return {
            ".github/copilot-instructions.md": fill(
                read_template("copilot-instructions.md.template"), mapping
            ),
            ".github/instructions/android-harness.instructions.md": fill(
                read_template("github-instructions.md.template"), mapping
            ),
        }
    if tool == "windsurf":
        return {
            ".windsurf/rules/android-harness.md": fill(
                read_template("windsurf-android-harness.md.template"), mapping
            ),
            ".windsurfrules": pointer,
        }
    if tool == "continue":
        return {
            ".continue/rules/android-harness.md": fill(
                read_template("continue-android-harness.md.template"), mapping
            )
        }
    out: dict[str, str] = {}
    for rel in TOOL_FILES[tool]:
        out[rel] = pointer
    return out


def keep_set(selected: set[str]) -> set[str]:
    keep = {"AGENTS.md"}
    for tool in selected:
        keep.update(TOOL_FILES[tool])
        keep.update(command_pack_rels(tool))
    return keep


def prune_unselected(repo: Path, keep: set[str], selected: set[str], *, dry_run: bool) -> list[str]:
    logs: list[str] = []
    catalog = {"AGENTS.md"}
    for files in TOOL_FILES.values():
        catalog.update(files)
    for tool in COMMAND_DIRS:
        catalog.update(command_pack_rels(tool))
    for rel in sorted(catalog):
        if rel in keep:
            continue
        path = repo / rel
        if not is_managed_file(path):
            continue
        rel_s = rel_of(path, repo)
        if dry_run:
            logs.append(f"dry-run delete {rel_s}")
            continue
        path.unlink()
        logs.append(f"deleted {rel_s}")
    claude_dir = repo / ".claude" / "agents"
    if "claude" not in selected and claude_dir.is_dir():
        for path in sorted(claude_dir.glob("*.md")):
            if not is_managed_file(path):
                continue
            rel_s = rel_of(path, repo)
            if dry_run:
                logs.append(f"dry-run delete {rel_s}")
                continue
            path.unlink()
            logs.append(f"deleted {rel_s}")
    if dry_run:
        return logs
    for rel in EMPTY_DIR_CANDIDATES:
        path = repo / rel
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            logs.append(f"removed empty {rel}")
    return logs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    known = ", ".join(KNOWN_TOOLS)
    p = argparse.ArgumentParser(description="Install selected Android harness adapters.")
    p.add_argument("--repo", help="Android checkout root. Default: parent of .agents when installed.")
    p.add_argument("--product", required=True, help="Product display name (e.g. MyApp).")
    p.add_argument("--py", required=True, help="Python command that actually runs here (python or python3).")
    p.add_argument("--assemble", required=True, help="Gradle assemble task (e.g. :composeApp:assembleDebug).")
    p.add_argument(
        "--tools",
        required=True,
        help=f"Comma-separated tool ids the developer uses, or 'all'. Known: {known}",
    )
    p.add_argument(
        "--device-policy",
        choices=sorted(DEVICE_TEXT),
        default="allow",
        help="I.4 device policy. Default: allow emulator.",
    )
    p.add_argument(
        "--git-policy",
        choices=sorted(GIT_TEXT),
        default="never",
        help="I.3 git policy. Default: agent never commits.",
    )
    p.add_argument("--device-text", help="Override the generated device-policy sentence.")
    p.add_argument("--git-text", help="Override the generated git-policy sentence.")
    p.add_argument("--dry-run", action="store_true", help="Print paths without writing.")
    p.add_argument("--skip-claude-agents", action="store_true", help="Do not generate .claude/agents/*.md.")
    p.add_argument(
        "--keep-extra-adapters",
        action="store_true",
        help="Do not delete managed adapters for tools that were not selected.",
    )
    p.add_argument(
        "--git-gate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write .githooks/pre-commit staged-changes quality gate and set core.hooksPath (default ON; --no-git-gate to opt out).",
    )
    p.add_argument(
        "--cc-hooks",
        action="store_true",
        help="Register the Claude Code PreToolUse bridge (requires --tools to include claude).",
    )
    p.add_argument(
        "--copilot-hooks",
        action="store_true",
        help="Register the GitHub Copilot preToolUse bridge under .github/hooks/ (requires --tools to include copilot).",
    )
    return p.parse_args(argv)


def mapping_from_args(args: argparse.Namespace) -> dict[str, str]:
    return {
        "PRODUCT": args.product.strip(),
        "PY": args.py.strip(),
        "ASSEMBLE": args.assemble.strip(),
        "DEVICE_POLICY": (args.device_text or DEVICE_TEXT[args.device_policy]).strip(),
        "GIT_POLICY": (args.git_text or GIT_TEXT[args.git_policy]).strip(),
    }


GIT_GATE_HOOK = """#!/usr/bin/env python
import os
import subprocess
import sys

top = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
).stdout.strip()
gate = os.path.join(top, ".agents", "scripts", "pre_commit_gate.py")
if not os.path.isfile(gate):
    sys.exit(0)
res = subprocess.run([sys.executable, gate], cwd=top)
sys.exit(res.returncode)
"""

CC_HOOK_COMMAND = "{py} .agents/scripts/cc_pre_tool_safety.py"

COPILOT_HOOKS_FILE = ".github/hooks/android-harness-pre-tool-use.json"


def copilot_hooks_payload(py: str) -> dict:
    return {
        "version": 1,
        "_comment": "<!-- managed-by: android-harness-kit -->",
        "hooks": {
            "preToolUse": [
                {
                    "type": "command",
                    "matcher": "bash|powershell",
                    "command": f"{py} .agents/scripts/copilot_pre_tool_safety.py",
                    "timeoutSec": 15,
                }
            ]
        },
    }


def install_git_gate(repo: Path, *, dry_run: bool) -> list[str]:
    logs: list[str] = []
    hook_path = repo / ".githooks" / "pre-commit"
    if dry_run:
        logs.append(f"dry-run write {rel_of(hook_path, repo)}")
        logs.append("dry-run git config core.hooksPath .githooks")
        logs.append("dry-run exclude .githooks/ in .git/info/exclude")
        return logs
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(GIT_GATE_HOOK, encoding="utf-8", newline="\n")
    logs.append(f"wrote {rel_of(hook_path, repo)}")
    proc = subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        logs.append("git core.hooksPath -> .githooks")
    else:
        logs.append("WARNING: could not set core.hooksPath; run: git config core.hooksPath .githooks")

    # Automatically exclude all harness rules, manifests, and adapter directories in .git/info/exclude
    # so they remain 100% local to this machine and NEVER pollute shared team branches or appear in Android Studio Git.
    exclude_path = repo / ".git" / "info" / "exclude"
    if (repo / ".git").is_dir() or exclude_path.is_file():
        try:
            exclude_path.parent.mkdir(parents=True, exist_ok=True)
            text = exclude_path.read_text(encoding="utf-8") if exclude_path.is_file() else ""
            lines = [ln.strip() for ln in text.splitlines()]
            local_patterns = [
                ".agents/",
                ".harness-setup/",
                ".harness-backup/",
                ".harness-backups/",
                ".githooks/",
                "AGENTS.md",
                "GEMINI.md",
                "CLAUDE.md",
                "CODEX.md",
                "QWEN.md",
                ".cursor/",
                ".cursorrules",
                ".windsurf/",
                ".windsurfrules",
                ".claude/",
                ".clinerules",
                ".amazonq/",
                ".continue/",
                ".junie/",
                ".kilocode/",
                ".roo/",
                ".goosehints",
                "*.diff",
                "*.patch",
                "*.secret",
            ]
            added = []
            for pat in local_patterns:
                if pat not in lines and pat.rstrip("/") not in lines:
                    added.append(pat)
            if added:
                with exclude_path.open("a", encoding="utf-8", newline="\n") as f:
                    if text and not text.endswith("\n"):
                        f.write("\n")
                    f.write("# Android Harness Kit — Local AI Manifests & Transient State\n")
                    for pat in added:
                        f.write(f"{pat}\n")
                logs.append(f"git exclude -> .git/info/exclude ({len(added)} harness patterns)")
        except Exception:
            pass

    # If any harness adapter is accidentally tracked in git index, mark assume-unchanged so working tree stays clean
    for tracked_cand in [".githooks/pre-commit", "AGENTS.md", "GEMINI.md", "CLAUDE.md"]:
        subprocess.run(
            ["git", "update-index", "--assume-unchanged", tracked_cand],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
    return logs


def ensure_cc_hooks(repo: Path, py: str, *, dry_run: bool) -> list[str]:
    settings_path = repo / ".claude" / "settings.json"
    rel = rel_of(settings_path, repo)
    data: dict = {}
    if settings_path.is_file():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            return [f"skip {rel}: existing settings.json is not valid JSON; merge the hook manually"]

    groups = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
    command = CC_HOOK_COMMAND.format(py=py)
    for group in groups:
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks") or []:
            if isinstance(hook, dict) and "cc_pre_tool_safety.py" in str(hook.get("command", "")):
                return [f"skip {rel}: harness PreToolUse bridge already registered"]

    new_group = {
        "matcher": "Bash",
        "_harnessManaged": True,
        "hooks": [{"type": "command", "command": command, "timeout": 15}],
    }
    if dry_run:
        logs = [f"dry-run merge PreToolUse(Bash) into {rel}"]
        return logs
    groups.append(new_group)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return [f"merged PreToolUse(Bash) bridge into {rel}"]


def ensure_copilot_hooks(repo: Path, py: str, *, dry_run: bool) -> list[str]:
    hooks_path = repo / COPILOT_HOOKS_FILE
    rel = rel_of(hooks_path, repo)
    payload = copilot_hooks_payload(py)
    if dry_run:
        return [f"dry-run write {rel} (preToolUse -> copilot_pre_tool_safety.py)"]
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return [f"wrote {rel} (Copilot preToolUse bridge)"]


def install(args: argparse.Namespace) -> list[str]:
    if not TEMPLATES_DIR.is_dir():
        raise SystemExit(f"Templates missing: {TEMPLATES_DIR}")
    selected = parse_tools(args.tools)
    repo = find_repo(args.repo)
    mapping = mapping_from_args(args)
    pointer = fill(read_template("pointer.md.template"), mapping)
    logs: list[str] = []

    keep = keep_set(selected)
    if not args.keep_extra_adapters:
        logs.extend(prune_unselected(repo, keep, selected, dry_run=args.dry_run))

    logs.append(
        write_file(
            repo / "AGENTS.md",
            fill(read_template("AGENTS.md.template"), mapping),
            dry_run=args.dry_run,
            repo=repo,
        )
    )
    for tool in sorted(selected):
        for rel, body in bodies_for_tool(tool, mapping, pointer).items():
            logs.append(write_file(repo / rel, body, dry_run=args.dry_run, repo=repo))
        if tool in COMMAND_DIRS:
            logs.extend(generate_command_packs(repo, tool, mapping, dry_run=args.dry_run))
    if "claude" in selected and not args.skip_claude_agents:
        logs.extend(generate_claude_agents(repo, dry_run=args.dry_run))
    if getattr(args, "git_gate", True):
        logs.extend(install_git_gate(repo, dry_run=args.dry_run))
    if getattr(args, "cc_hooks", False) and "claude" in selected:
        logs.extend(ensure_cc_hooks(repo, mapping["PY"], dry_run=args.dry_run))
    if getattr(args, "copilot_hooks", False) and "copilot" in selected:
        logs.extend(ensure_copilot_hooks(repo, mapping["PY"], dry_run=args.dry_run))
    logs.append(f"tools: {', '.join(sorted(selected))}")
    return logs


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logs = install(args)
    for line in logs:
        print(line)
    print(f"adapter files: {len([x for x in logs if x.startswith(('wrote ', 'dry-run '))])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

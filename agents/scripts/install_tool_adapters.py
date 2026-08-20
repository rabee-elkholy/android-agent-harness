"""Write entry files for the coding agents the developer actually uses.

Canonical rules stay in `.agents/rules/harness-rules.md`. This script writes thin
adapters only for `--tools` (and always `AGENTS.md`). Re-run with a new list to
add a tool. Managed files for tools that were not selected are removed.

Usage (from an installed app checkout):

    python .agents/scripts/install_tool_adapters.py --product Qosousa --py python --assemble :composeApp:assembleDebug --tools cursor,gemini

Usage (from the kit, targeting an app):

    python agents/scripts/install_tool_adapters.py --repo /path/to/app --product MyApp --py python3 --assemble :<module>:assembleDebug --tools all
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = AGENTS_DIR / "tool-adapters"
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
EMPTY_DIR_CANDIDATES = (
    ".amazonq/rules",
    ".amazonq",
    ".claude/agents",
    ".claude",
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


def rel_of(path: Path, repo: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return path.as_posix()


def write_file(path: Path, body: str, *, dry_run: bool, repo: Path) -> str:
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
        return MANAGED.strip() in path.read_text(encoding="utf-8")
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
    return keep


def prune_unselected(repo: Path, keep: set[str], selected: set[str], *, dry_run: bool) -> list[str]:
    logs: list[str] = []
    catalog = {"AGENTS.md"}
    for files in TOOL_FILES.values():
        catalog.update(files)
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
    p.add_argument("--product", required=True, help="Product display name (e.g. Qosousa).")
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
    return p.parse_args(argv)


def mapping_from_args(args: argparse.Namespace) -> dict[str, str]:
    return {
        "PRODUCT": args.product.strip(),
        "PY": args.py.strip(),
        "ASSEMBLE": args.assemble.strip(),
        "DEVICE_POLICY": (args.device_text or DEVICE_TEXT[args.device_policy]).strip(),
        "GIT_POLICY": (args.git_text or GIT_TEXT[args.git_policy]).strip(),
    }


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
    if "claude" in selected and not args.skip_claude_agents:
        logs.extend(generate_claude_agents(repo, dry_run=args.dry_run))
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

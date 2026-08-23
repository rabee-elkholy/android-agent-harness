"""Wire Zoho Sprints MCP into an Android checkout. Never copy tokens."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp" / "zoho_sprints"))
from _config import (  # noqa: E402
    ENV_CONFIG,
    SERVER_NAME,
    example_config_path,
    json_contains_secret_keys,
    kit_server_path,
    resolve_config_path,
    text_contains_secret_values,
)

EXAMPLE_NAME = "config.example.json"


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _dump_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if json_contains_secret_keys(data):
        raise SystemExit(f"Refusing to write secrets into {path}")
    path.write_text(text, encoding="utf-8")


def _ensure_gitignore(path: Path, extra: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    for line in extra:
        if line not in lines:
            lines.append(line)
    text = "\n".join(lines)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def write_example_if_missing(agents_root: Path) -> Path | None:
    src = agents_root / "mcp" / "zoho_sprints" / EXAMPLE_NAME
    dest = example_config_path()
    if dest.is_file() or not src.is_file():
        return dest if dest.is_file() else None
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest


def mcp_entry(py: str, server: Path, config_path: Path | None) -> dict:
    entry: dict = {"command": py, "args": [str(server)]}
    if config_path is not None:
        entry["env"] = {ENV_CONFIG: str(config_path)}
    if json_contains_secret_keys(entry):
        raise SystemExit("Refusing to put Zoho secret keys into MCP entry.")
    return entry


def merge_server(path: Path, entry: dict | None) -> None:
    data = _load_json(path)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    if entry is None:
        servers.pop(SERVER_NAME, None)
    else:
        servers[SERVER_NAME] = entry
    _dump_json(path, data)


def install(
    repo: Path,
    py: str,
    enable: bool,
    tools: list[str],
    dry_run: bool = False,
) -> list[str]:
    logs: list[str] = []
    agents = repo / ".agents" if (repo / ".agents").is_dir() else repo / "agents"
    server = kit_server_path(agents)
    mcp_path = agents / "mcp_config.json"
    cursor_mcp = repo / ".cursor" / "mcp.json"
    if not enable:
        if dry_run:
            logs.append(f"would clear {SERVER_NAME} from {mcp_path}")
            return logs
        merge_server(mcp_path, None)
        if cursor_mcp.is_file():
            merge_server(cursor_mcp, None)
        logs.append(f"cleared {SERVER_NAME} from project MCP configs")
        return logs
    if not server.is_file():
        raise SystemExit(f"Zoho Sprints server missing: {server}")
    config_path = resolve_config_path()
    example = None
    if config_path is None and not dry_run:
        example = write_example_if_missing(agents)
    entry = mcp_entry(py, server.resolve(), config_path)
    if dry_run:
        logs.append(f"would write {mcp_path}")
        if "cursor" in tools:
            logs.append(f"would merge {cursor_mcp}")
        logs.append(f"config: {'reuse ' + str(config_path) if config_path else 'missing — example only'}")
        return logs
    merge_server(mcp_path, entry)
    if config_path and text_contains_secret_values(mcp_path.read_text(encoding="utf-8"), config_path):
        mcp_path.write_text('{"mcpServers": {}}\n', encoding="utf-8")
        raise SystemExit("Aborted: MCP config would have contained Zoho token values.")
    _ensure_gitignore(
        agents / ".gitignore",
        ["state/", "scripts/__pycache__/", "mcp/zoho_sprints/__pycache__/", "mcp/zoho_sprints/zoho_config.json"],
    )
    if "cursor" in tools:
        merge_server(cursor_mcp, entry)
        if config_path and text_contains_secret_values(cursor_mcp.read_text(encoding="utf-8"), config_path):
            merge_server(cursor_mcp, None)
            raise SystemExit("Aborted: Cursor MCP config would have contained Zoho token values.")
        gi = repo / ".gitignore"
        _ensure_gitignore(gi, [".cursor/mcp.json"])
    logs.append(f"wired {SERVER_NAME} -> {server}")
    if config_path:
        logs.append(f"credentials path (not copied): {config_path}")
    else:
        logs.append(
            "no Zoho credentials file on this PC. Fill "
            f"{example or '~/.android-harness/zoho_sprints.example.json'} "
            "into ~/.android-harness/zoho_sprints.json. Never commit it."
        )
    return logs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Install or remove the Zoho Sprints MCP wiring.")
    p.add_argument("--repo", required=True, help="Android checkout root.")
    p.add_argument("--py", default="python", help="Python command for the MCP server.")
    p.add_argument("--enable", action="store_true", help="Wire Zoho Sprints MCP.")
    p.add_argument("--disable", action="store_true", help="Remove Zoho Sprints MCP from this checkout.")
    p.add_argument("--tools", default="", help="Comma-separated tool ids (cursor writes .cursor/mcp.json).")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.enable == args.disable:
        raise SystemExit("Pass exactly one of --enable or --disable.")
    tools = [x.strip() for x in args.tools.split(",") if x.strip()]
    logs = install(Path(args.repo).resolve(), args.py, args.enable, tools, dry_run=args.dry_run)
    for line in logs:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Locate the user-level Zoho Sprints config. Never copy or print secrets."""
from __future__ import annotations

import os
from pathlib import Path

SECRET_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "client_secret",
        "client_id",
        "api_key",
        "token",
        "password",
    }
)

ENV_CONFIG = "ZOHO_SPRINTS_CONFIG"
SERVER_NAME = "zoho-sprints"


def home_config_path() -> Path:
    return Path.home() / ".android-harness" / "zoho_sprints.json"


def example_config_path() -> Path:
    return Path.home() / ".android-harness" / "zoho_sprints.example.json"


def scratch_config_path() -> Path:
    return (
        Path.home()
        / ".gemini"
        / "antigravity"
        / "scratch"
        / "zoho_sprints"
        / "zoho_config.json"
    )


def candidate_config_paths() -> list[Path]:
    paths: list[Path] = []
    env = (os.environ.get(ENV_CONFIG) or "").strip()
    if env:
        paths.append(Path(env).expanduser())
    paths.append(home_config_path())
    paths.append(scratch_config_path())
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(path)
    return out


def resolve_config_path() -> Path | None:
    for path in candidate_config_paths():
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def kit_server_path(agents_root: Path) -> Path:
    return agents_root / "mcp" / "zoho_sprints" / "server.py"


def json_contains_secret_keys(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in SECRET_KEYS:
                return True
            if json_contains_secret_keys(child):
                return True
        return False
    if isinstance(value, list):
        return any(json_contains_secret_keys(item) for item in value)
    return False


def text_contains_secret_values(text: str, secret_file: Path) -> bool:
    """True if any nonempty string value from secret_file appears in text."""
    import json

    try:
        data = json.loads(secret_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    for key, raw in data.items():
        if str(key).lower() not in SECRET_KEYS:
            continue
        if not isinstance(raw, str):
            continue
        token = raw.strip()
        if len(token) >= 8 and token in text:
            return True
    return False

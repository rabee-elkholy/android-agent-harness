"""Validate managed Antigravity rule activation without a YAML dependency.

The checked files are a deliberately small managed schema. User-authored rules
are not rewritten or rejected by this helper. Host/runtime enforcement still
comes from actual hook capabilities, not from these static checks.
"""
from __future__ import annotations

from pathlib import Path
import re

MANAGED_RULES = {"harness-rules.md": "always_on", "compose-context.md": "glob",
                 "kmp-context.md": "glob", "gradle-context.md": "glob"}


def rule_errors(agents_root: Path) -> list[str]:
    errors = []
    for name, expected in MANAGED_RULES.items():
        path = agents_root / "rules" / name
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append(f"{name}: missing or unreadable managed rule; repair/update the kit.")
            continue
        if not content.startswith("---\n") or "\n---\n" not in content[4:]:
            errors.append(f"{name}: missing YAML frontmatter.")
            continue
        header = content.split("---", 2)[1]
        triggers = re.findall(r"^trigger:\s*([^\n]+)", header, re.MULTILINE)
        if triggers != [expected]:
            errors.append(f"{name}: expected trigger: {expected}; unsupported activation may be silently ignored by Antigravity.")
        if expected == "glob":
            patterns = re.findall(r'^globs:\s*"([^"\n]+)"\s*$', header, re.MULTILINE)
            if len(patterns) != 1 or any(not part.strip() for part in patterns[0].split(",")):
                errors.append(f"{name}: expected a quoted comma-separated globs string.")
        if not re.search(r"^description:\s*\S", header, re.MULTILINE):
            errors.append(f"{name}: missing description.")
    return errors

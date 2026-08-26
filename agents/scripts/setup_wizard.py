"""Record setup answers so install does not depend on a short chat modal.

Interactive (developer terminal):

    python agents/scripts/setup_wizard.py --repo /path/to/android --lang ar

Agent-assisted (do not shorten the printed prompts):

    python agents/scripts/setup_wizard.py questions --repo /path/to/android --lang ar
    python agents/scripts/setup_wizard.py write --repo /path/to/android --answers-json answers.json
    python agents/scripts/setup_wizard.py flags --repo /path/to/android

Writes <repo>/.harness-setup/answers.json and SETUP_ANSWERS.md.
Does not copy .agents or port the engine.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wizard.discovery import (  # noqa: E402
    _flavor_pascal,
    answers_path,
    auto_blurb,
    auto_from_facts,
    count_source_files,
    discover,
    discover_apk_hint,
    discover_application_ids,
    discover_flavors,
    discover_launchers,
    discover_locales,
    discover_modules,
    discover_product,
    discover_pythons,
    discover_stack,
    gemini_exists,
    gradle_files,
    has_classic_app_src,
    markdown_path,
    python_ok,
    read_text,
    setup_dir,
    skip_path,
    zoho_config_present,
)
from wizard.i18n import (  # noqa: E402
    DEFAULT_PM_PROVIDER,
    PM_PROVIDER_IDS,
    SCHEMA,
    SKIP_DIRS,
    T,
    TOOL_IDS,
    TOOL_LABELS,
    t,
)
from wizard.questions import (  # noqa: E402
    default_for_question,
    existing_defaults,
    flags_from_answers,
    interactive,
    normalize,
    pm_next_steps,
    prompt_choice,
    prompt_text,
    questions_payload,
    write_answers,
)

__all__ = [
    "SCHEMA",
    "PM_PROVIDER_IDS",
    "DEFAULT_PM_PROVIDER",
    "SKIP_DIRS",
    "TOOL_IDS",
    "TOOL_LABELS",
    "T",
    "t",
    "setup_dir",
    "answers_path",
    "markdown_path",
    "skip_path",
    "read_text",
    "python_ok",
    "discover_product",
    "discover_pythons",
    "gradle_files",
    "discover_modules",
    "discover_application_ids",
    "discover_launchers",
    "discover_apk_hint",
    "discover_locales",
    "discover_stack",
    "has_classic_app_src",
    "discover_flavors",
    "_flavor_pascal",
    "gemini_exists",
    "zoho_config_present",
    "count_source_files",
    "discover",
    "auto_from_facts",
    "auto_blurb",
    "questions_payload",
    "default_for_question",
    "prompt_choice",
    "prompt_text",
    "normalize",
    "write_answers",
    "flags_from_answers",
    "pm_next_steps",
    "existing_defaults",
    "interactive",
    "parse_args",
    "find_repo",
    "load_write_payload",
    "main",
]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Record Android harness setup answers.")
    p.add_argument("--repo", help="Android checkout root.")
    p.add_argument("--lang", choices=("en", "ar"), default="en")
    p.add_argument(
        "command",
        nargs="?",
        default="ask",
        choices=("ask", "discover", "questions", "write", "flags"),
    )
    p.add_argument("--answers-json", help="For write: JSON object of question ids to values.")
    return p.parse_args(argv)


def find_repo(explicit: str | None) -> Path:
    if explicit:
        repo = Path(explicit).resolve()
    else:
        repo = Path.cwd().resolve()
    if not ((repo / "gradlew").is_file() or (repo / "gradlew.bat").is_file()):
        raise SystemExit(
            "[ERROR] Target directory is NOT an Android project. Missing gradlew / gradlew.bat. "
            "Please pass --repo pointing to a valid Android or Kotlin Multiplatform (KMP) project."
        )
    return repo


def load_write_payload(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("answers JSON must be an object.")
    return data


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except OSError:
            pass
    args = parse_args(argv)
    repo = find_repo(args.repo)
    if args.command == "discover":
        print(json.dumps(discover(repo), indent=2, ensure_ascii=False))
        return 0
    if args.command == "questions":
        facts = discover(repo)
        payload = {
            "discover": facts,
            "auto": auto_from_facts(facts),
            "model_warning": t(args.lang, "model_warning"),
            "auto_blurb": auto_blurb(facts, args.lang),
            "questions": questions_payload(repo, args.lang, facts),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if args.command == "flags":
        path = answers_path(repo)
        if not path.is_file():
            raise SystemExit(f"Missing {path}")
        answers = json.loads(path.read_text(encoding="utf-8"))
        print(flags_from_answers(answers))
        return 0
    if args.command == "write":
        if not args.answers_json:
            raise SystemExit("write needs --answers-json")
        raw = load_write_payload(Path(args.answers_json))
        if raw.get("schema") == SCHEMA and raw.get("i0") is True and "product" in raw:
            answers = raw
        else:
            answers = normalize(raw, discover(repo))
        if not answers.get("i0"):
            print(t(args.lang, "stopped"))
            return 1
        write_answers(repo, answers)
        print(t(args.lang, "wrote", path=str(answers_path(repo))))
        print("installer flags:", flags_from_answers(answers))
        for line in pm_next_steps(answers):
            print(line)
        return 0
    answers = interactive(repo, args.lang)
    write_answers(repo, answers)
    print(t(args.lang, "wrote", path=str(answers_path(repo))))
    print("installer flags:", flags_from_answers(answers))
    for line in pm_next_steps(answers):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

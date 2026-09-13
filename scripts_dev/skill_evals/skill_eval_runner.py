"""Developer-side behavioral skill evaluation runner for Android Agent Harness.

This tool is isolated from client runtime execution and selftests. It is used
by harness contributors during release qualification to evaluate whether
skills actually guide agent behaviors under realistic development pressure.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = ROOT / "agents" / "skills"
CASES_FILE = Path(__file__).resolve().parent / "skill_eval_cases.json"


def validate_case_schema(case: dict) -> list[str]:
    errors = []
    required_fields = ("id", "skill", "scenario", "pressure", "required_behaviors", "forbidden_behaviors")
    for f in required_fields:
        if f not in case or not case[f]:
            errors.append(f"Case '{case.get('id', '<unknown>')}' missing non-empty field: {f}")
    if not isinstance(case.get("pressure"), list) or len(case.get("pressure", [])) == 0:
        errors.append(f"Case '{case.get('id')}' 'pressure' must be a non-empty list")
    if not isinstance(case.get("required_behaviors"), list) or len(case.get("required_behaviors", [])) == 0:
        errors.append(f"Case '{case.get('id')}' 'required_behaviors' must be a non-empty list")
    if not isinstance(case.get("forbidden_behaviors"), list) or len(case.get("forbidden_behaviors", [])) == 0:
        errors.append(f"Case '{case.get('id')}' 'forbidden_behaviors' must be a non-empty list")
    return errors


def lint_skills_and_cases(cases_path: Path, skills_dir: Path) -> int:
    print(f"[*] Validating skill eval cases from: {cases_path}")
    if not cases_path.is_file():
        print(f"[FAIL] Cases file not found: {cases_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(cases_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[FAIL] Cannot parse JSON in {cases_path}: {exc}", file=sys.stderr)
        return 1

    cases = data.get("cases", [])
    if not isinstance(cases, list) or not cases:
        print("[FAIL] 'cases' must be a non-empty list", file=sys.stderr)
        return 1

    all_errors = []
    seen_ids = set()
    skills_tested = set()

    for c in cases:
        cid = c.get("id")
        if cid in seen_ids:
            all_errors.append(f"Duplicate case id: {cid}")
        seen_ids.add(cid)

        case_errs = validate_case_schema(c)
        all_errors.extend(case_errs)

        skill_name = c.get("skill")
        if skill_name:
            skills_tested.add(skill_name)
            skill_md = skills_dir / skill_name / "SKILL.md"
            if not skill_md.is_file():
                all_errors.append(f"Case '{cid}' references non-existent skill file: {skill_md}")

    if all_errors:
        print(f"[FAIL] Found {len(all_errors)} evaluation case errors:")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    print(f"[+] All {len(cases)} evaluation cases adhere to schema.")
    print(f"[+] Covered high-value skills ({len(skills_tested)}): {', '.join(sorted(skills_tested))}")
    return 0


def evaluate_mock_transcript(case: dict, transcript_text: str) -> dict:
    """Evaluate an agent transcript text against case requirements."""
    observed = []
    violations = []
    lower_text = transcript_text.lower()

    for forbidden in case.get("forbidden_behaviors", []):
        keywords = [w for w in forbidden.lower().split() if len(w) > 4]
        # Heuristic check for blatant forbidden behaviors
        matched = sum(1 for k in keywords if k in lower_text)
        if matched >= max(2, len(keywords) // 2):
            violations.append(forbidden)

    for req in case.get("required_behaviors", []):
        keywords = [w for w in req.lower().split() if len(w) > 4]
        matched = sum(1 for k in keywords if k in lower_text)
        if matched >= max(1, len(keywords) // 3):
            observed.append(req)

    status = "PASS" if not violations and len(observed) >= len(case.get("required_behaviors", [])) // 2 else "FAIL"
    return {
        "case_id": case.get("id"),
        "skill": case.get("skill"),
        "status": status,
        "observed_behaviors": observed,
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default=str(CASES_FILE), help="Path to skill_eval_cases.json")
    parser.add_argument("--skills-dir", default=str(SKILLS_DIR), help="Path to agents/skills directory")
    parser.add_argument("--lint-only", action="store_true", default=True, help="Validate case schemas and skill references")
    args = parser.parse_args(argv)

    cases_path = Path(args.cases).resolve()
    skills_dir = Path(args.skills_dir).resolve()

    return lint_skills_and_cases(cases_path, skills_dir)


if __name__ == "__main__":
    raise SystemExit(main())

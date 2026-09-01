"""Senior-QA test-case-aware E2E runner for Android.

Executes declarative *test cases* (not just smoke passes) on a physical device
or emulator. A case bundles a title, type (positive/negative/edge), preconditions,
isolation policy, an ordered step list (same vocabulary as the smoke flows), and
an expected result. Every case gets an independent verdict plus failure evidence.

Test-case file format (YAML or JSON):

    appId: com.acme.app
    cases:
      - id: TC-001
        title: "Login succeeds with valid credentials"
        type: positive
        preconditions: "User is on the login screen"
        isolation: relaunch     # relaunch (default) | stop | none
        steps:
          - launchApp
          - tapOn: "username"
          - inputText: "user@example.com"
          - tapOn: "password"
          - inputText: "secret"
          - tapOn: "login"
          - assertVisible: "dashboard"
        expectedResult: "User lands on the dashboard"

Usage:
  python .agents/scripts/run_e2e_qa.py --cases .agents/e2e_cases/<task>/<phase>.yaml
  python .agents/scripts/run_e2e_qa.py --generate-cases --output <path>
  python .agents/scripts/run_e2e_qa.py --cases <path> --lint
  python .agents/scripts/run_e2e_qa.py --cases <path> --json
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _adb_core import (  # noqa: E402
    DeviceGoneError,
    DeviceSession,
    FlowExecutor,
    canonicalize_steps,
    discover_diff_targets,
    parse_flow_definition,
    validate_flow,
)
from _apk_freshness import check_apk_freshness, format_freshness_error  # noqa: E402
from _env_codes import (  # noqa: E402
    CLASS_ENV,
    EXIT_ENV,
    FailureVerdict,
    emit_env_failure,
    no_device_verdict,
)
from _gate_results import current_head_sha, write_gate_result  # noqa: E402
from _live_process import enable_line_buffered_stdio, live_print  # noqa: E402
from _product import ALLOW_EMULATOR, APPLICATION_ID, PRODUCT_NAME  # noqa: E402
from _repo_files import REPO, first_adb_serial  # noqa: E402
from _variants import apk_relative  # noqa: E402

E2E_STATE_DIR = REPO / ".agents" / "state" / "e2e"
SCREENSHOTS_DIR = REPO / ".agents" / "state" / "screenshots"
REPORTS_DIR = E2E_STATE_DIR / "reports"

CASE_SCALAR_KEYS = {"id", "title", "type", "preconditions", "isolation", "expectedResult", "expected_result", "tags"}
CASE_TYPES = {"positive", "negative", "edge", "smoke", "regression"}
ISOLATION_MODES = {"relaunch", "stop", "none"}


def _dedent(lines: list[str]) -> list[str]:
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return []
    min_indent = min(len(ln) - len(ln.lstrip()) for ln in non_empty)
    return [ln[min_indent:] if len(ln) >= min_indent else ln for ln in lines]


def parse_cases_definition(content: str) -> dict:
    """Parse a test-case definition from YAML or JSON into {"appId", "cases"}."""
    content = (content or "").strip()
    if not content:
        return {"appId": None, "cases": []}

    if content.startswith("{") or content.startswith("["):
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return {"appId": None, "cases": data}
            if isinstance(data, dict):
                return {"appId": data.get("appId") or data.get("app_id"), "cases": data.get("cases") or []}
        except Exception:
            pass

    app_id: str | None = None
    cases: list[dict] = []
    lines = content.splitlines()

    # 1. Top-level scalars (appId) and locate the cases block.
    i = 0
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()
        if stripped.startswith(("appId:", "app_id:")):
            app_id = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            i += 1
            continue
        if stripped == "cases:":
            i += 1
            break
        i += 1

    # 2. Collect case item blocks (lines beginning with '- ' at the block indent).
    def collect_case(j: int) -> tuple[dict, int]:
        case_lines: list[str] = []
        k = j
        while k < n:
            line = lines[k]
            stripped = line.strip()
            if k != j and stripped.startswith("-") and (len(line) - len(line.lstrip())) == (len(lines[j]) - len(lines[j].lstrip())):
                break
            case_lines.append(line)
            k += 1
        return _parse_case_block(case_lines), k

    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("-"):
            case, i = collect_case(i)
            if case:
                cases.append(case)
            continue
        # Stop at the next top-level key.
        if len(line) == len(line.lstrip()) and ":" in stripped:
            break
        i += 1

    return {"appId": app_id, "cases": cases}


CASE_ATTR_KEYS = {
    "id", "title", "type", "description", "preconditions",
    "expectedResult", "expected_result", "isolation", "tags", "timeout",
}


def _parse_case_block(block_lines: list[str]) -> dict | None:
    block_lines = [ln for ln in block_lines if ln.strip()]
    if not block_lines:
        return None

    first = block_lines[0].strip()
    if not first.startswith("-"):
        return None
    first_body = first[1:].strip()

    case: dict = {}
    if ":" in first_body:
        k, v = first_body.split(":", 1)
        case[k.strip()] = v.strip().strip('"').strip("'")

    steps_lines: list[str] | None = None
    i = 1
    n = len(block_lines)
    while i < n:
        line = block_lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("steps:"):
            steps_indent = len(line) - len(line.lstrip())
            steps_lines = []
            i += 1
            while i < n and not _is_case_key_line(block_lines[i], steps_indent):
                if block_lines[i].strip():
                    steps_lines.append(block_lines[i])
                i += 1
            continue
        if ":" in stripped and not stripped.startswith("-"):
            k, v = stripped.split(":", 1)
            case[k.strip()] = v.strip().strip('"').strip("'")
        i += 1

    if steps_lines is not None:
        flow = parse_flow_definition("\n".join(_dedent(steps_lines)))
        case["steps"] = flow.get("steps", [])
    else:
        case["steps"] = []
    return case


def _is_case_key_line(line: str, steps_indent: int) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("-"):
        return False
    indent = len(line) - len(line.lstrip())
    if indent <= steps_indent and ":" in stripped:
        key = stripped.split(":", 1)[0].strip()
        return key in CASE_ATTR_KEYS or key.startswith("case")
    return False


def validate_cases(definition: dict) -> list[str]:
    errors: list[str] = []
    cases = definition.get("cases") or []
    if not isinstance(cases, list):
        return ["'cases' must be a list"]
    for idx, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            errors.append(f"case {idx} is not a mapping")
            continue
        cid = case.get("id") or f"#{idx}"
        if not case.get("id"):
            errors.append(f"case {idx} has no 'id'")
        ctype = str(case.get("type") or "positive").lower()
        if ctype not in CASE_TYPES:
            errors.append(f"case {cid} has unknown type '{case.get('type')}'")
        isolation = str(case.get("isolation") or "relaunch").lower()
        if isolation not in ISOLATION_MODES:
            errors.append(f"case {cid} has unknown isolation '{case.get('isolation')}'")
        steps = case.get("steps") or []
        if not isinstance(steps, list) or not steps:
            errors.append(f"case {cid} has no steps")
            continue
        errors.extend(f"case {cid}: {e}" for e in validate_flow({"steps": steps}))
    return errors


# ---------------------------------------------------------------------------
# Case generation scaffold
# ---------------------------------------------------------------------------
def generate_cases_definition() -> dict:
    diff = discover_diff_targets(REPO)
    cases: list[dict] = []

    def _add(surface: str, hint: str) -> None:
        cases.append({
            "id": f"TC-{len(cases) + 1:03d}",
            "title": f"{surface} renders without crash",
            "type": "smoke",
            "preconditions": "App installed; fresh launch",
            "isolation": "relaunch",
            "steps": [
                {"action": "launchApp"},
                {"action": "assertVisible", "target": hint},
            ],
            "expectedResult": f"Screen {surface} renders and is interactive",
        })

    activity = diff.get("target_activity_component") or diff.get("target_activity")
    if activity:
        _add(activity, diff.get("target_strings")[0] if diff.get("target_strings") else activity)

    for screen in diff.get("modified_screens", [])[:5]:
        _add(screen, screen)

    if not cases:
        _add("MainActivity", "app content")

    return {"appId": APPLICATION_ID, "cases": cases}


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------
class QARunner:
    def __init__(self, serial: str, package: str, retries: int = 0):
        self.session = DeviceSession(serial, package)
        self.retries = retries

    def run(self, definition: dict, repo: Path, task: str = "") -> dict:
        cases = definition.get("cases") or []
        results: list[dict] = []
        self.session.wake_and_unlock()
        self.session.grant_common_permissions()

        for case in cases:
            results.append(self._run_case(case, repo))

        passed = all(r["verdict"] == "PASS" for r in results)
        return {
            "verdict": "PASS" if passed else "FAIL",
            "task": task,
            "package": self.session.package,
            "total": len(results),
            "passed": sum(1 for r in results if r["verdict"] == "PASS"),
            "failed": sum(1 for r in results if r["verdict"] == "FAIL"),
            "cases": results,
        }

    def _run_case(self, case: dict, repo: Path) -> dict:
        cid = str(case.get("id") or "case")
        title = str(case.get("title") or "")
        isolation = str(case.get("isolation") or "relaunch").lower()
        steps = canonicalize_steps(case.get("steps") or [])

        if isolation in ("relaunch", "stop"):
            self.session.stop_app()

        executor = FlowExecutor(self.session, repo, SCREENSHOTS_DIR)

        last: dict = {"verdict": "FAIL", "reason": "case did not produce a result", "steps": []}
        attempts = 1 + max(0, self.retries)
        for attempt in range(attempts):
            last = executor.execute(steps)
            if last["verdict"] == "PASS" or attempt == attempts - 1:
                break

        shot = self.session.capture_screenshot(f"case_{cid}", SCREENSHOTS_DIR)
        return {
            "id": cid,
            "title": title,
            "type": case.get("type", "positive"),
            "verdict": last["verdict"],
            "attempts": attempts,
            "reason": last.get("reason", ""),
            "classification": last.get("classification", "PASS" if last["verdict"] == "PASS" else "ASSERTION_FAILED"),
            "steps": last.get("steps", []),
            "final_screenshot": str(shot) if shot else None,
        }


def _write_report(result: dict, task: str) -> Path:
    report_dir = REPORTS_DIR / (task or "default")
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"{stamp}_qa_report.json"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    md_path = report_dir / f"{stamp}_qa_report.md"
    lines = [f"# QA E2E Report — {PRODUCT_NAME}", "", f"**Verdict:** {result['verdict']}", f"**Cases:** {result['passed']}/{result['total']} passed", ""]
    for c in result["cases"]:
        mark = "PASS" if c["verdict"] == "PASS" else "FAIL"
        lines.append(f"- [{mark}] `{c['id']}` — {c['title']}")
        if c["verdict"] == "FAIL":
            lines.append(f"    - reason: {c['reason']} ({c['classification']})")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path


def main() -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description=f"Senior-QA test-case E2E runner for {PRODUCT_NAME}")
    parser.add_argument("-s", "--serial", default=None, help="Device serial")
    parser.add_argument("-p", "--package", default=APPLICATION_ID, help="Target application package")
    parser.add_argument("--cases", default=None, help="Path to test-case YAML/JSON file")
    parser.add_argument("--generate-cases", action="store_true", help="Generate a test-case scaffold from the working-tree diff")
    parser.add_argument("--output", default=None, help="Output path for --generate-cases")
    parser.add_argument("--lint", action="store_true", help="Validate the cases file without a device")
    parser.add_argument("--retries", type=int, default=0, help="Per-case retry attempts for flaky steps (default 0)")
    parser.add_argument("--task", default="", help="Task id for report grouping")
    parser.add_argument("--json", action="store_true", help="Print structured JSON result")
    args = parser.parse_args()

    if args.generate_cases:
        definition = generate_cases_definition()
        out = Path(args.output) if args.output else REPO / ".agents" / "e2e_cases" / (args.task or "cases") / "cases.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_dump_cases_yaml(definition), encoding="utf-8")
        live_print(f"[*] Generated test-case scaffold -> {out}")
        return 0

    if not args.cases:
        live_print("[ERROR] Provide --cases <path> (or use --generate-cases).", err=True)
        return 1

    cases_path = Path(args.cases)
    if not cases_path.is_absolute():
        cases_path = REPO / cases_path
    if not cases_path.is_file():
        live_print(f"[ERROR] Cases file not found: {cases_path}", err=True)
        return 1
    content = cases_path.read_text(encoding="utf-8", errors="ignore")
    definition = parse_cases_definition(content)
    pkg = definition.get("appId") or args.package

    errors = validate_cases(definition)
    if errors:
        live_print("[FAIL] Test-case definition is invalid:", err=True)
        for e in errors:
            live_print(f"  - {e}", err=True)
        return 1

    if args.lint:
        live_print(f"[PASS] {len(definition.get('cases') or [])} test case(s) validated (offline).")
        return 0

    serial = args.serial or first_adb_serial(allow_emulator=bool(ALLOW_EMULATOR))
    if not serial:
        verdict = no_device_verdict()
        write_gate_result("e2e", {"schema_version": 1, "status": "ENV", "exit_code": EXIT_ENV, "env_class": verdict.env_class, "serial": None, "git_sha": current_head_sha(), "detail": verdict.reason})
        emit_env_failure(verdict, "run_e2e_qa.py")
        return EXIT_ENV

    apk_path = REPO / apk_relative()
    freshness = check_apk_freshness(apk_path, REPO)
    if not freshness.is_fresh:
        if freshness.status == "MISSING_APK":
            verdict = FailureVerdict(CLASS_ENV, freshness.reason)
            write_gate_result("e2e", {"schema_version": 1, "status": "ENV", "exit_code": EXIT_ENV, "env_class": verdict.env_class, "serial": serial, "git_sha": current_head_sha(), "detail": freshness.reason})
            emit_env_failure(verdict, "run_e2e_qa.py", serial=serial)
            return EXIT_ENV
        live_print(format_freshness_error(freshness, apk_path), err=True)
        write_gate_result("e2e", {"schema_version": 1, "status": "FAIL", "exit_code": 1, "env_class": "CODE", "serial": serial, "git_sha": current_head_sha(), "detail": f"STALE_APK: {freshness.reason}"})
        return 1

    runner = QARunner(serial, pkg, retries=args.retries)
    try:
        result = runner.run(definition, REPO, task=args.task)
    except DeviceGoneError as exc:
        verdict = FailureVerdict(CLASS_ENV, exc.reason)
        write_gate_result("e2e", {"schema_version": 1, "status": "ENV", "exit_code": EXIT_ENV, "env_class": verdict.env_class, "serial": serial, "git_sha": current_head_sha(), "detail": verdict.reason})
        emit_env_failure(verdict, "run_e2e_qa.py", serial=serial)
        return EXIT_ENV

    E2E_STATE_DIR.mkdir(parents=True, exist_ok=True)
    (E2E_STATE_DIR / "last_e2e_result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    report_path = _write_report(result, args.task)

    passed = result["verdict"] == "PASS"
    write_gate_result("e2e", {
        "schema_version": 1,
        "status": "PASS" if passed else "FAIL",
        "exit_code": 0 if passed else 1,
        "env_class": "",
        "serial": serial,
        "git_sha": current_head_sha(),
        "detail": f"{result['passed']}/{result['total']} cases passed",
    })

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if passed else 1

    for c in result["cases"]:
        mark = "[PASS]" if c["verdict"] == "PASS" else "[FAIL]"
        line = f"  {mark} {c['id']} - {c['title']}"
        if c["verdict"] == "FAIL":
            line += f" -> {c['reason']}"
        live_print(line, err=(c["verdict"] == "FAIL"))

    live_print(f"\n[{'SUCCESS' if passed else 'FAIL'}] QA E2E: {result['passed']}/{result['total']} cases passed.")
    live_print(f"[*] Report: {report_path}")
    return 0 if passed else 1


def _dump_cases_yaml(definition: dict) -> str:
    lines: list[str] = []
    if definition.get("appId"):
        lines.append(f"appId: {definition['appId']}")
    lines.append("cases:")
    for case in definition.get("cases") or []:
        lines.append(f"  - id: {case.get('id')}")
        lines.append(f"    title: \"{case.get('title')}\"")
        lines.append(f"    type: {case.get('type', 'positive')}")
        lines.append(f"    preconditions: \"{case.get('preconditions', '')}\"")
        lines.append(f"    isolation: {case.get('isolation', 'relaunch')}")
        lines.append("    steps:")
        for step in case.get("steps") or []:
            action = step.get("action", "")
            if action == "launchApp":
                lines.append("      - launchApp")
            elif action in ("assertVisible", "assertNotVisible", "tapOn"):
                lines.append(f"      - {action}: \"{step.get('target', '')}\"")
            else:
                lines.append(f"      - {action}: \"{step.get('target') or step.get('text') or step.get('value') or ''}\"")
        lines.append(f"    expectedResult: \"{case.get('expectedResult', '')}\"")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())

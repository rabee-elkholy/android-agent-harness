"""Autonomous E2E smoke-testing engine (fast fallback) for Android.

Thin wrapper over the shared device core (``_adb_core.py``). Use
``run_e2e_qa.py`` for test-case-aware Senior QA runs; this script stays as the
quick diff-aware smoke pass with the same corrected primitives.

Usage:
  python .agents/scripts/run_e2e_smoke.py --auto-diff
  python .agents/scripts/run_e2e_smoke.py --target-activity <ActivityName>
  python .agents/scripts/run_e2e_smoke.py --target-deeplink <URI>
  python .agents/scripts/run_e2e_smoke.py --target-text <Keyword>
  python .agents/scripts/run_e2e_smoke.py --flow <path.yaml>
  python .agents/scripts/run_e2e_smoke.py --dump-only
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _adb_core import (  # noqa: E402
    DeviceGoneError,
    DeviceSession,
    FlowExecutor,
    UINode,
    canonicalize_steps,
    discover_diff_targets,
    find_first,
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

SCREENSHOTS_DIR = REPO / ".agents" / "state" / "screenshots"
E2E_STATE_DIR = REPO / ".agents" / "state" / "e2e"


class SmokeRunner:
    def __init__(
        self,
        serial: str,
        package: str,
        target_activity: str | None = None,
        target_deeplink: str | None = None,
        target_texts: list[str] | None = None,
        require_targets: bool = False,
    ):
        self.session = DeviceSession(serial, package)
        self.target_activity = target_activity
        self.target_deeplink = target_deeplink
        self.target_texts = target_texts or []
        self.require_targets = require_targets

    def run_targeted_smoke_flow(self) -> dict:
        steps: list[dict] = []
        live_print(f"[*] Starting Targeted E2E Smoke Flow on {self.session.serial} ({self.session.package})...")

        if not self.session.launch_app_or_target(self.target_activity, self.target_deeplink):
            return {
                "verdict": "FAIL",
                "reason": f"Target application {self.session.package} failed to foreground.",
                "steps": steps,
                "crashes": self.session.check_logcat_crashes(),
            }

        nodes = self.session.dump_hierarchy()
        if not nodes:
            return {
                "verdict": "FAIL",
                "reason": "Failed to dump UI hierarchy from device.",
                "steps": steps,
                "crashes": self.session.check_logcat_crashes(),
            }

        shot = self.session.capture_screenshot("e2e_screen_launch", SCREENSHOTS_DIR)
        steps.append({"step": "App & Target Launch", "status": "PASS", "nodes_found": len(nodes), "screenshot": str(shot) if shot else None})
        live_print(f"  [PASS] Target UI foregrounded & hierarchy dumped ({len(nodes)} root nodes).")

        matched: list[str] = []
        for kw in self.target_texts:
            node = self._find_text(nodes, kw)
            if node:
                matched.append(kw)
                live_print(f"  [PASS] Verified modified UI target element: '{kw}' (center: {node.center}).")

        if self.target_texts:
            ok = bool(matched)
            steps.append({
                "step": "Target Elements Verification",
                "status": "PASS" if ok else ("FAIL" if self.require_targets else "INFO"),
                "matched_targets": matched,
                "expected_targets": self.target_texts,
            })
            if self.require_targets and not ok:
                return {"verdict": "FAIL", "reason": f"Required target text(s) not visible: {self.target_texts}", "steps": steps, "crashes": []}

        clickables = self.session.dump_hierarchy()
        clickable_nodes = [n for n in _flatten(clickables) if n.clickable]
        steps.append({"step": "Interactive UI Elements Discovery", "status": "PASS", "clickables_count": len(clickable_nodes)})
        live_print(f"  [PASS] Discovered {len(clickable_nodes)} interactive UI element(s).")

        scrollables = [n for n in _flatten(clickables) if n.scrollable or "RecyclerView" in n.class_name or "ScrollView" in n.class_name]
        if scrollables:
            live_print("  [*] Testing scroll responsiveness and frame stability...")
            down_ok = self.session.scroll_down()
            up_ok = self.session.scroll_up()
            status = "PASS" if down_ok and up_ok else "WARN"
            steps.append({"step": "Scroll Gesture Responsiveness", "status": status})
            live_print(f"  [{status}] Scroll responsiveness verified.")

        crashes = self.session.check_logcat_crashes()
        if crashes:
            live_print(f"  [FAIL] Detected runtime crash: {crashes[0]['summary']}", err=True)
            return {"verdict": "FAIL", "reason": f"Runtime crash detected: {crashes[0]['summary']}", "stacktrace": crashes[0].get("stacktrace"), "steps": steps, "crashes": crashes}

        steps.append({"step": "Logcat Crash Forensics", "status": "PASS", "crashes": 0})
        live_print("  [PASS] Zero fatal crashes, ANRs, or Room migration exceptions in Logcat.")

        final_shot = self.session.capture_screenshot("e2e_final_verified", SCREENSHOTS_DIR)
        return {"verdict": "PASS", "steps": steps, "crashes": [], "final_screenshot": str(final_shot) if final_shot else None}

    def execute_flow(self, flow: dict, repo: Path) -> dict:
        errors = validate_flow(flow)
        if errors:
            return {"verdict": "FAIL", "reason": f"invalid flow: {'; '.join(errors)}", "steps": []}

        executor = FlowExecutor(self.session, repo, SCREENSHOTS_DIR)
        live_print(f"[*] Executing Declarative E2E Flow on {self.session.serial} ({self.session.package})...")
        if not executor.prepare(self.target_activity, self.target_deeplink):
            return {"verdict": "FAIL", "reason": f"Target application {self.session.package} failed to foreground.", "steps": []}

        live_print(f"[*] Detected active in-app locale: '{executor.active_locale}'.")
        steps = flow.get("steps") or []
        if not steps:
            live_print("[WARN] Flow definition contains no steps; executing default smoke pass.")
            return self.run_targeted_smoke_flow()
        return executor.execute(canonicalize_steps(steps))

    def _find_text(self, nodes, kw: str):
        return find_first(nodes, text=kw) or find_first(nodes, content_desc=kw)


def _flatten(nodes: list):
    out: list[UINode] = []
    stack = list(nodes)
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(n.children)
    return out


def _resolve_serial(args) -> str | None:
    allow_emu = bool(ALLOW_EMULATOR)
    serial = args.serial or first_adb_serial(allow_emulator=allow_emu)
    if serial:
        return serial
    verdict = no_device_verdict()
    write_gate_result("e2e", {
        "schema_version": 1,
        "status": "ENV",
        "exit_code": EXIT_ENV,
        "env_class": verdict.env_class,
        "serial": None,
        "git_sha": current_head_sha(),
        "detail": verdict.reason,
    })
    emit_env_failure(verdict, "run_e2e_smoke.py")
    sys.exit(EXIT_ENV)


def _enforce_freshness(args, apk_path: Path) -> None:
    freshness = check_apk_freshness(apk_path, REPO)
    if freshness.is_fresh:
        return
    if freshness.status == "MISSING_APK":
        verdict = FailureVerdict(CLASS_ENV, freshness.reason)
        write_gate_result("e2e", {
            "schema_version": 1,
            "status": "ENV",
            "exit_code": EXIT_ENV,
            "env_class": verdict.env_class,
            "serial": None,
            "git_sha": current_head_sha(),
            "detail": freshness.reason,
        })
        emit_env_failure(verdict, "run_e2e_smoke.py")
        sys.exit(EXIT_ENV)
    live_print(format_freshness_error(freshness, apk_path), err=True)
    live_print("[ERROR] E2E test aborted: APK is stale relative to modified files.", err=True)
    write_gate_result("e2e", {
        "schema_version": 1,
        "status": "FAIL",
        "exit_code": 1,
        "env_class": "CODE",
        "serial": None,
        "git_sha": current_head_sha(),
        "detail": f"STALE_APK: {freshness.reason}",
    })
    sys.exit(1)


def main() -> int:
    enable_line_buffered_stdio()
    parser = argparse.ArgumentParser(description=f"Autonomous Targeted E2E Smoke Testing for {PRODUCT_NAME}")
    parser.add_argument("-s", "--serial", default=None, help="Device serial")
    parser.add_argument("-p", "--package", default=APPLICATION_ID, help="Target application package")
    parser.add_argument("--auto-diff", action="store_true", help="Auto-discover modified activities and strings from git diff")
    parser.add_argument("--target-activity", default=None, help="Direct target Activity class or component name to launch")
    parser.add_argument("--target-deeplink", default=None, help="Direct deep link URI to launch")
    parser.add_argument("--target-text", action="append", default=[], help="Expected text or keyword on target screen")
    parser.add_argument("--flow", default=None, help="Path to declarative YAML/JSON flow file to execute")
    parser.add_argument("--flow-text", default=None, help="Inline YAML/JSON flow string to execute")
    parser.add_argument("--force-native", action="store_true", help="Force native Python ADB runner even if Maestro CLI is installed")
    parser.add_argument("--dump-only", action="store_true", help="Dump and print current UI hierarchy JSON and exit")
    parser.add_argument("--json", action="store_true", help="Print structured JSON result")
    args = parser.parse_args()

    serial = _resolve_serial(args)
    apk_path = REPO / apk_relative()
    if not args.dump_only:
        _enforce_freshness(args, apk_path)

    target_act = args.target_activity
    target_dl = args.target_deeplink
    target_texts = list(args.target_text)
    require_targets = bool(args.target_text)

    use_auto_diff = args.auto_diff or (not target_act and not target_dl and not args.flow and not args.flow_text)
    if use_auto_diff:
        diff_info = discover_diff_targets(REPO)
        if diff_info.get("target_activity_component"):
            target_act = diff_info["target_activity_component"]
            live_print(f"[*] Auto-diff discovered target activity: {target_act}")
        elif diff_info.get("target_activity"):
            target_act = diff_info["target_activity"]
            live_print(f"[*] Auto-diff discovered target activity: {target_act}")
        if diff_info.get("target_strings"):
            target_texts.extend(diff_info["target_strings"][:3])
            live_print(f"[*] Auto-diff discovered advisory string assertions: {diff_info['target_strings'][:3]}")

    flow_content = None
    if args.flow:
        flow_path = Path(args.flow)
        if not flow_path.is_absolute():
            flow_path = REPO / flow_path
        if flow_path.is_file():
            flow_content = flow_path.read_text(encoding="utf-8", errors="ignore")
        else:
            live_print(f"[ERROR] Flow file not found: {flow_path}", err=True)
            return 1
    elif args.flow_text:
        flow_content = args.flow_text

    flow_data = parse_flow_definition(flow_content) if flow_content else None
    pkg = (flow_data.get("appId") if flow_data else None) or args.package

    if args.flow and not args.force_native and shutil.which("maestro"):
        live_print("[*] Maestro CLI detected; executing flow via Maestro...")
        res = subprocess.run(["maestro", "--device", serial, "test", str(Path(args.flow).resolve())], cwd=str(REPO))
        write_gate_result("e2e", {
            "schema_version": 1,
            "status": "PASS" if res.returncode == 0 else "FAIL",
            "exit_code": res.returncode,
            "env_class": "",
            "serial": serial,
            "git_sha": current_head_sha(),
            "detail": "executed via Maestro CLI",
        })
        return res.returncode

    runner = SmokeRunner(serial, pkg, target_act, target_dl, target_texts, require_targets)

    if args.dump_only:
        nodes = runner.session.dump_hierarchy()
        print(json.dumps([n.to_dict() for n in nodes], indent=2, ensure_ascii=False))
        return 0

    try:
        if flow_data and flow_data.get("steps"):
            result = runner.execute_flow(flow_data, REPO)
        else:
            result = runner.run_targeted_smoke_flow()
    except DeviceGoneError as exc:
        verdict = FailureVerdict(CLASS_ENV, exc.reason)
        write_gate_result("e2e", {
            "schema_version": 1,
            "status": "ENV",
            "exit_code": EXIT_ENV,
            "env_class": verdict.env_class,
            "serial": serial,
            "git_sha": current_head_sha(),
            "detail": verdict.reason,
        })
        emit_env_failure(verdict, "run_e2e_smoke.py", serial=serial)
        return EXIT_ENV

    E2E_STATE_DIR.mkdir(parents=True, exist_ok=True)
    (E2E_STATE_DIR / "last_e2e_result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    passed = result["verdict"] == "PASS"
    write_gate_result("e2e", {
        "schema_version": 1,
        "status": "PASS" if passed else "FAIL",
        "exit_code": 0 if passed else 1,
        "env_class": "",
        "serial": serial,
        "git_sha": current_head_sha(),
        "detail": str(result.get("reason") or "")[:300],
    })

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if passed else 1

    if passed:
        live_print(f"\n[SUCCESS] Autonomous Targeted E2E Smoke Test PASSED on {serial}!")
        if result.get("final_screenshot"):
            live_print(f"[*] Verification Screenshot: {result['final_screenshot']}")
        return 0

    live_print(f"\n[FAIL] Autonomous Targeted E2E Smoke Test FAILED: {result.get('reason')}", err=True)
    if result.get("stacktrace"):
        live_print(f"--- Stacktrace ---\n{result['stacktrace']}\n------------------", err=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())

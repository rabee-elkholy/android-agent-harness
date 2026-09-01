"""Self-test for final_verdict.py aggregation. Stdlib only, no device, no network."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

HEAD = "1" * 40
OTHER_HEAD = "2" * 40
FP = "f" * 64
OTHER_FP = "a" * 64
PKG12 = "c" * 12
PKG_FULL = "c" * 64

from _env_codes import EXIT_ENV  # noqa: E402
from _gate_results import write_gate_result  # noqa: E402
from _hook_state import state_path, write_verdict_record  # noqa: E402
from final_verdict import (  # noqa: E402
    LEAF_KEYS,
    LEAF_PASS_VALUES,
    build_verdict,
    diff_sha256,
    exit_code_for,
    write_last_verdict,
)

FAILURES: list[str] = []
ROOT = Path(tempfile.mkdtemp())


def check(cond: bool, label: str) -> None:
    if cond:
        print(f"[PASS] {label}")
    else:
        FAILURES.append(label)
        print(f"[FAIL] {label}")


def new_env() -> tuple[Path, Path]:
    results = ROOT / f"results-{len(list(ROOT.iterdir()))}"
    state = ROOT / f"state-{len(list(ROOT.iterdir()))}"
    results.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    os.environ["HARNESS_RESULTS_DIR"] = str(results)
    os.environ["HARNESS_HOOK_STATE"] = str(state / "review-invokes.json")
    return results, state


def write_result(name: str, status: str, exit_code: int = 0, git_sha: str = HEAD) -> None:
    write_gate_result(name, {
        "schema_version": 1,
        "status": status,
        "exit_code": exit_code,
        "env_class": "ENV" if status == "ENV" else "",
        "git_sha": git_sha,
        "detail": f"detail-{name}",
    })


def write_ledger(pkg_sha: str, tree_fp: str | None) -> None:
    state_path().with_name("review_ledger.json").write_text(
        json.dumps({"sha256": pkg_sha, "tree_fingerprint": tree_fp}), encoding="utf-8"
    )


def write_review(verdict: str, leaves: dict | None = None, tree_fp: str | None = FP) -> None:
    leaves = leaves if leaves is not None else {k: LEAF_PASS_VALUES[k] for k in LEAF_KEYS}
    write_verdict_record(PKG12, {
        "schema_version": 2,
        "task_id": "",
        "verdict": verdict,
        "tree_fingerprint": tree_fp,
        "leaves": leaves,
        "checks": [],
        "findings": [],
    })


def all_pass_results() -> None:
    write_result("gradle-app-testdebugunittest", "PASS")
    write_result("preflight", "PASS")
    write_result("gradle-app-assembledebug", "PASS")
    write_result("device", "PASS")
    write_result("e2e", "PASS")


def test_approved() -> None:
    new_env()
    all_pass_results()
    write_ledger(PKG_FULL, FP)
    write_review("APPROVED")
    verdict = build_verdict(task_id="T1", head_sha=HEAD, tree_fp=FP, files_override=[("a.kt", "d1"), ("b.xml", "d2")])
    check(verdict["status"] == "APPROVED", "all gates + 5 leaves PASS -> APPROVED")
    check(all(c["status"] == "PASS" for c in verdict["checks"]), "every check PASS")
    check(verdict["git_context"]["head_commit"] == HEAD, "head recorded")
    check(verdict["git_context"]["files_count"] == 2, "files_count recorded")
    check(len(verdict["git_context"]["diff_sha256"]) == 64, "diff_sha256 is a full sha256")
    check(verdict["leaves"]["bug_reviewer"] == "BUG_PASS", "leaf verdict recorded")
    check(verdict["blocked_by"] == [], "nothing blocked")


def test_missing_artifacts() -> None:
    new_env()
    write_ledger(PKG_FULL, FP)
    write_review("APPROVED")
    verdict = build_verdict(task_id="T1", head_sha=HEAD, tree_fp=FP, files_override=[("a.kt", "d1")])
    check(verdict["status"] == "BLOCKED", "missing artifacts -> BLOCKED")
    names = {item.split(":")[0] for item in verdict["blocked_by"]}
    check({"unit_tests", "preflight", "assemble", "device", "e2e"} <= names, "blocked_by lists every missing gate")


def test_env_blocked() -> None:
    new_env()
    all_pass_results()
    write_result("preflight", "ENV", exit_code=EXIT_ENV)
    write_ledger(PKG_FULL, FP)
    write_review("APPROVED")
    verdict = build_verdict(task_id="T1", head_sha=HEAD, tree_fp=FP, files_override=[("a.kt", "d1")])
    check(verdict["status"] == "ENV_BLOCKED", "ENV gate -> ENV_BLOCKED")
    check(exit_code_for("ENV_BLOCKED") == EXIT_ENV, "ENV_BLOCKED exits 30")


def test_review_pending() -> None:
    new_env()
    all_pass_results()
    write_ledger(PKG_FULL, FP)
    write_review("PENDING")
    verdict = build_verdict(task_id="T1", head_sha=HEAD, tree_fp=FP, files_override=[("a.kt", "d1")])
    check(verdict["status"] == "BLOCKED", "PENDING review -> BLOCKED")


def test_missing_leaf() -> None:
    new_env()
    all_pass_results()
    write_ledger(PKG_FULL, FP)
    leaves = {k: LEAF_PASS_VALUES[k] for k in LEAF_KEYS}
    leaves["convention_reviewer"] = "FINDINGS"
    write_review("APPROVED", leaves=leaves)
    verdict = build_verdict(task_id="T1", head_sha=HEAD, tree_fp=FP, files_override=[("a.kt", "d1")])
    check(verdict["status"] == "BLOCKED", "leaf without *_PASS -> BLOCKED")
    check(any("convention" in item for item in verdict["blocked_by"]), "blocked_by names the failing leaf")


def test_stale_review() -> None:
    new_env()
    all_pass_results()
    write_ledger(PKG_FULL, FP)
    write_review("APPROVED", tree_fp=OTHER_FP)
    verdict = build_verdict(task_id="T1", head_sha=HEAD, tree_fp=FP, files_override=[("a.kt", "d1")])
    check(verdict["status"] == "STALE", "fingerprint mismatch -> STALE")
    check(any("changed after" in item for item in verdict["blocked_by"]), "stale reason recorded")


def test_expired() -> None:
    new_env()
    all_pass_results()
    write_ledger(PKG_FULL, FP)
    write_review("EXPIRED")
    verdict = build_verdict(task_id="T1", head_sha=HEAD, tree_fp=FP, files_override=[("a.kt", "d1")])
    check(verdict["status"] == "EXPIRED", "EXPIRED review round -> EXPIRED")


def test_no_head() -> None:
    new_env()
    all_pass_results()
    write_ledger(PKG_FULL, FP)
    write_review("APPROVED")
    verdict = build_verdict(task_id="T1", head_sha="", tree_fp=FP, files_override=[("a.kt", "d1")])
    check(verdict["status"] == "BLOCKED", "no git HEAD -> BLOCKED")
    check(any("git HEAD" in item for item in verdict["blocked_by"]), "no-head reason recorded")


def test_stale_artifact() -> None:
    new_env()
    all_pass_results()
    write_result("preflight", "PASS", git_sha=OTHER_HEAD)
    write_ledger(PKG_FULL, FP)
    write_review("APPROVED")
    verdict = build_verdict(task_id="T1", head_sha=HEAD, tree_fp=FP, files_override=[("a.kt", "d1")])
    check(verdict["status"] == "BLOCKED", "artifact from older HEAD -> BLOCKED")
    stale = [c for c in verdict["checks"] if c["name"] == "preflight"][0]
    check(stale["status"] == "STALE", "older-HEAD artifact marked STALE")


def test_unit_tests_artifact_precedence() -> None:
    new_env()
    all_pass_results()
    write_result("unit_tests", "FAIL", exit_code=1)
    write_ledger(PKG_FULL, FP)
    write_review("APPROVED")
    verdict = build_verdict(task_id="T1", head_sha=HEAD, tree_fp=FP, files_override=[("a.kt", "d1")])
    unit = [c for c in verdict["checks"] if c["name"] == "unit_tests"][0]
    check(unit["status"] == "FAIL", "unit_tests artifact overrides the gradle artifact")
    check(verdict["status"] == "BLOCKED", "failing unit_tests artifact blocks delivery")


def test_device_mode_disabled() -> None:
    new_env()
    write_result("gradle-app-testdebugunittest", "PASS")
    write_result("preflight", "PASS")
    write_result("gradle-app-assembledebug", "PASS")
    write_ledger(PKG_FULL, FP)
    write_review("APPROVED")
    bits = {"unit_test_task": ":app:testDebugUnitTest", "assemble_task": ":app:assembleDebug", "device_mode": "disabled"}
    verdict = build_verdict(task_id="T1", head_sha=HEAD, tree_fp=FP, files_override=[("a.kt", "d1")], bits=bits)
    names = {c["name"] for c in verdict["checks"]}
    check("device" not in names and "e2e" not in names, "device/e2e not required in disabled mode")
    check(verdict["status"] == "APPROVED", "disabled mode approves without device gates")


def test_diff_sha_determinism() -> None:
    files = [("a.kt", "d1"), ("b.xml", "d2")]
    files_shuffled = [("b.xml", "d2"), ("a.kt", "d1")]
    check(diff_sha256(files) == diff_sha256(files_shuffled), "diff sha is order-independent")
    check(diff_sha256(files) != diff_sha256([("a.kt", "d1"), ("b.xml", "changed")]), "content change alters diff sha")
    check(diff_sha256([]) == diff_sha256([]), "empty files list is stable")


def test_smart_test_promotion() -> None:
    new_env()
    all_pass_results()
    write_ledger(PKG_FULL, FP)
    # Test diff with only 5 leaves (missing test_quality) must be BLOCKED
    write_verdict_record(PKG12, {
        "schema_version": 2,
        "task_id": "",
        "verdict": "APPROVED",
        "contains_tests": True,
        "tree_fingerprint": FP,
        "leaves": {k: LEAF_PASS_VALUES[k] for k in LEAF_KEYS},
    })
    verdict = build_verdict(task_id="T1", head_sha=HEAD, tree_fp=FP, files_override=[("app/src/test/A.kt", "d1")])
    check(verdict["status"] == "BLOCKED", "test diff without test_quality leaf -> BLOCKED")

    # Test diff with all 6 leaves (+ TEST_PASS) must be APPROVED
    write_verdict_record(PKG12, {
        "schema_version": 2,
        "task_id": "",
        "verdict": "APPROVED",
        "contains_tests": True,
        "tree_fingerprint": FP,
        "leaves": {**{k: LEAF_PASS_VALUES[k] for k in LEAF_KEYS}, "test_quality": "TEST_PASS"},
    })
    verdict2 = build_verdict(task_id="T1", head_sha=HEAD, tree_fp=FP, files_override=[("app/src/test/A.kt", "d1")])
    check(verdict2["status"] == "APPROVED", "test diff with 6 leaves (+ TEST_PASS) -> APPROVED")


def test_write_last_verdict() -> None:
    new_env()
    all_pass_results()
    write_ledger(PKG_FULL, FP)
    write_review("APPROVED")
    verdict = build_verdict(task_id="T1", head_sha=HEAD, tree_fp=FP, files_override=[("a.kt", "d1")])
    target = write_last_verdict(verdict)
    check(target is not None and target.is_file(), "last_verdict.json written")
    data = json.loads(target.read_text(encoding="utf-8"))
    check(data.get("schema_version") == 1, "schema_version present")
    check(data.get("status") == "APPROVED", "status persisted")
    target.write_text("{broken", encoding="utf-8")
    target2 = write_last_verdict(verdict)
    check(target2 is not None, "corrupted last_verdict is overwritten")
    check(json.loads(target2.read_text(encoding="utf-8")).get("status") == "APPROVED", "rewrite persisted")


def test_exit_codes() -> None:
    check(exit_code_for("APPROVED") == 0, "APPROVED exits 0")
    check(exit_code_for("BLOCKED") == 1, "BLOCKED exits 1")
    check(exit_code_for("STALE") == 1, "STALE exits 1")
    check(exit_code_for("EXPIRED") == 1, "EXPIRED exits 1")


def main() -> int:
    test_approved()
    test_missing_artifacts()
    test_env_blocked()
    test_review_pending()
    test_missing_leaf()
    test_stale_review()
    test_expired()
    test_no_head()
    test_stale_artifact()
    test_unit_tests_artifact_precedence()
    test_device_mode_disabled()
    test_diff_sha_determinism()
    test_smart_test_promotion()
    test_write_last_verdict()
    test_exit_codes()
    if FAILURES:
        print(f"\n[FAIL] {len(FAILURES)} check(s) failed:")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("\n[SUCCESS] FINAL VERDICT SELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

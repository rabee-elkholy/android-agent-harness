"""Self-test for the review-round cap ledger in _hook_state.py. Stdlib only."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

os.environ["HARNESS_HOOK_STATE"] = str(Path(tempfile.mkdtemp()) / "review-invokes.json")
os.environ["HARNESS_MAX_REVIEWS"] = "20"

from _hook_state import (  # noqa: E402
    MAX_REVIEW_ROUNDS,
    clear_task_rounds,
    record_review_round,
    record_review_round_local,
    reset_task_rounds,
    round_cap_warning,
    rounds_used,
    task_rounds_used,
)

FAILURES: list[str] = []
FAKE_HEAD_A = "a" * 40
FAKE_HEAD_B = "b" * 40


def check(cond: bool, label: str) -> None:
    if cond:
        print(f"[PASS] {label}")
    else:
        FAILURES.append(label)
        print(f"[FAIL] {label}")


def test_basic_counting() -> None:
    check(rounds_used("T1", head_sha=FAKE_HEAD_A) == 0, "fresh ledger starts at 0")
    record_review_round_local("T1", "pkg1", head_sha=FAKE_HEAD_A)
    check(rounds_used("T1", head_sha=FAKE_HEAD_A) == 1, "one round recorded")
    record_review_round_local("T1", "pkg2", head_sha=FAKE_HEAD_A)
    check(rounds_used("T1", head_sha=FAKE_HEAD_A) == 2, "two rounds recorded")
    clear_task_rounds("T1")


def test_task_separation() -> None:
    record_review_round_local("TASK-A", "pkg1", head_sha=FAKE_HEAD_A)
    record_review_round_local("TASK-A", "pkg2", head_sha=FAKE_HEAD_A)
    check(rounds_used("TASK-A", head_sha=FAKE_HEAD_A) == 2, "task A has 2 rounds")
    check(rounds_used("TASK-B", head_sha=FAKE_HEAD_A) == 0, "task B independent at 0")
    record_review_round_local("", "pkg3", head_sha=FAKE_HEAD_A)
    check(rounds_used(None, head_sha=FAKE_HEAD_A) == 1, "empty task id uses unscoped key")
    check(rounds_used("", head_sha=FAKE_HEAD_A) == 1, "blank task id equals unscoped key")
    clear_task_rounds("TASK-A")
    clear_task_rounds("")


def test_warning_threshold() -> None:
    record_review_round_local("W1", "pkg1", head_sha=FAKE_HEAD_A)
    check(round_cap_warning("W1", cap=2, head_sha=FAKE_HEAD_A) == "", "no warning below cap")
    record_review_round_local("W1", "pkg2", head_sha=FAKE_HEAD_A)
    warning = round_cap_warning("W1", cap=2, head_sha=FAKE_HEAD_A)
    check(bool(warning), "warning emitted at cap")
    check("REVIEW ROUND CAP" in warning, "warning carries the cap marker")
    check("Summary Card" in warning, "warning requires a summary card")
    check(round_cap_warning("W1", cap=3, head_sha=FAKE_HEAD_A) == "", "explicit larger cap silences warning")
    check(
        round_cap_warning("W1", cap=2, head_sha=FAKE_HEAD_A) == round_cap_warning("W1", head_sha=FAKE_HEAD_A),
        "default cap equals 2",
    )
    clear_task_rounds("W1")


def test_head_change_reset() -> None:
    record_review_round_local("H1", "pkg1", head_sha=FAKE_HEAD_A)
    record_review_round_local("H1", "pkg2", head_sha=FAKE_HEAD_A)
    check(rounds_used("H1", head_sha=FAKE_HEAD_B) == 0, "new HEAD resets the counter view")
    record_review_round_local("H1", "pkg3", head_sha=FAKE_HEAD_B)
    check(rounds_used("H1", head_sha=FAKE_HEAD_B) == 1, "recording after HEAD change starts fresh")
    clear_task_rounds("H1")


def test_clear_task_rounds() -> None:
    record_review_round_local("C1", "pkg1", head_sha=FAKE_HEAD_A)
    clear_task_rounds("C1")
    check(rounds_used("C1", head_sha=FAKE_HEAD_A) == 0, "clear resets the task counter")


def test_corrupted_ledger() -> None:
    from _hook_state import _rounds_path

    path = _rounds_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{corrupted json", encoding="utf-8")
    check(rounds_used("X1", head_sha=FAKE_HEAD_A) == 0, "corrupted ledger reads as empty")
    record_review_round_local("X1", "pkg1", head_sha=FAKE_HEAD_A)
    check(rounds_used("X1", head_sha=FAKE_HEAD_A) == 1, "recording overwrites corruption")
    clear_task_rounds("X1")


def test_hook_side_per_task() -> None:
    record_review_round("conv-1", "digest1", task_id="TA")
    check(task_rounds_used("conv-1", "TA") == 1, "hook round recorded for task TA")
    check(task_rounds_used("conv-1", "TB") == 0, "hook task TB independent")
    record_review_round("conv-1", "digest2", task_id="TA")
    check(task_rounds_used("conv-1", "TA") == 2, "hook rounds accumulate per task")
    record_review_round("conv-1", "digest3")
    check(task_rounds_used("conv-1", None) == 1, "hook unscoped key works")
    reset_task_rounds("conv-1", "TA")
    check(task_rounds_used("conv-1", "TA") == 0, "hook reset clears one task")
    check(task_rounds_used("conv-1", None) == 1, "hook reset leaves other tasks intact")


def test_default_cap_value() -> None:
    check(MAX_REVIEW_ROUNDS == 2, "default project round cap is 2")


def main() -> int:
    test_basic_counting()
    test_task_separation()
    test_warning_threshold()
    test_head_change_reset()
    test_clear_task_rounds()
    test_corrupted_ledger()
    test_hook_side_per_task()
    test_default_cap_value()
    if FAILURES:
        print(f"\n[FAIL] {len(FAILURES)} check(s) failed:")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("\n[SUCCESS] ROUND CAP SELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

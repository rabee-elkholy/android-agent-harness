"""Comprehensive Selftest Suite for Harness Environment Adaptability.

Exercises:
1. Universal environment & surface detection (_environment.py).
2. Cross-platform review bridge (record_review.py).
3. PreToolUse self-healing command rewriting (overwrite).
4. Stop lifecycle hook & loop breaker.
5. Generative UI cards & Markdown fallbacks (render_ui.py).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import _environment as env_mod  # noqa: E402
from _environment import AssistantEnv, AntigravitySurface  # noqa: E402

SAFETY_ENGINE = SCRIPTS / "pre_tool_safety.py"
RECORD_REVIEW = SCRIPTS / "record_review.py"
RENDER_UI = SCRIPTS / "render_ui.py"


def _case(name: str, ok: bool, detail: str = "") -> int:
    print(f"env_adaptive_{name}: {'OK' if ok else 'FAIL' + (' ' + detail if detail else '')}")
    return int(not ok)


def test_environment_detection() -> int:
    failed = 0

    # 1. Test override
    os.environ["HARNESS_TEST_ENV"] = "cursor"
    env_mod._CACHED_PROFILE = None
    p_cur = env_mod.detect_runtime_profile()
    del os.environ["HARNESS_TEST_ENV"]
    failed += _case("detection_test_override", p_cur.env == AssistantEnv.CURSOR)

    # 2. Antigravity via payload
    env_mod._CACHED_PROFILE = None
    p_ag = env_mod.detect_runtime_profile({"transcriptPath": "C:/fake/transcript.jsonl"})
    failed += _case(
        "detection_antigravity_payload",
        p_ag.env == AssistantEnv.ANTIGRAVITY
        and p_ag.has_stop_hook is True
        and p_ag.has_pre_tool_overwrite is True
        and p_ag.has_generative_ui is True,
    )

    # 3. Claude Code via tool_name == 'Bash'
    env_mod._CACHED_PROFILE = None
    p_cc = env_mod.detect_runtime_profile({"tool_name": "Bash", "tool_input": {"command": "git status"}})
    failed += _case("detection_claude_code_payload", p_cc.env == AssistantEnv.CLAUDE_CODE)

    # 4. Codex CLI via environment
    env_clean = os.environ.copy()
    for k in list(env_clean.keys()):
        if k.startswith("ANTIGRAVITY"):
            del env_clean[k]
    env_clean["CODEX_CLI"] = "1"
    proc_codex = subprocess.run(
        [sys.executable, "-c", "import _environment, sys; sys.stdout.write(_environment.detect_runtime_profile().env.value)"],
        cwd=str(SCRIPTS),
        capture_output=True,
        text=True,
        env=env_clean,
    )
    failed += _case("detection_codex_cli_subprocess", proc_codex.stdout.strip() == "codex")

    return failed


def test_record_review_bridge() -> int:
    failed = 0
    tmp_dir = Path(tempfile.mkdtemp())
    diff_content = "diff --git a/Foo.kt b/Foo.kt\n+val x = 1\n"
    pkg_file = tmp_dir / "pkg.diff"
    pkg_file.write_text(diff_content, encoding="utf-8", newline="\n")
    pkg_hash = hashlib.sha256(pkg_file.read_bytes()).hexdigest()[:12]

    env = os.environ.copy()
    env["_IN_HOOK_SELFTEST"] = "1"
    env["HARNESS_HOOK_STATE"] = str(tmp_dir / "review-invokes.json")

    # 1. Record approve all
    proc = subprocess.run(
        [sys.executable, str(RECORD_REVIEW), "--pkg", str(pkg_file), "--approve-all"],
        capture_output=True,
        text=True,
        env=env,
    )
    verdict_file = tmp_dir / "verdicts" / f"verdict-{pkg_hash}.json"
    ok_verdict = verdict_file.is_file()
    if ok_verdict:
        v_data = json.loads(verdict_file.read_text(encoding="utf-8"))
        leaves = v_data.get("leaves", {})
        ok_verdict = len(leaves) >= 5 and all("PASS" in str(l.get("verdict", "")) for l in leaves.values())

    failed += _case("record_review_approve_all", proc.returncode == 0 and ok_verdict)

    # 2. Record single leaf with findings
    proc_leaf = subprocess.run(
        [
            sys.executable,
            str(RECORD_REVIEW),
            "--pkg",
            str(pkg_file),
            "--leaf",
            "convention-reviewer-agent",
            "--verdict",
            "FINDINGS",
            "--finding",
            "ViewModel directly references MutableStateFlow",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    v_data2 = json.loads(verdict_file.read_text(encoding="utf-8"))
    leaves2 = v_data2.get("leaves", {})
    leaf_rec = leaves2.get("convention_reviewer") or leaves2.get("convention-reviewer-agent") or {}
    ok_leaf = leaf_rec.get("verdict") == "FINDINGS" and len(v_data2.get("findings", [])) > 0
    failed += _case("record_review_single_leaf_finding", proc_leaf.returncode == 0 and ok_leaf)

    return failed


def test_self_healing_command_overwrite() -> int:
    failed = 0
    env_ag = os.environ.copy()
    env_ag["_IN_HOOK_SELFTEST"] = "1"
    env_ag["HARNESS_TEST_ENV"] = "antigravity"

    payload_gradle = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "./gradlew :app:testDebugUnitTest"},
        }
    }
    proc_ag = subprocess.run(
        [sys.executable, str(SAFETY_ENGINE)],
        input=json.dumps(payload_gradle),
        capture_output=True,
        text=True,
        env=env_ag,
    )
    out_ag = json.loads(proc_ag.stdout or "{}")
    ok_ag = (
        out_ag.get("decision") == "allow"
        and "run_gradle_task.py :app:testDebugUnitTest" in str(out_ag.get("overwrite", {}).get("CommandLine", ""))
    )
    failed += _case("self_healing_gradlew_overwrite", ok_ag)

    # In Codex environment -> should deny raw gradlew
    env_codex = os.environ.copy()
    env_codex["_IN_HOOK_SELFTEST"] = "1"
    env_codex["HARNESS_TEST_ENV"] = "codex"
    proc_codex = subprocess.run(
        [sys.executable, str(SAFETY_ENGINE)],
        input=json.dumps(payload_gradle),
        capture_output=True,
        text=True,
        env=env_codex,
    )
    out_codex = json.loads(proc_codex.stdout or "{}")
    ok_codex = (
        out_codex.get("decision") == "deny"
        and "raw gradlew is forbidden" in str(out_codex.get("reason", ""))
    )
    failed += _case("codex_raw_gradlew_denial", ok_codex)

    return failed


def test_stop_hook_and_loop_breaker() -> int:
    failed = 0
    tmp_dir = Path(tempfile.mkdtemp())
    env = os.environ.copy()
    env["_IN_HOOK_SELFTEST"] = "1"
    env["HARNESS_HOOK_STATE"] = str(tmp_dir / "review-invokes.json")

    # 1. Clean tree (no code changes) -> allow stop
    env["HARNESS_TEST_FORCE_CODE_CHANGES"] = "0"
    p_clean = subprocess.run(
        [sys.executable, str(SAFETY_ENGINE)],
        input=json.dumps({"terminationReason": "model_stop"}),
        capture_output=True,
        text=True,
        env=env,
    )
    out_clean = json.loads(p_clean.stdout or "{}")
    failed += _case("stop_hook_clean_tree_allow", out_clean.get("decision") == "allow")

    # 2. Unreviewed code changes -> continue (block termination)
    env["HARNESS_TEST_FORCE_CODE_CHANGES"] = "1"
    env["HARNESS_TEST_DIFF_SIG"] = "diff-hash-alpha"
    p_block1 = subprocess.run(
        [sys.executable, str(SAFETY_ENGINE)],
        input=json.dumps({"terminationReason": "model_stop"}),
        capture_output=True,
        text=True,
        env=env,
    )
    out_block1 = json.loads(p_block1.stdout or "{}")
    failed += _case("stop_hook_unreviewed_continue", out_block1.get("decision") == "continue")

    # 3. Block 2 on same diff
    p_block2 = subprocess.run(
        [sys.executable, str(SAFETY_ENGINE)],
        input=json.dumps({"terminationReason": "model_stop"}),
        capture_output=True,
        text=True,
        env=env,
    )
    out_block2 = json.loads(p_block2.stdout or "{}")
    failed += _case("stop_hook_second_block_continue", out_block2.get("decision") == "continue")

    # 4. Loop breaker triggers on 3rd attempt with identical unchanged diff -> allow stop
    p_breaker = subprocess.run(
        [sys.executable, str(SAFETY_ENGINE)],
        input=json.dumps({"terminationReason": "model_stop"}),
        capture_output=True,
        text=True,
        env=env,
    )
    out_breaker = json.loads(p_breaker.stdout or "{}")
    ok_breaker = (
        out_breaker.get("decision") == "allow"
        and "loop breaker" in str(out_breaker.get("reason", "")).lower()
    )
    failed += _case("stop_hook_loop_breaker_allow", ok_breaker)

    # 5. Environment failure file present -> allow stop (exit 30 protocol)
    env_fail_file = tmp_dir / "env_failure.json"
    env_fail_file.write_text('{"exit_code": 30, "reason": "No device"}', encoding="utf-8")
    p_env_fail = subprocess.run(
        [sys.executable, str(SAFETY_ENGINE)],
        input=json.dumps({"terminationReason": "model_stop"}),
        capture_output=True,
        text=True,
        env=env,
    )
    out_env_fail = json.loads(p_env_fail.stdout or "{}")
    failed += _case("stop_hook_env_failure_allow", out_env_fail.get("decision") == "allow")

    return failed


def test_generative_ui_and_markdown() -> int:
    failed = 0

    # 1. Antigravity UI mode
    env_ag = os.environ.copy()
    env_ag["HARNESS_TEST_ENV"] = "antigravity"
    proc_ag = subprocess.run(
        [sys.executable, str(RENDER_UI), "--demo"],
        capture_output=True,
        text=True,
        env=env_ag,
    )
    ok_ag = "<agent-embed" in proc_ag.stdout
    failed += _case("render_ui_antigravity_embed", ok_ag)

    # 2. Codex Markdown fallback mode
    env_codex = os.environ.copy()
    env_codex["HARNESS_TEST_ENV"] = "codex"
    proc_codex = subprocess.run(
        [sys.executable, str(RENDER_UI), "--demo"],
        capture_output=True,
        text=True,
        env=env_codex,
    )
    ok_codex = (
        "### Review Round 1 Summary" in proc_codex.stdout
        and "[PASS]" in proc_codex.stdout
        and "<agent-embed" not in proc_codex.stdout
    )
    failed += _case("render_ui_codex_markdown_table", ok_codex)

    return failed


def main() -> int:
    total_failed = 0
    total_failed += test_environment_detection()
    total_failed += test_record_review_bridge()
    total_failed += test_self_healing_command_overwrite()
    total_failed += test_stop_hook_and_loop_breaker()
    total_failed += test_generative_ui_and_markdown()

    print(f"\nEnvironment adaptability selftest failures: {total_failed}")
    return total_failed


if __name__ == "__main__":
    sys.exit(main())

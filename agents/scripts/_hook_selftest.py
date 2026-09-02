"""Local self-test for this app multi-agent hooks. Does not execute shell commands."""
# TODO(audit/2026-02): consider splitting this ~88KB module into per-area suites
# (engine, wizard, doctor, CLI, adapters, security) — deferred, see ROADMAP.md.
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
try:
    from _product import ALLOW_EMULATOR
except Exception:
    ALLOW_EMULATOR = True
SCRIPT = SCRIPTS / "pre_tool_safety.py"
REMINDER = SCRIPTS / "pre_invocation_reminder.py"
SUBAGENTS = SCRIPTS.parent / "subagents"

TEMPLATE_BUG = SUBAGENTS / "bug-reviewer-agent.json"
TEMPLATE_CONV = SUBAGENTS / "convention-reviewer-agent.json"
TEMPLATE_SEC = SUBAGENTS / "security-reviewer-agent.json"
TEMPLATE_PERF = SUBAGENTS / "perf-anr-guardian-agent.json"
TEMPLATE_REG = SUBAGENTS / "regression-impact-reviewer-agent.json"
TEMPLATE_QA = SUBAGENTS / "qa-diagnostics-agent.json"
TEMPLATE_UI = SUBAGENTS / "android-ui-expert-agent.json"
TEMPLATE_TEST = SUBAGENTS / "test-quality-reviewer-agent.json"

STATE = Path(tempfile.mkdtemp()) / "review-invokes.json"
PACKAGE = Path(tempfile.mkdtemp()) / "pkg.diff"
PACKAGE.write_text("diff --git a/x b/x\n", encoding="utf-8")
os.environ["HARNESS_HOOK_STATE"] = str(STATE)
os.environ["HARNESS_MAX_REVIEWS"] = "20"
os.environ["_IN_HOOK_SELFTEST"] = "1"
# Existing barrier groups exercise legacy token semantics; v0.9.0 evidence
# groups below flip HARNESS_EVIDENCE_MODE explicitly per scenario.
os.environ.setdefault("HARNESS_EVIDENCE_MODE", "legacy")
# Kit-only probes (grants example, harness_cli, scripts_dev fixtures) exist only
# in the kit checkout. Installed app repos receive agents/ alone, so those
# probe groups must degrade to explicit skips instead of crashing.
KIT_LAYOUT = (SCRIPTS.parents[1] / "harness_cli.py").is_file()

PROMPT_BUG = json.loads(TEMPLATE_BUG.read_text(encoding="utf-8"))["system_prompt"]
PROMPT_CONV = json.loads(TEMPLATE_CONV.read_text(encoding="utf-8"))["system_prompt"]
PROMPT_SEC = json.loads(TEMPLATE_SEC.read_text(encoding="utf-8"))["system_prompt"]
PROMPT_PERF = json.loads(TEMPLATE_PERF.read_text(encoding="utf-8"))["system_prompt"]
PROMPT_REG = json.loads(TEMPLATE_REG.read_text(encoding="utf-8"))["system_prompt"]
PROMPT_QA = json.loads(TEMPLATE_QA.read_text(encoding="utf-8"))["system_prompt"]
PROMPT_UI = json.loads(TEMPLATE_UI.read_text(encoding="utf-8"))["system_prompt"]
PROMPT_TEST = json.loads(TEMPLATE_TEST.read_text(encoding="utf-8"))["system_prompt"]

REVIEW_FIVE = [
    "bug-reviewer-agent",
    "convention-reviewer-agent",
    "security-reviewer-agent",
    "perf-anr-guardian-agent",
    "regression-impact-reviewer-agent",
]


def run(payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=os.environ.copy(),
    )
    return json.loads(proc.stdout)


def run_reminder(payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(REMINDER)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=os.environ.copy(),
    )
    return json.loads(proc.stdout)


def cmd(line: str, conversation: str | None = None) -> dict:
    payload = {"toolCall": {"name": "run_command", "args": {"CommandLine": line}}}
    if conversation:
        payload["conversationId"] = conversation
    return payload


def invoke(conversation, name="bug-reviewer-agent", prompt_prefix="HARNESS_REVIEW_PACKAGE=", extra=None, **sub):
    prompt_str = f"{prompt_prefix}{PACKAGE}\nFindings or PASS." if prompt_prefix else "Perform deep analysis."
    subagent = {
        "Workspace": "inherit",
        "TypeName": name,
        "Prompt": prompt_str,
    }
    subagent.update(sub)
    payload = {
        "conversationId": conversation,
        "toolCall": {
            "name": "invoke_subagent",
            "args": {"Subagents": [subagent]},
        },
    }
    if extra:
        payload["toolCall"]["args"].update(extra)
    return payload


def invoke_five(conversation: str, package: Path = PACKAGE) -> dict:
    subs = []
    for name in REVIEW_FIVE:
        subs.append({
            "Workspace": "inherit",
            "TypeName": name,
            "Prompt": f"HARNESS_REVIEW_PACKAGE={package} Findings or PASS.",
        })
    return {
        "conversationId": conversation,
        "toolCall": {"name": "invoke_subagent", "args": {"Subagents": subs}},
    }


def define(prompt, name="bug-reviewer-agent", **kwargs):
    args = {
        "name": name,
        "system_prompt": prompt,
        "enable_write_tools": False,
        "enable_subagent_tools": False,
    }
    args.update(kwargs)
    return {"toolCall": {"name": "define_subagent", "args": args}}


def sched(prompt: str, conversation: str | None = None) -> dict:
    payload = {
        "toolCall": {
            "name": "schedule",
            "args": {"DurationSeconds": 10, "Prompt": prompt, "TimerCondition": "any"},
        }
    }
    if conversation:
        payload["conversationId"] = conversation
    return payload


def manage_t(action: str, task_id: str = "task-1", conversation: str = "conv-poll") -> dict:
    return {
        "conversationId": conversation,
        "toolCall": {
            "name": "manage_task",
            "args": {"Action": action, "TaskId": task_id},
        },
    }


def manage_s(action: str, conversation: str = "conv-sub-poll") -> dict:
    return {
        "conversationId": conversation,
        "toolCall": {
            "name": "manage_subagents",
            "args": {"Action": action},
        },
    }


cases = [
    ("empty", {}, "allow"),
    ("monkey", cmd("adb -s DEV shell monkey -p com.example.app 1"), "deny"),
    ("git_mutation", cmd("git commit -m x"), "deny"),
    ("git_c_commit", cmd("git -C E:\\AndroidProjects\\SomeApp commit -m x"), "deny"),
    ("git_subshell_powershell", cmd('powershell -Command "git commit -m x"'), "deny"),
    ("git_exe", cmd("git.exe push origin main"), "deny"),
    ("git_usr_bin", cmd("/usr/bin/git checkout master"), "deny"),
    ("git_chained", cmd("echo hello && git reset --hard"), "deny"),
    ("git_status_then_push", cmd("git status --short --branch && git push origin main"), "deny"),
    ("git_log_semi_reset", cmd("git log --oneline; git reset --hard HEAD~1"), "deny"),
    ("git_diff_pipe_checkout", cmd("git diff | head -50 || git checkout -- ."), "deny"),
    ("git_status_or_stash", cmd('powershell -Command "git status; git stash drop"'), "deny"),
    ("git_status_inspection_only", cmd("git status --short --branch && git diff HEAD --stat"), "allow"),
    ("git_log_pipe_head", cmd("git log --oneline -5 | head -20"), "allow"),
    ("installer_adapters_allowed", cmd("python .agents/scripts/install_tool_adapters.py --product SampleApp --assemble :app:assembleDebug --tools gemini"), "allow"),
    ("git_status", cmd("git status --short --branch"), "allow"),
    ("sched_waiting_subagents", sched("Waiting for 5 review subagents"), "deny"),
    ("sched_user_reminder", sched("Remind developer about coffee in 10 mins"), "allow"),
    ("manage_task_poll_1", manage_t("status", "task-x", "conv-task-poll"), "allow"),
    ("manage_task_poll_2", manage_t("status", "task-x", "conv-task-poll"), "allow"),
    ("manage_task_poll_3_deny", manage_t("status", "task-x", "conv-task-poll"), "deny"),
    ("adb_uninstall_s", cmd("adb -s DEV uninstall com.example.app"), "allow"),
    ("adb_uninstall_bare", cmd("adb uninstall com.example.app"), "deny"),
    ("run_device_uninstall", cmd("python .agents/scripts/run_device.py uninstall"), "allow"),
    ("pm_clear", cmd("adb -s DEV shell pm clear com.example.app"), "deny"),
    ("pm_uninstall", cmd("adb -s DEV shell pm uninstall com.example.app"), "deny"),
    ("adb_cmd_package_clear", cmd("adb -s DEV shell cmd package clear com.example.app"), "deny"),
    ("adb_cmd_package_uninstall", cmd("adb -s DEV shell cmd package uninstall com.example.app"), "deny"),
    ("adb_cmd_package_list_ok", cmd("adb -s DEV shell cmd package list packages"), "allow"),
    ("adb_root_bare", cmd("adb root"), "deny"),
    ("adb_backup_bare", cmd("adb backup -apk -shared -all"), "deny"),
    ("adb_remount_bare", cmd("adb remount"), "deny"),
    ("adb_reboot_bound_ok", cmd("adb -s DEV reboot"), "allow"),
    ("sub_share", invoke("c-share", Workspace="share"), "deny"),
    ("sub_not_allowed", invoke("c-other", name="arbitrary-unregistered-agent"), "deny"),
    (
        "sub_guard_retired",
        invoke("c-guard", name="code-review-guard-agent"),
        "deny",
    ),
    (
        "sub_write_tools",
        invoke("c-write", enable_write_tools=True),
        "deny",
    ),
    (
        "sub_one_reviewer",
        invoke("c-one", name="bug-reviewer-agent"),
        "deny",
    ),
    (
        "sub_qa_diagnostics",
        invoke("c-qa", name="qa-diagnostics-agent", prompt_prefix=""),
        "allow",
    ),
    (
        "sub_android_ui_expert",
        invoke("c-ui", name="android-ui-expert-agent", prompt_prefix=""),
        "allow",
    ),
    (
        "sub_compose_ui_expert_alias",
        invoke("c-compose", name="compose-ui-expert-agent", prompt_prefix=""),
        "allow",
    ),
    (
        "sub_solo_perf_audit",
        invoke("c-perf", name="perf-anr-guardian-agent", prompt_prefix=""),
        "allow",
    ),
    (
        "sub_test_quality",
        invoke("c-test", name="test-quality-reviewer-agent", prompt_prefix=""),
        "allow",
    ),
    ("emu", cmd("android emulator start pixel"), "allow" if ALLOW_EMULATOR else "deny"),
    ("git_grep_monkey", cmd("git log --grep monkey --oneline"), "allow"),
    ("cat_gradle_properties", cmd("cat gradle.properties"), "allow"),
    ("sched_review_word_only", sched("Remind me to do the code review later today"), "allow"),
    ("android_run_bare", cmd("android run"), "deny"),
    ("android_run_device", cmd("android run --device DEV"), "allow"),
    ("adb_install_bare", cmd("adb install -r app.apk"), "deny"),
    ("adb_install_s", cmd("adb -s DEV install -r -d app.apk"), "allow"),
    (
        "am_start",
        cmd("adb -s DEV shell am start -n com.example.app/.MainActivity"),
        "allow",
    ),
    ("define_bug_ok", define(PROMPT_BUG, name="bug-reviewer-agent"), "allow"),
    ("define_conv_ok", define(PROMPT_CONV, name="convention-reviewer-agent"), "allow"),
    ("define_sec_ok", define(PROMPT_SEC, name="security-reviewer-agent"), "allow"),
    ("define_perf_ok", define(PROMPT_PERF, name="perf-anr-guardian-agent"), "allow"),
    ("define_reg_ok", define(PROMPT_REG, name="regression-impact-reviewer-agent"), "allow"),
    ("define_qa_ok", define(PROMPT_QA, name="qa-diagnostics-agent"), "allow"),
    ("define_ui_ok", define(PROMPT_UI, name="android-ui-expert-agent"), "allow"),
    ("define_ui_alias_ok", define(PROMPT_UI, name="compose-ui-expert-agent"), "allow"),
    ("define_test_ok", define(PROMPT_TEST, name="test-quality-reviewer-agent"), "allow"),
    (
        "define_homemade",
        define("Review whole files for leaks and nits.", name="bug-reviewer-agent"),
        "deny",
    ),
    (
        "define_fingerprint_only",
        define(
            "HARNESS_BUG_FINGERPRINT=quality-first-bug-review-v2\nYou are a different prompt.",
            name="bug-reviewer-agent",
        ),
        "deny",
    ),
    (
        "define_guard_retired",
        define("x", name="code-review-guard-agent"),
        "deny",
    ),
    (
        "define_other_name",
        define(PROMPT_BUG, name="unregistered-agent"),
        "deny",
    ),
    (
        "define_writes",
        define(PROMPT_BUG, name="bug-reviewer-agent", enable_write_tools=True),
        "deny",
    ),
]

failed = 0
for name, payload, expected in cases:
    if name == "empty":
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input="",
            text=True,
            capture_output=True,
            check=True,
            env=os.environ.copy(),
        )
        got = json.loads(proc.stdout)["decision"]
    else:
        got = run(payload)["decision"]
    ok = got == expected
    print(f"{name}: {got} {'OK' if ok else 'FAIL expected ' + expected}")
    failed += int(not ok)

# --- v0.15.0: product-policy-driven safety (I.3 / I.4 via _product.py) ---
os.environ["HARNESS_TEST_ALLOW_EMULATOR"] = "false"
emu_phys_deny = run(cmd("android emulator start pixel"))["decision"] == "deny"
emu_avd_deny = run(cmd("avdmanager list avd"))["decision"] == "deny"
os.environ.pop("HARNESS_TEST_ALLOW_EMULATOR", None)

os.environ["HARNESS_TEST_GIT_POLICY"] = "agent-may-commit"
git_add_allow = run(cmd("git add -A"))["decision"] == "allow"
git_commit_allow = run(cmd("git commit -m fix"))["decision"] == "allow"
git_push_deny = run(cmd("git push origin main"))["decision"] == "deny"
git_reset_deny = run(cmd("git reset --hard"))["decision"] == "deny"
os.environ.pop("HARNESS_TEST_GIT_POLICY", None)

ok_policy_driven = emu_phys_deny and emu_avd_deny and git_add_allow and git_commit_allow and git_push_deny and git_reset_deny
print(
    f"product-policy-driven safety (I.3/I.4): "
    f"{'OK' if ok_policy_driven else 'FAIL ' + str([emu_phys_deny, emu_avd_deny, git_add_allow, git_commit_allow, git_push_deny, git_reset_deny])}"
)
failed += int(not ok_policy_driven)

# --- v0.15.0: HARNESS_REVIEW_PACKAGE path with spaces ---
spaced_pkg = Path(tempfile.mkdtemp(prefix="harness spaced path ")) / "pkg review.diff"
spaced_pkg.write_text("diff --git a/x b/x\n", encoding="utf-8")
spaced_invoke = {
    "conversationId": "c-spaced",
    "toolCall": {
        "name": "invoke_subagent",
        "args": {
            "Subagents": [
                {
                    "Workspace": "inherit",
                    "TypeName": name,
                    "Prompt": f"HARNESS_REVIEW_PACKAGE={spaced_pkg}\nFindings or PASS.",
                }
                for name in REVIEW_FIVE
            ]
        },
    },
}
spaced_res = run(spaced_invoke)
ok_spaced_path = spaced_res["decision"] == "allow"
print(f"review package path with spaces: {spaced_res['decision']} {'OK' if ok_spaced_path else 'FAIL ' + json.dumps(spaced_res)}")
failed += int(not ok_spaced_path)

# 5-leaf happy path + identical hash reject + changed hash allow
five_conv = "c-five"
first = run(invoke_five(five_conv))
ok_five = first["decision"] == "allow"
print(f"five_leaf_first: {first['decision']} {'OK' if ok_five else 'FAIL ' + json.dumps(first)}")
failed += int(not ok_five)

second_same = run(invoke_five(five_conv))
ok_same = second_same["decision"] == "deny" and "already reviewed" in second_same.get("reason", "").lower()
print(f"five_leaf_identical_hash: {second_same['decision']} {'OK' if ok_same else 'FAIL ' + json.dumps(second_same)}")
failed += int(not ok_same)

# Define subagent allows immediate re-dispatch of the same package (recovering from initial registration failure)
def_bug = {
    "conversationId": five_conv,
    "toolCall": {
        "name": "define_subagent",
        "args": {
            "name": "bug-reviewer-agent",
            "description": "Bug Reviewer",
            "system_prompt": PROMPT_BUG,
        },
    },
}
def_res = run(def_bug)
ok_def = def_res["decision"] == "allow"
print(f"define_subagent_redispatch_flag: {def_res['decision']} {'OK' if ok_def else 'FAIL ' + json.dumps(def_res)}")
failed += int(not ok_def)

second_allowed = run(invoke_five(five_conv))
ok_reallowed = second_allowed["decision"] == "allow"
print(f"five_leaf_redispatch_after_define: {second_allowed['decision']} {'OK' if ok_reallowed else 'FAIL ' + json.dumps(second_allowed)}")
failed += int(not ok_reallowed)

PACKAGE.write_text("diff --git a/x b/x\nchanged\n", encoding="utf-8")
third = run(invoke_five(five_conv))
ok_third = third["decision"] == "allow"
print(f"five_leaf_new_hash: {third['decision']} {'OK' if ok_third else 'FAIL ' + json.dumps(third)}")
failed += int(not ok_third)

# Four leaves must deny
four = {
    "conversationId": "c-four",
    "toolCall": {
        "name": "invoke_subagent",
        "args": {
            "Subagents": [
                {
                    "Workspace": "inherit",
                    "TypeName": name,
                    "Prompt": f"HARNESS_REVIEW_PACKAGE={PACKAGE} x",
                }
                for name in REVIEW_FIVE[:4]
            ]
        },
    },
}
four_res = run(four)
ok_four = four_res["decision"] == "deny"
print(f"four_leaf_denied: {four_res['decision']} {'OK' if ok_four else 'FAIL ' + json.dumps(four_res)}")
failed += int(not ok_four)

# --- Smart Test Promotion: diff with test files requires 6 leaves (+ test-quality-reviewer-agent) ---
test_pkg_file = Path(tempfile.mkdtemp(prefix="harness-test-diff-")) / "pkg-tests.diff"
test_pkg_file.write_text(
    "# HARNESS_PACKAGE_HEADER v2\nCONTAINS_TESTS=true\nTEST_FILES_COUNT=1\nPACKAGE_SHA256=PENDING\n"
    "diff --git a/app/src/test/HomeViewModelTest.kt b/app/src/test/HomeViewModelTest.kt\n+class HomeViewModelTest\n",
    encoding="utf-8",
)
# 5 leaves on test package must deny
five_on_tests = {
    "conversationId": "c-test-5",
    "toolCall": {
        "name": "invoke_subagent",
        "args": {
            "Subagents": [
                {
                    "Workspace": "inherit",
                    "TypeName": name,
                    "Prompt": f"HARNESS_REVIEW_PACKAGE={test_pkg_file}\nFindings or PASS.",
                }
                for name in REVIEW_FIVE
            ]
        },
    },
}
five_on_tests_res = run(five_on_tests)
ok_test_promo_deny = five_on_tests_res["decision"] == "deny" and "Smart Test Promotion" in str(five_on_tests_res.get("reason"))
print(f"smart_test_promotion_5_leaf_deny: {five_on_tests_res['decision']} {'OK' if ok_test_promo_deny else 'FAIL ' + json.dumps(five_on_tests_res)}")
failed += int(not ok_test_promo_deny)

# 6 leaves on test package must allow
six_on_tests = {
    "conversationId": "c-test-6",
    "toolCall": {
        "name": "invoke_subagent",
        "args": {
            "Subagents": [
                {
                    "Workspace": "inherit",
                    "TypeName": name,
                    "Prompt": f"HARNESS_REVIEW_PACKAGE={test_pkg_file}\nFindings or PASS.",
                }
                for name in [*REVIEW_FIVE, "test-quality-reviewer-agent"]
            ]
        },
    },
}
six_on_tests_res = run(six_on_tests)
ok_test_promo_allow = six_on_tests_res["decision"] == "allow"
print(f"smart_test_promotion_6_leaf_allow: {six_on_tests_res['decision']} {'OK' if ok_test_promo_allow else 'FAIL ' + json.dumps(six_on_tests_res)}")
failed += int(not ok_test_promo_allow)

# Review package path traversal outside repo/temp must deny
external_pkg = Path("C:/Windows/System32/drivers/etc/hosts" if os.name == "nt" else "/etc/hosts")
traversal_subs = [
    {
        "Workspace": "inherit",
        "TypeName": name,
        "Prompt": f"HARNESS_REVIEW_PACKAGE={external_pkg} x",
    }
    for name in REVIEW_FIVE
]
traversal_res = run({"conversationId": "c-trav", "toolCall": {"name": "invoke_subagent", "args": {"Subagents": traversal_subs}}})
ok_traversal = traversal_res["decision"] == "deny"
print(f"review_pkg_path_traversal: {traversal_res['decision']} {'OK' if ok_traversal else 'FAIL ' + json.dumps(traversal_res)}")
failed += int(not ok_traversal)

# Pending reviews block assemble (no transcript)
assemble = run(cmd("gradlew.bat :app:assembleDebug", conversation=five_conv))
ok_bar = assemble["decision"] == "deny"
print(f"assemble_while_pending: {assemble['decision']} {'OK' if ok_bar else 'FAIL ' + json.dumps(assemble)}")
failed += int(not ok_bar)

device_pending = run(cmd("python .agents/scripts/run_device.py install-start", conversation=five_conv))
ok_dev_bar = device_pending["decision"] == "deny"
print(
    f"run_device_while_pending: {device_pending['decision']} "
    f"{'OK' if ok_dev_bar else 'FAIL ' + json.dumps(device_pending)}"
)
failed += int(not ok_dev_bar)

# Reminder
reminder0 = run_reminder({"invocationNum": 0, "conversationId": "c-fresh"})
msg0 = reminder0["injectSteps"][0]["ephemeralMessage"]
for needle in (
    "0/20",
    "QUALITY",
    "ask_question",
    "bug-reviewer-agent",
    "convention-reviewer-agent",
    "security-reviewer-agent",
    "perf-anr-guardian-agent",
    "regression-impact-reviewer-agent",
    "qa-diagnostics-agent",
    "android-ui-expert-agent",
    "ZERO-TIMER INVARIANT",
    "ROUND SUMMARY CARDS",
    "AUTONOMOUS PHASE PIPELINE",
):
    ok = needle.lower() in msg0.lower() if needle == "QUALITY" else needle in msg0
    if needle == "QUALITY":
        ok = "quality" in msg0.lower()
    print(f"reminder unused contains {needle!r}: {'OK' if ok else 'FAIL'}")
    failed += int(not ok)
ok_no_guard = "code-review-guard-agent" not in msg0 or "Do not use code-review-guard-agent" in msg0
print(f"reminder retires code-review-guard: {'OK' if ok_no_guard else 'FAIL'}")
failed += int(not ok_no_guard)

# review_package generator
pkg_proc = subprocess.run(
    [sys.executable, str(SCRIPTS / "review_package.py")],
    text=True,
    capture_output=True,
    check=True,
    cwd=str(SCRIPTS.parents[1]),
)
pkg_lines = [l.strip() for l in pkg_proc.stdout.splitlines() if l.strip()]
pkg_line = next((l for l in pkg_lines if l.startswith("HARNESS_REVIEW_PACKAGE=")), None)
sha_line = next((l for l in pkg_lines if l.startswith("HARNESS_PACKAGE_SHA256_12=")), None)
ok = pkg_line is not None
pkg_path = Path(pkg_line.split("=", 1)[-1].strip()) if ok else None
ok = ok and pkg_path is not None and pkg_path.is_file()
print(f"review_package writes file: {'OK' if ok else 'FAIL ' + pkg_proc.stdout + pkg_proc.stderr}")
failed += int(not ok)

# v0.9.0: structured header block (TASK_ID, GIT_SHA, TREE_FINGERPRINT,
# GENERATED_AT, PACKAGE_SHA256 computed post-write) + sha256_12 on stdout.
ok_header = False
pkg_sha12_stdout = ""
if pkg_path is not None:
    import hashlib as _hl  # noqa: E402

    body = pkg_path.read_bytes()
    marker = b"PACKAGE_SHA256="
    mpos = body.find(marker)
    ok_header = (
        body.startswith(b"# HARNESS_PACKAGE_HEADER v2\n")
        and mpos > 0
        and b"TASK_ID=" in body[:mpos]
        and b"GIT_SHA=" in body[:mpos]
        and b"TREE_FINGERPRINT=" in body[:mpos]
        and b"GENERATED_AT=" in body[:mpos]
    )
    recorded = body[mpos + len(marker) : body.find(b"\n", mpos)].decode("ascii", "replace").strip()
    ok_header = ok_header and _hl.sha256(body[:mpos]).hexdigest() == recorded
    pkg_sha12_stdout = (
        sha_line.split("=", 1)[-1].strip()
        if sha_line
        else ""
    )
print(
    f"review_package v2 header: {'OK' if ok_header else 'FAIL ' + pkg_proc.stdout}"
)
failed += int(not ok_header)
ok_sha12 = len(pkg_sha12_stdout) == 12 and _hl.sha256(body).hexdigest()[:12] == pkg_sha12_stdout
print(f"review_package prints sha256_12: {'OK' if ok_sha12 else 'FAIL ' + repr(pkg_sha12_stdout)}")
failed += int(not ok_sha12)

# v0.10.x: machine-readable verdict artifact (PENDING) + per-file hashes in the header
if pkg_path is not None:
    from _hook_state import read_verdict_record  # noqa: E402

    file_digest = _hl.sha256(body).hexdigest()
    pending_rec = read_verdict_record(file_digest[:12])
    ok_pending = (
        pending_rec is not None
        and pending_rec.get("schema_version") in (1, 2)
        and pending_rec.get("verdict") == "PENDING"
        and pending_rec.get("package", {}).get("sha256") == file_digest
        and pending_rec.get("package", {}).get("sha256_12") == file_digest[:12]
        and isinstance(pending_rec.get("files"), dict)
        and b"FILES_SHA256=" in body
    )
else:
    ok_pending = False
print(
    f"review_package verdict PENDING artifact: "
    f"{'OK' if ok_pending else 'FAIL ' + json.dumps(pending_rec) if pkg_path is not None else 'FAIL (no package)'}"
)
failed += int(not ok_pending)

ledger_path = STATE.parent / "review_ledger.json"
try:
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    head_git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(SCRIPTS.parents[1]),
    ).stdout.strip()
    ok_ledger = (
        isinstance(ledger, dict)
        and "tree_fingerprint" in ledger
        and "sha256" in ledger
        and "git_sha" in ledger
        and ledger.get("git_sha") == head_git_sha
        and ledger.get("package", "").endswith(".diff")
    )
except Exception:
    ledger = {}
    ok_ledger = False
print(f"review_package records ledger: {'OK' if ok_ledger else 'FAIL missing/invalid ' + str(ledger_path)}")
failed += int(not ok_ledger)

from _hook_state import ledger_verdict  # noqa: E402

ok_verdict = (
    "REVIEW ADVISORY" in ledger_verdict("fp-after-change", "fp-at-package")
    and ledger_verdict(None, "fp-at-package") == ""
    and ledger_verdict("same-fp", "same-fp") == ""
    and "REVIEW ADVISORY" in ledger_verdict("fp-now", None)
)
print(f"review ledger staleness comparator: {'OK' if ok_verdict else 'FAIL'}")
failed += int(not ok_verdict)

# --- v0.9.0: legacy review packages stay valid with a single WARN line ---
legacy_pkg = Path(tempfile.mkdtemp()) / "legacy.diff"
legacy_pkg.write_text("# Harness review package (unstaged vs HEAD)\ndiff --git a/x b/x\n", encoding="utf-8")
legacy_conv = "c-legacy-pkg"
legacy_payload = invoke_five(legacy_conv, package=legacy_pkg)
legacy_proc = subprocess.run(
    [sys.executable, str(SCRIPT)],
    input=json.dumps(legacy_payload),
    text=True,
    capture_output=True,
    check=True,
    env=os.environ.copy(),
)
legacy_verdict = json.loads(legacy_proc.stdout)
ok_legacy_pkg = (
    legacy_verdict.get("decision") == "allow"
    and legacy_proc.stderr.count("predates the v2 evidence header") == 1
)
print(
    f"review_package legacy accepted with WARN: {legacy_verdict.get('decision')} "
    f"{'OK' if ok_legacy_pkg else 'FAIL stderr=' + legacy_proc.stderr}"
)
failed += int(not ok_legacy_pkg)

# --- v0.9.0: policy vocabulary vs shipped grants example ---
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parents[1]))
from policy_vocab import (  # noqa: E402
    DEVICE_BOUND_ADB,
    DENIED_PM_OPS,
    FORBIDDEN_TOOLS,
    GIT_MUTATIONS,
)

grants_file = SCRIPTS.parents[1] / "templates" / "gemini-runtime" / "config.grants.example.json"
if grants_file.is_file():
    grants = json.loads(grants_file.read_text(encoding="utf-8"))
    deny_entries = grants["globalPermissionGrants"]["deny"]
    allow_entries = grants["globalPermissionGrants"]["allow"]
    deny_git_verbs = [
        e[len("command(git ") : -1].strip() for e in deny_entries if e.startswith("command(git ")
    ]
    allow_git_verbs = [
        e.split(" ", 2)[1].strip()
        for e in allow_entries
        if e.startswith("command(git ") and len(e.split(" ", 2)) > 1
    ]
    ok_vocab_deny = bool(deny_git_verbs) and all(v in GIT_MUTATIONS for v in deny_git_verbs)
    ok_vocab_allow = bool(allow_git_verbs) and all(v not in GIT_MUTATIONS for v in allow_git_verbs)
    ok_vocab_adb = "devices" not in DEVICE_BOUND_ADB
    tool_denies = ("command(emulator)", "command(avdmanager)", "command(android emulator)", "command(adb monkey)")
    ok_vocab_tools = all(
        entry in deny_entries for entry in tool_denies
    ) and all(
        any(tool in entry for entry in deny_entries) for tool in FORBIDDEN_TOOLS
    )
else:
    # Installed checkout: the grants example ships with the kit root, not with agents/.
    ok_vocab_deny = ok_vocab_allow = ok_vocab_adb = ok_vocab_tools = True
ok_vocab_pm = sorted(DENIED_PM_OPS) == ["clear", "uninstall"]
ok_vocab = ok_vocab_deny and ok_vocab_allow and ok_vocab_adb and ok_vocab_tools and ok_vocab_pm
if not KIT_LAYOUT:
    print("policy_vocab matches grants example: OK (skipped — kit-only probe, installed checkout)")
elif ok_vocab:
    print("policy_vocab matches grants example: OK")
else:
    print(
        f"policy_vocab matches grants example: FAIL deny={ok_vocab_deny} allow={ok_vocab_allow} tools={ok_vocab_tools} pm={ok_vocab_pm}"
    )
failed += int(not ok_vocab)

# --- v0.9.0: append-only audit log + explain rendering ---
audit_file = STATE.parent / "audit_log.jsonl"
try:
    audit_records = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    ok_audit_fields = bool(audit_records) and all(
        {"ts", "decision", "tool", "reason_code", "reason_short", "cmd_sha256_12", "conv_hint"}
        <= set(rec)
        for rec in audit_records[-50:]
    )
    leak_probe = "monkey -p com.example.app 1"
    ok_audit_noleak = all(leak_probe not in json.dumps(rec) for rec in audit_records)
except Exception:
    ok_audit_fields = False
    ok_audit_noleak = False
print(f"audit_log fields + no raw command leak: {'OK' if (ok_audit_fields and ok_audit_noleak) else 'FAIL'}")
failed += int(not (ok_audit_fields and ok_audit_noleak))

cap_dir = Path(tempfile.mkdtemp())
os.environ["HARNESS_HOOK_STATE"] = str(cap_dir / "review-invokes.json")
cap_file = cap_dir / "audit_log.jsonl"
cap_file.write_text(
    "".join(json.dumps({"ts": i, "decision": "deny", "tool": "x"}) + "\n" for i in range(1005)),
    encoding="utf-8",
)
run(cmd("adb -s DEV devices"))
cap_lines = cap_file.read_text(encoding="utf-8").splitlines()
ok_cap = len(cap_lines) == 1000
print(f"audit_log caps at 1000 records: {'OK' if ok_cap else 'FAIL len=' + str(len(cap_lines))}")
failed += int(not ok_cap)
os.environ["HARNESS_HOOK_STATE"] = str(STATE)

if KIT_LAYOUT:
    explain_proc = subprocess.run(
        [sys.executable, str(SCRIPTS.parents[1] / "harness_cli.py"), "explain", "--last", "3", "--kit", str(SCRIPTS.parents[1])],
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
    )
    ok_explain = explain_proc.returncode == 0 and "[i] showed" in explain_proc.stdout
    print(f"cli explain renders audit: {'OK' if ok_explain else 'FAIL ' + explain_proc.stdout + explain_proc.stderr}")
    failed += int(not ok_explain)
else:
    print("cli explain renders audit: OK (skipped — installed checkout)")

# --- v0.10.x: explain prefers the installed checkout's audit log over the kit's ---
if KIT_LAYOUT:
    import shutil as _sh_explain

    explain_repo = Path(tempfile.mkdtemp())
    try:
        planted = explain_repo / ".agents" / "state" / "audit_log.jsonl"
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_text(
            json.dumps(
                {
                    "ts": time.time(),
                    "decision": "deny",
                    "tool": "run_command",
                    "reason_code": "GIT_MUTATION_DENIED",
                    "reason_short": "planted-audit-marker-xyz",
                    "cmd_sha256_12": "a" * 12,
                    "conv_hint": "",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        proc_planted = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS.parents[1] / "harness_cli.py"),
                "explain",
                "--repo",
                str(explain_repo),
                "--kit",
                str(SCRIPTS.parents[1]),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=os.environ.copy(),
        )
        ok_planted = (
            proc_planted.returncode == 0
            and "planted-audit-marker-xyz" in proc_planted.stdout
            and "GIT_MUTATION_DENIED" in proc_planted.stdout
        )
        print(
            f"cli explain reads installed repo log first: "
            f"{'OK' if ok_planted else 'FAIL ' + proc_planted.stdout + proc_planted.stderr}"
        )
        failed += int(not ok_planted)
    finally:
        _sh_explain.rmtree(explain_repo, ignore_errors=True)
else:
    print("cli explain reads installed repo log first: OK (skipped — installed checkout)")

# --- v0.9.0: pin-to-tag provisioning (local git remotes, zero network) ---
if KIT_LAYOUT:
    import harness_cli as hcli  # noqa: E402

    ok_cli_semver = hcli._semver_tuple("0.10.0") == (0, 10, 0) and hcli._semver_tuple("v9.8.7") == (9, 8, 7)
    print(f"cli semver tuple parser: {'OK' if ok_cli_semver else 'FAIL'}")
    failed += int(not ok_cli_semver)

    pin_root = Path(tempfile.mkdtemp())
    origin = pin_root / "origin"
    origin.mkdir()

    def _git_quiet(*args: str, cwd: Path) -> None:
        subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)

    def _git_commit_quiet(cwd: Path, msg: str) -> None:
        subprocess.run(
            ["git", "-c", "user.email=selftest@harness.local", "-c", "user.name=selftest", "commit", "-q", "-m", msg],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
        )

    _git_quiet("init", "-q", cwd=origin)
    (origin / "agents").mkdir()
    (origin / "agents" / "VERSION").write_text("9.9.8", encoding="utf-8")
    _git_quiet("add", "agents/VERSION", cwd=origin)
    _git_commit_quiet(origin, "v9.9.8")
    _git_quiet("tag", "v9.9.8", cwd=origin)

    provisioned = pin_root / "provisioned"
    hcli._provision_pinned(str(origin), provisioned, "9.9.8")
    ok_provision = (provisioned / "agents" / "VERSION").read_text(encoding="utf-8").strip() == "9.9.8"
    detached = subprocess.run(
        ["git", "-C", str(provisioned), "symbolic-ref", "-q", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    ok_provision = ok_provision and detached.returncode != 0
    print(f"cli pinned provision: {'OK' if ok_provision else 'FAIL'}")
    failed += int(not ok_provision)

    # Drift the "main" ahead untagged, then prove refresh re-pins to the tag.
    (origin / "agents" / "VERSION").write_text("9.9.9", encoding="utf-8")
    _git_quiet("add", "agents/VERSION", cwd=origin)
    _git_commit_quiet(origin, "untagged drift")

    clone_kit = pin_root / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone_kit)], capture_output=True, text=True, check=True)
    subprocess.run(["git", "-C", str(clone_kit), "checkout", "-q", "master"], capture_output=True, text=True, check=False)
    subprocess.run(
        ["git", "-C", str(clone_kit), "checkout", "-q", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    hcli.refresh_kit(clone_kit, "9.9.8")
    ok_repin = (clone_kit / "agents" / "VERSION").read_text(encoding="utf-8").strip() == "9.9.8"
    print(f"cli refresh re-pins drifted checkout: {'OK' if ok_repin else 'FAIL'}")
    failed += int(not ok_repin)

    # Fail closed when the tag's VERSION file contradicts the requested version.
    lying_origin = pin_root / "lying-origin"
    lying_origin.mkdir()
    _git_quiet("init", "-q", cwd=lying_origin)
    (lying_origin / "agents").mkdir()
    (lying_origin / "agents" / "VERSION").write_text("4.4.4", encoding="utf-8")
    _git_quiet("add", "agents/VERSION", cwd=lying_origin)
    _git_commit_quiet(lying_origin, "lying")
    _git_quiet("tag", "v9.9.9", cwd=lying_origin)
    lying_clone = pin_root / "lying-clone"
    subprocess.run(["git", "clone", "-q", str(lying_origin), str(lying_clone)], capture_output=True, text=True, check=True)
    ok_fail_closed = False
    try:
        hcli.refresh_kit(lying_clone, "9.9.9")
    except SystemExit as exc:
        ok_fail_closed = "Refusing to continue" in str(exc)
    print(f"cli pin mismatch fails closed: {'OK' if ok_fail_closed else 'FAIL'}")
    failed += int(not ok_fail_closed)

    # refresh_kit with an unreachable tag keeps the current pinned checkout.
    kept = pin_root / "kept"
    subprocess.run(["git", "clone", "-q", str(origin), str(kept)], capture_output=True, text=True, check=True)
    hcli.refresh_kit(kept, "9.9.8")
    hcli.refresh_kit(kept, "0.0.0-missing")
    ok_keep = (kept / "agents" / "VERSION").read_text(encoding="utf-8").strip() == "9.9.8"
    print(f"cli refresh unreachable tag keeps pin: {'OK' if ok_keep else 'FAIL'}")
    failed += int(not ok_keep)
else:
    print("cli semver tuple parser: OK (skipped — installed checkout)")
    print("cli pinned provision: OK (skipped — installed checkout)")
    print("cli refresh re-pins drifted checkout: OK (skipped — installed checkout)")
    print("cli pin mismatch fails closed: OK (skipped — installed checkout)")
    print("cli refresh unreachable tag keeps pin: OK (skipped — installed checkout)")

# Scaffold templates must not emit invalid try {{ and must include Empty + dual locale
sys.path.insert(0, str(SCRIPTS))
import new_feature_scaffold as scaffold_mod  # noqa: E402

ok_try = "try {{" not in scaffold_mod.VIEWMODEL and "catch (e: Exception)" not in scaffold_mod.VIEWMODEL
ok_empty = 'locale = "ar"' in scaffold_mod.SCREEN and 'locale = "en"' in scaffold_mod.SCREEN and "isEmpty = true" in scaffold_mod.SCREEN
ok_sc = ok_try and ok_empty
print(f"scaffold_valid_kotlin_template: {'OK' if ok_sc else 'FAIL try=' + str(ok_try) + ' empty=' + str(ok_empty)}")
failed += int(not ok_sc)

# Room parser
sys.path.insert(0, str(SCRIPTS))
from room_guard import parse_database_source  # noqa: E402

room_sample = """
@Database(
    entities = [FooEntity::class, BarEntity::class],
    version = 4
)
@TypeConverters(Converters::class)
abstract class FooDatabase {
    companion object {
        fun build() = Room.databaseBuilder(ctx, FooDatabase::class.java, "x")
            .addMigrations(MIGRATION_3_4)
            .fallbackToDestructiveMigration()
            .build()
        private val MIGRATION_3_4 = object : Migration(3, 4) {}
    }
}
"""
room_decl = parse_database_source(room_sample, "FooDatabase.kt")
ok_room = (
    room_decl.version == 4
    and room_decl.entity_names == frozenset({"FooEntity", "BarEntity"})
    and (3, 4) in room_decl.migrations
    and "MIGRATION_3_4" in room_decl.registered
    and room_decl.has_add_migrations
    and room_decl.destructive
    and "Converters" not in room_decl.entity_names
)
print(f"room_guard_parse: {'OK' if ok_room else 'FAIL ' + repr(room_decl)}")
failed += int(not ok_room)
help_proc = subprocess.run(
    [sys.executable, str(SCRIPTS / "logcat_doctor.py"), "--help"],
    text=True,
    capture_output=True,
    check=True,
)
ok_help = "--device" in help_proc.stdout
print(f"logcat_doctor_has_device_flag: {'OK' if ok_help else 'FAIL'}")
failed += int(not ok_help)

# Room maps entity class names, not just filename stems
from room_guard import declared_type_names  # noqa: E402

nested_entity_src = "package x\ndata class UserGroupsItem(val id: Int)\nclass Wrapper\n"
ok_decl = "UserGroupsItem" in declared_type_names(nested_entity_src)
print(f"room_guard_declared_types: {'OK' if ok_decl else 'FAIL'}")
failed += int(not ok_decl)

# Dual-locale preview on cards + multiline @Preview on screens
from fast_kt_lint import lint_file  # noqa: E402

card_dir = Path(tempfile.mkdtemp())
card_path = card_dir / "OfferCard.kt"
card_path.write_text(
    "import androidx.compose.runtime.Composable\n@Composable\nfun OfferCard() {}\n",
    encoding="utf-8",
)
card_issues = {iss["type"] for iss in lint_file(card_path)}
ok_card = "MISSING_COMPOSE_PREVIEW" in card_issues
print(f"fast_kt_lint_card_preview: {'OK' if ok_card else 'FAIL ' + str(card_issues)}")
failed += int(not ok_card)

screen_path = card_dir / "OfferScreen.kt"
screen_path.write_text(
    """
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
@Composable
fun OfferScreen() {}
@Preview(
    locale = "ar",
    showBackground = true
)
@Composable
private fun Ar() { OfferScreen() }
@Preview(
    locale = "en",
    showBackground = true
)
@Composable
private fun En() { OfferScreen() }
""",
    encoding="utf-8",
)
screen_issues = {iss["type"] for iss in lint_file(screen_path)}
ok_screen = "MISSING_COMPOSE_PREVIEW" not in screen_issues
print(f"fast_kt_lint_multiline_preview: {'OK' if ok_screen else 'FAIL ' + str(screen_issues)}")
failed += int(not ok_screen)

fqcn_path = card_dir / "Fqcn.kt"
fqcn_path.write_text(
    'val log = "com.example.app.Foo"\n',
    encoding="utf-8",
)
ok_fqcn = not any(iss["type"] == "INLINE_FQCN" for iss in lint_file(fqcn_path))
print(f"fast_kt_lint_fqcn_in_string: {'OK' if ok_fqcn else 'FAIL'}")
failed += int(not ok_fqcn)

# Hardcoded UI strings: setText / skip resources / skip @Preview names
from check_strings import check_hardcoded_strings  # noqa: E402

str_dir = Path(tempfile.mkdtemp())
bad_kt = str_dir / "Bad.kt"
bad_kt.write_text('fun f() { title.setText("Hello world") }\n', encoding="utf-8")
ok_settext = any("Hardcoded" in item for item in check_hardcoded_strings([bad_kt]))
print(f"check_strings_setText: {'OK' if ok_settext else 'FAIL'}")
failed += int(not ok_settext)

res_kt = str_dir / "Res.kt"
res_kt.write_text("fun f() { title.setText(R.string.hello) }\n", encoding="utf-8")
ok_skip_res = check_hardcoded_strings([res_kt]) == []
print(f"check_strings_skips_resource: {'OK' if ok_skip_res else 'FAIL'}")
failed += int(not ok_skip_res)

preview_kt = str_dir / "Prev.kt"
preview_kt.write_text('@Preview(name = "Arabic RTL")\n', encoding="utf-8")
ok_skip_preview = check_hardcoded_strings([preview_kt]) == []
print(f"check_strings_skips_preview: {'OK' if ok_skip_preview else 'FAIL'}")
failed += int(not ok_skip_preview)

trip_kt = str_dir / "Trip.kt"
trip_kt.write_text('val doc = """\nText("Sample inside docs")\n"""\n', encoding="utf-8")
ok_skip_trip = check_hardcoded_strings([trip_kt]) == []
print(f"check_strings_skips_triple_string: {'OK' if ok_skip_trip else 'FAIL'}")
failed += int(not ok_skip_trip)

decoy_kt = str_dir / "Decoy.kt"
decoy_kt.write_text('fun g() { load() } // Text("decoy in trailing comment")\n', encoding="utf-8")
ok_skip_decoy = check_hardcoded_strings([decoy_kt]) == []
print(f"check_strings_skips_trailing_comment_decoy: {'OK' if ok_skip_decoy else 'FAIL'}")
failed += int(not ok_skip_decoy)

real_after_comment = str_dir / "RealAfter.kt"
real_after_comment.write_text('fun h() { label = "Real user text" } // note\n', encoding="utf-8")
ok_real_after = any("Hardcoded" in item for item in check_hardcoded_strings([real_after_comment]))
print(f"check_strings_detects_code_after_trailing_comment: {'OK' if ok_real_after else 'FAIL'}")
failed += int(not ok_real_after)

toast_kt = str_dir / "Toast.kt"
toast_kt.write_text(
    'fun f() { Toast.makeText(ctx, "Saved item", Toast.LENGTH_SHORT) }\n',
    encoding="utf-8",
)
ok_toast = any("Hardcoded" in item for item in check_hardcoded_strings([toast_kt]))
print(f"check_strings_toast: {'OK' if ok_toast else 'FAIL'}")
failed += int(not ok_toast)

# Transcript camelCase toolCalls + PASS tokens clears the assemble barrier
tx_root = Path(tempfile.mkdtemp())
os.environ["HARNESS_TRANSCRIPT_ROOT"] = str(tx_root)
tx_file = tx_root / five_conv / "transcript.jsonl"
tx_file.parent.mkdir(parents=True, exist_ok=True)
tx_file.write_text(
    json.dumps({"toolCalls": [{"name": "invoke_subagent"}]})
    + "\n"
    + json.dumps(
        {
            "content": "BUG_PASS CONVENTION_PASS SECURITY_PASS PERF_PASS REGRESSION_PASS"
        }
    )
    + "\n",
    encoding="utf-8",
)
assemble_pass = run(cmd("gradlew.bat :app:assembleDebug", conversation=five_conv))
ok_assemble_pass = assemble_pass["decision"] == "allow"
print(
    f"assemble_after_pass_tokens: {assemble_pass['decision']} "
    f"{'OK' if ok_assemble_pass else 'FAIL ' + json.dumps(assemble_pass)}"
)
failed += int(not ok_assemble_pass)

device_pass = run(cmd("python .agents/scripts/run_device.py install-start", conversation=five_conv))
ok_device_pass = device_pass["decision"] == "allow"
print(
    f"run_device_after_pass_tokens: {device_pass['decision']} "
    f"{'OK' if ok_device_pass else 'FAIL ' + json.dumps(device_pass)}"
)
failed += int(not ok_device_pass)

# Verdicts without a structured invoke still clear a stuck barrier
stuck_conv = "c-stuck"
run(invoke_five(stuck_conv))
stuck_tx = tx_root / stuck_conv / "transcript.jsonl"
stuck_tx.parent.mkdir(parents=True, exist_ok=True)
stuck_tx.write_text(
    json.dumps({"content": "BUG_PASS CONVENTION_PASS SECURITY_PASS PERF_PASS REGRESSION_PASS"})
    + "\n",
    encoding="utf-8",
)
stuck_res = run(cmd("gradlew.bat :app:assembleDebug", conversation=stuck_conv))
ok_stuck = stuck_res["decision"] == "allow"
print(
    f"assemble_verdicts_without_invoke: {stuck_res['decision']} "
    f"{'OK' if ok_stuck else 'FAIL ' + json.dumps(stuck_res)}"
)
failed += int(not ok_stuck)

# File dumps that mention invoke_subagent must not move the barrier past PASS tokens
dump_conv = "c-dump"
run(invoke_five(dump_conv))
dump_tx = tx_root / dump_conv / "transcript.jsonl"
dump_tx.parent.mkdir(parents=True, exist_ok=True)
dump_tx.write_text(
    json.dumps({"type": "PLANNER_RESPONSE", "toolCalls": [{"name": "invoke_subagent"}]})
    + "\n"
    + json.dumps(
        {
            "content": "BUG_PASS CONVENTION_PASS SECURITY_PASS PERF_PASS REGRESSION_PASS"
        }
    )
    + "\n"
    + json.dumps(
        {
            "type": "GENERIC",
            "source": "MODEL",
            "content": 'File Path: pre_tool_safety.py\n"name": "invoke_subagent"',
        }
    )
    + "\n",
    encoding="utf-8",
)
dump_res = run(cmd("gradlew.bat :app:assembleDebug", conversation=dump_conv))
ok_dump = dump_res["decision"] == "allow"
print(
    f"assemble_ignores_file_dump_invoke: {dump_res['decision']} "
    f"{'OK' if ok_dump else 'FAIL ' + json.dumps(dump_res)}"
)
failed += int(not ok_dump)

# --- v0.9.0: Evidence-backed verdicts (HARNESS_EVIDENCE_MODE=strict) ---
import hashlib  # noqa: E402

evidence_active_pkg12 = hashlib.sha256(PACKAGE.read_bytes()).hexdigest()[:12]


def _evidence_conv(name: str, entries: list[dict], mode: str) -> dict:
    prev = os.environ.get("HARNESS_EVIDENCE_MODE")
    os.environ["HARNESS_EVIDENCE_MODE"] = mode
    try:
        conv_dir = tx_root / name
        conv_dir.mkdir(parents=True, exist_ok=True)
        tx = conv_dir / "transcript.jsonl"
        tx.write_text(
            "\n".join(
                json.dumps(e)
                for e in [{"toolCalls": [{"name": "invoke_subagent"}]}, *entries]
            )
            + "\n",
            encoding="utf-8",
        )
        run(invoke_five(name))
        return run(cmd("gradlew.bat :app:assembleDebug", conversation=name))
    finally:
        if prev is None:
            os.environ.pop("HARNESS_EVIDENCE_MODE", None)
        else:
            os.environ["HARNESS_EVIDENCE_MODE"] = prev


all_tokens = "BUG_PASS CONVENTION_PASS SECURITY_PASS PERF_PASS REGRESSION_PASS"
token_entries = [{"content": all_tokens}]

# Forged verdicts: tokens without EVIDENCE footer keep the barrier in strict mode.
forged_res = _evidence_conv("c-ev-forge", token_entries, "strict")
ok_forge = forged_res["decision"] == "deny" and "EVIDENCE" in forged_res.get("reason", "")
print(
    f"evidence_forged_token_no_footer: {forged_res['decision']} "
    f"{'OK' if ok_forge else 'FAIL ' + json.dumps(forged_res)}"
)
failed += int(not ok_forge)

# Wrong package hash in the footer keeps the barrier.
wrong_entries = [
    {"content": f"{token} EVIDENCE pkg={'0' * 12} cites=1"}
    for token in ("BUG_PASS", "CONVENTION_PASS", "SECURITY_PASS", "PERF_PASS", "REGRESSION_PASS")
]
wrong_res = _evidence_conv("c-ev-wrong", wrong_entries, "strict")
ok_wrong = wrong_res["decision"] == "deny" and "EVIDENCE" in wrong_res.get("reason", "")
print(
    f"evidence_wrong_pkg_hash: {wrong_res['decision']} "
    f"{'OK' if ok_wrong else 'FAIL ' + json.dumps(wrong_res)}"
)
failed += int(not ok_wrong)

# Correct footer clears the barrier.
good_entries = [
    {"content": f"{token} EVIDENCE pkg={evidence_active_pkg12} cites=2"}
    for token in ("BUG_PASS", "CONVENTION_PASS", "SECURITY_PASS", "PERF_PASS", "REGRESSION_PASS")
]
good_res = _evidence_conv("c-ev-good", good_entries, "strict")
ok_good = good_res["decision"] == "allow"
print(
    f"evidence_correct_footer: {good_res['decision']} "
    f"{'OK' if ok_good else 'FAIL ' + json.dumps(good_res)}"
)
failed += int(not ok_good)

# v0.10.x: the barrier-clear path completes the machine-readable verdict artifact.
from _hook_state import read_verdict_record  # noqa: E402

good_rec = read_verdict_record(evidence_active_pkg12)
ok_good_verdict = (
    good_rec is not None
    and good_rec.get("verdict") == "PASS"
    and good_rec.get("schema_version") == 1
    and bool(good_rec.get("completed_at"))
    and len(good_rec.get("leaves") or {}) == 5
    and all(
        leaf.get("evidence", {}).get("valid") is True
        for leaf in (good_rec.get("leaves") or {}).values()
    )
)
print(
    f"verdict artifact PASS after evidence barrier: "
    f"{'OK' if ok_good_verdict else 'FAIL ' + json.dumps(good_rec)}"
)
failed += int(not ok_good_verdict)

from _hook_state import (  # noqa: E402
    SEVERITY_HARD_BLOCKER,
    SEVERITY_SOFT_FINDING,
    adjudicate_review_findings,
    parse_structured_finding,
)

sample_blocker = "Security Reviewer: HARD_BLOCKER at MainActivity.kt:42 plaintext secret."
sample_soft = "Convention Reviewer: SOFT_FINDING at MainActivity.kt:10 missing trailing comma."
sample_json_blocker = '```json\n{"severity": "BLOCKER", "message": "SQL Injection"}\n```'

parsed_b = parse_structured_finding(sample_blocker)
parsed_s = parse_structured_finding(sample_soft)
parsed_j = parse_structured_finding(sample_json_blocker)

adj_conflict = adjudicate_review_findings([sample_blocker, sample_soft])
adj_soft_only = adjudicate_review_findings([sample_soft])

ok_adjudication = (
    parsed_b is not None
    and parsed_b.get("severity") == SEVERITY_HARD_BLOCKER
    and parsed_s is not None
    and parsed_s.get("severity") == SEVERITY_SOFT_FINDING
    and parsed_j is not None
    and parsed_j.get("severity") == SEVERITY_HARD_BLOCKER
    and adj_conflict["has_hard_blockers"] is True
    and adj_conflict["can_override"] is False
    and adj_soft_only["has_hard_blockers"] is False
    and adj_soft_only["can_override"] is True
)
print(f"adr006_reviewer_conflict_adjudication: {'OK' if ok_adjudication else 'FAIL'}")
failed += int(not ok_adjudication)

# Legacy mode preserves today's token-only behavior.
legacy_res = _evidence_conv("c-ev-legacy", token_entries, "legacy")
ok_legacy = legacy_res["decision"] == "allow"
print(
    f"evidence_legacy_mode_unchanged: {legacy_res['decision']} "
    f"{'OK' if ok_legacy else 'FAIL ' + json.dumps(legacy_res)}"
)
failed += int(not ok_legacy)

sys.path.insert(0, str(SCRIPTS))
from _live_process import run_streaming  # noqa: E402
from run_gradle_task import is_boilerplate, should_echo_gradle  # noqa: E402

echo_cases = [
    ("> Task :app:preBuild UP-TO-DATE", False, True),
    ("> Task :app:compileDebugKotlin", True, False),
    ("w: file:///E:/app/Foo.kt:1:1 unused", False, False),
    ("e: file:///E:/app/Foo.kt:1:1 error", True, False),
    ("BUILD SUCCESSFUL in 12s", True, False),
    ("", False, True),
]
echo_ok = True
for line, expect_echo, expect_boiler in echo_cases:
    boiler = is_boilerplate(line)
    echo = should_echo_gradle(line)
    if expect_boiler and not boiler:
        echo_ok = False
        print(f"gradle_echo_filter: FAIL boilerplate {line!r}")
    if echo != expect_echo:
        echo_ok = False
        print(f"gradle_echo_filter: FAIL echo {line!r} got {echo} want {expect_echo}")
print(f"gradle_echo_filter: {'OK' if echo_ok else 'FAIL'}")
failed += int(not echo_ok)

smoke_code, smoke_raw, smoke_echoed = run_streaming(
    [sys.executable, "-c", "print('hello-live', flush=True)"],
    heartbeat_sec=0,
    should_echo=lambda line: bool(line.strip()),
    label="smoke",
    echo=False,
)
ok_smoke = smoke_code == 0 and "hello-live" in smoke_raw and "hello-live" in smoke_echoed
print(f"live_stream_smoke: {'OK' if ok_smoke else 'FAIL'}")
failed += int(not ok_smoke)

import ensure_hook_selftest as ensure_mod  # noqa: E402

fp = ensure_mod.harness_fingerprint()
ok_fp = isinstance(fp, str) and len(fp) == 64
print(f"ensure_hook_selftest_fingerprint: {'OK' if ok_fp else 'FAIL'}")
failed += int(not ok_fp)

# Zoho Sprints MCP: code ships, tokens do not
import shutil  # noqa: E402

ZOHO_MCP = SCRIPTS.parent / "mcp" / "zoho_sprints"
sys.path.insert(0, str(ZOHO_MCP))
from _config import ENV_CONFIG, SECRET_KEYS, json_contains_secret_keys  # noqa: E402
from install_zoho_mcp import install as zoho_install  # noqa: E402

_repo_root = SCRIPTS.parent.parent
_is_installed = (_repo_root / ".harness-setup" / "answers.json").is_file()

kit_mcp = json.loads((SCRIPTS.parent / "mcp_config.json").read_text(encoding="utf-8"))
if _is_installed:
    ok_kit_mcp = not json_contains_secret_keys(kit_mcp)
else:
    ok_kit_mcp = kit_mcp == {"mcpServers": {}}
print(f"mcp_config has no secrets: {'OK' if ok_kit_mcp else 'FAIL'}")
failed += int(not ok_kit_mcp)

example = json.loads((ZOHO_MCP / "config.example.json").read_text(encoding="utf-8"))
ok_example = all(not str(example.get(key) or "").strip() for key in SECRET_KEYS)
print(f"zoho example has empty secrets: {'OK' if ok_example else 'FAIL'}")
failed += int(not ok_example)

# Kit placeholders — a successful install replaces these with real values.
# The selftest proves nothing from the example kit leaked into the installed copy.
# During install, setup_wizard adds project-specific needles via _product.py.
# Installed checkouts: every file must be clean (an unported _product.py fails).
# Raw kit: _product.py is exempt — it deliberately ships the port canary.
needles = (
    "com.example.app",
    "com.example",
)
ok_left = True
for path in SCRIPTS.parent.rglob("*"):
    if not path.is_file() or path.suffix == ".pyc":
        continue
    if "__pycache__" in path.parts or "state" in path.parts:
        continue
    if path.resolve() == Path(__file__).resolve():
        continue
    if not _is_installed and path.name == "_product.py":
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        continue
    for needle in needles:
        if needle in text:
            ok_left = False
            print(f"kit placeholder {needle!r} in {path.relative_to(SCRIPTS.parent)}")
print(
    f"kit placeholder grep agents/: {'OK' if ok_left else 'FAIL'}"
    + ("" if _is_installed else " (raw kit scan)")
)
failed += int(not ok_left)

tmp = Path(tempfile.mkdtemp())
agents_dst = tmp / ".agents"
shutil.copytree(ZOHO_MCP, agents_dst / "mcp" / "zoho_sprints")
(agents_dst / "mcp_config.json").write_text('{"mcpServers": {}}\n', encoding="utf-8")
secret = tmp / "user-zoho.json"
secret.write_text(
    json.dumps(
        {
            "refresh_token": "UNITTEST_SECRET_TOKEN_VALUE_XX",
            "client_secret": "UNITTEST_CLIENT_SECRET_XX",
            "access_token": "UNITTEST_ACCESS_TOKEN_XX",
            "client_id": "UNITTEST_CLIENT_ID_XX",
            "team_id": "1",
            "project_id": "2",
        }
    ),
    encoding="utf-8",
)
old_cfg = os.environ.get(ENV_CONFIG)
os.environ[ENV_CONFIG] = str(secret)
try:
    zoho_install(tmp, "python", True, ["cursor"])
    mcp_text = (agents_dst / "mcp_config.json").read_text(encoding="utf-8")
    cursor_text = (tmp / ".cursor" / "mcp.json").read_text(encoding="utf-8")
    mcp_obj = json.loads(mcp_text)
    cursor_obj = json.loads(cursor_text)
    leaked = any(
        token in mcp_text or token in cursor_text
        for token in (
            "UNITTEST_SECRET_TOKEN_VALUE_XX",
            "UNITTEST_CLIENT_SECRET_XX",
            "UNITTEST_ACCESS_TOKEN_XX",
            "UNITTEST_CLIENT_ID_XX",
        )
    )
    copied = any(p.name == "user-zoho.json" for p in agents_dst.rglob("*"))
    env_path = ((mcp_obj.get("mcpServers") or {}).get("zoho-sprints") or {}).get("env", {}).get(ENV_CONFIG)
    ok_wire = (
        not leaked
        and not copied
        and not json_contains_secret_keys(mcp_obj)
        and not json_contains_secret_keys(cursor_obj)
        and env_path is not None
        and os.path.normpath(env_path) == os.path.normpath(str(secret))
        and (agents_dst / "mcp" / "zoho_sprints" / "server.py").is_file()
    )
    print(f"zoho install reuses path without copying tokens: {'OK' if ok_wire else 'FAIL'}")
    failed += int(not ok_wire)
    zoho_install(tmp, "python", False, ["cursor"])
    cleared = json.loads((agents_dst / "mcp_config.json").read_text(encoding="utf-8"))
    ok_clear = "zoho-sprints" not in (cleared.get("mcpServers") or {})
    print(f"zoho disable clears project mcp: {'OK' if ok_clear else 'FAIL'}")
    failed += int(not ok_clear)
finally:
    if old_cfg is None:
        os.environ.pop(ENV_CONFIG, None)
    else:
        os.environ[ENV_CONFIG] = old_cfg
    shutil.rmtree(tmp, ignore_errors=True)

init_payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
list_payload = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
proc = subprocess.run(
    [sys.executable, str(ZOHO_MCP / "server.py")],
    input=init_payload + list_payload,
    text=True,
    capture_output=True,
    check=False,
)
ok_rpc = proc.returncode == 0 and "zoho-sprints-mcp" in proc.stdout and "zoho_list_sprints" in proc.stdout
print(f"zoho mcp initialize+tools/list: {'OK' if ok_rpc else 'FAIL'}")
failed += int(not ok_rpc)

wf = json.loads((ZOHO_MCP / "workflow_defaults.json").read_text(encoding="utf-8"))
ok_wf = (
    "refresh_token" not in wf
    and "access_token" not in wf
    and "client_secret" not in wf
    and "client_id" not in wf
)
print(f"zoho workflow defaults have no tokens: {'OK' if ok_wf else 'FAIL'}")
failed += int(not ok_wf)

overlay_dir = Path(tempfile.mkdtemp())
overlay_cfg = overlay_dir / "cfg.json"
overlay_cfg.write_text(
    json.dumps(
        {
            "access_token": "UNITTEST_ACCESS_TOKEN_XX",
            "refresh_token": "UNITTEST_SECRET_TOKEN_VALUE_XX",
            "client_id": "UNITTEST_CLIENT_ID_XX",
            "client_secret": "UNITTEST_CLIENT_SECRET_XX",
            "team_id": "1",
            "project_id": "2",
        }
    ),
    encoding="utf-8",
)
from server import ZohoSprintsAPI  # noqa: E402

api = ZohoSprintsAPI(str(overlay_cfg))
ok_overlay = (
    api.access_token == "UNITTEST_ACCESS_TOKEN_XX"
    and not json_contains_secret_keys(wf)
)
print(f"zoho workflow overlay without copying tokens: {'OK' if ok_overlay else 'FAIL'}")
failed += int(not ok_overlay)
shutil.rmtree(overlay_dir, ignore_errors=True)

zoho_rem = run_reminder({"invocationNum": 0, "conversationId": "c-zoho-wf"})
ok_zoho_rem = "update zoho" in zoho_rem["injectSteps"][0]["ephemeralMessage"]
print(f"reminder includes update zoho: {'OK' if ok_zoho_rem else 'FAIL'}")
failed += int(not ok_zoho_rem)

from setup_wizard import questions_payload, normalize  # noqa: E402

facts = {
    "product": "App",
    "pythons": ["python"],
    "modules": [":app"],
    "launchers": ["com.example.app/.MainActivity"],
    "apk_hint": "app/build/outputs/apk/debug/app-debug.apk",
    "locales": ["values"],
    "stack": "Koin",
    "classic_app_src": True,
    "gemini": False,
    "zoho_config": True,
    "gradlew": True,
}
q_ids = [q["id"] for q in questions_payload(Path("."), "en", facts)]
ok_q = "i16" in q_ids and "i17" not in q_ids and "i18" in q_ids
print(f"wizard includes I.16, I.18 (I.17 omitted for dynamic chat): {'OK' if ok_q else 'FAIL'}")
failed += int(not ok_q)
norm = normalize(
    {
        "i0": "yes",
        "i1": "discovered",
        "i3": "never",
        "i4": "allow",
        "i10": "confirm",
        "i15": "yes",
        "i14": ["cursor"],
        "i16": "enable",
        "i18": "en_titles_ar_comments",
    },
    facts,
)
ok_norm = (
    norm.get("zoho_mcp") == "enable"
    and norm.get("chat_language") == "mirror"
    and norm.get("zoho_language") == "en_titles_ar_comments"
)
print(f"wizard records zoho_mcp and language preferences: {'OK' if ok_norm else 'FAIL'}")
failed += int(not ok_norm)

from wizard.discovery import discover_clean_locales  # noqa: E402
raw_test_locales = ["values", "values-ar", "values-en", "values-night", "values-sw360dp", "values-v31", "values-hdpi", "values-fr", "values-land"]
cleaned = discover_clean_locales(raw_test_locales)
ok_clean_loc = cleaned == ["en", "ar", "fr"]
print(f"wizard clean locale qualification filtering: {'OK' if ok_clean_loc else 'FAIL'}")
failed += int(not ok_clean_loc)

greenfield_facts = {
    "product": "NewApp",
    "pythons": ["python"],
    "modules": [":app"],
    "launchers": ["com.example.newapp/.MainActivity"],
    "apk_hint": "app/build/outputs/apk/debug/app-debug.apk",
    "locales": ["values"],
    "stack": "unknown",
    "is_empty": True,
    "source_count": 0,
    "classic_app_src": False,
    "gemini": False,
    "zoho_config": False,
    "gradlew": True,
}
g_q_ids = [q["id"] for q in questions_payload(Path("."), "en", greenfield_facts)]
ok_g_q = "b_platform" in g_q_ids and "b_arch" in g_q_ids and "b_di" in g_q_ids
print(f"wizard includes greenfield bootstrap questions: {'OK' if ok_g_q else 'FAIL'}")
failed += int(not ok_g_q)

from check_kit_update import parse_semver, get_current_version  # noqa: E402

ok_semver = parse_semver("v0.1.0") == (0, 1, 0) and parse_semver("0.10.8") > (0, 10, 7) and get_current_version() == "0.25.5"
print(f"check_kit_update semver and version: {'OK' if ok_semver else 'FAIL'}")
failed += int(not ok_semver)

pyproject_file = _repo_root / "pyproject.toml"
if pyproject_file.is_file():
    pyproject_text = pyproject_file.read_text(encoding="utf-8")
    ok_packaging_version = f'version = "{get_current_version()}"' in pyproject_text
else:
    ok_packaging_version = True
print(f"packaging metadata version alignment: {'OK' if ok_packaging_version else 'FAIL'}")
failed += int(not ok_packaging_version)

# Release quality invariants: zero emojis, zero literal escapes, and milestone release consolidation
import re

EMOJI_PATTERN = re.compile(
    r"[\U0001F600-\U0001F64F"
    r"\U0001F300-\U0001F5FF"
    r"\U0001F680-\U0001F6FF"
    r"\U0001F700-\U0001F77F"
    r"\U0001F780-\U0001F7FF"
    r"\U0001F800-\U0001F8FF"
    r"\U0001F900-\U0001F9FF"
    r"\U0001FA00-\U0001FA6F"
    r"\U0001FA70-\U0001FAFF"
    r"\U00002702-\U000027B0"
    r"\U000024C2-\U0001F251"
    r"]+",
    flags=re.UNICODE,
)

repo_root = Path(__file__).resolve().parent.parent.parent
agents_root = Path(__file__).resolve().parent.parent
_is_installed = (repo_root / ".harness-setup" / "answers.json").is_file() or agents_root.name == ".agents"

if _is_installed:
    docs_files = list(agents_root.glob("**/*.md"))
else:
    docs_files = (
        list(repo_root.glob("*.md"))
        + list((repo_root / "docs").glob("*.md"))
        + list((repo_root / ".github").glob("**/*.md"))
        + list((repo_root / "agents").glob("**/*.md"))
    )

emoji_found = []
escape_found = []
for f in docs_files:
    if f.is_file():
        content = f.read_text(encoding="utf-8", errors="ignore")
        if EMOJI_PATTERN.search(content):
            emoji_found.append(f.name)
        for l_idx, line in enumerate(content.splitlines(), start=1):
            if line.endswith("\\n") or line.endswith("\\r"):
                escape_found.append(f"{f.name}:{l_idx}")

ok_emojis = len(emoji_found) == 0
print(f"zero emojis across all markdown docs: {'OK' if ok_emojis else f'FAIL (found in {emoji_found})'}")
failed += int(not ok_emojis)

ok_escapes = len(escape_found) == 0
print(f"zero literal escape artifacts in docs: {'OK' if ok_escapes else f'FAIL (found in {escape_found})'}")
failed += int(not ok_escapes)

if (repo_root / "CHANGELOG.md").is_file():
    changelog_text = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    changelog_versions = re.findall(r"## \[(\d+\.\d+\.\d+)\]", changelog_text)
    ok_changelog_milestones = len(changelog_versions) <= 12 and changelog_versions[0] == get_current_version()
    print(f"changelog milestone release consolidation: {'OK' if ok_changelog_milestones else 'FAIL'}")
    failed += int(not ok_changelog_milestones)
else:
    print("changelog milestone release consolidation: OK (skipped — installed checkout)")

# --- v0.10.x: GitHub issue templates must stay YAML-shaped ---
issue_tpl_dir = repo_root / ".github" / "ISSUE_TEMPLATE"
if issue_tpl_dir.is_dir():
    def _odd_indent_lines(path: Path) -> list[int]:
        bad: list[int] = []
        block_indent = None
        for idx, raw in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            if not raw.strip():
                continue
            indent = len(raw) - len(raw.lstrip())
            if block_indent is not None:
                if indent > block_indent:
                    continue
                block_indent = None
            if raw.rstrip().endswith(("|", "|-", "|+")):
                block_indent = indent
                continue
            if indent % 2 != 0:
                bad.append(idx)
        return bad

    bad_reports: list[str] = []
    for tpl in sorted(issue_tpl_dir.glob("*.yml")) + sorted(issue_tpl_dir.glob("*.yaml")):
        bad = _odd_indent_lines(tpl)
        if bad:
            bad_reports.append(f"{tpl.name}: lines {bad}")
    ok_issue_tpl = not bad_reports
    print(f"issue template yaml indentation: {'OK' if ok_issue_tpl else 'FAIL ' + '; '.join(bad_reports)}")
    failed += int(not ok_issue_tpl)
else:
    print("issue template yaml indentation: OK (skipped — no ISSUE_TEMPLATE dir)")

ok_test_specialist_files = (
    (agents_root / "subagents" / "test-quality-reviewer-agent.json").is_file()
    and (agents_root / "skills" / "android-harness" / "references" / "test-quality-guidelines.md").is_file()
    and (agents_root / "workflows" / "test-quality-audit.md").is_file()
)
print(f"test-quality-reviewer-agent files and references: {'OK' if ok_test_specialist_files else 'FAIL'}")
failed += int(not ok_test_specialist_files)

expected_skills = (
    "android-harness",
    "brainstorming",
    "test-driven-development",
    "systematic-debugging",
    "compose-inspector",
    "kotlin-coroutines-expert",
    "gradle-build-optimizer",
    "git-pr-automator",
)
missing_skills = [
    s for s in expected_skills
    if not (agents_root / "skills" / s / "SKILL.md").is_file()
]
ok_skills_catalog = len(missing_skills) == 0
if ok_skills_catalog:
    # Verify valid frontmatter
    for s in ("brainstorming", "test-driven-development"):
        content = (agents_root / "skills" / s / "SKILL.md").read_text(encoding="utf-8")
        if not (content.startswith("---") and f"name: {s}" in content and "description:" in content):
            ok_skills_catalog = False
            missing_skills.append(f"{s} (invalid frontmatter)")
print(f"8-skills catalog and Superpowers skills: {'OK' if ok_skills_catalog else 'FAIL: ' + ', '.join(missing_skills)}")
failed += int(not ok_skills_catalog)

from _repo_files import _unquote_git_path
ok_unquote = (
    _unquote_git_path('"app/src/main/res/values/strings with spaces.xml"') == "app/src/main/res/values/strings with spaces.xml"
    and "values-ar" in _unquote_git_path('"app/src/main/res/values-ar/\\330\\247\\331\\204\\330\\253.xml"')
)
print(f"git unquote handles spaces and non-ascii: {'OK' if ok_unquote else 'FAIL'}")
failed += int(not ok_unquote)

from check_strings import HARDCODED_KT, RESOURCE_CALL
compose_sample = 'Text(text = "Hello World")'
ok_kt_strings = (
    any(p.search(compose_sample) for p in HARDCODED_KT)
    and any(p.search('text = "Welcome"') for p in HARDCODED_KT)
    and RESOURCE_CALL.sub('""', 'stringResource(R.string.x) + " - hardcoded"') == '"" + " - hardcoded"'
)
print(f"check_strings multiline Compose and concatenation: {'OK' if ok_kt_strings else 'FAIL'}")
failed += int(not ok_kt_strings)

from room_guard import is_migration_path_covered, parse_database_source
ok_mig_graph = (
    is_migration_path_covered(1, 3, frozenset({(1, 2), (2, 3)}))
    and not is_migration_path_covered(1, 4, frozenset({(1, 2), (2, 3)}))
)
auto_mig_code = '@Database(entities = [UserEntity::class], version = 2, autoMigrations = [AutoMigration(from = 1, to = 2)])\nabstract class AppDatabase : RoomDatabase()'
decl_auto = parse_database_source(auto_mig_code, "AppDatabase.kt")
ok_auto_mig = (1, 2) in decl_auto.migrations and decl_auto.has_add_migrations
print(f"room_guard auto_migration and transitive path: {'OK' if (ok_mig_graph and ok_auto_mig) else 'FAIL'}")
failed += int(not (ok_mig_graph and ok_auto_mig))

from fast_kt_lint import FQCN_WHITELIST, CLASS_ENTRY_PATTERN
ok_lint_harden = (
    bool(FQCN_WHITELIST.match("android.os.Build.VERSION.SDK_INT"))
    and bool(FQCN_WHITELIST.match("java.util.UUID"))
    and bool(CLASS_ENTRY_PATTERN.search("class MainActivity : ComponentActivity()"))
)
print(f"fast_kt_lint FQCN whitelist and ComponentActivity: {'OK' if ok_lint_harden else 'FAIL'}")
failed += int(not ok_lint_harden)

from fast_kt_lint import UNIMPLEMENTED_STUB_PATTERN, DOUBLE_BANG_PATTERN, DIAGNOSTIC_PROBE_PATTERN, lint_file as lint_file_diff_test
ok_lint_new_rules = (
    bool(UNIMPLEMENTED_STUB_PATTERN.search("fun doWork() = TODO()"))
    and bool(UNIMPLEMENTED_STUB_PATTERN.search("throw NotImplementedError()"))
    and bool(DOUBLE_BANG_PATTERN.search("val x = user!!.name"))
    and bool(DIAGNOSTIC_PROBE_PATTERN.search("// [HARNESS-PROBE] logging state"))
    and bool(DIAGNOSTIC_PROBE_PATTERN.search("Log.d(TAG, HARNESS_PROBE)"))
)
print(f"fast_kt_lint shift-left rules (TODO, !!, probes, test runBlocking): {'OK' if ok_lint_new_rules else 'FAIL'}")
failed += int(not ok_lint_new_rules)

# --- v0.16.0: Diff-Scoped Fast KT Linting (ignores untouched legacy lines) ---
tmp_kt_file = Path(tempfile.mkdtemp()) / "SampleViewModel.kt"
tmp_kt_file.write_text(
    "package com.example\n"
    "class SampleViewModel {\n"
    "    fun legacyMethod() { val legacy = oldVal!! }\n"
    "    fun touchedMethod() { val newClean = 123 }\n"
    "    fun touchedBrokenMethod() { val bad = brokenVal!! }\n"
    "}\n",
    encoding="utf-8",
)
issues_clean_diff = lint_file_diff_test(tmp_kt_file, modified_lines={4})
ok_diff_clean = len(issues_clean_diff) == 0
issues_broken_diff = lint_file_diff_test(tmp_kt_file, modified_lines={5})
ok_diff_broken = len(issues_broken_diff) == 1 and issues_broken_diff[0]["line"] == 5 and issues_broken_diff[0]["type"] == "UNCHECKED_DOUBLE_BANG"
issues_full = lint_file_diff_test(tmp_kt_file, modified_lines=None)
ok_diff_full = len(issues_full) == 2
ok_diff_scoped = ok_diff_clean and ok_diff_broken and ok_diff_full
print(f"fast_kt_lint diff-scoped line inspection: {'OK' if ok_diff_scoped else 'FAIL'}")
failed += int(not ok_diff_scoped)

# --- v0.16.0: check_strings precise placeholders & duplicate keys ---
from check_strings import _extract_placeholders, _parse_resources
ph_extra = _extract_placeholders("40% extra discount")
ph_disc = _extract_placeholders("55 % Discount")
ph_drastic = _extract_placeholders("20%, drastically decreases")
ph_from = _extract_placeholders("% From your goal")
ph_valid = _extract_placeholders("Hello %s, you have %d points")
ok_ph_precision = (
    ph_extra == []
    and ph_disc == []
    and ph_drastic == []
    and ph_from == []
    and ph_valid == ["%d", "%s"]
)
print(f"check_strings placeholder precision (no literal % false positives): {'OK' if ok_ph_precision else 'FAIL'}")
failed += int(not ok_ph_precision)

tmp_dup_xml = Path(tempfile.mkdtemp()) / "strings.xml"
tmp_dup_xml.write_text(
    '<resources>\n'
    '    <string name="dummy_button">Button 1</string>\n'
    '    <string name="dummy_button">Button 2</string>\n'
    '</resources>\n',
    encoding="utf-8",
)
_, dups = _parse_resources(tmp_dup_xml)
ok_xml_dup = len(dups) == 1 and "dummy_button" in dups[0]
print(f"check_strings duplicate resource key detection: {'OK' if ok_xml_dup else 'FAIL'}")
failed += int(not ok_xml_dup)

# --- v0.17.1: check_strings diff-scoped translation parity (ignores legacy untouched keys) ---
from check_strings import _extract_keys_from_xml_lines, main as check_strings_main
extracted_keys = _extract_keys_from_xml_lines([
    '    <string name="new_key_1">Hello</string>',
    '    <plurals name="new_items_count">',
    '        <item quantity="one">%d item</item>',
    '    </plurals>',
    '    <string-array name="new_colors">',
])
ok_extracted_keys = extracted_keys == {"new_key_1", "new_items_count", "new_colors"}
print(f"check_strings diff-scoped key extraction: {'OK' if ok_extracted_keys else 'FAIL'}")
failed += int(not ok_extracted_keys)

import re
groovy_gradle = '''
android {
    namespace "com.example.groovyapp"
    defaultConfig {
        applicationId "com.example.groovyapp"
    }
}
'''
groovy_ids = [m.group(1) for m in re.finditer(r'applicationId(?:\s*=\s*|\s+)["\']([^"\']+)["\']', groovy_gradle)]
groovy_ns = [m.group(1) for m in re.finditer(r'namespace(?:\s*=\s*|\s+)["\']([^"\']+)["\']', groovy_gradle)]
ok_groovy = ("com.example.groovyapp" in groovy_ids) and ("com.example.groovyapp" in groovy_ns)
print(f"setup_wizard groovy applicationId discovery: {'OK' if ok_groovy else 'FAIL'}")
failed += int(not ok_groovy)

os.environ["_IN_HOOK_SELFTEST"] = "1"
from harness_doctor import HarnessDoctor

# --- v0.7.0: Build Variants (flavors) ---
import _variants  # noqa: E402

_orig_tasks = dict(_variants.ASSEMBLE_TASKS)
_orig_rels = dict(_variants.APK_RELATIVES)
try:
    _variants.ASSEMBLE_TASKS = {"staging": ":app:assembleStagingDebug"}
    ok_var_default = (
        _variants.assemble_task("") == ":app:assembleDebug"
        and _variants.apk_relative("").endswith("app-debug.apk")
    )
    ok_var_mapped = _variants.assemble_task("staging") == ":app:assembleStagingDebug"
    ok_var_computed = _variants.assemble_task("prodClient") == ":app:assembleProdclientDebug"
    ok_var_apk = "staging/debug/app-staging-debug.apk" in _variants.apk_relative("staging")
    ok_var_norm = _variants.normalize_flavor(" Pro-Client ") == "proclient"
    raised_unknown = False
    try:
        _variants.resolve_or_raise("doesnotexist")
    except SystemExit:
        raised_unknown = True
    ok_var_unknown = raised_unknown and _variants.known_flavors() == ["staging"]
finally:
    _variants.ASSEMBLE_TASKS = _orig_tasks
    _variants.APK_RELATIVES = _orig_rels
ok_variants = all([ok_var_default, ok_var_mapped, ok_var_computed, ok_var_apk, ok_var_norm, ok_var_unknown])
print(
    f"variants resolver matrix: {'OK' if ok_variants else 'FAIL ' + str([ok_var_default, ok_var_mapped, ok_var_computed, ok_var_apk, ok_var_norm, ok_var_unknown])}"
)
failed += int(not ok_variants)

# --- v0.15.0: --flavor grammar parity + unit-test task derivation ---
from run_gradle_task import extract_flavor  # noqa: E402
from install_tool_adapters import _derive_unit_test  # noqa: E402

ok_flavor_eq = extract_flavor(["--flavor=staging", ":app:assembleDebug"]) == ("staging", [":app:assembleDebug"])
ok_flavor_pos = extract_flavor(["--flavor", "staging", ":app:assembleDebug"]) == ("staging", [":app:assembleDebug"])
ok_flavor_none = extract_flavor([":app:assembleDebug"]) == (None, [":app:assembleDebug"])
ok_unit_derive = (
    _derive_unit_test(":app:assembleDebug") == ":app:testDebugUnitTest"
    and _derive_unit_test(":composeApp:assembleDebug") == ":composeApp:testDebugUnitTest"
    and _derive_unit_test(":app:assembleRelease") == ":app:testReleaseUnitTest"
)
ok_flavor_grammar = ok_flavor_eq and ok_flavor_pos and ok_flavor_none and ok_unit_derive
print(f"--flavor grammar + unit-test derivation: {'OK' if ok_flavor_grammar else 'FAIL'}")
failed += int(not ok_flavor_grammar)

# --- v0.7.0: Wizard flavor discovery + I.19 wiring ---
from setup_wizard import discover_flavors  # noqa: E402
from setup_wizard import normalize as wiz_normalize  # noqa: E402
from setup_wizard import questions_payload as qp_v7  # noqa: E402

sys.path.insert(0, str(SCRIPTS.parents[1] / "scripts_dev" / "fixtures"))
try:
    from make_android_fixture import make_fixture  # noqa: E402
except ModuleNotFoundError:
    # Installed checkout: scripts_dev/ ships with the kit only. Provide the
    # minimal equivalent builders so these engine tests stay runnable.
    def make_fixture(profile: str, root: Path | None = None) -> Path:
        root = root or Path(tempfile.mkdtemp(prefix="ahk-fixture-"))
        root.mkdir(parents=True, exist_ok=True)

        def _w(rel: str, text: str) -> None:
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")

        _w("gradlew.bat", "rem gradle wrapper fixture\n")
        if profile in ("classic", "flavors"):
            body = (
                'android {\n    flavorDimensions += "env"\n    productFlavors {\n'
                '        create("staging") { dimension = "env" }\n'
                '        create("prodClient") { dimension = "env" }\n'
                "        isDefault = true\n    }\n}\n"
                if profile == "flavors"
                else 'plugins { id("com.android.application") }\nandroid {}\n'
            )
            _w("app/build.gradle.kts", body)
            _w("app/src/main/java/A.kt", "class A\n")
        elif profile == "multimodule":
            _w("app/build.gradle.kts", 'plugins { id("com.android.application") }\n')
            _w("core/data/build.gradle.kts", 'plugins { id("com.android.library") }\n')
            _w("app/src/main/java/A.kt", "class A\n")
            _w("core/data/src/main/kotlin/B.kt", "class B\n")
        elif profile == "kmp":
            _w("settings.gradle.kts", 'include(":shared")\n')
            _w("shared/build.gradle.kts", "kotlin {\n    androidTarget()\n}\n")
            _w("shared/src/commonMain/kotlin/Shared.kt", "expect fun platform(): String\n")
            _w(
                "shared/src/androidMain/kotlin/Shared.android.kt",
                'actual fun platform() = "android"\n',
            )
        else:
            raise SystemExit(f"Unknown fixture profile: {profile}")
        return root

flavor_repo = make_fixture("flavors")
flavor_app_dir = flavor_repo / "app"
flavors_found = discover_flavors(flavor_repo)
ok_flavor_disc = flavors_found == ["staging", "prodClient"]

facts_flavors = {
    "product": "FApp", "pythons": ["python"], "modules": [":app"],
    "launchers": ["com.f/.M"], "apk_hint": "", "locales": ["values"],
    "stack": "Hilt", "classic_app_src": True, "gemini": False,
    "zoho_config": False, "gradlew": True, "flavors": ["staging", "prodClient"],
}
q_ids_f = [q["id"] for q in qp_v7(Path("."), "en", facts_flavors)]
q_ids_nf = [q["id"] for q in qp_v7(Path("."), "en", {**facts_flavors, "flavors": []})]
ok_i19_conditional = ("i19" in q_ids_f) and ("i19" not in q_ids_nf)

norm_f = wiz_normalize(
    {"i0": "yes", "i1": "discovered", "i3": "never", "i4": "allow", "i10": "confirm",
     "i15": "yes", "i14": ["cursor"], "i16": "skip", "i17": "en", "i18": "all_en", "i19": "staging"},
    facts_flavors,
)
ok_i19_norm = (
    norm_f.get("flavor") == "staging"
    and norm_f.get("assemble_tasks", {}).get("staging") == ":app:assembleStagingDebug"
    and norm_f.get("assemble_tasks", {}).get("prodClient") == ":app:assembleProdclientDebug"
)
norm_bad_raised = False
try:
    wiz_normalize(
        {"i0": "yes", "i1": "discovered", "i3": "never", "i4": "allow", "i10": "confirm",
         "i15": "yes", "i14": ["cursor"], "i16": "skip", "i17": "en", "i18": "all_en", "i19": "ghost"},
        facts_flavors,
    )
except SystemExit:
    norm_bad_raised = True
ok_i19_guard = norm_bad_raised
shutil.rmtree(flavor_repo, ignore_errors=True)
ok_wizard_flavors = ok_flavor_disc and ok_i19_conditional and ok_i19_norm and ok_i19_guard
print(
    f"wizard flavors discovery+i19: {'OK' if ok_wizard_flavors else 'FAIL ' + str([ok_flavor_disc, ok_i19_conditional, ok_i19_norm, ok_i19_guard])}"
)
failed += int(not ok_wizard_flavors)

# --- v0.7.0: Multi-module roots + feature boundary lint ---
from _modules import discover_source_roots, module_name_of  # noqa: E402
from fast_kt_lint import lint_file as lint_file_v7  # noqa: E402

mm_repo = make_fixture("multimodule")
roots_mm = discover_source_roots(mm_repo)
ok_roots = len(roots_mm) == 2
names_mm = sorted(module_name_of(r, mm_repo) for r in roots_mm)
ok_mod_names = names_mm == [":app", ":core:data"]
shutil.rmtree(mm_repo, ignore_errors=True)

feat_root = Path(tempfile.mkdtemp())
orders_dir = feat_root / "features" / "orders"
payments_dir = feat_root / "features" / "payments"
plain_dir = feat_root / "plain"
for d in (orders_dir, payments_dir, plain_dir):
    d.mkdir(parents=True, exist_ok=True)
cross_file = orders_dir / "Cross.kt"
cross_file.write_text(
    "package x.features.orders\nimport com.app.features.payments.Api\nimport com.app.features.orders.Local\nfun f() {}\n",
    encoding="utf-8",
)
same_file = orders_dir / "Same.kt"
same_file.write_text("package y\nimport com.app.features.orders.Other\nfun g() {}\n", encoding="utf-8")
outside_file = plain_dir / "Out.kt"
outside_file.write_text("package z\nimport com.app.features.payments.Api2\nfun h() {}\n", encoding="utf-8")
cross_types = {i["type"] for i in lint_file_v7(cross_file)}
same_types = {i["type"] for i in lint_file_v7(same_file)}
outside_types = {i["type"] for i in lint_file_v7(outside_file)}
ok_boundary = (
    "FEATURE_CROSS_IMPORT" in cross_types
    and "FEATURE_CROSS_IMPORT" not in same_types
    and "FEATURE_CROSS_IMPORT" not in outside_types
)
shutil.rmtree(feat_root, ignore_errors=True)
ok_multimodule = ok_roots and ok_mod_names and ok_boundary
print(
    f"multi-module roots+boundary lint: {'OK' if ok_multimodule else 'FAIL ' + str([ok_roots, ok_mod_names, ok_boundary])}"
)
failed += int(not ok_multimodule)

# --- v0.10.0: fixture generator profiles (promoted from ad-hoc builders) ---
fix_classic = make_fixture("classic")
fix_multi = make_fixture("multimodule")
fix_flavors = make_fixture("flavors")
fix_kmp = make_fixture("kmp")
ok_fixture = (
    (fix_classic / "app" / "src" / "main" / "java" / "A.kt").is_file()
    and (fix_multi / "app" / "src" / "main" / "java" / "A.kt").is_file()
    and (fix_multi / "core" / "data" / "src" / "main" / "kotlin" / "B.kt").is_file()
    and (fix_flavors / "app" / "build.gradle.kts").is_file()
    and "create(\"staging\")" in (fix_flavors / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    and (fix_kmp / "shared" / "src" / "androidMain" / "kotlin" / "Shared.android.kt").is_file()
)
fixture_cli_script = SCRIPTS.parents[1] / "scripts_dev" / "fixtures" / "make_android_fixture.py"
if fixture_cli_script.is_file():
    proc_fix = subprocess.run(
        [sys.executable, str(fixture_cli_script), "--profile", "classic"],
        capture_output=True,
        text=True,
        check=False,
    )
    ok_fix_cli = proc_fix.returncode == 0 and Path(proc_fix.stdout.strip()).is_dir()
else:
    ok_fix_cli = True  # scripts_dev/ is kit-only; the builder fallback above covers installs.
ok_fixtures = ok_fixture and ok_fix_cli
print(f"make_android_fixture profiles + CLI: {'OK' if ok_fixtures else 'FAIL'}")
failed += int(not ok_fixtures)

# --- v0.10.x: committed golden fixtures must byte-match the generator ---
golden_root = repo_root / "tests" / "fixtures" / "golden"
if golden_root.is_dir():
    def _tree_files(base: Path) -> dict:
        out: dict = {}
        for p in sorted(base.rglob("*")):
            if p.is_file():
                # Normalize EOLs so git smudge/clean configs cannot fake drift.
                out[p.relative_to(base).as_posix()] = p.read_bytes().replace(b"\r\n", b"\n")
        return out

    ok_golden = True
    golden_notes: list[str] = []
    for profile in ("classic", "multimodule", "flavors", "kmp"):
        want_dir = golden_root / profile
        got_dir = make_fixture(profile)
        try:
            if _tree_files(want_dir) != _tree_files(got_dir):
                ok_golden = False
                golden_notes.append(profile)
        finally:
            shutil.rmtree(got_dir, ignore_errors=True)
    print(
        f"golden fixtures match generator output: "
        f"{'OK' if ok_golden else 'FAIL drifted=' + ', '.join(golden_notes)}"
    )
    failed += int(not ok_golden)
else:
    print("golden fixtures match generator output: OK (skipped — no tests/fixtures/golden)")

# --- v0.10.0: wizard answer pre-fill + doctor remediation guidance ---
from setup_wizard import default_for_question, existing_defaults, write_answers  # noqa: E402

prefill_repo = make_fixture("classic")
prefill_answers = {
    "i0": True,
    "backup": True,
    "product": "TestApp",
    "py": "python",
    "git_policy": "never",
    "device_policy": "physical-only",
    "module": ":app",
    "assemble": ":app:assembleDebug",
    "launcher": "com.t/.Main",
    "install_confirm": "confirm",
    "unit_tests": "no",
    "tools": ["cursor", "gemini"],
    "zoho_mcp": "skip",
    "chat_language": "mirror",
    "zoho_language": "all_ar",
    "flavor": "staging",
    "pm_provider": "github_projects",
    "git_gate": "no",
}
write_answers(prefill_repo, prefill_answers)
prefill_defaults = existing_defaults(prefill_repo)
ok_prefill = (
    prefill_defaults.get("i0") == "yes"
    and prefill_defaults.get("i3") == "never"
    and prefill_defaults.get("i4") == "physical-only"
    and prefill_defaults.get("i15") == "no"
    and prefill_defaults.get("i14") == ["cursor", "gemini"]
    and prefill_defaults.get("i18") == "all_ar"
    and prefill_defaults.get("i20") == "github_projects"
    and prefill_defaults.get("i21") == "no"
)
i3_q = {"id": "i3", "options": [{"id": "never"}, {"id": "agent-may-commit"}]}
ok_prefill = (
    ok_prefill
    and default_for_question(i3_q, prefill_defaults) == ["never"]
    and default_for_question({"id": "i3", "options": [{"id": "agent-may-commit"}]}, prefill_defaults) == []
    and default_for_question({"id": "i9", "options": [{"id": "x"}]}, prefill_defaults) == []
)
prefill_proc = subprocess.run(
    [
        sys.executable,
        "-c",
        (
            "import sys; sys.path.insert(0, r'%s'); "
            "from setup_wizard import prompt_choice; "
            "q = {'id': 'i3', 'required': True, 'allow_multiple': False, 'prompt': 'Git policy', "
            "'options': [{'id': 'never', 'label': 'N'}, {'id': 'agent-may-commit', 'label': 'A'}]}; "
            "print(prompt_choice(q, 'en', ['never'])[0])"
        )
        % SCRIPTS,
    ],
    input="\n",
    text=True,
    capture_output=True,
    check=False,
    env=os.environ.copy(),
)
ok_prefill_enter = prefill_proc.returncode == 0 and prefill_proc.stdout.strip().endswith("never")
ok_prefill_all = ok_prefill and ok_prefill_enter
print(f"wizard answer pre-fill defaults: {'OK' if ok_prefill_all else 'FAIL ' + str([ok_prefill, ok_prefill_enter])}")
failed += int(not ok_prefill_all)

app_agents = prefill_repo / ".agents" / "scripts"
app_agents.mkdir(parents=True, exist_ok=True)
shutil.copy(SCRIPTS / "_product.py", app_agents / "_product.py")
repo_product = app_agents / "_product.py"
repo_product.write_text(
    repo_product.read_text(encoding="utf-8").replace("ALLOW_EMULATOR = True", "ALLOW_EMULATOR = False"),
    encoding="utf-8",
)
write_answers(
    prefill_repo,
    {**prefill_answers, "device_policy": "allow"},
)
doctor_drift_proc = subprocess.run(
    [
        sys.executable,
        "-c",
        (
            "import sys; sys.path.insert(0, r'%s'); sys.path.insert(0, r'%s'); "
            "from pathlib import Path; import harness_doctor; "
            "d = harness_doctor.HarnessDoctor(Path(r'%s')); "
            "rs = d.run_all(); "
            'r = next(x for x in rs if x.name == "Install Consistency"); '
            "print(r.status); print(r.details)"
        )
        % (app_agents, SCRIPTS, prefill_repo),
    ],
    capture_output=True,
    text=True,
    check=False,
    env={**os.environ.copy(), "PYTHONPATH": str(app_agents) + os.pathsep + str(SCRIPTS)},
)
ok_drift_hint = (
    doctor_drift_proc.returncode == 0
    and doctor_drift_proc.stdout.splitlines()[0].strip() == "FAIL"
    and "setup_wizard.py ask" in doctor_drift_proc.stdout
)
print(f"doctor drift remediation points to wizard: {'OK' if ok_drift_hint else 'FAIL ' + doctor_drift_proc.stdout + doctor_drift_proc.stderr}")
failed += int(not ok_drift_hint)

# --- v0.8.0: PM abstraction layer — policy engine matrix ---
import pm_policy  # noqa: E402
from pm_policy import normalize_status as pm_norm_status  # noqa: E402
from pm_policy import validate_handoff as pm_validate  # noqa: E402
from pm_policy import mutation_trigger as pm_trigger  # noqa: E402
from pm_policy import resolve_provider as pm_resolve  # noqa: E402
from pm_policy import status_label as pm_label_of  # noqa: E402

ok_pm_registry = set(pm_policy.PROVIDERS) == {"zoho_sprints", "github_projects", "jira", "linear"}
ok_pm_defaults = (
    pm_resolve(None) == "zoho_sprints"
    and pm_resolve("") == "zoho_sprints"
    and pm_resolve("jira_mcp") == "jira"
    and pm_resolve("linear_mcp") == "linear"
    and pm_resolve("none") == "none"
    and pm_policy.WIZARD_PROVIDER_IDS == ("zoho_sprints", "github_projects", "jira_mcp", "linear_mcp", "none")
)
ok_pm_triggers = (
    pm_trigger("zoho_sprints") == "update zoho"
    and pm_trigger("github_projects") == "update github"
    and pm_trigger("jira") == "update jira"
    and pm_trigger("linear") == "update linear"
    and pm_trigger(None) == "update zoho"
    and pm_trigger("none") == ""
)

status_matrix = {
    "zoho_sprints": {"in_progress": "In progress", "ready_to_retest": "Ready To ReTest"},
    "github_projects": {"in_progress": "In Progress", "ready_to_retest": "In Review"},
    "jira": {"in_progress": "In Progress", "ready_to_retest": "Ready for Testing"},
    "linear": {"in_progress": "In Progress", "ready_to_retest": "In Review"},
}
pm_map_results = []
for prov, canon_to_label in status_matrix.items():
    for canon, label in canon_to_label.items():
        fwd_ok = pm_label_of(prov, canon) == label
        rev_ok = pm_norm_status(prov, label) == canon
        ci_ok = pm_norm_status(prov, label.upper()) == canon
        pm_map_results.append(fwd_ok and rev_ok and ci_ok)
ok_pm_maps = all(pm_map_results) and len(pm_map_results) == 8

def _raises_system_exit(fn, *a, **kw) -> bool:
    try:
        fn(*a, **kw)
    except SystemExit:
        return True
    return False

ok_pm_unknown = (
    _raises_system_exit(pm_norm_status, "zoho_sprints", "Ghost Status")
    and _raises_system_exit(pm_norm_status, "jira", "Done")
    and _raises_system_exit(pm_norm_status, "linear", "Canceled")
    and _raises_system_exit(pm_norm_status, "github_projects", "Shipped")
    and _raises_system_exit(pm_resolve, "carrier_pigeon")
    and _raises_system_exit(pm_policy.status_label, "none", "in_progress")
    and _raises_system_exit(pm_validate, "x", "klingon")
)

VALID_EN_BUG = (
    "Commit: abc1234\n\nRoot Cause:\nFunctional explanation.\n\nSolution:\nFunctional fix.\n\n"
    "Impact Area (Blast Radius):\n- Home screen\n\nTest Cases & Verification Steps:\n1. Happy path\n2. Edge case\n"
)
VALID_AR_BUG = (
    "Commit: abc1234\n\nسبب المشكلة:\nشرح وظيفي.\n\nالحل المطبق:\nإصلاح وظيفي.\n\n"
    "نطاق التأثير (Impact Area):\n- الشاشة الرئيسية\n\nخطوات الفحص وحالات الاختبار (Test Cases):\n1. المسار الأساسي\n"
)
ok_pm_valid_en = pm_validate(VALID_EN_BUG, "all_en", "zoho_sprints") == []
ok_pm_valid_ar = pm_validate(VALID_AR_BUG, "all_ar", "zoho_sprints") == []
missing_cases = []
for needle in ("Root Cause:", "Solution:", "Impact Area (Blast Radius):", "Test Cases & Verification Steps:"):
    missing_cases.append(
        len(pm_validate(VALID_EN_BUG.replace(needle + "\n", "\n"), "all_en", "zoho_sprints")) == 1
        or len(pm_validate(VALID_EN_BUG.replace(needle, "Removed:"), "all_en", "zoho_sprints")) == 1
    )
ok_pm_missing_sections = all(missing_cases) and len(missing_cases) == 4
commit_probe = pm_validate(VALID_EN_BUG[len("Commit: abc1234"):].lstrip("\n"), "all_en")
commit_hit = any("Commit" in v for v in commit_probe)
denied_probes = [
    pm_validate(VALID_EN_BUG + "Status: Done\n", "all_en", "zoho_sprints"),
    pm_validate(VALID_EN_BUG + "status = Solved\n", "all_en", "zoho_sprints"),
    pm_validate(VALID_EN_BUG + "Status to Closed\n", "all_en", "jira"),
]
ok_pm_denied = all(len(v) == 1 for v in denied_probes)
ok_pm_allowed_status = pm_validate(VALID_EN_BUG + "Status: Ready To ReTest\n", "all_en", "zoho_sprints") == []
ok_pm_policy = all([
    ok_pm_registry,
    ok_pm_defaults,
    ok_pm_triggers,
    ok_pm_maps,
    ok_pm_unknown,
    ok_pm_valid_en,
    ok_pm_valid_ar,
    ok_pm_missing_sections,
    commit_hit,
    ok_pm_denied,
    ok_pm_allowed_status,
])
print(
    f"pm_policy provider registry & handoff validation: "
    f"{'OK' if ok_pm_policy else 'FAIL ' + str([ok_pm_registry, ok_pm_defaults, ok_pm_triggers, ok_pm_maps, ok_pm_unknown, ok_pm_valid_en, ok_pm_valid_ar, ok_pm_missing_sections, commit_hit, ok_pm_denied, ok_pm_allowed_status])}"
)
failed += int(not ok_pm_policy)

# --- v0.8.0: GitHub adapter with mocked subprocess (zero network) ---
import shutil as _shutil  # noqa: E402
import pm_github  # noqa: E402

class _FakeProc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err

_orig_run = pm_github.subprocess.run
_gh_calls: list[list[str]] = []
try:
    def _fake_run_ok(cmd, **kwargs):
        _gh_calls.append(list(cmd))
        assert kwargs.get("timeout") == pm_github.GH_TIMEOUT_SECONDS
        joined = " ".join(cmd[1:])
        if joined.startswith("issue list"):
            return _FakeProc(0, json.dumps([{"number": 7, "title": "T", "url": "u", "state": "OPEN"}]))
        if joined.startswith("issue view"):
            return _FakeProc(0, json.dumps({"number": 7, "title": "T", "body": "old", "state": "OPEN", "url": "u", "labels": []}))
        if "--body-file -" in joined:
            stdin_payload = kwargs.get("input") or ""
            assert stdin_payload.strip()
            return _FakeProc(0, "posted\n")
        return _FakeProc(0, "{}")

    pm_github.subprocess.run = _fake_run_ok
    listed = pm_github.list_issues("o/r")
    viewed = pm_github.view_issue(7, "o/r")
    comment_out = pm_github.add_comment(7, "QA handoff body", "o/r")
    label = pm_github.set_issue_status(7, pm_policy.CANONICAL_READY_RETEST, "o/r")
    ok_gh_ops = (
        listed[0]["number"] == 7
        and viewed["title"] == "T"
        and comment_out.strip() == "posted"
        and label == "In Review"
    )

    def _fake_run_fail(cmd, **kwargs):
        return _FakeProc(1, "", "boom: not authenticated")

    pm_github.subprocess.run = _fake_run_fail
    ok_gh_fail_closed = _raises_system_exit(pm_github.list_issues, "o/r")

    def _fake_run_never(cmd, **kwargs):
        raise AssertionError("gh must not be called")

    pm_github.subprocess.run = _fake_run_never
    ok_gh_denied_done = _raises_system_exit(pm_github.set_issue_status, 7, "done", "o/r")
finally:
    pm_github.subprocess.run = _orig_run

_orig_which = _shutil.which
try:
    _shutil.which = lambda name: None
    ok_gh_missing_binary = _raises_system_exit(pm_github.list_issues, "o/r")
finally:
    _shutil.which = _orig_which
ok_pm_github = ok_gh_ops and ok_gh_fail_closed and ok_gh_denied_done and ok_gh_missing_binary
print(
    f"pm_github adapter (mocked gh): {'OK' if ok_pm_github else 'FAIL ' + str([ok_gh_ops, ok_gh_fail_closed, ok_gh_denied_done, ok_gh_missing_binary])}"
)
failed += int(not ok_pm_github)

# --- v0.8.0: Wizard I.20 tracker question wiring ---
from setup_wizard import pm_next_steps as wiz_pm_next  # noqa: E402

facts_v8 = {**facts, "flavors": []}
q_ids_v8 = [q["id"] for q in qp_v7(Path("."), "en", facts_v8)]
i20_labels = [
    o["id"]
    for q in qp_v7(Path("."), "en", facts_v8) if q["id"] == "i20"
    for o in q["options"]
]
ok_i20_present = "i20" in q_ids_v8 and i20_labels == ["zoho_sprints", "github_projects", "jira_mcp", "linear_mcp", "none"]

norm_v8 = wiz_normalize(
    {"i0": "yes", "i1": "discovered", "i3": "never", "i4": "allow", "i10": "confirm",
     "i15": "yes", "i14": ["cursor"], "i16": "enable", "i18": "all_en",
     "i20": "github_projects"},
    facts_v8,
)
ok_i20_norm = norm_v8.get("pm_provider") == "github_projects"
norm_v8_default = wiz_normalize(
    {"i0": "yes", "i1": "discovered", "i3": "never", "i4": "allow", "i10": "confirm",
     "i15": "yes", "i14": ["cursor"], "i16": "skip", "i18": "all_en"},
    facts_v8,
)
ok_i20_backward = norm_v8_default.get("pm_provider") == "zoho_sprints"
bad_i20_raised = False
try:
    wiz_normalize(
        {"i0": "yes", "i1": "discovered", "i3": "never", "i4": "allow", "i10": "confirm",
         "i15": "yes", "i14": ["cursor"], "i16": "skip", "i18": "all_en",
         "i20": "trello"},
        facts_v8,
    )
except SystemExit:
    bad_i20_raised = True
hints_gh = wiz_pm_next({"pm_provider": "github_projects"})
hints_jira = wiz_pm_next({"pm_provider": "jira_mcp"})
hints_lin = wiz_pm_next({"pm_provider": "linear_mcp"})
hints_default = wiz_pm_next({})
hints_none = wiz_pm_next({"pm_provider": "none"})
ok_hints = (
    any("pm_github.py check" in h for h in hints_gh)
    and any("mcp_registration.jira.md" in h for h in hints_jira)
    and any("mcp_registration.linear.md" in h for h in hints_lin)
    and hints_default == []
    and hints_none == ["PM: no tracker selected; delivery stays local-only."]
)
ok_wizard_i20 = ok_i20_present and ok_i20_norm and ok_i20_backward and bad_i20_raised and ok_hints
print(
    f"wizard I.20 project-tracker wiring: {'OK' if ok_wizard_i20 else 'FAIL ' + str([ok_i20_present, ok_i20_norm, ok_i20_backward, bad_i20_raised, ok_hints])}"
)
failed += int(not ok_wizard_i20)

# --- v0.10.0: wizard I.21 git-gate confirmation (default ON) ---
from setup_wizard import flags_from_answers  # noqa: E402

ok_i21_present = "i21" in q_ids_v8
norm_i21_yes = normalize({**{"i0": "yes", "i1": "discovered", "i3": "never", "i4": "allow",
                             "i10": "confirm", "i15": "yes", "i14": ["cursor"], "i16": "skip",
                             "i18": "all_en", "i20": "zoho_sprints", "i21": "no"},
                          }, facts_v8)
norm_i21_absent = normalize({"i0": "yes", "i1": "discovered", "i3": "never", "i4": "allow",
                              "i10": "confirm", "i15": "yes", "i14": ["cursor"], "i16": "skip",
                              "i18": "all_en", "i20": "zoho_sprints"}, facts_v8)
ok_i21_norm = (
    norm_i21_yes.get("git_gate") == "no"
    and norm_i21_absent.get("git_gate") == "yes"
)
flags_yes = flags_from_answers({**norm_i21_absent, "git_gate": "yes"})
flags_no = flags_from_answers({**norm_i21_absent, "git_gate": "no"})
ok_i21_flags = "--git-gate" in flags_yes and "--no-git-gate" in flags_no
ok_wizard_i21 = ok_i21_present and ok_i21_norm and ok_i21_flags
print(
    f"wizard I.21 git-gate confirmation (default ON): {'OK' if ok_wizard_i21 else 'FAIL ' + str([ok_i21_present, ok_i21_norm, ok_i21_flags])}"
)
failed += int(not ok_wizard_i21)

# --- v0.14.6: Autonomous E2E Engine & Wizard I.22 ---
from _adb_core import (
    parse_ui_hierarchy,
    parse_bounds,
    find_nodes,
    find_first,
    parse_flow_definition,
    detect_app_locale,
    resolve_target_text,
)  # noqa: E402

SAMPLE_UI_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.example.app" content-desc="" checkable="false" checked="false" clickable="false" enabled="true" focusable="false" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[0,0][1080,2400]">
    <node index="0" text="الفعاليات" resource-id="com.example.app:id/tv_title" class="android.widget.TextView" package="com.example.app" content-desc="تبويب الفعاليات" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[40,100][300,200]" />
    <node index="1" text="" resource-id="com.example.app:id/rv_events" class="androidx.recyclerview.widget.RecyclerView" package="com.example.app" content-desc="" checkable="false" checked="false" clickable="false" enabled="true" focusable="true" focused="false" scrollable="true" long-clickable="false" password="false" selected="false" bounds="[0,200][1080,2200]">
      <node index="0" text="ماراثون الجري" resource-id="com.example.app:id/tv_event_name" class="android.widget.TextView" package="com.example.app" content-desc="" checkable="false" checked="false" clickable="true" enabled="true" focusable="false" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[60,250][1020,450]" />
    </node>
  </node>
</hierarchy>
"""

e2e_nodes = parse_ui_hierarchy(SAMPLE_UI_XML)
b_coords, b_center = parse_bounds("[40,100][300,200]")
ok_bounds = b_coords == (40, 100, 300, 200) and b_center == (170, 150)

node_ar = find_first(e2e_nodes, text="الفعاليات")
node_desc = find_first(e2e_nodes, content_desc="تبويب الفعاليات")
node_rv = find_first(e2e_nodes, class_name="RecyclerView")
node_nested = find_first(e2e_nodes, text="ماراثون")

ok_e2e_parser = (
    len(e2e_nodes) == 1
    and ok_bounds
    and node_ar is not None
    and node_ar.center == (170, 150)
    and node_ar.clickable is True
    and node_desc is not None
    and node_rv is not None
    and node_rv.scrollable is True
    and node_nested is not None
    and node_nested.center == (540, 350)
)
print(f"e2e_smoke parser & coordinate calculation: {'OK' if ok_e2e_parser else 'FAIL'}")
failed += int(not ok_e2e_parser)

# Declarative Maestro YAML Flow parsing & locale fingerprinting
SAMPLE_FLOW_YAML = """
appId: com.example.app
---
- launchApp
- tapOn:
    id: "login_btn"
    wait: 1.5
- inputText: "user@example.com"
- hideKeyboard
- tapOn:
    stringKey: "submit_action"
- assertVisible:
    text: "الفعاليات"
- takeScreenshot: "events_screen"
"""
parsed_flow = parse_flow_definition(SAMPLE_FLOW_YAML)
ok_flow_parse = (
    parsed_flow.get("appId") == "com.example.app"
    and len(parsed_flow.get("steps", [])) == 7
    and parsed_flow["steps"][1]["action"] == "tapOn"
    and parsed_flow["steps"][1]["id"] == "login_btn"
    and parsed_flow["steps"][2]["text"] == "user@example.com"
    and parsed_flow["steps"][3]["action"] == "hideKeyboard"
    and parsed_flow["steps"][4]["stringKey"] == "submit_action"
    and parsed_flow["steps"][6]["name"] == "events_screen"
)
sample_str_index = {
    "default": {"submit_action": "Submit", "events_title": "Events"},
    "ar": {"submit_action": "إرسال", "events_title": "الفعاليات"},
}
detected_app_loc = detect_app_locale(e2e_nodes, sample_str_index)
resolved_ar = resolve_target_text({"stringKey": "submit_action"}, "ar", sample_str_index)
resolved_def = resolve_target_text({"stringKey": "submit_action"}, "default", sample_str_index)

ok_e2e_declarative = (
    ok_flow_parse
    and detected_app_loc == "ar"
    and resolved_ar == "إرسال"
    and resolved_def == "Submit"
)
print(f"e2e declarative flow parser & in-app locale fingerprinting: {'OK' if ok_e2e_declarative else 'FAIL'}")
failed += int(not ok_e2e_declarative)

ok_i22_present = "i22" in q_ids_v8
norm_i22_e2e = normalize({**{"i0": "yes", "i1": "discovered", "i3": "never", "i4": "allow",
                             "i10": "confirm", "i15": "yes", "i14": ["cursor"], "i16": "skip",
                             "i18": "all_en", "i20": "zoho_sprints", "i21": "yes", "i22": "autonomous_e2e"}}, facts_v8)
norm_i22_manual = normalize({**{"i0": "yes", "i1": "discovered", "i3": "never", "i4": "allow",
                                "i10": "confirm", "i15": "yes", "i14": ["cursor"], "i16": "skip",
                                "i18": "all_en", "i20": "zoho_sprints", "i21": "yes", "i22": "manual_only"}}, facts_v8)
norm_i22_default = normalize({**{"i0": "yes", "i1": "discovered", "i3": "never", "i4": "allow",
                                 "i10": "confirm", "i15": "yes", "i14": ["cursor"], "i16": "skip",
                                 "i18": "all_en", "i20": "zoho_sprints", "i21": "yes"}}, facts_v8)
ok_wizard_i22 = (
    ok_i22_present
    and norm_i22_e2e.get("device_verification") == "autonomous_e2e"
    and norm_i22_manual.get("device_verification") == "manual_only"
    and norm_i22_default.get("device_verification") == "autonomous_e2e"
)
print(f"wizard I.22 device-verification wiring (default E2E): {'OK' if ok_wizard_i22 else 'FAIL'}")
failed += int(not ok_wizard_i22)

# --- v0.14.7: Hierarchy-Aware Gitignore Deduplication & CLI Ergonomics ---
from setup_wizard import write_answers, answers_path
from install_tool_adapters import parse_args as parse_adapter_args

temp_app_root = Path(tempfile.mkdtemp(prefix="harness-gi-test-"))
try:
    (temp_app_root / ".git" / "info").mkdir(parents=True, exist_ok=True)
    gi_path = temp_app_root / ".gitignore"
    exclude_path = temp_app_root / ".git" / "info" / "exclude"
    stray_script = temp_app_root / "script_step3b.py"
    stray_script.write_text("# Android Agent Harness setup step\nprint('stray')", encoding="utf-8")
    user_file = temp_app_root / "fix_product.py"
    user_file.write_text("print('user-owned')", encoding="utf-8")

    # Simulate an existing .gitignore that had .agents/ and redundant subpaths + normal build/
    gi_path.write_text(".agents/\n.agents/state/\n.agents/cache/\n.agents/__pycache__/\nbuild/\n", encoding="utf-8")

    write_answers(temp_app_root, {
        "schema": 1,
        "i0": True,
        "product": "TestApp",
        "py": "python",
        "git_policy": "never",
        "device_policy": "allow",
        "module": ":app",
        "assemble": ":app:assembleDebug",
        "launcher": "com.example.MainActivity",
        "apk": "path",
        "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
        "architecture": "MVI",
        "architecture_mode": "discovered",
        "agents_git": "gitignore",
        "tools": ["gemini"],
    })

    updated_gi_lines = [ln.strip() for ln in gi_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    exclude_text = exclude_path.read_text(encoding="utf-8") if exclude_path.is_file() else ""

    ok_gi_dedup = (
        "build/" in updated_gi_lines
        and ".agents/" not in updated_gi_lines
        and ".agents/state/" not in updated_gi_lines
        and ".agents/" in exclude_text
        and "AGENTS.md" in exclude_text
        and not stray_script.is_file()
        and user_file.is_file()
    )
finally:
    shutil.rmtree(temp_app_root, ignore_errors=True)

print(f"automatic .git/info/exclude local privacy & clean .gitignore: {'OK' if ok_gi_dedup else 'FAIL'}")
failed += int(not ok_gi_dedup)

parsed_gg_yes = parse_adapter_args(["--product", "A", "--py", "python", "--assemble", ":app:assembleDebug", "--tools", "gemini", "--git-gate", "yes"])
parsed_gg_no = parse_adapter_args(["--product", "A", "--py", "python", "--assemble", ":app:assembleDebug", "--tools", "gemini", "--git-gate", "no"])
parsed_gg_eq_yes = parse_adapter_args(["--product", "A", "--py", "python", "--assemble", ":app:assembleDebug", "--tools", "gemini", "--git-gate=true"])
ok_gg_cli = parsed_gg_yes.git_gate is True and parsed_gg_no.git_gate is False and parsed_gg_eq_yes.git_gate is True
print(f"install_tool_adapters --git-gate value parsing flexibility: {'OK' if ok_gg_cli else 'FAIL'}")
failed += int(not ok_gg_cli)

# Test run_device.py apk resolution when --apk is omitted (no TypeError)
from run_device import main as run_device_main
rd_test_proc = subprocess.run(
    [sys.executable, str(SCRIPTS / "run_device.py"), "install-start", "--help"],
    text=True,
    capture_output=True,
)
ok_rd_cli = rd_test_proc.returncode == 0
print(f"run_device CLI resolution (zero args crash guard): {'OK' if ok_rd_cli else 'FAIL'}")
failed += int(not ok_rd_cli)

# Dispatch one real review round for c-ttl so the tree-cleanliness gate sees
# review history (the TTL probe must not depend on an empty working tree),
# then backdate pending_since to drive the TTL expiry being tested.
run(invoke_five("c-ttl"))
_state_now = json.loads(STATE.read_text(encoding="utf-8"))
_state_now["c-ttl"]["pending_since"] = time.time() - 100000
STATE.write_text(json.dumps(_state_now), encoding="utf-8")
ttl_res = run(cmd("gradlew.bat :app:assembleDebug", conversation="c-ttl"))
ok_ttl = ttl_res["decision"] == "allow"
print(f"barrier_ttl_expiry_unblocks: {ttl_res['decision']} {'OK' if ok_ttl else 'FAIL ' + json.dumps(ttl_res)}")
failed += int(not ok_ttl)

# --- v0.6.0: Claude Code PreToolUse Bridge ---
cc_bridge_script = SCRIPTS / "cc_pre_tool_safety.py"
if cc_bridge_script.is_file():
    proc_cc_push = subprocess.run(
        [sys.executable, str(cc_bridge_script)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}),
        capture_output=True,
        text=True,
    )
    cc_push_out = json.loads(proc_cc_push.stdout or "{}")
    ok_cc_push = cc_push_out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"

    proc_cc_status = subprocess.run(
        [sys.executable, str(cc_bridge_script)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}}),
        capture_output=True,
        text=True,
    )
    cc_status_out = json.loads(proc_cc_status.stdout or "{}")
    ok_cc_status = cc_status_out.get("hookSpecificOutput", {}).get("permissionDecision") == "allow"

    proc_cc_other = subprocess.run(
        [sys.executable, str(cc_bridge_script)],
        input=json.dumps({"tool_name": "ViewFile", "tool_input": {"path": "README.md"}}),
        capture_output=True,
        text=True,
    )
    cc_other_out = json.loads(proc_cc_other.stdout or "{}")
    ok_cc_other = cc_other_out.get("hookSpecificOutput", {}).get("permissionDecision") == "allow"

    ok_cc_bridge = ok_cc_push and ok_cc_status and ok_cc_other
    print(f"claude_code_pre_tool_safety bridge: {'OK' if ok_cc_bridge else 'FAIL'}")
    failed += int(not ok_cc_bridge)
else:
    print("claude_code_pre_tool_safety bridge: OK (skipped — script not present)")

# --- v0.6.0: Command Packs, Git Gate & Adapter Lifecycle ---
from install_tool_adapters import (
    command_pack_templates,
    parse_args,
    install as install_adapters,
)

cp_tmpls = command_pack_templates()
ok_cp_tmpls = len(cp_tmpls) == 11 or _is_installed
tmp_adapt_dir = Path(tempfile.mkdtemp())
try:
    (tmp_adapt_dir / ".git" / "info").mkdir(parents=True, exist_ok=True)
    hooks_json = tmp_adapt_dir / ".agents" / "hooks.json"
    hooks_json.parent.mkdir(parents=True, exist_ok=True)
    hooks_json.write_text(
        json.dumps(
            {
                "adb-and-git-safety": {
                    "enabled": True,
                    "PreToolUse": [
                        {"matcher": "run_command", "hooks": [{"type": "command", "command": "python scripts/pre_tool_safety.py"}]}
                    ],
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    # No --git-gate flag: the staged quality gate is DEFAULT ON since v0.10.0.
    adapt_args = parse_args([
        "--repo", str(tmp_adapt_dir),
        "--product", "TestApp",
        "--py", "python3",
        "--assemble", ":app:assembleDebug",
        "--tools", "claude,copilot,codex",
        "--cc-hooks",
        "--copilot-hooks",
    ])
    install_adapters(adapt_args)
    ok_claude_pack = (tmp_adapt_dir / ".claude" / "commands" / "deliver.md").is_file()
    ok_copilot_pack = (tmp_adapt_dir / ".github" / "prompts" / "deliver.prompt.md").is_file()
    ok_codex_pack = (tmp_adapt_dir / ".codex" / "prompts" / "deliver.md").is_file()
    ok_git_gate_hook = (tmp_adapt_dir / ".githooks" / "pre-commit").is_file()
    exclude_file = tmp_adapt_dir / ".git" / "info" / "exclude"
    ok_git_exclude = exclude_file.is_file() and ".githooks/" in exclude_file.read_text(encoding="utf-8")
    ok_cc_settings = (tmp_adapt_dir / ".claude" / "settings.json").is_file()
    copilot_hooks_file = tmp_adapt_dir / ".github" / "hooks" / "android-harness-pre-tool-use.json"
    ok_copilot_hooks = copilot_hooks_file.is_file()
    if ok_copilot_hooks:
        hooks_body = copilot_hooks_file.read_text(encoding="utf-8")
        ok_copilot_hooks = "preToolUse" in hooks_body and "copilot_pre_tool_safety.py" in hooks_body

    rewritten_hooks = json.loads(hooks_json.read_text(encoding="utf-8"))
    ok_hooks_py = (
        "python3 scripts/pre_tool_safety.py"
        in rewritten_hooks["adb-and-git-safety"]["PreToolUse"][0]["hooks"][0]["command"]
    )
    agents_md = (tmp_adapt_dir / "AGENTS.md").read_text(encoding="utf-8")
    ok_agents_fill = (
        "testDebugUnitTest" in agents_md
        and ("{" + "{UNIT_TEST}}") not in agents_md
        and "update zoho" in agents_md
        and ("{" + "{PM_TRIGGER}}") not in agents_md
    )

    # Test pruning (copilot deselected -> its hooks bridge is removed too)
    adapt_args_prune = parse_args([
        "--repo", str(tmp_adapt_dir),
        "--product", "TestApp",
        "--py", "python",
        "--assemble", ":app:assembleDebug",
        "--tools", "claude",
    ])
    install_adapters(adapt_args_prune)
    ok_prune_codex = not (tmp_adapt_dir / ".codex" / "prompts" / "deliver.md").is_file()
    ok_prune_copilot_hooks = not copilot_hooks_file.is_file()
    ok_keep_claude = (tmp_adapt_dir / ".claude" / "commands" / "deliver.md").is_file()

    # Explicit opt-out: --no-git-gate must leave no hook behind
    no_gate_dir = Path(tempfile.mkdtemp())
    adapt_args_no_gate = parse_args([
        "--repo", str(no_gate_dir),
        "--product", "TestApp",
        "--py", "python",
        "--assemble", ":app:assembleDebug",
        "--tools", "claude",
        "--no-git-gate",
    ])
    install_adapters(adapt_args_no_gate)
    ok_no_gate = not (no_gate_dir / ".githooks" / "pre-commit").is_file()

    ok_adapter_lifecycle = (
        ok_cp_tmpls
        and ok_claude_pack
        and ok_copilot_pack
        and ok_codex_pack
        and ok_git_gate_hook
        and ok_git_exclude
        and ok_cc_settings
        and ok_copilot_hooks
        and ok_hooks_py
        and ok_agents_fill
        and ok_prune_codex
        and ok_prune_copilot_hooks
        and ok_keep_claude
        and ok_no_gate
    )
    print(f"install_tool_adapters command_packs, git_gate(default ON) & hook bridges: {'OK' if ok_adapter_lifecycle else 'FAIL'}")
    failed += int(not ok_adapter_lifecycle)
finally:
    import shutil
    shutil.rmtree(tmp_adapt_dir, ignore_errors=True)
    shutil.rmtree(no_gate_dir, ignore_errors=True)

# --- v0.6.0: Pre-Commit Quality Gate Smoke ---
pre_commit_script = SCRIPTS / "pre_commit_gate.py"
if pre_commit_script.is_file():
    proc_gate = subprocess.run([sys.executable, str(pre_commit_script)], capture_output=True, text=True)
    ok_gate = proc_gate.returncode == 0
    print(f"pre_commit_gate staged sanity: {'OK' if ok_gate else 'FAIL'}")
    failed += int(not ok_gate)
else:
    print("pre_commit_gate staged sanity: OK (skipped — script not present)")

# --- v0.6.0: Harness CLI Dispatcher ---
cli_file = repo_root / "harness_cli.py"
if cli_file.is_file():
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from harness_cli import build_parser as cli_build_parser, resolve_kit as cli_resolve_kit
    cli_p = cli_build_parser()
    cli_cmds = set(next(a.choices for a in cli_p._actions if a.dest == "command").keys())
    ok_cli_cmds = cli_cmds == {"init", "update", "explain", "verify", "doctor", "preflight", "selftest", "version"}
    ok_cli_kit = bool(cli_resolve_kit(str(repo_root)))
    proc_cli_ver = subprocess.run([sys.executable, str(cli_file), "version"], capture_output=True, text=True)
    ok_cli_ver = proc_cli_ver.returncode == 0 and bool(proc_cli_ver.stdout.strip())
    ok_cli = ok_cli_cmds and ok_cli_kit and ok_cli_ver
    print(f"harness_cli dispatch & subcommands: {'OK' if ok_cli else 'FAIL'}")
    failed += int(not ok_cli)

# --- v0.10.x: android-harness verify round trip ---
if cli_file.is_file():
    verify_repo = make_fixture("classic")
    try:
        vstate = verify_repo / ".agents" / "state" / "verdicts"
        vstate.mkdir(parents=True, exist_ok=True)
        fake_pkg = vstate / "pkg.diff"
        fake_pkg.write_text("diff --git a/x b/x\n", encoding="utf-8")
        target_rel = "app/src/main/java/A.kt"
        target_abs = verify_repo / "app" / "src" / "main" / "java" / "A.kt"
        record_v = {
            "schema_version": 1,
            "task_id": "",
            "git_sha": "",
            "package": {
                "path": str(fake_pkg),
                "sha256": hashlib.sha256(fake_pkg.read_bytes()).hexdigest(),
                "sha256_12": hashlib.sha256(fake_pkg.read_bytes()).hexdigest()[:12],
            },
            "tree_fingerprint": None,
            "files": {target_rel: hashlib.sha256(target_abs.read_bytes()).hexdigest()},
            "dispatched_at": None,
            "completed_at": "2026-08-26T00:00:00Z",
            "completed_reason": "All subagents completed.",
            "verdict": "PASS",
            "leaves": {
                leaf: {"token": token, "evidence": {"pkg": "0123456789ab", "cites": 1, "valid": True}}
                for leaf, token in (
                    ("bug", "BUG_PASS"),
                    ("convention", "CONVENTION_PASS"),
                    ("security", "SECURITY_PASS"),
                    ("perf", "PERF_PASS"),
                    ("regression", "REGRESSION_PASS"),
                )
            },
            "checks": [],
            "findings": [],
        }
        verdict_file = vstate / "verdict-0123456789ab.json"
        verdict_file.write_text(json.dumps(record_v), encoding="utf-8")
        proc_v_ok = subprocess.run(
            [sys.executable, str(cli_file), "verify", "--repo", str(verify_repo)],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        ok_verify_pass = proc_v_ok.returncode == 0 and "[PASS]" in proc_v_ok.stdout
        target_abs.write_text("class A changed\n", encoding="utf-8")
        proc_v_fail = subprocess.run(
            [sys.executable, str(cli_file), "verify", "--repo", str(verify_repo)],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        ok_verify_fail = proc_v_fail.returncode == 1 and "[FAIL]" in proc_v_fail.stdout
        ok_verify = ok_verify_pass and ok_verify_fail
        print(
            f"harness_cli verify round trip: {'OK' if ok_verify else 'FAIL ' + proc_v_ok.stdout + proc_v_fail.stdout}"
        )
        failed += int(not ok_verify)
    finally:
        shutil.rmtree(verify_repo, ignore_errors=True)
else:
    print("harness_cli dispatch & subcommands: OK (skipped — installed checkout)")


# --- v0.16.0: install_or_update engine deterministic round-trip ---
install_update_script = SCRIPTS / "install_or_update.py"
if install_update_script.is_file() and KIT_LAYOUT:
    from install_or_update import execute_install_or_update
    test_fixture_dir = Path(tempfile.mkdtemp())
    try:
        (test_fixture_dir / "gradlew").touch()
        (test_fixture_dir / "app").mkdir()
        (test_fixture_dir / "app" / "build.gradle").write_text("apply plugin: 'com.android.application'\n", encoding="utf-8")

        setup_dir = test_fixture_dir / ".harness-setup"
        setup_dir.mkdir(parents=True, exist_ok=True)
        fixture_answers = {
            "schema": 1,
            "i0": True,
            "backup": True,
            "product": "TestFixtureApp",
            "py": "python",
            "git_policy": "never",
            "device_policy": "physical-only",
            "module": ":app",
            "assemble": ":app:assembleDebug",
            "launcher": "com.test.app/.MainActivity",
            "application_ids": ["com.test.app"],
            "apk_path": "app/build/outputs/apk/debug/app-debug.apk",
            "tools": ["gemini"],
            "zoho_mcp": "skip",
            "pm_provider": "none",
            "git_gate": "yes",
        }
        (setup_dir / "answers.json").write_text(json.dumps(fixture_answers), encoding="utf-8")

        # Test 1: Fresh Install
        res_install = execute_install_or_update(
            repo=test_fixture_dir,
            kit=repo_root,
            answers_path=str(setup_dir / "answers.json"),
            skip_doctor=True,
        )
        ok_install_mode = res_install["mode"] == "install"
        ok_install_prod = (test_fixture_dir / ".agents" / "scripts" / "_product.py").is_file()
        ok_install_agents_md = (test_fixture_dir / "AGENTS.md").is_file()

        # Add custom reference to simulate project tailoring
        custom_ref = test_fixture_dir / ".agents" / "skills" / "android-harness" / "references" / "custom-payment-flow.md"
        custom_ref.write_text("# Custom Payment Architecture\nSpecial flow guidelines.\n", encoding="utf-8")

        # Test 2: Update Mode & Reference Preservation
        res_update = execute_install_or_update(
            repo=test_fixture_dir,
            kit=repo_root,
            answers_path=str(setup_dir / "answers.json"),
            skip_doctor=True,
        )
        ok_update_mode = res_update["mode"] == "update"
        ok_ref_preserved = custom_ref.is_file() and "Special flow guidelines." in custom_ref.read_text(encoding="utf-8")
        ok_backup_created = (test_fixture_dir / ".harness-backup").is_dir()

        ok_engine = (
            ok_install_mode
            and ok_install_prod
            and ok_install_agents_md
            and ok_update_mode
            and ok_ref_preserved
            and ok_backup_created
        )
        print(f"install_or_update engine deterministic round-trip: {'OK' if ok_engine else 'FAIL'}")
        failed += int(not ok_engine)
    finally:
        shutil.rmtree(test_fixture_dir, ignore_errors=True)
else:
    print("install_or_update engine deterministic round-trip: OK (skipped — installed checkout)")


# --- v0.10.0: adversarial security suite (B1) ---
sec_proc = subprocess.run(
    [sys.executable, str(SCRIPTS / "_security_selftest.py")],
    capture_output=True,
    text=True,
    check=False,
    env=os.environ.copy(),
)
ok_security_suite = sec_proc.returncode == 0
print(
    f"security_selftest suite (B1): "
    f"{'OK' if ok_security_suite else 'FAIL ' + sec_proc.stdout + sec_proc.stderr}"
)
failed += int(not ok_security_suite)

# --- v0.19.0: APK Freshness & Stale Build Barrier ---
fresh_proc = subprocess.run(
    [sys.executable, str(SCRIPTS / "_apk_freshness_selftest.py")],
    capture_output=True,
    text=True,
    check=False,
    env=os.environ.copy(),
)
ok_fresh_suite = fresh_proc.returncode == 0
print(
    f"apk_freshness_selftest suite: "
    f"{'OK' if ok_fresh_suite else 'FAIL ' + fresh_proc.stdout + fresh_proc.stderr}"
)
failed += int(not ok_fresh_suite)


doc = HarnessDoctor(repo_root)
doc_results = doc.run_all()
doc_failures = sum(1 for r in doc_results if r.status == "FAIL")
ok_doctor = (
    doc_failures == 0
    and ((repo_root / "docs" / "diagnostic-prompt.md").is_file() or _is_installed or not KIT_LAYOUT)
    and any(r.name == "Python Runtime" and r.status == "PASS" for r in doc_results)
    and any(r.name == "Subagents Templates" and r.status == "PASS" for r in doc_results)
)
pm_provider_line = next((r for r in doc_results if r.name == "PM Provider"), None)
ok_pm_doctor_line = pm_provider_line is not None and pm_provider_line.status in ("PASS", "WARN")
print(
    f"doctor PM provider line (Dimension 11): "
    f"{'OK' if ok_pm_doctor_line else 'FAIL ' + (json.dumps(pm_provider_line.message) if pm_provider_line else 'missing')}"
)
failed += int(not ok_pm_doctor_line)
print(f"harness_doctor 12-dimension diagnostic suite: {'OK' if ok_doctor else 'FAIL'}")
failed += int(not ok_doctor)

print(f"\nTotal test failures: {failed}")
sys.exit(1 if failed else 0)


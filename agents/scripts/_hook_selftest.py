"""Local self-test for this app multi-agent hooks. Does not execute shell commands."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
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
    prompt_str = f"{prompt_prefix}{PACKAGE} Findings or PASS." if prompt_prefix else "Perform deep analysis."
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
    ("installer_adapters_allowed", cmd("python .agents/scripts/install_tool_adapters.py --product Rashaqa --assemble :app:assembleDebug --tools gemini"), "allow"),
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
    ("emu", cmd("android emulator start pixel"), "deny"),
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
            "HARNESS_BUG_FINGERPRINT=quality-first-bug-review-v1\nYou are a different prompt.",
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
ok = pkg_proc.stdout.strip().startswith("HARNESS_REVIEW_PACKAGE=")
pkg_path = Path(pkg_proc.stdout.strip().split("=", 1)[-1].strip()) if ok else None
ok = ok and pkg_path is not None and pkg_path.is_file()
print(f"review_package writes file: {'OK' if ok else 'FAIL ' + pkg_proc.stdout + pkg_proc.stderr}")
failed += int(not ok)

ledger_path = STATE.parent / "review_ledger.json"
try:
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ok_ledger = (
        isinstance(ledger, dict)
        and "tree_fingerprint" in ledger
        and "sha256" in ledger
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
# This check only applies AFTER install (when answers.json exists).
needles = (
    "com.example.app",
    "com.example",
)
ok_left = True
if _is_installed:
    for path in SCRIPTS.parent.rglob("*"):
        if not path.is_file() or path.suffix == ".pyc":
            continue
        if "__pycache__" in path.parts or "state" in path.parts:
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for needle in needles:
            if needle in text:
                ok_left = False
                print(f"kit placeholder {needle!r} in {path.relative_to(SCRIPTS.parent)}")
    print(f"kit placeholder grep agents/: {'OK' if ok_left else 'FAIL'}")
else:
    print("kit placeholder grep agents/: OK (skipped — raw kit, not an installed checkout)")
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
ok_q = "i16" in q_ids and "i17" in q_ids and "i18" in q_ids
print(f"wizard includes I.16, I.17, I.18: {'OK' if ok_q else 'FAIL'}")
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
        "i17": "en",
        "i18": "en_titles_ar_comments",
    },
    facts,
)
ok_norm = (
    norm.get("zoho_mcp") == "enable"
    and norm.get("chat_language") == "en"
    and norm.get("zoho_language") == "en_titles_ar_comments"
)
print(f"wizard records zoho_mcp and language preferences: {'OK' if ok_norm else 'FAIL'}")
failed += int(not ok_norm)

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

ok_semver = parse_semver("v0.1.0") == (0, 1, 0) and parse_semver("0.8.0") > (0, 7, 0) and get_current_version() == "0.8.0"
print(f"check_kit_update semver and version: {'OK' if ok_semver else 'FAIL'}")
failed += int(not ok_semver)

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

ok_test_specialist_files = (
    (agents_root / "subagents" / "test-quality-reviewer-agent.json").is_file()
    and (agents_root / "skills" / "android-harness" / "references" / "test-quality-guidelines.md").is_file()
    and (agents_root / "workflows" / "test-quality-audit.md").is_file()
)
print(f"test-quality-reviewer-agent files and references: {'OK' if ok_test_specialist_files else 'FAIL'}")
failed += int(not ok_test_specialist_files)

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

# --- v0.7.0: Wizard flavor discovery + I.19 wiring ---
from setup_wizard import discover_flavors  # noqa: E402
from setup_wizard import normalize as wiz_normalize  # noqa: E402
from setup_wizard import questions_payload as qp_v7  # noqa: E402

flavor_repo = Path(tempfile.mkdtemp())
flavor_app_dir = flavor_repo / "app"
flavor_app_dir.mkdir(parents=True)
(flavor_repo / "gradlew.bat").write_text("rem", encoding="utf-8")
(flavor_app_dir / "build.gradle.kts").write_text(
    'android {\n'
    '    flavorDimensions += "env"\n'
    '    productFlavors {\n'
    '        create("staging") { dimension = "env" }\n'
    '        create("prodClient") { dimension = "env" }\n'
    '        isDefault = true\n'
    '    }\n'
    '}\n',
    encoding="utf-8",
)
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

mm_repo = Path(tempfile.mkdtemp())
for mod in ("app/src/main/java", "core/data/src/main/kotlin"):
    (mm_repo / mod).mkdir(parents=True, exist_ok=True)
(mm_repo / "app/src/main/java/A.kt").write_text("class A\n", encoding="utf-8")
(mm_repo / "core/data/src/main/kotlin/B.kt").write_text("class B\n", encoding="utf-8")
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
     "i15": "yes", "i14": ["cursor"], "i16": "enable", "i17": "en", "i18": "all_en",
     "i20": "github_projects"},
    facts_v8,
)
ok_i20_norm = norm_v8.get("pm_provider") == "github_projects"
norm_v8_default = wiz_normalize(
    {"i0": "yes", "i1": "discovered", "i3": "never", "i4": "allow", "i10": "confirm",
     "i15": "yes", "i14": ["cursor"], "i16": "skip", "i17": "en", "i18": "all_en"},
    facts_v8,
)
ok_i20_backward = norm_v8_default.get("pm_provider") == "zoho_sprints"
bad_i20_raised = False
try:
    wiz_normalize(
        {"i0": "yes", "i1": "discovered", "i3": "never", "i4": "allow", "i10": "confirm",
         "i15": "yes", "i14": ["cursor"], "i16": "skip", "i17": "en", "i18": "all_en",
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

STATE.write_text(
    json.dumps({"c-ttl": {"pending_reviews": True, "pending_since": time.time() - 100000}}),
    encoding="utf-8",
)
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
    adapt_args = parse_args([
        "--repo", str(tmp_adapt_dir),
        "--product", "TestApp",
        "--py", "python",
        "--assemble", ":app:assembleDebug",
        "--tools", "claude,copilot,codex",
        "--git-gate",
        "--cc-hooks",
    ])
    install_adapters(adapt_args)
    ok_claude_pack = (tmp_adapt_dir / ".claude" / "commands" / "deliver.md").is_file()
    ok_copilot_pack = (tmp_adapt_dir / ".github" / "prompts" / "deliver.prompt.md").is_file()
    ok_codex_pack = (tmp_adapt_dir / ".codex" / "prompts" / "deliver.md").is_file()
    ok_git_gate_hook = (tmp_adapt_dir / ".githooks" / "pre-commit").is_file()
    ok_cc_settings = (tmp_adapt_dir / ".claude" / "settings.json").is_file()

    # Test pruning
    adapt_args_prune = parse_args([
        "--repo", str(tmp_adapt_dir),
        "--product", "TestApp",
        "--py", "python",
        "--assemble", ":app:assembleDebug",
        "--tools", "claude",
    ])
    install_adapters(adapt_args_prune)
    ok_prune_codex = not (tmp_adapt_dir / ".codex" / "prompts" / "deliver.md").is_file()
    ok_keep_claude = (tmp_adapt_dir / ".claude" / "commands" / "deliver.md").is_file()

    ok_adapter_lifecycle = (
        ok_cp_tmpls
        and ok_claude_pack
        and ok_copilot_pack
        and ok_codex_pack
        and ok_git_gate_hook
        and ok_cc_settings
        and ok_prune_codex
        and ok_keep_claude
    )
    print(f"install_tool_adapters command_packs, git_gate & cc_hooks: {'OK' if ok_adapter_lifecycle else 'FAIL'}")
    failed += int(not ok_adapter_lifecycle)
finally:
    import shutil
    shutil.rmtree(tmp_adapt_dir, ignore_errors=True)

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
    ok_cli_cmds = cli_cmds == {"init", "update", "doctor", "preflight", "selftest", "version"}
    ok_cli_kit = bool(cli_resolve_kit(str(repo_root)))
    proc_cli_ver = subprocess.run([sys.executable, str(cli_file), "version"], capture_output=True, text=True)
    ok_cli_ver = proc_cli_ver.returncode == 0 and bool(proc_cli_ver.stdout.strip())
    ok_cli = ok_cli_cmds and ok_cli_kit and ok_cli_ver
    print(f"harness_cli dispatch & subcommands: {'OK' if ok_cli else 'FAIL'}")
    failed += int(not ok_cli)
else:
    print("harness_cli dispatch & subcommands: OK (skipped — installed checkout)")


doc = HarnessDoctor(repo_root)
doc_results = doc.run_all()
doc_failures = sum(1 for r in doc_results if r.status == "FAIL")
ok_doctor = (
    doc_failures == 0
    and ((repo_root / "docs" / "diagnostic-prompt.md").is_file() or _is_installed)
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
sys.exit(failed)



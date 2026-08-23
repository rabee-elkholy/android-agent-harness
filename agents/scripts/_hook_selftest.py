"""Local self-test for this app multi-agent hooks. Does not execute shell commands."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
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


cases = [
    ("empty", {}, "allow"),
    ("monkey", cmd("adb -s DEV shell monkey -p com.example.app 1"), "deny"),
    ("git_mutation", cmd("git commit -m x"), "deny"),
    ("git_c_commit", cmd("git -C E:\\AndroidProjects\\SomeApp commit -m x"), "deny"),
    ("git_subshell_powershell", cmd('powershell -Command "git commit -m x"'), "deny"),
    ("git_exe", cmd("git.exe push origin main"), "deny"),
    ("git_usr_bin", cmd("/usr/bin/git checkout master"), "deny"),
    ("git_chained", cmd("echo hello && git reset --hard"), "deny"),
    ("git_status", cmd("git status --short --branch"), "allow"),
    ("sched_waiting_subagents", sched("Waiting for 5 review subagents"), "deny"),
    ("sched_user_reminder", sched("Remind developer about coffee in 10 mins"), "allow"),
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

kit_mcp = json.loads((SCRIPTS.parent / "mcp_config.json").read_text(encoding="utf-8"))
ok_kit_mcp = kit_mcp == {"mcpServers": {}}
print(f"kit mcp_config empty: {'OK' if ok_kit_mcp else 'FAIL'}")
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
_repo_root = SCRIPTS.parent.parent
_is_installed = (_repo_root / ".harness-setup" / "answers.json").is_file()
ok_left = True
if _is_installed:
    for path in SCRIPTS.parent.rglob("*"):
        if not path.is_file() or path.suffix == ".pyc":
            continue
        if "__pycache__" in path.parts or "state" in path.parts:
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
ok_q = "i16" in q_ids
print(f"wizard includes I.16: {'OK' if ok_q else 'FAIL'}")
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
    },
    facts,
)
ok_norm = norm.get("zoho_mcp") == "enable"
print(f"wizard records zoho_mcp: {'OK' if ok_norm else 'FAIL'}")
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

ok_semver = parse_semver("v0.1.0") == (0, 1, 0) and parse_semver("0.2.5") > (0, 2, 3) and get_current_version() == "0.2.3"
print(f"check_kit_update semver and version: {'OK' if ok_semver else 'FAIL'}")
failed += int(not ok_semver)

print(f"\nTotal test failures: {failed}")
sys.exit(failed)


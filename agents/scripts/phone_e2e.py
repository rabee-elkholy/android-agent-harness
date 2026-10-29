"""Live, agent-driven phone E2E session on the verified device; no plan revision, no delivery PASS.

The developer chooses "Run phone E2E" at device sign-off. The agent then drives the already
installed build on the phone bound to the current install/launch evidence, scenario by scenario:
observe the screen, act (tap/type/key/swipe/restart), observe again, record each scenario result.
When a scenario needs a human (Google account, OTP, payment, physical action), the agent records
`need-developer`, asks the developer with ask_question, then `resume`s and continues.

Boundaries: the task, approval, frozen run, reviews and budgets are never touched. No uninstall,
data clear, permission grant, downgrade, network/system setting change or purchase is available.
The report is advisory; the final sign-off (and sensitive approval) stays with the developer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vnext_common import ValidationError, atomic_write_json, read_json, state_root, utc_now, validate_id  # noqa: E402

STATUSES = ("PASS", "FAIL", "BLOCKED", "SKIPPED")
KEYS = {"BACK": "4", "ENTER": "66", "DEL": "67", "TAB": "61"}
SAFE_TEXT = re.compile(r"[A-Za-z0-9 @._+\-]{1,256}")
MAX_NODES = 90
MAX_SCENARIOS = 40
DEVICE_HUB_PILL = "[Android Device Hub](sidecar://android-cli-plugin/device-hub/)"


def adb_executable() -> str:
    found = shutil.which("adb")
    if found:
        return found
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = os.environ.get(env)
        if root:
            candidate = Path(root) / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
            if candidate.is_file():
                return str(candidate)
    raise ValidationError("ENV_BLOCKED: adb is unavailable on PATH/ANDROID_HOME; connect the SDK platform-tools.")


def _active_task(repo: Path, explicit: str | None) -> str:
    if explicit:
        return validate_id(explicit, "task id")
    path = state_root(repo) / "active-task.json"
    if path.is_file():
        task_id = str(read_json(path).get("task_id") or "")
        if task_id:
            return validate_id(task_id, "task id")
    raise ValidationError("no active task; pass --task-id")


def session_dir(repo: Path, task_id: str, run_id: str) -> Path:
    return state_root(repo) / "tasks" / task_id / "e2e" / validate_id(run_id, "run id")


def _load_session(repo: Path, task_id: str) -> tuple[dict, Path]:
    from workflow import _load_plan, task_dir
    plan = _load_plan(repo, task_id)
    if plan.get("status") != "VERIFYING":
        raise ValidationError(f"phone E2E requires a VERIFYING task (task is {plan.get('status')})")
    current = read_json(task_dir(repo, task_id) / "current-run.json")
    directory = session_dir(repo, task_id, str(current.get("run_id") or ""))
    path = directory / "session.json"
    if not path.is_file():
        raise ValidationError(f"no phone E2E session for the current run; run: python .agents/harness.py e2e start --task-id {task_id}")
    session = read_json(path)
    if session.get("run_id") != current.get("run_id") or session.get("delivery_snapshot_sha256") != current.get("delivery_snapshot_sha256"):
        raise ValidationError("the verification run changed after this E2E session started; start a new session")
    return session, path


def _save(path: Path, session: dict) -> None:
    session["updated_at"] = utc_now()
    atomic_write_json(path, session)


def _bound_device(repo: Path, task_id: str) -> tuple[dict, dict, str, dict]:
    """Fresh run + valid install/launch evidence + the one connected phone that matches it."""
    from verification_contract import active_context
    from final_verifier import _validate_artifact
    plan, current, store = active_context(repo, task_id, require_fresh=True)
    version = (state_root(repo).parent / "VERSION").read_text(encoding="utf-8").strip()
    records = []
    for name in ("device_install", "device_launch"):
        record, error = _validate_artifact(store, current["delivery_snapshot_sha256"], current["change_set_sha256"],
                                           current["run_id"], name, version)
        if error:
            raise ValidationError(f"phone E2E needs the current install/start first ({name}: {error}); run: python .agents/harness.py device install-start")
        records.append(record.get("evidence") or {})
    install, launch = records
    serial_sha = str(launch.get("serial_sha256") or install.get("serial_sha256") or "")
    from _repo_files import matching_adb_serials
    phones = [s for s in matching_adb_serials(policy="allow") if hashlib.sha256(s.encode()).hexdigest() == serial_sha]
    if len(phones) != 1:
        raise ValidationError("ENV_BLOCKED: the phone the build was installed on is not connected over adb. "
                              "Ask the developer to reconnect it (USB debugging on), then retry; no other device is used.")
    package = str(install.get("application_id") or launch.get("application_id") or "")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", package):
        raise ValidationError("install evidence has no valid application id")
    return plan, current, phones[0], {"application_id": package, "target_user": str(install.get("target_user") or "0")}


class Phone:
    def __init__(self, serial: str, package: str, user: str = "0"):
        if not re.fullmatch(r"[A-Za-z0-9_.:\-]{1,128}", serial):
            raise ValidationError("invalid device serial")
        self.adb = adb_executable()
        self.serial, self.package, self.user = serial, package, str(int(user))

    def call(self, args: list[str], timeout: float = 15, binary: bool = False):
        try:
            result = subprocess.run([self.adb, "-s", self.serial, *args], capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ValidationError("ENV_BLOCKED: the phone did not answer in time (screen locked or adb stalled?)") from exc
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()[:200]
            raise ValidationError(f"ENV_BLOCKED: adb command failed on the bound phone: {detail or 'no detail'}")
        return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")

    def foreground(self) -> str:
        out = self.call(["shell", "dumpsys", "activity", "activities"], 10)
        for line in out.splitlines():
            if re.search(r"topResumedActivity|mResumedActivity", line):
                match = re.search(r"([A-Za-z0-9_.]+/[A-Za-z0-9_.$]+)", line)
                if match:
                    return match.group(1)
        return ""

    def nodes(self):
        from _adb_core import parse_ui_hierarchy
        raw = self.call(["exec-out", "uiautomator", "dump", "/dev/tty"], 20)
        nodes = parse_ui_hierarchy(raw)
        if not nodes:
            raise ValidationError("ENV_BLOCKED: UI hierarchy unavailable (screen off/locked or secure window); "
                                  "ask the developer to unlock the phone and keep the screen on")
        return nodes

    def screen_size(self) -> tuple[int, int]:
        match = re.search(r"(\d+)x(\d+)", self.call(["shell", "wm", "size"], 10).splitlines()[-1])
        return (int(match.group(1)), int(match.group(2))) if match else (1080, 2340)


def _flatten(nodes) -> list:
    flat = []

    def walk(items):
        for node in items:
            flat.append(node)
            walk(node.children)
    walk(nodes)
    return flat


def _meaningful(nodes) -> list[dict]:
    out = []
    for node in _flatten(nodes):
        if node.width <= 0 or node.height <= 0:
            continue
        if not (node.text or node.content_desc or node.clickable or node.scrollable or node.checkable or node.focused):
            continue
        item = {"i": len(out), "text": node.text[:80], "id": node.resource_id.split("/")[-1] if node.resource_id else "",
                "desc": node.content_desc[:80], "cls": node.class_name.rsplit(".", 1)[-1], "center": list(node.center)}
        flags = [name for name, value in (("click", node.clickable), ("scroll", node.scrollable), ("checked", node.checked),
                                          ("focused", node.focused), ("disabled", not node.enabled), ("password", node.password)) if value]
        if flags:
            item["flags"] = flags
        if node.package and node.package != "":
            item["pkg"] = node.package
        out.append(item)
        if len(out) >= MAX_NODES:
            break
    return out


def _select(phone: Phone, args) -> tuple[int, int, dict]:
    if args.x is not None and args.y is not None:
        return args.x, args.y, {"x": args.x, "y": args.y}
    from _adb_core import find_nodes
    nodes = phone.nodes()
    query = {}
    if args.resource_id:
        query["resource_id"] = args.resource_id
    if args.text:
        query["text"] = args.text
    if args.desc:
        query["content_desc"] = args.desc
    if not query:
        raise ValidationError("tap needs --resource-id, --text, --desc, or --x/--y")
    found = find_nodes(nodes, exact=True, **query) or find_nodes(nodes, exact=False, **query)
    found = [n for n in found if n.width > 0 and n.height > 0]
    if not found:
        raise ValidationError(f"TARGET_NOT_FOUND: no visible element matches {query}; run `e2e observe` and pick another selector")
    if len(found) > 1 and args.index is None:
        raise ValidationError(f"AMBIGUOUS: {len(found)} elements match {query}; add --index 0..{len(found) - 1}")
    node = found[args.index or 0] if (args.index or 0) < len(found) else found[0]
    if not node.enabled:
        raise ValidationError(f"TARGET_DISABLED: {query} is visible but disabled")
    return node.center[0], node.center[1], {"text": node.text[:60], "id": node.resource_id, "desc": node.content_desc[:60]}


def _log(session: dict, action: str, detail: dict) -> None:
    session.setdefault("actions", []).append({"at": utc_now(), "action": action, **detail})
    session["actions"] = session["actions"][-400:]


def _scenarios(repo: Path, task_id: str, plan: dict, current: dict) -> list[dict]:
    lines: list[str] = []
    strategy = str(plan.get("device_strategy") or "").strip()
    if strategy:
        lines += [part.strip(" -") for part in re.split(r"(?:^|\s)(?=\d+[.)]\s)|\n|;", strategy) if part.strip(" -")]
    for journey in (plan.get("verification_contract") or {}).get("journeys") or []:
        lines.append(str(journey.get("purpose") or journey.get("id")))
    walkthrough = state_root(repo) / "tasks" / task_id / "walkthrough.md"
    if walkthrough.is_file():
        for line in walkthrough.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if re.match(r"^(\d+\.|-)\s+", stripped) and "Launched Activity" not in stripped and "Requested Outcome" not in stripped:
                lines.append(re.sub(r"^(\d+\.|-)\s+", "", stripped))
    for surface, steps in (current.get("verification_recipes") or {}).items():
        for step in steps or []:
            lines.append(f"[{surface}] {step}")
    seen, out = set(), []
    for line in lines:
        key = line.lower()
        if line and key not in seen:
            seen.add(key)
            out.append({"id": f"S{len(out) + 1}", "title": line[:300], "status": "PENDING"})
        if len(out) >= MAX_SCENARIOS:
            break
    return out


def _tools(repo: Path) -> dict:
    android = shutil.which("android")
    tools = {"adb": True, "android_cli": bool(android), "screenshots": True}
    try:
        from review_sources import resolve_review_host
        host = resolve_review_host(repo)
    except Exception:
        host = ""
    if host == "antigravity" and android:
        tools["device_hub"] = DEVICE_HUB_PILL
    return tools


PROTOCOL = (
    "Drive the phone yourself; do not revise the plan and do not rerun gates or reviewers. For EVERY scenario: "
    "(1) `e2e observe` (compact element list; add --screenshot and view the PNG when layout/visuals matter); "
    "(2) act with `e2e tap --text|--resource-id|--desc|--x --y`, `e2e type --value \"...\"` (optionally with a target selector), `e2e key --name BACK|ENTER|DEL|TAB`, "
    "`e2e swipe --direction up|down|left|right`, `e2e wait --seconds N|--until-text T`, `e2e restart` (force-stop + relaunch, data kept); "
    "(3) observe again and compare with the expected result; (4) record it: `e2e step --scenario <S#> --status PASS|FAIL|BLOCKED|SKIPPED "
    "--observed \"<what the screen showed>\"`. Add scenarios you discover from the changed code with `e2e add --title \"...\"` "
    "(happy path, back navigation, invalid input, empty state, rotation-free re-entry, process restart). "
    "When a scenario needs the developer (Google/Facebook sign-in, OTP, payment, turning Wi-Fi off, a physical action, "
    "an account state you cannot create), run `e2e need-developer --scenario <S#> --ask \"<exact action>\"`, ask with "
    "ask_question in the same turn, wait, then `e2e resume --scenario <S#>` and continue. Never grant permissions via adb, "
    "never clear data/uninstall, never buy. If a command returns ENV_BLOCKED, ask the developer to fix that (unlock, reconnect) "
    "and retry once. When all scenarios have a result, run `e2e finish`."
)


def cmd_start(repo: Path, args) -> dict:
    task_id = _active_task(repo, args.task_id)
    plan, current, serial, app = _bound_device(repo, task_id)
    directory = session_dir(repo, task_id, current["run_id"])
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "session.json"
    existing = read_json(path) if path.is_file() else None
    if existing and existing.get("run_id") == current["run_id"] and existing.get("state") != "FINISHED" and not args.restart:
        session = existing
        session["state"] = "RUNNING"
    else:
        session = {
            "schema_version": 1, "task_id": task_id, "run_id": current["run_id"],
            "delivery_snapshot_sha256": current["delivery_snapshot_sha256"], "plan_sha256": plan.get("plan_sha256"),
            "serial_sha256": hashlib.sha256(serial.encode()).hexdigest(), "application_id": app["application_id"],
            "target_user": app["target_user"], "state": "RUNNING", "started_at": utc_now(),
            "scenarios": _scenarios(repo, task_id, plan, current), "pending_developer": None, "actions": [],
            "delivery_evidence": False,
        }
    phone = Phone(serial, app["application_id"], app["target_user"])
    session["foreground"] = phone.foreground()
    _save(path, session)
    return {"status": "RUNNING", "task_id": task_id, "application_id": app["application_id"],
            "foreground": session["foreground"], "tools": _tools(repo), "scenarios": session["scenarios"],
            "session": str(path), "protocol": PROTOCOL,
            "next": f"python .agents/harness.py e2e observe --task-id {task_id}"}


def _phone_for(repo: Path, args) -> tuple[dict, Path, Phone, str]:
    task_id = _active_task(repo, args.task_id)
    try:
        session, path = _load_session(repo, task_id)
    except ValidationError as exc:
        if "no phone E2E session" not in str(exc) or args.action not in {"observe", "screenshot"}:
            raise
        # Screen inspection during verification needs no ceremony: bind the verified phone on demand.
        cmd_start(repo, args)
        session, path = _load_session(repo, task_id)
    if session.get("state") == "FINISHED" and args.action not in {"observe", "screenshot"}:
        raise ValidationError(f"E2E session already finished; restart with: python .agents/harness.py e2e start --task-id {task_id} --restart")
    if session.get("pending_developer") and args.action not in {"observe", "resume"}:
        pending = session["pending_developer"]
        raise ValidationError(f"WAITING_FOR_DEVELOPER on {pending['scenario']}: {pending['ask']}. Ask with ask_question, then run e2e resume.")
    from _repo_files import matching_adb_serials
    phones = [s for s in matching_adb_serials(policy="allow") if hashlib.sha256(s.encode()).hexdigest() == session["serial_sha256"]]
    if len(phones) != 1:
        raise ValidationError("ENV_BLOCKED: the bound phone disconnected; ask the developer to reconnect it, then retry.")
    return session, path, Phone(phones[0], session["application_id"], session.get("target_user") or "0"), task_id


def cmd_observe(repo: Path, args) -> dict:
    session, path, phone, task_id = _phone_for(repo, args)
    foreground = phone.foreground()
    elements = _meaningful(phone.nodes())
    result = {"foreground": foreground, "in_app": foreground.startswith(session["application_id"] + "/"), "elements": elements}
    if args.screenshot:
        result["screenshot"] = _screenshot(phone, path.parent, len(session.get("actions") or []))
    _log(session, "observe", {"foreground": foreground, "elements": len(elements)})
    _save(path, session)
    return result


def _screenshot(phone: Phone, directory: Path, index: int) -> str:
    shots = directory / "screens"
    shots.mkdir(parents=True, exist_ok=True)
    target = shots / f"{index:04d}-{int(time.time())}.png"
    data = phone.call(["exec-out", "screencap", "-p"], 20, binary=True)
    if not data.startswith(b"\x89PNG"):
        raise ValidationError("ENV_BLOCKED: screenshot unavailable (secure window or locked screen)")
    target.write_bytes(data)
    pngs = sorted(shots.glob("*.png"))
    for old in pngs[:-60]:
        old.unlink(missing_ok=True)
    return str(target)


def cmd_tap(repo: Path, args) -> dict:
    session, path, phone, _ = _phone_for(repo, args)
    x, y, target = _select(phone, args)
    phone.call(["shell", "input", "tap", str(x), str(y)])
    time.sleep(0.6)
    _log(session, "tap", {"target": target})
    _save(path, session)
    return {"status": "DONE", "tapped": target, "foreground": phone.foreground()}


def cmd_type(repo: Path, args) -> dict:
    session, path, phone, _ = _phone_for(repo, args)
    value = str(args.value or "")
    if not SAFE_TEXT.fullmatch(value):
        raise ValidationError("type accepts 1..256 characters of [A-Za-z0-9 @._+-]; ask the developer to type other text (e.g. Arabic) on the phone")
    if args.resource_id or args.text or args.desc or args.x is not None:
        x, y, _ = _select(phone, args)
        phone.call(["shell", "input", "tap", str(x), str(y)])
        time.sleep(0.4)
    phone.call(["shell", "input", "text", value.replace(" ", "%s")])
    _log(session, "type", {"length": len(value)})
    _save(path, session)
    return {"status": "DONE", "typed_length": len(value)}


def cmd_key(repo: Path, args) -> dict:
    session, path, phone, _ = _phone_for(repo, args)
    phone.call(["shell", "input", "keyevent", KEYS[args.name]])
    time.sleep(0.5)
    _log(session, "key", {"name": args.name})
    _save(path, session)
    return {"status": "DONE", "key": args.name, "foreground": phone.foreground()}


def cmd_swipe(repo: Path, args) -> dict:
    session, path, phone, _ = _phone_for(repo, args)
    width, height = phone.screen_size()
    cx, cy = width // 2, height // 2
    dx, dy = {"up": (0, -height // 3), "down": (0, height // 3), "left": (-width // 3, 0), "right": (width // 3, 0)}[args.direction]
    phone.call(["shell", "input", "swipe", str(cx - dx // 2), str(cy - dy // 2), str(cx + dx // 2), str(cy + dy // 2), "300"])
    time.sleep(0.5)
    _log(session, "swipe", {"direction": args.direction})
    _save(path, session)
    return {"status": "DONE", "direction": args.direction}


def cmd_wait(repo: Path, args) -> dict:
    session, path, phone, _ = _phone_for(repo, args)
    seconds = max(0.2, min(float(args.seconds or 2), 20))
    if not args.until_text and not args.until_id:
        time.sleep(seconds)
        return {"status": "DONE", "waited": seconds}
    from _adb_core import find_nodes
    deadline = time.monotonic() + seconds
    query = {"text": args.until_text} if args.until_text else {"resource_id": args.until_id}
    while True:
        if find_nodes(phone.nodes(), exact=False, **query):
            _log(session, "wait", {"found": True})
            _save(path, session)
            return {"status": "FOUND", "query": query}
        if time.monotonic() >= deadline:
            return {"status": "NOT_FOUND", "query": query, "waited": seconds}
        time.sleep(0.7)


def cmd_restart(repo: Path, args) -> dict:
    session, path, phone, _ = _phone_for(repo, args)
    phone.call(["shell", "am", "force-stop", "--user", phone.user, phone.package])
    phone.call(["shell", "monkey", "-p", phone.package, "-c", "android.intent.category.LAUNCHER", "1"], 20)
    time.sleep(2.5)
    _log(session, "restart", {})
    _save(path, session)
    return {"status": "DONE", "foreground": phone.foreground(), "note": "App data kept; process restarted."}


def cmd_screenshot(repo: Path, args) -> dict:
    session, path, phone, _ = _phone_for(repo, args)
    shot = _screenshot(phone, path.parent, len(session.get("actions") or []))
    _log(session, "screenshot", {"file": Path(shot).name})
    _save(path, session)
    return {"status": "DONE", "screenshot": shot, "hint": "Open the PNG with your file-view tool to judge the screen."}


def _scenario(session: dict, identity: str) -> dict:
    for item in session.get("scenarios") or []:
        if item["id"] == identity:
            return item
    raise ValidationError(f"unknown scenario {identity}; known: {', '.join(s['id'] for s in session.get('scenarios') or [])}")


def cmd_add(repo: Path, args) -> dict:
    task_id = _active_task(repo, args.task_id)
    session, path = _load_session(repo, task_id)
    if len(session["scenarios"]) >= MAX_SCENARIOS:
        raise ValidationError("scenario limit reached (40)")
    item = {"id": f"S{len(session['scenarios']) + 1}", "title": str(args.title)[:300], "status": "PENDING", "added_by_agent": True}
    session["scenarios"].append(item)
    _save(path, session)
    return {"status": "ADDED", "scenario": item}


def cmd_step(repo: Path, args) -> dict:
    task_id = _active_task(repo, args.task_id)
    session, path = _load_session(repo, task_id)
    item = _scenario(session, args.scenario)
    item.update(status=args.status, observed=str(args.observed or "")[:600], recorded_at=utc_now())
    if args.screenshot:
        item["screenshot"] = str(args.screenshot)[:400]
    _save(path, session)
    pending = [s["id"] for s in session["scenarios"] if s["status"] == "PENDING"]
    return {"status": "RECORDED", "scenario": item, "remaining": pending,
            "next": (f"continue with {pending[0]}" if pending else f"python .agents/harness.py e2e finish --task-id {task_id}")}


def cmd_need_developer(repo: Path, args) -> dict:
    task_id = _active_task(repo, args.task_id)
    session, path = _load_session(repo, task_id)
    item = _scenario(session, args.scenario)
    session["pending_developer"] = {"scenario": item["id"], "ask": str(args.ask)[:500], "at": utc_now()}
    item["status"] = "WAITING_DEVELOPER"
    _save(path, session)
    return {"status": "WAITING_FOR_DEVELOPER", "scenario": item["id"], "ask": args.ask,
            "next_action": "E2E_DEVELOPER_ASSIST",
            "instruction": ("In THIS turn invoke ask_question with the exact action (options: 'Done - continue' / "
                            "'Skip this scenario' / 'Stop E2E'). On 'Done' run e2e resume --scenario "
                            f"{item['id']} and retry the scenario; on 'Skip' run e2e step --status SKIPPED.")}


def cmd_resume(repo: Path, args) -> dict:
    task_id = _active_task(repo, args.task_id)
    session, path = _load_session(repo, task_id)
    pending = session.get("pending_developer")
    if not pending:
        return {"status": "RUNNING", "note": "nothing was waiting for the developer"}
    item = _scenario(session, args.scenario or pending["scenario"])
    if item["status"] == "WAITING_DEVELOPER":
        item["status"] = "PENDING"
    item.setdefault("developer_assists", []).append({"ask": pending["ask"], "resumed_at": utc_now()})
    session["pending_developer"] = None
    _save(path, session)
    return {"status": "RUNNING", "scenario": item["id"], "next": f"python .agents/harness.py e2e observe --task-id {task_id}"}


def cmd_status(repo: Path, args) -> dict:
    task_id = _active_task(repo, args.task_id)
    session, path = _load_session(repo, task_id)
    return {"state": session["state"], "pending_developer": session.get("pending_developer"),
            "scenarios": session["scenarios"], "session": str(path)}


def cmd_finish(repo: Path, args) -> dict:
    task_id = _active_task(repo, args.task_id)
    session, path = _load_session(repo, task_id)
    open_items = [s["id"] for s in session["scenarios"] if s["status"] in ("PENDING", "WAITING_DEVELOPER")]
    if open_items and not args.force:
        raise ValidationError(f"scenarios without a result: {', '.join(open_items)}; record them (SKIPPED is allowed) or pass --force")
    counts = {status: sum(1 for s in session["scenarios"] if s["status"] == status) for status in (*STATUSES, "PENDING", "WAITING_DEVELOPER")}
    verdict = "FAIL" if counts["FAIL"] else "BLOCKED" if (counts["BLOCKED"] or counts["PENDING"] or counts["WAITING_DEVELOPER"]) else "PASS"
    session.update(state="FINISHED", finished_at=utc_now(), verdict=verdict, counts=counts)
    rows = ["| # | Scenario | Result | Observed |", "|---|---|---|---|"]
    for s in session["scenarios"]:
        rows.append(f"| {s['id']} | {s['title'].replace('|', '/')} | {s['status']} | {str(s.get('observed') or '').replace('|', '/')} |")
    report = path.parent / "report.md"
    report.write_text("\n".join([f"# Phone E2E report — `{task_id}`", "", f"- **Verdict**: {verdict}",
                                 f"- **Run**: `{session['run_id']}`", "- Advisory: not delivery evidence; the developer signs off.", "",
                                 *rows, ""]), encoding="utf-8")
    session["report_sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
    _save(path, session)
    return {"status": verdict, "counts": counts, "report": str(report), "report_uri": report.resolve().as_uri(),
            "next_action": "DEVICE_SIGNOFF_REQUIRED",
            "instruction": ("In THIS turn show a compact result table (failed/blocked scenarios first, at most 8 rows, link the report) "
                            "and invoke ask_question for sign-off: 'PASS - approve (E2E report)' / 'FAIL - needs fixes'. "
                            "Record the answer with device signoff --source conversation --proof-reference \"<answer> (E2E "
                            f"{session['report_sha256'][:12]})\". A FAIL verdict should be presented as FAIL with the failing scenarios.")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "observe", "tap", "type", "key", "swipe", "wait", "restart", "screenshot",
                                           "add", "step", "need-developer", "resume", "status", "finish"))
    parser.add_argument("--repo", type=Path, default=Path(os.environ.get("HARNESS_REPO") or Path(__file__).resolve().parents[2]))
    parser.add_argument("--task-id")
    parser.add_argument("--restart", action="store_true", help="start: discard the unfinished session of this run")
    parser.add_argument("--screenshot", nargs="?", const="1", default=None)
    parser.add_argument("--resource-id")
    parser.add_argument("--text")
    parser.add_argument("--desc")
    parser.add_argument("--index", type=int)
    parser.add_argument("--x", type=int)
    parser.add_argument("--y", type=int)
    parser.add_argument("--value", help="type: text to enter")
    parser.add_argument("--name", choices=sorted(KEYS))
    parser.add_argument("--direction", choices=("up", "down", "left", "right"))
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--until-text")
    parser.add_argument("--until-id")
    parser.add_argument("--scenario")
    parser.add_argument("--status", choices=STATUSES)
    parser.add_argument("--observed")
    parser.add_argument("--title")
    parser.add_argument("--ask")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "type" and args.value is None and args.text and not (args.resource_id or args.desc):
        args.value, args.text = args.text, None
    required = {"key": "name", "swipe": "direction", "step": "scenario", "need-developer": "scenario", "add": "title"}
    if args.action in required and not getattr(args, required[args.action]):
        parser.error(f"{args.action} requires --{required[args.action]}")
    if args.action == "step" and not args.status:
        parser.error("step requires --status")
    if args.action == "need-developer" and not args.ask:
        parser.error("need-developer requires --ask")
    handlers = {"start": cmd_start, "observe": cmd_observe, "tap": cmd_tap, "type": cmd_type, "key": cmd_key,
                "swipe": cmd_swipe, "wait": cmd_wait, "restart": cmd_restart, "screenshot": cmd_screenshot, "add": cmd_add,
                "step": cmd_step, "need-developer": cmd_need_developer, "resume": cmd_resume, "status": cmd_status,
                "finish": cmd_finish}
    repo = args.repo.resolve()
    try:
        result = handlers[args.action](repo, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValidationError) as exc:
        message = str(exc)
        print(json.dumps({"status": "ENV_BLOCKED" if message.startswith("ENV_BLOCKED") else "ERROR", "reason": message,
                          "hint": "ENV_BLOCKED: ask the developer to fix the device condition with ask_question, then retry once."
                          if message.startswith("ENV_BLOCKED") else ""}, ensure_ascii=False))
        return 30 if message.startswith("ENV_BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())

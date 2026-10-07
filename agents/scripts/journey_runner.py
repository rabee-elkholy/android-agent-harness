"""Explicit bounded UI journey replay; no arbitrary device shell or implicit effects."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

from _vnext_common import ValidationError, canonical_sha256, validate_id

MAX_STEPS = 40
MAX_SECONDS = 120


def validate_journey(value):
    from verification_contract import strict_keys, text
    fields = {"schema_version", "id", "version", "purpose", "criteria", "module", "variant",
              "application_id", "prerequisites", "effects", "steps"}
    strict_keys(value, fields, fields, "journey")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 \
            or type(value["version"]) is not int or value["version"] < 1:
        raise ValidationError("unsupported journey schema or version")
    identity = validate_id(text(value["id"], "journey id", 48))
    if identity != value["id"]:
        raise ValidationError("noncanonical journey id")
    for key in ("purpose", "prerequisites", "module", "variant", "application_id"):
        text(value[key], key)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", value["application_id"]):
        raise ValidationError("invalid application id")
    if not isinstance(value["criteria"], list) or not 1 <= len(value["criteria"]) <= 32:
        raise ValidationError("journey requires bounded criterion IDs")
    for identity in value["criteria"]:
        if validate_id(identity) != identity:
            raise ValidationError("invalid journey criterion")
    if len(set(value["criteria"])) != len(value["criteria"]):
        raise ValidationError("duplicate journey criterion")
    if not isinstance(value["effects"], list) or any(x != "ui_interaction" for x in value["effects"]) \
            or len(value["effects"]) > 1:
        raise ValidationError("unsupported journey effects")
    steps = value["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValidationError("journey requires 1..40 steps")
    assertion, budget = False, 0.0
    for step in steps:
        strict_keys(step, {"action", "selector", "timeout", "secret_env"}, {"action"}, "journey step")
        action = step["action"]
        if not isinstance(action, str) or action not in {"tap", "back", "input", "wait_present", "assert_present", "assert_absent"}:
            raise ValidationError("unsupported journey action")
        timeout = step.get("timeout", 3)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0.1 <= timeout <= 10:
            raise ValidationError("invalid step timeout")
        budget += timeout
        if action == "back":
            if "selector" in step:
                raise ValidationError("back does not accept a selector")
        else:
            selector = step.get("selector")
            strict_keys(selector, {"resource_id", "content_desc", "text"}, set(), "selector")
            if len(selector) != 1:
                raise ValidationError("selector must have exactly one stable identity")
            for selected in selector.values():
                text(selected, "selector value", 300)
        if action == "input":
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", str(step.get("secret_env") or "")):
                raise ValidationError("input requires a local secret environment reference")
        elif "secret_env" in step:
            raise ValidationError("only input accepts secret_env")
        if action in {"tap", "back", "input"} and "ui_interaction" not in value["effects"]:
            raise ValidationError("UI interactions require an approved effect")
        assertion |= action in {"assert_present", "assert_absent"}
    if not assertion or budget > MAX_SECONDS:
        raise ValidationError("journey needs an assertion and a bounded execution budget")
    return value


def execute_journey(value, transport):
    validate_journey(value)  # All steps validate before the first action.
    results = []
    deadline = time.monotonic() + MAX_SECONDS
    observed_identity = {}
    checkpoint = []
    try:
        for index, step in enumerate(value["steps"]):
            if time.monotonic() >= deadline:
                raise TimeoutError("journey deadline")
            observed_identity = transport.check_identity()
            action = step["action"]
            timeout = min(float(step.get("timeout", 3)), deadline - time.monotonic())
            found = []
            # Only consecutive positive assertions share one observation. Actions,
            # waits and negative assertions always obtain a fresh hierarchy.
            if action == "assert_present" and not checkpoint and hasattr(transport, "observe_present"):
                selectors = []
                for following in value["steps"][index:]:
                    if following["action"] != "assert_present":
                        break
                    selectors.append(following["selector"])
                if len(selectors) > 1:
                    checkpoint = transport.observe_present(selectors, timeout)
            if action != "back":
                if action == "assert_present" and checkpoint:
                    found = checkpoint.pop(0)
                    # A missing selector retains its own bounded polling behavior.
                    if not found:
                        checkpoint = []
                        found = transport.find(step["selector"], timeout)
                else:
                    checkpoint = []
                    found = transport.find(step["selector"], timeout)
                if len(found) > 1:
                    results.append({"step": index + 1, "status": "FAIL", "reason": "ambiguous selector"})
                    return {"status": "FAIL", "steps": results, "device": observed_identity}
                expected = 0 if action == "assert_absent" else 1
                if len(found) != expected:
                    results.append({"step": index + 1, "status": "FAIL", "reason": "assertion or target missing"})
                    return {"status": "FAIL", "steps": results, "device": observed_identity}
            if action in {"tap", "back", "input"}:
                # Recheck foreground/device after polling, immediately before mutation.
                transport.check_identity()
                secret = os.environ.get(step.get("secret_env", ""), "") if action == "input" else ""
                if action == "input" and (not secret or len(secret) > 256 or not re.fullmatch(r"[A-Za-z0-9 @._+-]+", secret)):
                    raise OSError("input reference absent or unsupported characters")
                transport.act(action, found[0] if found else None, secret, timeout)
            results.append({"step": index + 1, "status": "PASS"})
        transport.check_identity()
        return {"status": "PASS", "steps": results, "device": observed_identity}
    except (OSError, TimeoutError, subprocess.TimeoutExpired):
        # Do not include raw subprocess output, selectors, or input values in diagnostics.
        results.append({"step": len(results) + 1, "status": "ENV", "reason": "device, hierarchy, input, or deadline unavailable"})
        return {"status": "ENV", "steps": results, "device": observed_identity}


class AdbTransport:
    def __init__(self, serial, package, expected_apk_hashes):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", serial):
            raise ValidationError("invalid selected device serial")
        self.serial, self.package = serial, package
        self.expected_apk_hashes = sorted(expected_apk_hashes)
        self.deadline = time.monotonic() + MAX_SECONDS
        self.observed = None
        self.step_deadline = None

    def verify_installed_artifact(self):
        paths = self.call(["shell", "pm", "path", "--user", "0", self.package], 5).splitlines()
        if not paths or len(paths) > 32:
            raise OSError("installed artifact unavailable")
        hashes = []
        for line in paths:
            if not line.startswith("package:"):
                raise OSError("installed package paths unavailable")
            path = line[len("package:"):].strip()
            if not re.fullmatch(r"/data/app/[A-Za-z0-9_./=+~-]+\.apk", path):
                raise OSError("unsupported installed APK path")
            output = self.call(["shell", "sha256sum", path], 5).split()
            if not output or not re.fullmatch(r"[0-9a-f]{64}", output[0]):
                raise OSError("installed artifact checksum unavailable")
            hashes.append(output[0])
        if sorted(hashes) != self.expected_apk_hashes:
            raise OSError("installed APK differs from approved artifact")

    def call(self, args, timeout=3):
        remaining = min(timeout, min(self.deadline, self.step_deadline or self.deadline) - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("device deadline")
        result = subprocess.run(["adb", "-s", self.serial, *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=remaining, check=False)
        if result.returncode:
            raise OSError("device command failed")
        return result.stdout

    def check_identity(self):
        # A successful shell command proves the selected serial is connected.
        # Read user and foreground together instead of three separate ADB launches.
        probe = self.call(["shell", "am get-current-user && dumpsys activity activities"])
        lines = probe.splitlines()
        if not lines or lines[0].strip() != "0":
            raise OSError("journey supports the verified primary Android user only")
        focus = "\n".join(lines[1:])
        focused = [line for line in focus.splitlines() if re.search("topResumedActivity", line, re.I)]
        if not focused:
            focused = [line for line in focus.splitlines() if "ResumedActivity" in line]
        if not focused or any(not re.search(r"\b" + re.escape(self.package) + r"/", line)
                              or not re.search(r"\bu0\b", line) for line in focused):
            raise OSError("target application is not foreground")
        # UI hierarchy operations use the selected serial; never switch devices or reconnect.
        if self.observed is None:
            self.verify_installed_artifact()
            self.observed = {"os": self.call(["shell", "getprop", "ro.build.version.sdk"]).strip(),
                             "locale": self.call(["shell", "getprop", "persist.sys.locale"]).strip()}
        return self.observed

    def observe_present(self, selectors, timeout):
        """Return positive assertion matches from one explicit screen checkpoint."""
        from _adb_core import parse_ui_hierarchy, find_nodes
        self.step_deadline = time.monotonic() + timeout
        try:
            self.check_identity()
            nodes = parse_ui_hierarchy(self.call(["exec-out", "uiautomator", "dump", "/dev/tty"], timeout))
            if not nodes:
                raise OSError("UI hierarchy unavailable")
            return [find_nodes(nodes, exact=True, **selector) for selector in selectors]
        finally:
            self.step_deadline = None

    def find(self, selector, timeout):
        from _adb_core import parse_ui_hierarchy, find_nodes
        deadline = time.monotonic() + timeout
        self.step_deadline = deadline
        matches = None
        try:
            while True:
                if matches is not None and time.monotonic() >= deadline:
                    return matches
                self.check_identity()
                raw = self.call(["exec-out", "uiautomator", "dump", "/dev/tty"], deadline - time.monotonic())
                nodes = parse_ui_hierarchy(raw)
                if not nodes:
                    raise OSError("UI hierarchy unavailable")
                matches = find_nodes(nodes, exact=True, **selector)
                if matches or time.monotonic() >= deadline:
                    return matches
                time.sleep(min(0.2, max(0, deadline - time.monotonic())))
        finally:
            self.step_deadline = None

    def act(self, action, node, value, timeout):
        if action == "back":
            self.call(["shell", "input", "keyevent", "4"], timeout)
        elif action == "tap":
            if not node.enabled or node.center[0] <= 0 or node.center[1] <= 0:
                raise OSError("target is not interactable")
            self.call(["shell", "input", "tap", str(node.center[0]), str(node.center[1])], timeout)
        else:
            if not node.enabled or not node.focused:
                raise OSError("input target must already be focused")
            self.call(["shell", "input", "text", shlex.quote(value.replace(" ", "%s"))], timeout)


def run_selected(repo, task_id, journey_id, serial, transport=None):
    from verification_contract import active_context
    from _vnext_common import read_json
    from workflow import task_dir, state_root
    from evidence_store import StateLock
    plan, current, store = active_context(repo, task_id, True)
    selected = next((j for j in (plan.get("verification_contract") or {}).get("journeys", []) if j["id"] == journey_id), None)
    if not selected:
        raise ValidationError("journey is not in the approved task")
    validate_journey(selected)
    from _product import ACTIVE_VARIANT, DEVICE_VERIFICATION_MODE
    if DEVICE_VERIFICATION_MODE == "disabled" or selected["variant"] != ACTIVE_VARIANT:
        raise ValidationError("journey incompatible with configured device policy or variant")
    if selected["module"] not in (plan.get("expected_modules") or []):
        raise ValidationError("journey module is outside approved task")
    policy = read_json(Path(current["policy"]))
    if not policy.get("device_required"):
        raise ValidationError("central policy did not select device verification")
    snapshot, run_id = current["delivery_snapshot_sha256"], current["run_id"]
    records = {name: store.read(snapshot, run_id, name) for name in ("assemble", "device_install", "device_launch")}
    hashes = []
    for name, record in records.items():
        from final_verifier import _validate_artifact
        _, error = _validate_artifact(store, snapshot, current["change_set_sha256"], run_id, name, record["harness_version"])
        if error or record["status"] != "PASS":
            raise ValidationError("missing valid build/install/launch evidence")
        ev = record.get("evidence") or {}
        hashes.append(ev.get("artifact_set_sha256") or (ev.get("artifact_set") or {}).get("artifact_set_sha256"))
    if not all(hashes) or len(set(hashes)) != 1:
        raise ValidationError("build/install/launch artifact sets differ")
    serial_hash = hashlib.sha256(serial.encode()).hexdigest()
    for name in ("device_install", "device_launch"):
        evidence = records[name]["evidence"]
        if evidence.get("serial_sha256") != serial_hash or evidence.get("application_id") != selected["application_id"] \
                or str(evidence.get("target_user") or "0") != "0":
            raise ValidationError("journey device, application, or user differs from installed artifact")
    # Reuse the established review prerequisites and final verifier contracts.
    from run_gradle_task import validate_reviewer_precondition_before_assemble
    allowed, reason = validate_reviewer_precondition_before_assemble(repo, state_root(repo))
    if not allowed:
        raise ValidationError(reason)
    # Verify established proof contracts before any device effect. Only final human approval
    # and acceptance associations may remain missing at this point.
    from final_verifier import verify_task
    prerequisite = verify_task(repo, task_id)
    allowed_missing = ("device_signoff", "sensitive_approval", "required acceptance coverage missing:",
                       "selected journey evidence missing or invalid")
    if prerequisite.get("status") != "APPROVED":
        reasons = prerequisite.get("blocked_by") or []
        if prerequisite.get("status") != "BLOCKED" or not reasons or any(
                not any(token in reason for token in allowed_missing) for reason in reasons):
            raise ValidationError("journey prerequisites are not verified: " + "; ".join(str(r) for r in reasons))
    with StateLock(state_root(repo) / "journey-execution"):
        # Only other device replays wait for execution; the central state lock stays short-lived.
        locked_plan, locked_run, _ = active_context(repo, task_id, True)
        if locked_plan["plan_sha256"] != plan["plan_sha256"] or locked_run["run_id"] != run_id:
            raise ValidationError("task approval or verification run changed before replay")
        version = records["assemble"]["harness_version"]
        with StateLock(state_root(repo)):
            locked_plan, locked_run, _ = active_context(repo, task_id, True)
            if locked_plan["plan_sha256"] != plan["plan_sha256"] or locked_run["run_id"] != run_id:
                raise ValidationError("task approval or verification run changed before replay")
            for name, record in records.items():
                if store.read(snapshot, run_id, name) != record:
                    raise ValidationError("build/install/launch evidence changed before replay")
            # A retry supersedes earlier PASS before effects, including when interrupted.
            # Completion cannot race with an in-flight replay and reuse its earlier result.
            store.write(snapshot=snapshot, run_id=run_id, name="journey-" + selected["id"], producer="journey_runner",
                        harness_version=version, change_set=current["change_set_sha256"], status="BLOCKED",
                        evidence={"task_id": task_id, "plan_sha256": plan["plan_sha256"],
                                  "definition_sha256": canonical_sha256(selected), "execution_state": "IN_PROGRESS"},
                        lock=False, allow_pass_retry=True)
        active_transport = transport or AdbTransport(serial, selected["application_id"],
                            [member["sha256"] for member in records["assemble"]["evidence"]["artifact_set"]["members"]])
        result = execute_journey(selected, active_transport)
        if isinstance(active_transport, AdbTransport) and result["status"] == "PASS":
            try:
                active_transport.verify_installed_artifact()
            except (OSError, TimeoutError, subprocess.TimeoutExpired):
                result["status"] = "ENV"
        with StateLock(state_root(repo)):
            latest_plan, latest_run, _ = active_context(repo, task_id, True)
            if latest_plan["plan_sha256"] != plan["plan_sha256"] or latest_run["run_id"] != run_id:
                raise ValidationError("task approval or verification run changed during replay")
            for name, record in records.items():
                if store.read(snapshot, run_id, name) != record:
                    raise ValidationError("build/install/launch evidence changed during replay")
            store.write(snapshot=snapshot, run_id=run_id, name="journey-" + selected["id"], producer="journey_runner",
                        harness_version=version, change_set=current["change_set_sha256"], status=result["status"],
                        evidence={**result, "task_id": task_id, "plan_sha256": plan["plan_sha256"],
                                  "definition_sha256": canonical_sha256(selected), "artifact_set_sha256": hashes[0],
                                  "serial_sha256": serial_hash, "application_id": selected["application_id"],
                                  "variant": selected["variant"], "criterion_ids": selected["criteria"]},
                        lock=False, allow_pass_retry=True)
    return result


def run_device_validation(repo, task_id, serial, source, proof_reference, approval_token=None, transport=None):
    """Execute the approved whole walkthrough selected by the developer after install."""
    from verification_contract import active_context, allows_validation_choice, bind_evidence, validate_contract
    from workflow import state_root
    from evidence_store import StateLock
    if source not in {"conversation", "developer_terminal", "host_native"} or not str(proof_reference or "").strip():
        raise ValidationError("automatic validation requires explicit developer selection and proof reference")
    if source == "host_native" and not approval_token:
        raise ValidationError("host-native selection requires a trusted approval token")
    plan, current, store = active_context(repo, task_id, True)
    if not allows_validation_choice(plan):
        raise ValidationError("no complete automatic walkthrough was approved; use manual validation")
    validate_contract(plan["verification_contract"])
    snapshot, run_id = current["delivery_snapshot_sha256"], current["run_id"]
    from final_verifier import _validate_artifact
    records = {name: store.read(snapshot, run_id, name) for name in ("assemble", "device_install", "device_launch")}
    version = records["assemble"]["harness_version"]
    for name in records:
        _, error = _validate_artifact(store, snapshot, current["change_set_sha256"], run_id, name, version)
        if error:
            raise ValidationError("automatic validation requires verified build/install/launch: " + error)
    evidence = {"task_id": task_id, "plan_sha256": plan["plan_sha256"], "mode": "automatic",
                "contract_sha256": canonical_sha256(plan["verification_contract"]),
                "approval_source": source, "proof_reference_sha256": canonical_sha256(str(proof_reference).strip()),
                "prerequisite_sha256": {name: r["artifact_sha256"] for name, r in records.items()}}
    publication_sha = None
    def publish(status, extra=None):
        nonlocal publication_sha
        with StateLock(state_root(repo)):
            latest_plan, latest_run, _ = active_context(repo, task_id, True)
            if latest_plan["plan_sha256"] != plan["plan_sha256"] or latest_run["run_id"] != run_id:
                raise ValidationError("automatic validation approval or run changed")
            for name, record in records.items():
                if store.read(snapshot, run_id, name) != record:
                    raise ValidationError("automatic validation prerequisites changed")
            if publication_sha is not None and store.read(snapshot, run_id, "device_validation_result")["artifact_sha256"] != publication_sha:
                raise ValidationError("developer validation selection changed during execution")
            store.write(snapshot=snapshot, run_id=run_id, name="device_validation_result", producer="device_validation",
                        harness_version=version, change_set=current["change_set_sha256"], status=status,
                        evidence={**evidence, **(extra or {})}, lock=False, allow_pass_retry=True)
            publication_sha = store.read(snapshot, run_id, "device_validation_result")["artifact_sha256"]
    # Supersede earlier success before any device effect. Interruptions remain blocked.
    with StateLock(state_root(repo) / "device-validation-execution"):
        publish("BLOCKED", {"execution_state": "IN_PROGRESS"})
        journeys = plan["verification_contract"]["journeys"]
        active_transport = transport or AdbTransport(serial, journeys[0]["application_id"],
            [member["sha256"] for member in records["assemble"]["evidence"]["artifact_set"]["members"]])
        results = []
        try:
            for definition in journeys:
                result = run_selected(repo, task_id, definition["id"], serial, active_transport)
                results.append({"id": definition["id"], **result})
                if result["status"] != "PASS":
                    publish(result["status"], {"results": results})
                    return {"status": result["status"], "results": results}
        except (ValidationError, OSError, TimeoutError, subprocess.TimeoutExpired):
            publish("ENV", {"results": results, "detail": "Automatic validation could not finish; use manual validation or resolve the environment."})
            return {"status": "ENV", "results": results}
        with StateLock(state_root(repo)):
            latest_plan, latest_run, _ = active_context(repo, task_id, True)
            if latest_plan["plan_sha256"] != plan["plan_sha256"] or latest_run["run_id"] != run_id:
                raise ValidationError("automatic validation approval or run changed")
            sources = {}
            for definition in journeys:
                artifact = "journey-" + definition["id"]
                sources[definition["id"]] = store.read(snapshot, run_id, artifact)["artifact_sha256"]
                for identity in definition["criteria"]:
                    bind_evidence(plan, current, store, identity, artifact, lock=False)
        publish("PASS", {"journey_sha256": sources, "results": results})
        return {"status": "PASS", "results": results, "manual_repeat_required": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "list", "run"))
    parser.add_argument("--repo", default=".")
    parser.add_argument("--file")
    parser.add_argument("--task-id")
    parser.add_argument("--id")
    parser.add_argument("--serial")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        repo = Path(args.repo).resolve()
        if args.action == "validate":
            from verification_contract import load_definition
            if not args.file:
                raise ValidationError("--file is required")
            definition = validate_journey(load_definition(repo, args.file))
            result = {"status": "VALID", "id": definition["id"], "definition_sha256": canonical_sha256(definition)}
        else:
            if not args.task_id:
                raise ValidationError("--task-id is required")
            if args.action == "list":
                from verification_contract import active_context
                plan, _, _ = active_context(repo, args.task_id)
                result = {"journeys": (plan.get("verification_contract") or {}).get("journeys", [])}
            else:
                if not args.id or not args.serial:
                    raise ValidationError("--id and --serial are required")
                result = run_selected(repo, args.task_id, args.id, args.serial)
        print(json.dumps(result, indent=2))
        return 30 if result.get("status") == "ENV" else 1 if result.get("status") == "FAIL" else 0
    except (ValidationError, OSError, ValueError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

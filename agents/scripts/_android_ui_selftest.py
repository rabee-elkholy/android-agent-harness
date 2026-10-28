"""Android UI adapter contracts, with no Android SDK, CLI or device execution."""
from __future__ import annotations
import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import android_ui as ui
from _vnext_common import ValidationError


class AndroidUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / ".agents/state").mkdir(parents=True)
        (self.repo / ".agents/VERSION").write_text("1.0.0")
        self.plan = {"task_id": "ui", "status": "IMPLEMENTING"}
        self.caps = {"identity": "cli", "version": "1", "features": {"list": True, "render": True, "hub": True}}

    def args(self, **kwargs):
        return argparse.Namespace(**dict({"action": "render", "reference": ":mobile", "fqn": ["sample.ScreenKt.Preview"],
                                         "image": False, "no_daemon": False, "refresh": False}, **kwargs))

    def renderer(self, executable, command, repo, timeout):
        directory = Path(next(a.split("=", 1)[1] for a in command if a.startswith("--output=")))
        (directory / "preview.json").write_text('{"name":"Text"}')
        if "--no-image" not in command:
            (directory / "preview.png").write_bytes(b"png")
        return 0, "Rendered"

    def render(self, args=None, identity="source"):
        with patch.object(ui, "authorize", return_value=self.plan), \
             patch.object(ui, "input_identity", return_value=identity), \
             patch("_variants.resolve_assemble_task", return_value=":mobile:assembleDebug"):
            return ui.preview(self.repo, args or self.args(), "android", self.caps, self.plan)

    def test_batched_tree_defaults_and_cache_revalidates_outputs(self):
        with patch.object(ui, "invoke", side_effect=self.renderer) as invoke:
            first = self.render(self.args(fqn=["sample.B.Preview", "sample.A.Preview", "sample.B.Preview"]))
            command = invoke.call_args.args[1]
            self.assertIn("--no-image", command)
            self.assertIn("--daemon", command)
            self.assertEqual(2, len([a for a in command if a.startswith("--fqn=")]))
            second = self.render(self.args(fqn=["sample.B.Preview", "sample.A.Preview"]))
            self.assertTrue(second["reused"])
            self.assertEqual(1, invoke.call_count)
            Path(first["files"][0]["path"]).write_text("changed")
            self.assertFalse(self.render()["reused"])
            self.assertEqual(2, invoke.call_count)

    def test_source_change_and_refresh_rerender(self):
        with patch.object(ui, "invoke", side_effect=self.renderer) as invoke:
            self.render()
            self.render(identity="changed")
            self.render(self.args(refresh=True))
            self.assertEqual(3, invoke.call_count)

    def test_image_and_one_shot_options(self):
        with patch.object(ui, "invoke", side_effect=self.renderer) as invoke:
            result = self.render(self.args(image=True, no_daemon=True))
            command = invoke.call_args.args[1]
            self.assertNotIn("--daemon", command)
            self.assertNotIn("--no-image", command)
            self.assertEqual(2, len(result["files"]))
            self.assertFalse(result["delivery_evidence"])

    def test_failure_or_missing_outputs_never_cached(self):
        for response in ((1, "failure"), (0, "no files")):
            with patch.object(ui, "invoke", return_value=response), self.assertRaises(ValidationError):
                self.render()
        self.assertFalse((self.repo / ".agents/state/diagnostics/android-ui/source.json").exists())

    def test_inputs_changed_during_build_rejected(self):
        with patch.object(ui, "authorize"), patch.object(ui, "input_identity", side_effect=["before", "after"]), \
             patch("_variants.resolve_assemble_task", return_value=":mobile:assembleDebug"), \
             patch.object(ui, "invoke", side_effect=self.renderer), self.assertRaisesRegex(ValidationError, "STALE"):
            ui.preview(self.repo, self.args(), "android", self.caps, self.plan)

    def test_invalid_fqn_and_reference_are_not_executed(self):
        with patch.object(ui, "invoke") as invoke:
            for fqn in ([], ["--help"], ["sample.Preview;evil"], ["a.B" + str(i) for i in range(17)]):
                with self.assertRaises(ValidationError):
                    self.render(self.args(fqn=fqn))
            for reference in ("../elsewhere", ":app --init-script x", "--help", "gradle://outside"):
                with self.assertRaises(ValidationError):
                    self.render(self.args(reference=reference))
            invoke.assert_not_called()

    def test_build_lock_blocks_preview_and_gradle(self):
        import run_gradle_task
        with ui.build_lock(self.repo), patch.object(ui, "invoke") as invoke:
            with self.assertRaises(ValidationError):
                self.render()
            with patch.object(run_gradle_task, "_run_gradle_locked") as gradle:
                self.assertEqual(30, run_gradle_task.run_gradle([":mobile:assembleDebug"], cwd=self.repo))
                gradle.assert_not_called()
            invoke.assert_not_called()

    def test_non_antigravity_and_unapproved_states_rejected(self):
        with patch("review_sources.resolve_review_host", return_value="codex"), self.assertRaisesRegex(ValidationError, "UNSUPPORTED"):
            ui.authorize(self.repo, "render")
        with patch("review_sources.resolve_review_host", return_value="antigravity"), \
             patch("mutation_guard.active_plan", return_value={"status": "AWAITING_DEVELOPER_APPROVAL"}), \
             patch("host_continuation.assert_execution_session"), self.assertRaises(ValidationError):
            ui.authorize(self.repo, "render")

    def test_hub_during_implementation_rejected(self):
        with patch("review_sources.resolve_review_host", return_value="antigravity"), \
             patch("mutation_guard.active_plan", return_value=self.plan), \
             patch("host_continuation.assert_execution_session"), self.assertRaises(ValidationError):
            ui.authorize(self.repo, "hub")

    def phone(self, explicit=None, phones=None, mismatch=False, error=None):
        import hashlib
        evidence = {"serial_sha256": hashlib.sha256(b"phone").hexdigest(), "artifact_set_sha256": "apk", "target_user": "0"}
        launch = {**evidence, "artifact_set_sha256": "other"} if mismatch else evidence
        current = {"delivery_snapshot_sha256": "snapshot", "change_set_sha256": "changes", "run_id": "run"}
        with patch("workflow.assert_active_run_fresh", return_value=current), \
             patch("run_gradle_task.validate_reviewer_precondition_before_assemble", return_value=(True, "verified")), \
             patch("final_verifier._validate_artifact", side_effect=[({"evidence": evidence}, error), ({"evidence": launch}, None)]), \
             patch("_repo_files.matching_adb_serials", return_value=phones if phones is not None else ["phone", "other"]):
            return ui.bound_phone(self.repo, self.plan, explicit)

    def test_hub_selects_verified_phone_even_with_multiple_connected(self):
        self.assertEqual("phone", self.phone())
        self.assertEqual("phone", self.phone("phone"))

    def test_hub_never_switches_or_accepts_stale_proof(self):
        for kwargs in ({"explicit": "other"}, {"phones": []}, {"phones": ["other"]}, {"mismatch": True}, {"error": "stale"}):
            with self.assertRaises(ValidationError):
                self.phone(**kwargs)

    def test_capabilities_cached_and_invalidated_by_executable_change(self):
        executable = self.repo / "tool.exe"
        executable.write_bytes(b"one")
        help_text = "--format --fqn --output --component-tree --no-image --daemon --device"
        with patch.object(ui, "invoke", return_value=(0, help_text)) as invoke:
            ui.capabilities(self.repo, str(executable))
            ui.capabilities(self.repo, str(executable))
            self.assertEqual(4, invoke.call_count)
            executable.write_bytes(b"changed")
            ui.capabilities(self.repo, str(executable))
            self.assertEqual(8, invoke.call_count)

    def test_public_main_unsupported_does_not_run_preview(self):
        with patch.object(ui, "authorize", return_value=self.plan), patch.object(ui, "executable_path", return_value="android"), \
             patch.object(ui, "capabilities", return_value={"features": {"render": False}}), \
             patch.object(ui, "preview") as preview, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(30, ui.main(["render", "--repo", str(self.repo), "--fqn", "a.B"]))
            self.assertFalse(json.loads(output.getvalue())["delivery_evidence"])
            preview.assert_not_called()

    def test_public_main_render_and_bounded_receipt(self):
        with patch.object(ui, "authorize", return_value=self.plan), patch.object(ui, "executable_path", return_value="android"), \
             patch.object(ui, "capabilities", return_value=self.caps), \
             patch.object(ui, "input_identity", return_value="snapshot"), \
             patch("_variants.resolve_assemble_task", return_value=":mobile:assembleDebug"), \
             patch.object(ui, "invoke", side_effect=self.renderer), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, ui.main(["render", "--repo", str(self.repo), "--fqn", "sample.Home.Preview"]))
            result = json.loads(output.getvalue())
            self.assertEqual("DIAGNOSTIC_OK", result["status"])
            self.assertFalse(result["delivery_evidence"])
            self.assertTrue(Path(result["receipt"]).is_file())

    def test_public_hub_passes_only_bound_serial_and_no_test_verdict(self):
        with patch.object(ui, "authorize", return_value=self.plan), patch.object(ui, "executable_path", return_value="android"), \
             patch.object(ui, "capabilities", return_value=self.caps), patch.object(ui, "bound_phone", return_value="verified-phone"), \
             patch.object(ui, "invoke", return_value=(0, "opened")) as invoke, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, ui.main(["hub", "--repo", str(self.repo)]))
            self.assertEqual(["device", "hub", "--device=verified-phone"], invoke.call_args.args[1])
            self.assertEqual("OPEN_REQUESTED", json.loads(output.getvalue())["status"])

    def test_retention_removes_only_owned_directories(self):
        root = self.repo / "diagnostics"
        root.mkdir()
        for index in range(14):
            folder = root / f"{index:032x}"
            folder.mkdir()
            (folder / "output.json").write_text("{}")
        unrelated = root / "user-files"
        unrelated.mkdir()
        (unrelated / "keep.txt").write_text("keep")
        ui.prune_diagnostics(root)
        self.assertEqual(13, len(list(root.iterdir())))
        self.assertEqual("keep", (unrelated / "keep.txt").read_text())

    def test_capability_corruption_reprobes_and_old_cli_degrades(self):
        executable = self.repo / "tool.exe"
        executable.write_bytes(b"one")
        with patch.object(ui, "invoke", side_effect=[(0, "old"), (1, "unknown"), (1, "unknown"), (1, "unknown")]):
            result = ui.capabilities(self.repo, str(executable))
            self.assertEqual({"list": False, "render": False, "hub": False}, result["features"])
        cache = self.repo / ".agents/state/cache/android-ui-capabilities.json"
        cache.write_text("[]")
        with patch.object(ui, "invoke", return_value=(0, "none")) as invoke:
            ui.capabilities(self.repo, str(executable))
            self.assertEqual(4, invoke.call_count)

    def test_repository_local_executable_rejected(self):
        executable = self.repo / "android.exe"
        executable.write_bytes(b"not trusted")
        with patch("shutil.which", return_value=str(executable)), self.assertRaises(ValidationError):
            ui.executable_path(self.repo)

    def test_cache_identity_includes_resources_and_environment(self):
        manifest = {"delivery_snapshot_sha256": "source", "change_set_sha256": "changes", "external_inputs_sha256": "external"}
        with patch("delivery_manifest.build_manifest", return_value=manifest):
            first = ui.input_identity(self.repo, self.plan, self.caps, {})
            manifest["delivery_snapshot_sha256"] = "resource-change"
            self.assertNotEqual(first, ui.input_identity(self.repo, self.plan, self.caps, {}))

    def test_installed_command_dispatches_adapter(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ui_test_entry", Path(__file__).resolve().parents[1] / "harness.py")
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        with patch.object(entry, "_run", return_value=0) as run:
            self.assertEqual(0, entry._main(["android-ui", "render", "--fqn", "sample.Home.Preview"]))
            self.assertEqual("android_ui.py", run.call_args.args[0])
            self.assertIn("--repo", run.call_args.args[1])

    def test_hook_command_authorization_uses_adapter_boundary(self):
        import shutil
        from mutation_guard import command_allowed
        root = Path(__file__).resolve().parents[1]
        shutil.copyfile(root / "harness.py", self.repo / ".agents/harness.py")
        command = "python .agents/harness.py android-ui hub"
        with patch.object(ui, "authorize", side_effect=ValidationError("phone is not ready")):
            allowed, reason = command_allowed(self.repo, command)
            self.assertFalse(allowed)
            self.assertIn("phone is not ready", reason)
        with patch.object(ui, "authorize", return_value=self.plan):
            self.assertTrue(command_allowed(self.repo, command)[0])


if __name__ == "__main__":
    unittest.main()

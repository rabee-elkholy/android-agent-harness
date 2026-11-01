"""Public contracts for optional Android semantic inspection and documentation."""
from __future__ import annotations
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

KIT = Path(__file__).resolve().parents[2]


class AndroidInspectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / 'src').mkdir()
        (self.repo / 'src/Main.kt').write_text('class Main\n', encoding='utf-8')

    def test_kernel_uses_supported_always_on_trigger(self):
        text = (KIT / 'agents/rules/harness-rules.md').read_text()
        self.assertIn('trigger: always_on\n', text)

    def test_semantic_commands_bind_project_and_context(self):
        import android_inspect as adapter
        args = adapter.parse_args(['declaration', 'Main', '--file', 'src/Main.kt'])
        command = adapter.command_for(self.repo, args)
        self.assertEqual(command, ['studio', 'find-declaration', '--project=' + str(self.repo.resolve()),
                                  '--short', '--context-file=' + str(self.repo / 'src/Main.kt'), 'Main'])
        self.assertEqual(adapter.command_for(self.repo, adapter.parse_args(['analyze', 'src/Main.kt'])),
                         ['studio', 'analyze-file', '--project=' + str(self.repo.resolve()), str(self.repo / 'src/Main.kt')])

    def test_unsafe_arguments_rejected_before_cli_runs(self):
        import android_inspect as adapter
        from _vnext_common import ValidationError
        for argv in (['analyze', '../secret.kt'], ['analyze', 'src/missing.kt'],
                     ['declaration', '--init-script=evil'], ['docs-fetch', 'https://evil.example'],
                     ['docs-fetch', 'kb://android/../../secret'], ['docs-search', '-V']):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises((ValidationError, SystemExit)):
                adapter.command_for(self.repo, adapter.parse_args(argv))

    def test_documentation_uses_kb_urls_and_never_project_context(self):
        import android_inspect as adapter
        self.assertEqual(adapter.command_for(self.repo, adapter.parse_args(['docs-fetch', 'kb://android/topic/compose'])),
                         ['docs', 'fetch', 'kb://android/topic/compose'])
        self.assertEqual(adapter.command_for(self.repo, adapter.parse_args(['docs-search', 'Compose navigation'])),
                         ['docs', 'search', 'Compose navigation'])

    def test_probe_does_not_accept_similarly_named_flags(self):
        import android_inspect as adapter
        with patch.object(adapter, 'invoke', side_effect=[
                (0, 'version'), (0, 'studio find-declaration --project-other --context-file --shorter')]):
            self.assertFalse(adapter.probe(self.repo, '/tool/android', 'declaration')['supported'])

    def test_public_cli_pins_repo_even_with_inherited_environment(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('inspect_public_cli', KIT / 'harness_cli.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        (self.repo / 'gradlew').write_text('# fixture only\n')
        args = cli.build_parser().parse_args(['android-inspect', '--repo', str(self.repo), 'usages', 'Main'])
        with patch.dict(os.environ, {'HARNESS_REPO': '/wrong/project'}), \
             patch.object(cli, '_dispatch_pipeline_script', return_value=0) as dispatch:
            self.assertEqual(0, cli.cmd_android_inspect(args))
        self.assertEqual(['--repo', str(self.repo.resolve())], dispatch.call_args.args[2][-2:])

    def test_missing_provider_is_explicit_fallback_not_pass(self):
        import android_inspect as adapter
        from _vnext_common import ValidationError
        output = io.StringIO()
        with patch.object(adapter, 'executable_path', side_effect=ValidationError('missing')), contextlib.redirect_stdout(output):
            code = adapter.main(['docs-search', 'Compose', '--repo', str(self.repo)])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 30)
        self.assertFalse(result['delivery_evidence'])
        self.assertIn('fallback', result)

    def test_success_is_transport_status_not_clean_analysis(self):
        import android_inspect as adapter
        output = io.StringIO()
        with patch.object(adapter, 'executable_path', return_value='/tool/android'), \
             patch.object(adapter, 'probe', return_value={'supported': True, 'version': 'test'}), \
             patch.object(adapter, 'invoke', return_value=(0, 'error: unresolved reference')) as call, contextlib.redirect_stdout(output):
            code = adapter.main(['analyze', 'src/Main.kt', '--repo', str(self.repo)])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result['status'], 'INSPECTION_COMPLETE')
        self.assertFalse(result['delivery_evidence'])
        self.assertIn('error:', result['output'])
        self.assertIn('--project=' + str(self.repo.resolve()), call.call_args.args[1])

    def test_changed_source_during_analysis_is_stale(self):
        import android_inspect as adapter
        def mutate(*args, **kwargs):
            (self.repo / 'src/Main.kt').write_text('class Changed\n')
            return 0, 'no issues'
        output = io.StringIO()
        with patch.object(adapter, 'executable_path', return_value='/tool/android'), \
             patch.object(adapter, 'probe', return_value={'supported': True, 'version': 'test'}), \
             patch.object(adapter, 'invoke', side_effect=mutate), contextlib.redirect_stdout(output):
            self.assertEqual(30, adapter.main(['analyze', 'src/Main.kt', '--repo', str(self.repo)]))
        self.assertIn('STALE', output.getvalue())

    def test_public_facades_and_hook_allow_only_inspection(self):
        from mutation_guard import command_allowed
        for command in ('python .agents/harness.py android-inspect docs-search "Compose"',
                        'python .agents/harness.py android-inspect usages Main --file src/Main.kt'):
            allowed, reason = command_allowed(self.repo, command)
            self.assertTrue(allowed, reason)
        self.assertFalse(command_allowed(self.repo, 'python .agents/harness.py android-inspect install')[0])
        for entry in (KIT / 'agents/harness.py', KIT / 'harness_cli.py'):
            command = [sys.executable, str(entry), 'android-inspect']
            if entry.name == 'harness_cli.py':
                command += ['--kit', str(KIT), '--repo', str(self.repo)]
            command += ['--help']
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('docs-search', result.stdout)

    def test_native_hook_payload_allows_inspection_but_preserves_mutation_guards(self):
        env = {**os.environ, 'HARNESS_REPO': str(self.repo),
               'HARNESS_HOOK_STATE': str(self.repo / 'hook-audit.json')}
        for command, decision in (
            ('python .agents/harness.py android-inspect docs-search "Compose"', 'allow'),
            ('python .agents/harness.py android-inspect install', 'deny'),
            ('./gradlew assembleDebug', 'deny'), ('git push', 'deny')):
            with self.subTest(command=command):
                result = subprocess.run(
                    [sys.executable, str(KIT / 'agents/scripts/pre_tool_safety.py')],
                    input=json.dumps({'toolCall': {'name': 'run_command',
                          'args': {'CommandLine': command, 'Cwd': str(self.repo)}}}),
                    capture_output=True, text=True, env=env, timeout=15)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(decision, json.loads(result.stdout)['decision'])

    def test_unsupported_or_timed_out_tool_never_produces_evidence(self):
        import android_inspect as adapter
        for supported in (False, True):
            output = io.StringIO()
            with patch.object(adapter, 'executable_path', return_value='/tool/android'), \
                 patch.object(adapter, 'probe', return_value={'supported': supported, 'version': 'test'}), \
                 patch.object(adapter, 'invoke', side_effect=subprocess.TimeoutExpired('android', 60)) as invoke, \
                 contextlib.redirect_stdout(output):
                self.assertEqual(30, adapter.main(['docs-search', 'Compose', '--repo', str(self.repo)]))
            self.assertFalse(json.loads(output.getvalue())['delivery_evidence'])
            self.assertEqual(int(supported), invoke.call_count)

    def test_real_capture_bounds_head_and_tail_without_shell(self):
        from android_ui import invoke
        command = ['-c', 'print("HEAD" + "x" * 9000 + "TAIL")']
        code, head = invoke(sys.executable, command, self.repo, head=True)
        self.assertEqual(code, 0)
        self.assertTrue(head.startswith('HEAD'))
        self.assertEqual(len(head), 6000)
        _, tail = invoke(sys.executable, command, self.repo)
        self.assertTrue(tail.endswith('TAIL\n'))
        self.assertEqual(len(tail), 6000)

    def test_managed_rules_validate_and_report_host_contract_regression(self):
        import shutil
        from antigravity_contract import rule_errors
        shutil.copytree(KIT / 'agents/rules', self.repo / 'rules')
        self.assertEqual([], rule_errors(self.repo))
        kernel = self.repo / 'rules/harness-rules.md'
        kernel.write_text(kernel.read_text().replace('trigger: always_on', 'trigger: always'))
        scoped = self.repo / 'rules/compose-context.md'
        scoped.write_text(scoped.read_text().replace('trigger: glob', 'trigger: glob\ntrigger: manual'))
        self.assertEqual(2, len(rule_errors(self.repo)))
        scoped.unlink()
        self.assertIn('missing', ' '.join(rule_errors(self.repo)))


class GradleOutputTests(unittest.TestCase):
    def test_runner_exit_and_gate_verdict_ignore_success_text_on_failure(self):
        import run_gradle_task as runner
        for code in (0, 7):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                script = 'print("BUILD SUCCESSFUL"); raise SystemExit(' + str(code) + ')'
                with patch.object(runner, 'gradle_wrapper', return_value=root / 'gradlew'), \
                     patch.object(runner, 'unix_wrapper_cmd', return_value=[sys.executable, '-c', script]), \
                     patch.object(runner.shutil, 'which', return_value='test-shell'), \
                     patch.object(runner, 'write_gate_result') as record, \
                     patch.object(runner, 'current_head_sha', return_value='test-head'), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(code, runner.run_gradle([':feature:compileDebugKotlin'], cwd=root))
                self.assertEqual(code, record.call_args.args[1]['exit_code'])
                self.assertEqual('PASS' if code == 0 else 'FAIL', record.call_args.args[1]['status'])

    def test_late_noncompiler_failure_reason_survives_live_output_budget(self):
        import run_gradle_task as runner
        raw = ('task chatter\n' * 100 + 'FAILURE: Build failed\n* What went wrong:\n'
               'Configuration callback rejected unsupported target\nBUILD FAILED\n')
        with tempfile.TemporaryDirectory() as td, \
             patch.object(runner, 'gradle_wrapper', return_value=Path(td) / 'gradlew'), \
             patch.object(runner.shutil, 'which', return_value='test-shell'), \
             patch.object(runner, 'unix_wrapper_cmd', return_value=['unused']), \
             patch.object(runner, 'run_streaming', return_value=(7, raw, ['task chatter'] * 40)), \
             patch.object(runner, 'write_gate_result'), \
             patch.object(runner, 'current_head_sha', return_value='head'), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(7, runner.run_gradle([':feature:compileDebugKotlin'], cwd=td))
        self.assertIn('Configuration callback rejected unsupported target', output.getvalue())

    def test_noisy_build_preserves_late_errors_and_full_log(self):
        import run_gradle_task as runner
        from _live_process import run_streaming
        budget = runner.GradleOutputBudget()
        output = io.StringIO()
        script = 'print(("noise" + "x" * 2000 + "\\n") * 200); print("e: file:///Main.kt:1:1 broken")'
        with contextlib.redirect_stdout(output):
            code, raw, shown = run_streaming([sys.executable, '-c', script], heartbeat_sec=0,
                                             should_echo=budget, format_echo=runner.display_line)
        self.assertEqual(code, 0)
        self.assertIn('broken', output.getvalue())
        self.assertEqual(200, raw.count('noise'))
        self.assertLessEqual(len(shown), 80)
        self.assertTrue(all(len(line) <= runner.DISPLAY_LINE_LIMIT for line in shown))
        self.assertGreater(budget.hidden, 0)
        with tempfile.TemporaryDirectory() as td:
            first = runner.save_raw_log(Path(td), 'compile', raw)
            second = runner.save_raw_log(Path(td), 'compile', raw)
            self.assertNotEqual(first, second)
            self.assertEqual(raw, first.read_text(encoding='utf-8'))
        summary = runner.bounded_summary(('error: ' + 'x' * 3000 + '\n') * 100)
        self.assertLess(len(summary), 15000)


if __name__ == '__main__':
    unittest.main()

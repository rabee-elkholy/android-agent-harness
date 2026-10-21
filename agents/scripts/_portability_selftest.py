"""Regression contracts for platform safety, public commands, lint and Room."""
from __future__ import annotations

import argparse
import ast
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

KIT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'agents/scripts'))
sys.path.insert(0, str(KIT / 'agents/mcp/zoho_sprints'))

import harness_cli
import room_guard
import fast_kt_lint
import _idempotency
from doctor.engine import HarnessDoctor


class PublicCommands(unittest.TestCase):
    def test_batch_review_uses_orchestrator(self):
        args = harness_cli.build_parser().parse_args(['review', 'dispatch-batch', '--task', 'demo'])
        with mock.patch.object(harness_cli, '_dispatch_pipeline_script', return_value=0) as run:
            self.assertEqual(0, args.func(args))
        self.assertEqual('review_orchestrator.py', run.call_args.args[1])
        self.assertEqual(['dispatch-batch', '--task', 'demo'], run.call_args.args[2])

    def test_compile_forwards_explicit_task(self):
        args = harness_cli.build_parser().parse_args(['compile', ':library:compileDebugJavaWithJavac'])
        with mock.patch.object(harness_cli, '_dispatch_pipeline_script', return_value=0) as run:
            self.assertEqual(0, args.func(args))
        self.assertEqual(('run_gradle_task.py', [':library:compileDebugJavaWithJavac']), run.call_args.args[1:])


class ProcessSafety(unittest.TestCase):
    def test_windows_probe_uses_read_only_handles_and_closes_them(self):
        from harness_shared import processes
        kernel = mock.Mock()
        kernel.OpenProcess.return_value = 123
        def exit_code(_handle, pointer):
            pointer._obj.value = 259
            return 1
        kernel.GetExitCodeProcess.side_effect = exit_code
        with mock.patch.object(ctypes, 'WinDLL', return_value=kernel, create=True), mock.patch.object(processes.os, 'name', 'nt'), mock.patch.object(processes.os, 'kill') as kill:
            self.assertTrue(processes.pid_alive(1234))
            kernel.CloseHandle.assert_called_once_with(123)
            kill.assert_not_called()

    def test_windows_unknown_probe_failure_cannot_evict_owner(self):
        from harness_shared import processes
        kernel = mock.Mock()
        kernel.OpenProcess.return_value = 0
        with mock.patch.object(ctypes, 'WinDLL', return_value=kernel, create=True):
            for error, expected in ((87, False), (5, True), (8, True)):
                with self.subTest(error=error), mock.patch.object(ctypes, 'get_last_error', return_value=error, create=True):
                    self.assertEqual(expected, processes._windows_pid_alive(1234))
        kernel.CloseHandle.assert_not_called()

    def test_invalid_pid_never_signals_a_process_group(self):
        for pid in (0, -1, -100):
            with self.subTest(pid=pid), mock.patch.object(_idempotency.os, 'kill') as kill:
                self.assertFalse(_idempotency._pid_alive(pid))
                kill.assert_not_called()

    def test_live_process_probe_does_not_kill_owner(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])
        try:
            self.assertTrue(_idempotency._pid_alive(child.pid))
            self.assertIsNone(child.poll())
        finally:
            child.terminate()
            child.wait(timeout=5)


class RoomSyntax(unittest.TestCase):
    def test_comments_strings_and_duplicate_args_do_not_fabricate_migrations(self):
        source = '''// AutoMigration(from=1, to=2)
        val text = "AutoMigration(from=2, to=3)"
        /* outer /* nested */ AutoMigration(from=3, to=4) */
        @AutoMigration(from=4, from=5, to=6)
        '''
        self.assertEqual([], room_guard.find_auto_migrations(source))

    def test_named_auto_migration_argument_order(self):
        variants = [
            'AutoMigration(from = 1, to = 2)',
            'AutoMigration(to = 2, from = 1)',
            'AutoMigration(from = 1, spec = MySpec::class, to = 2)',
            'AutoMigration(spec = MySpec.class, to = 2, from = 1)',
            'AutoMigration(1, 2)',
        ]
        with tempfile.TemporaryDirectory() as raw:
            for annotation in variants:
                with self.subTest(annotation=annotation):
                    result = room_guard.parse_database_source(annotation, repo=Path(raw))
                    self.assertEqual(frozenset({(1, 2)}), result.migrations)

    def test_java_embedded_transitive_type_is_part_of_schema(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            (repo / 'User.java').write_text('@Entity class User { @Embedded(prefix = "a_") private Address address; }')
            (repo / 'Address.java').write_text('class Address { @Embedded public Coordinates coordinates; }')
            (repo / 'Coordinates.java').write_text('class Coordinates { double lat; }')
            self.assertEqual(frozenset({'User', 'Address', 'Coordinates'}), room_guard.resolve_all_entity_types(frozenset({'User'}), repo))


class ModifiedLineSelection(unittest.TestCase):
    def test_eol_only_change_selects_no_lines(self):
        path = self.file('source.kt')
        path.write_bytes(b'one\r\ntwo\r\n')
        self.commit()
        path.write_bytes(b'one\ntwo\n')
        self.assertEqual(set(), fast_kt_lint.get_modified_lines_map(self.repo, [path])[path])

    def test_relative_paths_are_relative_to_repository(self):
        path = self.file('source.kt')
        self.commit()
        path.write_text('one\nchanged\nthree\n')
        relative = Path('source.kt')
        self.assertEqual({2}, fast_kt_lint.get_modified_lines_map(self.repo, [relative])[relative])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Harness Tests')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'core.autocrlf', 'false')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, check=True, capture_output=True)

    def file(self, name, text='one\ntwo\nthree\n'):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'baseline')

    def test_many_files_use_bounded_git_calls(self):
        files = [self.file(f'source {i}.kt') for i in range(30)]
        self.commit()
        for path in files:
            path.write_text('one\nchanged\nthree\n')
        real_run = subprocess.run
        with mock.patch.object(fast_kt_lint.subprocess, 'run', wraps=real_run) as run:
            result = fast_kt_lint.get_modified_lines_map(self.repo, files)
        self.assertTrue(all(result[p] == {2} for p in files))
        self.assertLessEqual(run.call_count, 3)

    def test_untracked_unchanged_cached_and_unusual_names(self):
        special = self.file('مرحبا \"quoted\".kt' if os.name != 'nt' else 'مرحبا space.kt')
        same = self.file('same.kt')
        self.commit()
        special.write_text('one\nstaged\nthree\n', encoding='utf-8')
        self.git('add', '.')
        special.write_text('one\nstaged\nworking\n', encoding='utf-8')
        new = self.file('new.kt')
        result = fast_kt_lint.get_modified_lines_map(self.repo, [special, same, new])
        self.assertEqual({2, 3}, result[special])
        self.assertEqual(set(), result[same])
        self.assertIsNone(result[new])
        cached = fast_kt_lint.get_modified_lines_map(self.repo, [special, same, new], cached=True)
        self.assertEqual({2}, cached[special])
        self.assertEqual(set(), cached[same])
        self.assertIsNone(cached[new])

    def test_cached_changes_before_first_commit(self):
        new = self.file('brand new.kt')
        self.git('add', '.')
        self.assertEqual({1, 2, 3}, fast_kt_lint.get_modified_lines_map(self.repo, [new], cached=True)[new])

    def test_deletion_only_does_not_lint_unchanged_lines(self):
        path = self.file('source.kt')
        self.commit()
        path.write_text('one\nthree\n')
        self.assertEqual(set(), fast_kt_lint.get_modified_lines_map(self.repo, [path])[path])

    def test_tabs_newlines_and_literal_pathspecs(self):
        if os.name == 'nt':
            self.skipTest('Windows filenames cannot contain tabs or newlines')
        paths = [self.file('tab\tline\n.kt'), self.file(':(glob)literal.kt')]
        self.commit()
        for path in paths:
            path.write_text('one\nchanged\nthree\n')
        result = fast_kt_lint.get_modified_lines_map(self.repo, paths)
        self.assertTrue(all(result[path] == {2} for path in paths))

    def test_git_failure_lints_every_line(self):
        path = self.file('new.kt')
        with mock.patch.object(fast_kt_lint.subprocess, 'run', side_effect=OSError('git unavailable')):
            self.assertIsNone(fast_kt_lint.get_modified_lines_map(self.repo, [path])[path])

    def test_rename_lints_new_content(self):
        path = self.file('old.kt')
        self.commit()
        self.git('mv', 'old.kt', 'renamed.kt')
        renamed = self.repo / 'renamed.kt'
        self.assertEqual({1, 2, 3}, fast_kt_lint.get_modified_lines_map(self.repo, [renamed], cached=True)[renamed])

    def test_indented_todo_comments_allowed_while_executable_todo_flagged(self):
        kt = self.repo / 'Sample.kt'
        kt.write_text(
            'class Sample {\n'
            '    fun onClick() {\n'
            '        // TODO(analytics): awaiting contract from developer\n'
            '        val x = 1 /* TODO(analytics): inline block comment */\n'
            '    }\n'
            '}\n',
            encoding='utf-8',
        )
        self.assertEqual([], fast_kt_lint.lint_file(kt))
        kt_stub = self.repo / 'Stub.kt'
        kt_stub.write_text(
            'class Stub {\n'
            '    fun onClick() {\n'
            '        TODO("not implemented")\n'
            '    }\n'
            '}\n',
            encoding='utf-8',
        )
        issues = fast_kt_lint.lint_file(kt_stub)
        self.assertEqual(['UNIMPLEMENTED_STUB'], [i['type'] for i in issues])


class HookCommandParsing(unittest.TestCase):
    def test_windows_backslashes_survive_quoted_command_parsing(self):
        from harness_shared import commands
        with mock.patch.object(commands.os, 'name', 'nt'):
            self.assertEqual([r'C:\Program Files\Python\python.exe', r'scripts\pre_tool_safety.py'], commands.split_command(r'"C:\Program Files\Python\python.exe" scripts\pre_tool_safety.py'))

    def test_rewrite_python_exe_does_not_duplicate_suffix(self):
        from harness_shared.commands import rewrite_python_hooks
        data = {'command': 'python.exe scripts/check.py'}
        self.assertTrue(rewrite_python_hooks(data, 'python3'))
        self.assertEqual('python3 scripts/check.py', data['command'])

    def test_repair_normalizes_hooks_once_and_preserves_ownership(self):
        from _public_cli_selftest import PhaseDRepairSelftest
        from _vnext_common import read_json, sha256_file, canonical_sha256
        from repair import repair_repository
        from harness_shared.commands import split_command
        fixture = PhaseDRepairSelftest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        ownership = fixture.repo / '.harness-setup/ownership-v1.json'
        data = read_json(ownership)
        data['entries'] = [{'path': '.agents/hooks.json', 'post_install_sha256': sha256_file(fixture.repo / '.agents/hooks.json')}]
        data['ownership_sha256'] = canonical_sha256({key: value for key, value in data.items() if key != 'ownership_sha256'})
        ownership.write_text(json.dumps(data))
        real_which = __import__('shutil').which
        with mock.patch('shutil.which', side_effect=lambda name, *a, **k: None if name == 'python' else real_which(name, *a, **k)):
            first = repair_repository(fixture.repo, KIT)
            second = repair_repository(fixture.repo, KIT)
        self.assertEqual('PASS', first['status'], first['doctor'])
        self.assertEqual('PASS', second['status'], second['doctor'])
        self.assertEqual(0, second['restored']['total'])
        hooks = fixture.repo / '.agents/hooks.json'
        data = json.loads(hooks.read_text())
        self.assertEqual(sys.executable, split_command(data['adb-and-git-safety']['PreToolUse'][0]['hooks'][0]['command'])[0])
        self.assertEqual(sha256_file(hooks), read_json(ownership)['entries'][0]['post_install_sha256'])

    def test_doctor_preserves_quoted_interpreter_path(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            agents = repo / '.agents'
            (agents / 'scripts').mkdir(parents=True)
            (agents / 'scripts/pre_tool_safety.py').write_text('print(\'{"decision":"allow"}\')')
            exe = str(repo / 'python runtime' / 'python.exe')
            command = '"' + exe + '" scripts/pre_tool_safety.py'
            (agents / 'hooks.json').write_text(json.dumps({'group': {'PreToolUse': [{'command': command}]}}))
            doctor = HarnessDoctor(repo, run_selftest=False)
            doctor.is_raw_kit = True
            with mock.patch('doctor.engine.shutil.which', side_effect=lambda name: exe if name == exe else None), mock.patch('doctor.engine.subprocess.run', return_value=subprocess.CompletedProcess([], 0, b'{"decision":"allow"}', b'')):
                doctor.check_antigravity_installation()
            smoke = next(r for r in doctor.results if r.name == 'Hook Runtime Smoke')
            self.assertEqual('PASS', smoke.status, smoke.message)


class ErrorBoundaries(unittest.TestCase):
    def test_malformed_transcript_is_rejected_without_traceback(self):
        from record_review import _extract_transcript_response
        from _vnext_common import ValidationError
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'transcript.json'
            for payload in ('not json', '[]', 'null'):
                path.write_text(payload)
                with self.subTest(payload=payload), self.assertRaises(ValidationError):
                    _extract_transcript_response(path)

    def test_programming_errors_are_not_swallowed_by_context_cache(self):
        import workflow
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            cache = repo / '.agents/cache'
            cache.mkdir(parents=True)
            (cache / 'last-task-context.json').write_text('{}')
            with mock.patch.object(workflow.json, 'loads', side_effect=TypeError('programming defect')):
                with self.assertRaises(TypeError):
                    workflow._resolve_task_context_for_draft(repo, None)

    def test_production_has_no_silent_broad_exception_handlers(self):
        files = [KIT / 'harness_cli.py', *(KIT / 'agents').rglob('*.py')]
        for path in files:
            if path.name.endswith('selftest.py') or (KIT / 'agents' / 'state') in path.parents:
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Name) and node.type.id == 'Exception':
                    self.assertFalse(len(node.body) == 1 and isinstance(node.body[0], ast.Pass), f'{path.relative_to(KIT)}:{node.lineno}')


if __name__ == '__main__':
    unittest.main()

"""Efficiency contracts: presentation cannot grant authority or hide changes."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from context_presentation import present_context, architecture_context
import task_context as tc
import task_metrics as tm
import _project_intelligence_selftest as fixtures

class EfficiencyTests(unittest.TestCase):
    def test_explicit_baseline_only_and_safety_fields_retained(self):
        payload = {'status':'RESOLVED', 'query':'a', 'warnings':['careful'],
                   'developer_instructions':[{'text':'keep'}], 'discovery':{'created_at':'a','resolved_paths':['a']},
                   'project_notes':{'content':'x'*10000,'sha256':'abc'}, 'direct_dependencies':[{'path':'b'}]}
        first=present_context(Path('.'),payload)
        second=present_context(Path('.'),payload,since=first['context_digest'])
        self.assertEqual('UNCHANGED',second['presentation'])
        self.assertLess(len(json.dumps(second)),len(json.dumps(first))*.75)
        for key in ('warnings','developer_instructions','discovery'):
            self.assertEqual(first[key],second[key])
        self.assertIn('content',present_context(Path('.'),payload)['project_notes'])
        changed={**payload,'project_notes':{'content':'changed','sha256':'def'}}
        self.assertEqual('FULL',present_context(Path('.'),changed,since=first['context_digest'])['presentation'])
        self.assertNotEqual(first['context_digest'],present_context(Path('/other'),payload)['context_digest'])
        self.assertIn('content',payload['project_notes'])

    def test_failure_never_compacted_and_architecture_bounded(self):
        for status in ('AMBIGUOUS','BATCH_PARTIAL','SOURCE_CHANGED_DURING_DISCOVERY'):
            p={'status':status,'warnings':['x'*20000],'local_profiles':[{'family_id':None,'paths':None},{'family_id':'MVVM_LIVE_DATA','paths':['a/b.kt']}]}
            a=present_context(Path('.'),p)
            self.assertEqual('FULL',present_context(Path('.'),p,since=a['context_digest'])['presentation'])
            arch=architecture_context(p)
            self.assertLess(len(json.dumps(arch).encode()),8192)
            self.assertFalse(arch['scope_authorization'])
        small=architecture_context({'local_profiles':[{'family_id':None,'paths':None},{'family_id':'MVVM_LIVE_DATA','paths':['a/b.kt']}]})
        self.assertEqual(['MVVM_LIVE_DATA','UNKNOWN'],small['local_families'])
        self.assertEqual(['a/b.kt'],small['representative_existing_patterns'])

    def test_batch_shares_inputs_and_keeps_source_freshness(self):
        f=fixtures.ProjectIntelligenceTests();f.setUp()
        try:
            f.mixed_project()
            files=['app/src/main/kotlin/com/example/home/HomeScreen.kt',
                   'feature/profile/src/main/java/com/example/profile/ProfilePresenter.java']
            with patch.object(tc,'_load_facts',wraps=tc._load_facts) as facts, patch.object(tc,'load_project_notes',wraps=tc.load_project_notes) as notes:
                result=tc.resolve_task_contexts(f.repo,files=files)
            self.assertEqual('BATCH_RESOLVED',result['status'])
            self.assertEqual(1,facts.call_count)
            self.assertEqual(1,notes.call_count)
            self.assertTrue(result['discovery'])
            import subprocess, sys
            command = [sys.executable, tc.__file__, '--repo', str(f.repo), '--json']
            for file in files:
                command.extend(['--file', file])
            summary = json.loads(subprocess.check_output(command, text=True))
            full = json.loads(subprocess.check_output(command + ['--full'], text=True))
            self.assertEqual('SUMMARY', summary['presentation'])
            self.assertEqual('FULL', full['presentation'])
            self.assertEqual(summary['context_digest'], full['context_digest'])
            self.assertIn('developer_instructions', summary['shared_context'])
            self.assertEqual(2, len(summary['results']))
            for row, expanded in zip(summary['results'], full['results']):
                self.assertTrue(row['discovery'])
                self.assertEqual(expanded.get('read_ranges'), row.get('read_ranges'))
            repeated = json.loads(subprocess.check_output(command + ['--since', summary['context_digest']], text=True))
            self.assertEqual('UNCHANGED', repeated['presentation'])
            self.assertIn('shared_context', repeated)

            arch=result['results'][0]['architecture_context']
            self.assertEqual([':app'],arch['target_modules'])
            self.assertIn('main',arch['source_sets'])
            self.assertLess(len(json.dumps(arch).encode()),8192)
            from mutation_guard import _valid_context_targets
            self.assertTrue(_valid_context_targets(['--file', files[0], '--symbol', 'ProfilePresenter', '--json']))
            mixed_cmd = [sys.executable, tc.__file__, '--repo', str(f.repo), '--file', files[0], '--symbol', 'ProfilePresenter', '--json']
            mixed_out = json.loads(subprocess.check_output(mixed_cmd, text=True))
            self.assertEqual('BATCH_RESOLVED', mixed_out['status'])
            self.assertEqual(2, len(mixed_out['results']))
        finally:f.tearDown()

    def test_summary_batch_shares_exact_values_without_scope_loss(self):
        import copy
        instructions = [{'text': 'Must preserve this instruction', 'scope': 'src'}]
        rows = [{'status': 'RESOLVED', 'query': str(i),
                 'developer_instructions': instructions,
                 'warnings': ['keep warning'], 'discovery': {'resolved_paths': [str(i)]},
                 'target': {'path': str(i), 'nodes': [{'large': 'x' * 5000}], 'outline': [str(i)]},
                 'direct_dependents': [{'path': str(n), 'name': str(n)} for n in range(30)]}
                for i in range(3)]
        rows[-1]['developer_instructions'] = [{'text': 'Different scoped instruction'}]
        payload = {'status': 'BATCH_RESOLVED', 'results': rows}
        original = copy.deepcopy(payload)
        summary = present_context(Path('.'), payload)
        self.assertEqual('SUMMARY', summary['presentation'])
        self.assertEqual(instructions, summary['shared_context']['developer_instructions'][0])
        for before, after in zip(rows, summary['results']):
            self.assertEqual(before['discovery'], after['discovery'])
            self.assertEqual(before['warnings'], after['warnings'])
            self.assertEqual(before['target']['outline'], after['target']['outline'])
            self.assertEqual(22, after['omitted_details']['direct_dependents'])
            self.assertLessEqual(len(after['direct_dependents']), 8)
            ref = after['shared_context_refs']['developer_instructions']
            self.assertEqual(before['developer_instructions'], summary['shared_context']['developer_instructions'][ref])
        full = present_context(Path('.'), payload, full=True)
        self.assertEqual(rows, full['results'])
        self.assertEqual(full['context_digest'], summary['context_digest'])
        self.assertEqual(original, payload)
        self.assertLess(len(json.dumps(summary)), len(json.dumps(full)) / 2)
        for status in ('BATCH_PARTIAL', 'BATCH_FAILED', 'SOURCE_CHANGED_DURING_DISCOVERY'):
            failed = present_context(Path('.'), {**payload, 'status': status})
            self.assertEqual('FULL', failed['presentation'])
            self.assertEqual(rows, failed['results'])
        # A change outside the displayed first eight entries still invalidates reuse.
        changed = copy.deepcopy(payload)
        changed['results'][0]['direct_dependents'][-1]['name'] = 'Changed'
        stale = present_context(Path('.'), changed, since=summary['context_digest'])
        self.assertEqual('FULL', stale['presentation'])
        self.assertEqual('BASELINE_MISMATCH', stale['presentation_reason'])
        self.assertEqual(changed['results'], stale['results'])


    def test_metrics_mixed_versions_privacy_and_no_nested_double_count(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td)
            tm.record_operation(repo,'task','test',2,0)
            tm.record_operation(repo,'task','manifest',1,0,counters={'manifest_calls':1,'secret':123},span_kind='substep')
            result=tm.metrics_report(repo,'task')
            self.assertEqual(2,result['observed_execution_seconds'])
            self.assertEqual(1,result['substeps']['manifest']['attempts'])
            self.assertNotIn('secret',result['counters'])
            self.assertEqual('UNAVAILABLE',result['tokens'])
            with patch.dict(os.environ,{'HARNESS_LOCAL_METRICS':'0'}),patch.object(tm,'_directory',side_effect=AssertionError('IO')):
                with tm.operation_span(repo,'test'):pass
                self.assertEqual('',tm.metric_task_id(repo,[]))

    def test_real_public_cli_full_then_since_and_source_change(self):
        import subprocess,sys
        f=fixtures.ProjectIntelligenceTests();f.setUp()
        try:
            f.mixed_project()
            target='app/src/main/kotlin/com/example/home/HomeScreen.kt'
            command=[sys.executable,tc.__file__,'--repo',str(f.repo),'--file',target,'--json']
            first=json.loads(subprocess.check_output(command,text=True))
            with patch.dict(os.environ, {'ANTIGRAVITY_CONVERSATION_ID': 'same-session'}):
                repeated = json.loads(subprocess.check_output(command, text=True))
            self.assertEqual('SUMMARY', repeated['presentation'])
            self.assertEqual(first['context_digest'], repeated['context_digest'])
            full=json.loads(subprocess.check_output(command+['--full'],text=True))
            self.assertEqual('FULL',full['presentation'])
            self.assertEqual(first['context_digest'],full['context_digest'])
            second=json.loads(subprocess.check_output(command+['--since',first['context_digest']],text=True))
            self.assertEqual('UNCHANGED',second['presentation'])
            self.assertTrue(second['discovery'])
            path=f.repo/target
            path.write_text(path.read_text()+'\nclass NewlyAdded')
            third=json.loads(subprocess.check_output(command+['--since',first['context_digest']],text=True))
            self.assertEqual('FULL',third['presentation'])
        finally:f.tearDown()

    def test_reviewer_accepts_only_valid_presentation_options(self):
        from reviewer_host import discovery_command_allowed as allowed
        prefix='python .agents/harness.py task-context --file src/A.kt --json '
        self.assertTrue(allowed(prefix+'--full'))
        self.assertTrue(allowed(prefix+'--since '+'a'*64))
        self.assertFalse(allowed(prefix+'--since invalid'))
        self.assertFalse(allowed(prefix+'--since '+'a'*64+'; rm file'))

    def test_review_topology_indexes_paths_once(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from review_package import generate_review_topology
        from _graph_core import GraphNode
        counts=[]
        class Node(GraphNode):
            def __getattribute__(self,name):
                if name=='file_path':counts.append(1)
                return super().__getattribute__(name)
        nodes={str(i):Node(str(i),'Class'+str(i),'COMPONENT',file_path='src/C'+str(i)+'.kt') for i in range(500)}
        graph=SimpleNamespace(nodes=nodes,get_targets=lambda _:[],get_sources=lambda _:[])
        engine=Mock(graph=graph)
        with patch('_graph_core.GraphEngine',return_value=engine):
            result=generate_review_topology(Path('.'),['src/C'+str(i)+'.kt' for i in range(50)])
        self.assertIn('Class0',result)
        self.assertLess(len(counts),5000)
        engine.sync.assert_called_once()

    def test_malformed_cursor_rejected_before_discovery(self):
        with patch.object(tc,'resolve_task_context',side_effect=AssertionError('discovery')),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):tc.main(['--file','a.kt','--since','bad','--json'])

if __name__=='__main__':unittest.main()

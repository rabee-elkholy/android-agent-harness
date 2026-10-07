"""Compare warm legacy router performance to HEAD and measure bounded optional reports."""
from __future__ import annotations
import argparse
import contextlib
import io
import json
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = """
import json, statistics, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from workflow import resolve_next_action
repo=Path(sys.argv[2])
resolve_next_action(repo, 'feature')
for line in sys.stdin:
 start=time.perf_counter()
 action=resolve_next_action(repo, 'feature')
 print(json.dumps({'ms': (time.perf_counter()-start)*1000, 'code': action['code']}), flush=True)
"""

def measure(function, repeats=25):
    function()
    samples=[]
    for _ in range(repeats):
        start=time.perf_counter()
        function()
        samples.append((time.perf_counter()-start)*1000)
    return {"median_ms": statistics.median(samples), "p95_ms": sorted(samples)[int(0.95*(len(samples)-1))]}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args=parser.parse_args()
    sys.path.insert(0, str(ROOT / "agents/scripts"))
    from _verification_value_selftest import PublicWorkflowContracts, contract
    from verification_contract import coverage_report, bind_evidence
    from evidence_store import EvidenceStore
    from task_metrics import record_operation, metrics_report
    from _vnext_common import atomic_write_json
    result={"method": "25 paired warm repetitions, alternating order; router HEAD vs working tree; no Android or network", "legacy_router": {}, "optional": {}}
    with tempfile.TemporaryDirectory() as temp:
        baseline=Path(temp)/"baseline"
        archived=subprocess.run(["git", "archive", "--format=zip", "HEAD", "agents"], cwd=ROOT, check=True, capture_output=True).stdout
        with zipfile.ZipFile(io.BytesIO(archived)) as z:
            z.extractall(baseline)
        for count in (1, 500):
            fixture=PublicWorkflowContracts()
            fixture.setUp()
            try:
                if count>1:
                    directory=fixture.repo / "docs"
                    directory.mkdir()
                    for index in range(count):
                        (directory / f"page-{index}.md").write_text("Fixture documentation\n")
                    subprocess.run(["git", "add", "docs"], cwd=fixture.repo, check=True, capture_output=True)
                    subprocess.run(["git", "commit", "-qm", "benchmark fixture"], cwd=fixture.repo, check=True, capture_output=True)
                with contextlib.redirect_stdout(io.StringIO()):
                    fixture.start(False)
                row={}
                sources={"HEAD": baseline / "agents/scripts", "working_tree": ROOT / "agents/scripts"}
                processes={name: subprocess.Popen([sys.executable, "-u", "-c", WORKER, str(source), str(fixture.repo)],
                    cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    for name, source in sources.items()}
                samples={name: [] for name in sources}
                try:
                    for index in range(26):
                        order=list(sources) if index % 2 == 0 else list(reversed(sources))
                        for name in order:
                            process=processes[name]
                            process.stdin.write("measure\n")
                            process.stdin.flush()
                            observed=json.loads(process.stdout.readline())
                            if index:
                                samples[name].append(observed["ms"])
                            row[name]={"median_ms": statistics.median(samples[name]) if samples[name] else 0,
                                       "p95_ms": sorted(samples[name])[int(0.95*(len(samples[name])-1))] if samples[name] else 0,
                                       "code": observed["code"]}
                finally:
                    for process in processes.values():
                        process.stdin.close()
                        process.wait(timeout=30)
                        if process.returncode:
                            raise RuntimeError(process.stderr.read())
                row["median_change_percent"]=(row["working_tree"]["median_ms"] / row["HEAD"]["median_ms"]-1)*100
                result["legacy_router"][str(count)+"_fixture_docs"]=row
            finally:
                fixture.tearDown()
        repo=Path(temp)/"reports"
        repo.mkdir()
        store=EvidenceStore(repo / ".agents/state")
        current={"run_id": "run", "delivery_snapshot_sha256": "snapshot", "change_set_sha256": "change"}
        plan={"task_id": "task", "plan_sha256": "plan", "verification_contract": contract()}
        plan["verification_contract"]["criteria"]=[dict(contract()["criteria"][0], id=f"criterion-{index}") for index in range(32)]
        store.write(snapshot="snapshot", run_id="run", name="unit_tests", producer="run_tests_gate", harness_version="1", change_set="change", status="PASS", evidence={"test_outcomes": {"Tests#refresh": "PASS"}})
        for item in plan["verification_contract"]["criteria"]:
            bind_evidence(plan, current, store, item["id"], "unit_tests", "Tests#refresh")
        result["optional"]["coverage_32_criteria"]=measure(lambda: coverage_report(plan, current, store))
        directory=repo / ".agents/state/metrics/task"
        for index in range(512):
            atomic_write_json(directory / f"{index}.json", {"schema_version": 1, "task_id": "task", "operation": "test", "duration_seconds": 1, "started_at": index, "ended_at": index+1, "exit_code": 0})
        result["optional"]["metrics_report_512_events"]=measure(lambda: metrics_report(repo, "task"))
        result["optional"]["metrics_collection_at_cap"]=measure(lambda: record_operation(repo, "task", "test", 1, 0))
        result["optional"]["metrics_collection_writing"]=measure(lambda: record_operation(repo, "new-task", "test", 1, 0))
        result["limitations"]="Local Windows warm timing; order and filesystem noise may affect percentages. Device replay, cold startup, host reviewer time, and exact-commit CI are excluded."
    Path(args.output).write_bytes((json.dumps(result, indent=2)+"\n").encode())
    print(json.dumps(result, indent=2))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())

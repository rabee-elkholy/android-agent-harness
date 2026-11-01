"""Paired baseline/candidate context and topology measurements; development only."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys

WORKER = r'''
import contextlib,io,json,sys,time
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'agents/scripts'))
import _project_intelligence_selftest as fixture
import task_context as tc
f=fixture.ProjectIntelligenceTests();f.setUp()
try:
 f.mixed_project()
 count=int(sys.argv[2])
 if count == -1:
  f.write("shared/src/commonMain/kotlin/sample/Shared.kt", "package sample\nclass Shared")
  f.write("shared/src/iosMain/kotlin/sample/Native.kt", "package sample\nclass Native")
 for i in range(count):f.write('app/src/main/kotlin/com/example/Extra'+str(i)+'.kt','package com.example\nclass Extra'+str(i))
 f.write('.agents/project-context/project-notes.md','# Project Notes\n\n## Domain Conventions & Context\n'+('Use the existing project patterns.\n'*300))
 files=['app/src/main/kotlin/com/example/home/HomeScreen.kt','feature/profile/src/main/java/com/example/profile/ProfilePresenter.java']
 def run():
  with contextlib.redirect_stdout(io.StringIO()),patch.object(tc,'_load_facts',wraps=tc._load_facts) as reads:
   value=tc.resolve_task_contexts(f.repo,files=files)
  return value,reads.call_count
 cold_started=time.perf_counter();run();cold_query_ms=(time.perf_counter()-cold_started)*1000
 tc.GraphEngine(f.repo).sync()
 first,reads=run()
 print("READY",flush=True)
 times=[]
 for _ in sys.stdin:
  start=time.perf_counter();value,reads=run();times=[(time.perf_counter()-start)*1000]
  try:
   from context_presentation import present_context
   full=present_context(f.repo,value); compact=present_context(f.repo,value,since=full['context_digest'])
  except ImportError: full=compact=value
  print(json.dumps({'median_ms':times[0],'p95_ms':times[0], 'facts_reads':reads,'full_bytes':len((json.dumps(full,ensure_ascii=True,indent=2)+"\n").encode()),'repeated_bytes':len((json.dumps(compact,ensure_ascii=True,indent=2)+"\n").encode()),'cold_query_ms':cold_query_ms,'status':value['status']}),flush=True)
finally:f.tearDown()
'''

def main():
 p=argparse.ArgumentParser();p.add_argument('--baseline',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 root=Path(__file__).resolve().parents[1]; rows=[]
 for count in (0,-1,500):
  row={'extra_files':count,'scenario':'mixed' if count==0 else 'kmp' if count==-1 else 'large'}
  workers={}; samples={label:[] for label in ('baseline','candidate')}
  try:
   for label,path in [('baseline',a.baseline),('candidate',str(root))]:
    workers[label]=subprocess.Popen([sys.executable,'-c',WORKER,path,str(count)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    ready=workers[label].stdout.readline()
    if ready.strip()!='READY':raise RuntimeError(workers[label].stderr.read())
   for iteration in range(25):
    for label in (('baseline','candidate') if iteration%2==0 else ('candidate','baseline')):
     worker=workers[label];worker.stdin.write('run\n');worker.stdin.flush()
     samples[label].append(json.loads(worker.stdout.readline()))
   for label,items in samples.items():
    row[label]={**items[-1], 'median_ms':statistics.median(v['median_ms'] for v in items), 'p95_ms':sorted(v['median_ms'] for v in items)[23]}
   rows.append(row)
  finally:
   for worker in workers.values():
    worker.stdin.close();worker.wait(timeout=30)
 data={'method':'25 paired warm samples, alternating checkout order, content cache warmed explicitly; timing informational.','baseline':a.baseline,'candidate_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'scenarios':rows}
 Path(a.output).write_text(json.dumps(data,indent=2)+'\n');print(json.dumps(data,indent=2))
if __name__=='__main__':main()

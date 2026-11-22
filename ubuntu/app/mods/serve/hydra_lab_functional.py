"""Admitted functional lab path. Stops owned runtime before persisting terminal output."""
import hashlib,json,os,time,uuid
from pathlib import Path
from serve.hydra_execution_v10 import exclusive_execute
PATHS={'/lab/ingest':'ingest','/lab/retrieve':'retrieve','/lab/chat':'chat','/lab/performance':'performance','/lab/score':'score','/lab/score-prefix':'prefix_score','/lab/system-one-bridge':'semantic_bridge','/lab/provider-off':'unavailable'}
def validate(body):
 if not isinstance(body,dict) or set(body)!={'path','request'} or body['path'] not in PATHS or not isinstance(body['request'],dict):raise ValueError('unsupported laboratory functional request')
 return body
@exclusive_execute
def _execute(workspace,body,_key=None):
 from serve.hydra_lab_benchmarks import now,digest,sample,summary,reserve_system_runtime
 from serve.hydra_lab_app import lab_gpu_layers
 import psutil
 body=validate(body);lab=workspace.lab;p=lab.profile;key=_key or uuid.uuid4().hex
 if not workspace.lock.acquire(False):raise ValueError('BLOCKED_BUSY')
 original=lab.data;folder=workspace.store.root/'runs'/key;folder.mkdir(parents=True,exist_ok=False);system=None;failure=None;output=None;live=None
 row=dict(run_id=key,origin='E2E_TEST',status='RUNNING',timestamp=now(),model='local/Qwen3-0.6B-Q8_0',model_hash=p['model_sha256'],runtime=p['runtime'],runtime_hash=digest(p['runtime_manifest']),backend='NOT_STARTED',quantization='Q8_0',profile='functional-cpu-v11',prompt_id='functional-'+body['path'].split('/')[-1],prompt=json.dumps(body['request'],ensure_ascii=False),prompt_hash=digest(body['request']),template_hash=p['model_sha256'],parameters={'functional_path':body['path']},configuration={k:v for k,v in p.items() if k not in ('key','dense')},request_json=body,samples=[],warmup=[],summary={},quality_gate='NOT_APPLICABLE',cleanup=False,error=None,exit_code=None,log_path=str(folder/'runtime.log'),artifacts=str(folder),events=[],owner_pid=os.getpid(),owner_created=psutil.Process().create_time(),measurement_scope='functional_app_request_cold_start_separate')
 if body['path'] in ('/lab/ingest','/lab/retrieve'):
  row.update(model='hydra/graph-memory',model_hash=None,runtime='GraphMemory + authorized local dense provider',runtime_hash=hashlib.sha256(Path(__file__).with_name('hydra_graph_memory.py').read_bytes()).hexdigest(),quantization='NOT_APPLICABLE',template_hash=None)
 row['comparison_key']=digest([row['model_hash'],row['runtime_hash'],row['prompt_hash'],'functional-v11'])
 def event(kind,detail=None):row['events'].append(dict(at=now(),monotonic=time.monotonic(),kind=kind,detail=detail));workspace.store.put(row)
 started=time.perf_counter()
 try:
  event('admission')
  from serve.hydra_lab_live import LiveMonitor
  live=LiveMonitor(workspace,row)
  if lab_gpu_layers(p):row['status']='BLOCKED_GPU_QUARANTINE';raise ValueError('functional v11 requires explicit CPU profile')
  if psutil.virtual_memory().available<12*1024**3:row['status']='RESOURCE_BLOCKED';raise MemoryError('RAM below 12GiB')
  system=reserve_system_runtime(Path(__file__).resolve().parents[1]);lab.stop_backend();lab.data=folder
  from serve.hydra_graphify_runtime import repository_context
  event('request_start')
  with repository_context(lab,body) as graphify:
   output=getattr(lab,PATHS[body['path']])(body['request'])
   if graphify is not None:output['graphify']=graphify
  row['original_result']=output # Preserve partial native scores and boundary refusals too.
  if body['path']=='/lab/performance':
   from serve.hydra_performance_v15 import require_complete
   require_complete(output)
  row['backend']=lab.status()['backend'] if lab.child else 'CPU' if body['path'] in ('/lab/performance','/lab/score','/lab/score-prefix','/lab/system-one-bridge') else 'SQLITE_OR_CPU_PROVIDER'
  if body['path']=='/lab/performance':
   row.update(origin='BENCHMARK',real_execution_kind='fixed-budget CPU performance; not functional task completion',measurement_scope='admitted application sequence including identity/startup/generation/cleanup',samples=output['samples'],summary=summary(output['samples']),protocol_sha256=output['protocol_sha256'])
  if body['path']=='/lab/chat':row['samples']=[sample(output,output['end_to_end_ms'])];row['summary']=summary(row['samples']);row['startup_ms']=output.get('startup_ms')
  if body['path'] in ('/lab/score','/lab/score-prefix','/lab/system-one-bridge') and output.get('status')!='complete':raise RuntimeError('scoring incomplete; preserve original result')
  row['original_result']=output;row['functional_e2e_ms']=(time.perf_counter()-started)*1000;event('request_complete')
 except Exception as exc:
  from serve.hydra_task_completion import TaskIncomplete
  if isinstance(exc,TaskIncomplete):
   row['status']='TASK_INCOMPLETE';output={'response':exc.response,'task_status':'TASK_INCOMPLETE'};row['original_result']=output
  failure=type(exc).__name__+': '+str(exc);row['error']=failure;row['http_status']=400 if isinstance(exc,(ValueError,TypeError,KeyError)) else 503
  if row['status']=='RUNNING':row['status']='TIMEOUT' if isinstance(exc,TimeoutError) else 'FAIL'
  event('error',failure)
 finally:
  try:
   lab.stop_backend();row['cleanup']=lab.child is None
   from serve.hydra_lab_app import attest_model_loaders
   row['model_loaders']=attest_model_loaders(lab.calls,folder)
   if row['model_loaders']:row['configuration']['effective_model_loaders']=row['model_loaders']
   if any(x.get('candidate') for x in row['model_loaders']):
    row['reference_runtime']=row['runtime'];row['runtime']=row['model_loaders'][0]['runtime'];row['runtime_hash']=row['model_loaders'][0]['manifest_sha256']
    row['comparison_key']=digest([row['model_hash'],row['runtime_hash'],row['prompt_hash'],'functional-v14-iocp'])
   row['exit_code']=next((v['exit_code'] for v in reversed(lab.calls) if v['event']=='backend_cleanup'),None)
  except Exception as exc:row['cleanup']=False;row['error']='cleanup: '+str(exc);row['status']='FAIL'
  if system:system.release()
  if live:live.close()
  lab.data=original;workspace.lock.release();row['finished_at']=now();event('cleanup',{'owned_runtime_stopped':row['cleanup'],'application_lock_released':True})
 if not failure and row['cleanup']:row['status']='PASS'
 row['real_execution_kind']='fixed-budget CPU performance; not functional task completion' if body['path']=='/lab/performance' else 'native CPU scoring; isolated question bridge, no System One parity' if body['path']=='/lab/system-one-bridge' else 'native CPU scoring' if body['path'] in ('/lab/score','/lab/score-prefix') else 'CPU application inference' if body['path']=='/lab/chat' else 'real local I/O; no inference unless explicit dense provider'
 (folder/'response.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
 row['artifact_hashes']={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in folder.iterdir() if x.is_file()};workspace.store.put(row)
 return row

def execute(workspace,body,_key=None):
 return _execute(workspace,validate(body),_key=_key)

def response(row):
 value=dict(row.get('original_result') or {},benchmark_run_id=row['run_id'],run_status=row['status'])
 if row.get('error'):value['error']=row['error']
 return row.get('http_status') or (200 if row['status']=='PASS' else 409 if row['status'] in ('BLOCKED_BUSY','BLOCKED_FEATURE','BLOCKED_GPU_QUARANTINE') else 503),value

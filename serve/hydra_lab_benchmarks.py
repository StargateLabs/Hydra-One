from serve.hydra_execution_v10 import guarded_run
from serve.hydra_execution_v10 import exclusive_execute
"""Persistent benchmark workspace; imported evidence and real lab runs stay distinct."""
from contextlib import contextmanager
import csv,hashlib,io,json,os,re,sqlite3,statistics,subprocess,threading,time,uuid
from pathlib import Path
from datetime import datetime,timezone
CANONICAL='9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031'
def reserve_system_runtime(root):
 from serve.gpu_lease import GpuLease
 return GpuLease(root,'hydra-benchmark-lab').acquire()
def probe_environment(source=None):
 result=dict(os.environ if source is None else source);result.update(HIP_VISIBLE_DEVICES='0',ROCR_VISIBLE_DEVICES='0');result.pop('GGML_BACKEND_PATH',None);return result
def acquire_runtime_lock(root):
 handle=(Path(root)/'runtime.lock').open('a+b')
 if handle.tell()==0:handle.write(b'0');handle.flush()
 handle.seek(0)
 try:
  if os.name=='nt':
   import msvcrt
   msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
  else:
   import fcntl
   fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 except (OSError,IOError):handle.close();raise ValueError('another lab benchmark owns this registry runtime lease')
 return handle
def release_runtime_lock(handle):
 try:
  handle.seek(0)
  if os.name=='nt':
   import msvcrt
   msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
  else:
   import fcntl
   fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
 finally:handle.close()
def active_owner(row):
 try:
  import psutil
  return bool(row.get('owner_pid')) and abs(psutil.Process(row['owner_pid']).create_time()-row['owner_created'])<.01
 except (KeyError,psutil.Error):return False
def now():return datetime.now(timezone.utc).isoformat()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def comparison_key(row):
 values={k:row.get(k) for k in ('model_hash','runtime_hash','prompt_hash','parameters','quantization','template_hash','measurement_scope')}
 complete=all(values.get(k) not in (None,'UNKNOWN','NOT_AVAILABLE','NOT_VERIFIED') for k in ('model_hash','runtime_hash','prompt_hash','quantization','template_hash'))
 return ('' if complete else 'INCOMPLETE:')+digest(values)
def summary(samples):
 out={}
 for key in ('e2e_ms','prefill_ms','prefill_tps','decode_ms','decode_tps','ttft_ms','tokens'):
  vals=[s[key] for s in samples if isinstance(s.get(key),(int,float))]
  out[key]=dict(median=statistics.median(vals),min=min(vals),max=max(vals),stdev=statistics.stdev(vals) if len(vals)>1 else None,n=len(vals)) if vals else None
 return out
def validate_runner_request(body):
 if not isinstance(body,dict) or set(body)-{'profile','prompt','prompt_id','model_id','samples','max_tokens','thinking','graph','variant','gpu_layers','checkpoint','state_mode','followup'}:raise ValueError('unsupported benchmark fields')
 if 'checkpoint' in body and type(body['checkpoint']) is not bool:raise ValueError('checkpoint must be boolean')
 if 'thinking' in body:
  if body['thinking'] not in ('auto','on','off') or body.get('profile') not in ('cpu','v20-bonsai-hybrid-16','v20-bonsai-vulkan-full','v21-bonsai-hybrid') or body.get('model_id') not in ('prism-ml/Ternary-Bonsai-2-27B-gguf','huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF','cdiamond/Qwen3.8-27B-iMatrix-NVFP4-MTP-GGUF'):raise ValueError('thinking mode requires a supported native CPU text adapter')
 if str(body.get('profile','')).startswith('v20-bonsai-'):
  from serve.hydra_engine_v20 import validate
  validate(body)
 if body.get('profile')=='v21-bonsai-hybrid':
  from serve.hydra_engine_v21 import validate
  validate(body)
 elif 'gpu_layers' in body:raise ValueError('V21_EXPLICIT_NATIVE_PROFILE_REQUIRED')
 if body.get('checkpoint'):
  if body.get('profile') not in ('cpu','v21-bonsai-hybrid') or body.get('model_id')!='prism-ml/Ternary-Bonsai-2-27B-gguf' or body.get('thinking')!='off' or body.get('samples')!=2:raise ValueError('NATIVE_STATE_BONSAI_SESSION_REQUIRED')
  if body.get('state_mode')!='continuation' or not isinstance(body.get('followup'),str) or not 1<=len(body['followup'])<=200:raise ValueError('NATIVE_STATE_REPEATED_PREFIX_UNSUPPORTED; recurrent state cannot rewind a restored final-state slot; use explicit continuation')
 elif any(k in body for k in ('state_mode','followup')):raise ValueError('NATIVE_STATE_NOT_REQUESTED')
 if 'graph' in body and (type(body['graph']) is not bool or body.get('thinking') not in ('on','off')):raise ValueError('native graph requires explicit thinking mode')
 if 'variant' in body and (not body.get('graph') or body['variant'] not in ('H0','H1','H1v2')):raise ValueError('explicit native retrieval required')
 v8_profile=str(body.get('profile','')).startswith('v8-') or body.get('profile')=='hydra-fastpath-v1'
 v7_profile=str(body.get('profile','')).startswith('v7-qwen-')
 if v7_profile:
  from serve.hydra_v7_experiments import options
  options(body['profile'])
  if body.get('model_id')!='local/Qwen3-0.6B-Q8_0':raise ValueError('v7 model mismatch')
 v6_profile=str(body.get('profile','')).startswith('prism-v6-')
 prism_profile=str(body.get('profile','')).startswith('prism-v5-') or body.get('profile')=='prism-bonsai27b-vulkan-verified-v1'
 if v6_profile:
  from serve.hydra_prefill_campaign import configuration,MODEL_ID
  configuration(body['profile'])
  if body.get('model_id')!=MODEL_ID:raise ValueError('v6 restricted to frozen Bonsai')

 if prism_profile:
  from serve.hydra_prism_campaign import profile_spec,MODEL_ID
  profile_spec(body['profile'])
  if body.get('model_id')!=MODEL_ID:raise ValueError('Prism profile restricted to attested Bonsai model')
 elif not v8_profile and not v6_profile and not v7_profile and body.get('profile') not in ('cpu','gpu4','qwen06b-gpu-full-verified-v1','v20-bonsai-hybrid-16','v20-bonsai-vulkan-full','v21-bonsai-hybrid'):raise ValueError('unsupported profile')
 if body.get('model_id','local/Qwen3-0.6B-Q8_0') not in ('local/Qwen3-0.6B-Q8_0','audio-cpp/audio.cpp-gguf','mudler/locate-anything.cpp-gguf','prism-ml/Ternary-Bonsai-2-27B-gguf','unsloth/Qwen-Image-2.1-GGUF','abenzerps/Qwen-Image-2.1-Uncensored-Quantized','unsloth/Z-Image-Turbo-GGUF','huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF','cdiamond/Qwen3.8-27B-iMatrix-NVFP4-MTP-GGUF','Serveurperso/YuE2-GGUF'):raise ValueError('model requires a verified family adapter and resource budget')
 if not isinstance(body.get('prompt'),str) or not 1<=len(body['prompt'])<=(24000 if v8_profile else 800) or not isinstance(body.get('prompt_id'),str) or not 1<=len(body['prompt_id'])<=80:raise ValueError('invalid prompt')
 for name,maximum in [('samples',15 if v8_profile else 7 if v6_profile or v7_profile else 5),('max_tokens',128)]:
  if type(body.get(name,5 if name=='samples' else 64)) is not int or not 1<=body.get(name,5 if name=='samples' else 64)<=maximum:raise ValueError('invalid '+name)
 if body.get('profile')=='cpu' and body.get('model_id','local/Qwen3-0.6B-Q8_0') not in ('local/Qwen3-0.6B-Q8_0','audio-cpp/audio.cpp-gguf') and not (body.get('thinking') in ('on','off') and body.get('samples') in (1,2)) and body.get('samples',5)!=1:raise ValueError('native single-shot adapter requires samples=1; no repetitions are silently ignored')
 return dict(body,model_id=body.get('model_id','local/Qwen3-0.6B-Q8_0'),samples=body.get('samples',5),max_tokens=body.get('max_tokens',64))

class BenchmarkCancelled(RuntimeError):pass

class Registry:
 def __init__(self,root):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.path=self.root/'benchmarks.sqlite'
  with self.db() as c:
   c.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
   c.execute('CREATE TABLE IF NOT EXISTS catalog_entries (model_id TEXT PRIMARY KEY,payload TEXT NOT NULL,attested_at TEXT NOT NULL)')
   c.execute('CREATE TABLE IF NOT EXISTS run_events (run_id TEXT, seq INTEGER, payload TEXT NOT NULL, PRIMARY KEY(run_id,seq))')
   c.execute("CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON run_events BEGIN SELECT RAISE(ABORT,'append-only events'); END")
   c.execute("CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON run_events BEGIN SELECT RAISE(ABORT,'append-only events'); END")
   for key,payload in c.execute('SELECT id,payload FROM runs').fetchall():
    row=json.loads(payload)
    if row['status'] in ('RUNNING','QUEUED') and not active_owner(row):row['status']='INTERRUPTED';row.setdefault('events',[]).append(dict(at=now(),kind='interrupted',detail='app restart; no automatic retry'));c.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(row,ensure_ascii=False),key))
  # Populate append-only event storage for pre-v3 records without changing event data.
  for row in self.list():self.put(row)
 @contextmanager
 def db(self):
  c=sqlite3.connect(self.path,timeout=5)
  try:
   with c:yield c
  finally:c.close()
 def put(self,row,insert_only=False):
  from serve.hydra_execution_v10 import publication_row
  row=publication_row(row)
  row.update(created_at=row.get('created_at',row.get('timestamp')),started_at=row.get('started_at'),ended_at=row.get('finished_at'),test_type=row.get('test_type',row.get('real_execution_kind','benchmark')),model_id=row.get('model_id',row.get('model')),runtime_id=row.get('runtime'),config_json=row.get('configuration',{}),request_json=row.get('request_json',{'prompt':row.get('prompt'),'parameters':row.get('parameters',{})}),metrics_json=row.get('summary',{}),output_artifact=row.get('artifacts'),error_code=row.get('status') if row.get('error') else None,cleanup_status=row.get('cleanup'))
  with self.db() as c:
   if insert_only and c.execute('SELECT 1 FROM runs WHERE id=?',(row['run_id'],)).fetchone():return
   previous=c.execute('SELECT payload FROM run_events WHERE run_id=? ORDER BY seq',(row['run_id'],)).fetchall()
   events=row.get('events',[])
   if len(events)<len(previous) or any(json.loads(v[0])!=events[i] for i,v in enumerate(previous)):raise ValueError('existing events are immutable')
   for i in range(len(previous),len(events)):c.execute('INSERT INTO run_events VALUES(?,?,?)',(row['run_id'],i,json.dumps(events[i],ensure_ascii=False,allow_nan=False)))
   c.execute('INSERT OR REPLACE INTO runs(id,payload) VALUES(?,?)',(row['run_id'],json.dumps(row,ensure_ascii=False,allow_nan=False)))
 def get(self,key):
  with self.db() as c:r=c.execute('SELECT payload FROM runs WHERE id=?',(key,)).fetchone()
  if not r:raise ValueError('unknown run')
  return json.loads(r[0])
 def list(self):
  with self.db() as c:return sorted([json.loads(r[0]) for r in c.execute('SELECT payload FROM runs')],key=lambda r:r.get('timestamp',''),reverse=True)
 def export(self,kind):
  rows=self.list()
  if kind=='json':return json.dumps(rows,ensure_ascii=False,indent=2).encode(), 'application/json'
  buf=io.StringIO();fields=['run_id','origin','timestamp','model','model_hash','runtime_hash','backend','profile','quantization','prompt_id','prompt_hash','status','quality_gate','comparison_key','e2e_median_ms','decode_tps_median','error','exit_code'];w=csv.DictWriter(buf,fieldnames=fields);w.writeheader()
  for r in rows:w.writerow({**{k:r.get(k) for k in fields if k not in ('e2e_median_ms','decode_tps_median')},'e2e_median_ms':(r.get('summary',{}).get('e2e_ms') or {}).get('median'),'decode_tps_median':(r.get('summary',{}).get('decode_tps') or {}).get('median')})
  return ('\ufeff'+buf.getvalue()).encode(),'text/csv'
def read_artifact(row,name):
 if name not in row.get('artifact_hashes',{}) or Path(name).name!=name or Path(name).suffix not in ('.wav','.png','.json','.txt','.abc'):raise ValueError('unknown output artifact')
 root=Path(row['artifacts']).resolve();path=(root/name).resolve()
 if not path.is_relative_to(root) or path.is_symlink() or not path.is_file() or path.stat().st_size>16*1024**2:raise ValueError('artifact unavailable')
 data=path.read_bytes()
 if hashlib.sha256(data).hexdigest()!=row['artifact_hashes'][name]:raise ValueError('artifact integrity mismatch')
 return data

def export_samples(row):
 buf=io.StringIO();fields=['run_id','repetition','e2e_ms','prefill_ms','prefill_tps','decode_ms','decode_tps','ttft_ms','tokens','prompt_tokens','audio_seconds','real_time_factor','audio_bytes','output','output_sha256'];w=csv.DictWriter(buf,fieldnames=fields);w.writeheader()
 for i,s in enumerate(row.get('samples',[])):w.writerow({k:row['run_id'] if k=='run_id' else i+1 if k=='repetition' else s.get(k) for k in fields})
 return ('\ufeff'+buf.getvalue()).encode()
def sample(response,e2e,diagnostics=None):
 r=response['response'];t=r.get('timings',{});u=r.get('usage',{});diag=diagnostics or {}
 return dict(e2e_ms=e2e,prefill_ms=t.get('prompt_ms'),prefill_tps=t.get('prompt_per_second'),decode_ms=t.get('predicted_ms'),decode_tps=t.get('predicted_per_second'),ttft_ms=diag.get('first_content_s')*1000 if diag.get('first_content_s') is not None else None,tokens=u.get('completion_tokens'),prompt_tokens=u.get('prompt_tokens'),output=r['choices'][0]['message']['content'],response=response)
def import_history(store,source):
 source=Path(source);protocol=json.loads((source/'protocol.json').read_text(encoding='utf-8'))
 if protocol.get('recovery_format')=='saved-registry-records-v1':
  # Preserve genuine saved rows; never fabricate the missing native run files.
  if protocol.get('records_file')!='recovered-records.json':raise ValueError('invalid recovered history path')
  path=source/'recovered-records.json'
  if path.stat().st_size>16*1024**2:raise ValueError('recovered history exceeds budget')
  raw=path.read_bytes()
  if hashlib.sha256(raw).hexdigest()!=protocol.get('records_sha256'):raise ValueError('recovered history integrity mismatch')
  rows=json.loads(raw)
  if not isinstance(rows,list) or len(rows)!=6:raise ValueError('incomplete recovered history')
  identities=set()
  for row in rows:
   if not isinstance(row,dict) or row.get('origin')!='IMPORTED_HISTORICAL' or row.get('status')!='IMPORTED_HISTORICAL' or row.get('model_hash')!=CANONICAL or not isinstance(row.get('run_id'),str) or not row['run_id'].startswith('hist-') or row['run_id'] in identities:raise ValueError('invalid recovered history identity')
   identities.add(row['run_id'])
  for row in rows:store.put(row,insert_only=True)
  return
 metrics=json.loads((source/'metrics.json').read_text(encoding='utf-8'))
 for layers in (0,4,29):
  folder=source/'runs'/f'{layers:02d}-layers';x=json.loads((folder/'result.json').read_text(encoding='utf-8'));p=json.loads((folder/'profile.json').read_text(encoding='utf-8'))
  if p['model_sha256']!=CANONICAL:raise ValueError('historical canonical model mismatch')
  for name in ('breve','lungo'):
   vals=[v for v in x['measurements'] if v['prompt']==name];samples=[sample(v['response'],v['end_to_end_ms']) for v in vals];metric=next(r for r in metrics['rows'] if r['layers_actual']==layers and r['prompt']==name)
   row=dict(run_id='hist-'+digest([str(source),layers,name])[:20],origin='IMPORTED_HISTORICAL',status='IMPORTED_HISTORICAL',timestamp=datetime.fromtimestamp((folder/'result.json').stat().st_mtime,timezone.utc).isoformat(),model='Qwen3-0.6B-Q8_0',model_hash=p['model_sha256'],runtime=p['runtime'],runtime_hash=digest(p['runtime_manifest']),backend='CPU' if layers==0 else 'ROCm',quantization='Q8_0',profile=f'historical-ngl{layers}',configuration={k:v for k,v in p.items() if k not in ('key','dense')},parameters=protocol['parameters'],template_hash=p['model_sha256'],prompt_id=name,prompt=protocol['prompts'][name],prompt_hash=protocol['prompt_sha256'][name],warmup=[v for v in x['warmups'] if v['prompt']==name],startup_ms=metric['startup_ms'],samples=samples,summary=summary(samples),quality_gate=metric['quality_gate'],actual_layers=layers,total_layers=29,ram_before=None,vram_free_before_mib=metric['vram_free_before_mib'],memory_reported=metric['memory_runtime_lines'],error=None,exit_code=x['exit_code'],cleanup=not x['residual_owned_pids'],log_path=str(folder/'data/runtime.log'),artifacts=str(folder),events=[dict(at=now(),kind='historical_import',detail='original run retained; not a new inference')])
   row['timestamp_basis']='original result artifact mtime; import event timestamp is separate';row['measurement_scope']='client_http_round_trip';row['comparison_key']=comparison_key(row);store.put(row,insert_only=True)
def import_functional_history(store,source):
 source=Path(source)
 for file in sorted(source.glob('**/result.json')):
  if 'graphify-before' in file.parts:continue
  x=json.loads(file.read_text(encoding='utf-8'));profile=file.parent/'profile.json'
  if not profile.is_file():continue
  p=json.loads(profile.read_text(encoding='utf-8'));requests=[(i,r) for i,r in enumerate(x.get('requests',[])) if r.get('path') in ('/lab/chat','/lab/score','/lab/retrieve')]
  if not requests and x.get('error'):requests=[(-1,{'path':'startup','request':None,'response':{},'http_status':None})]
  for i,r in requests:
   path=r['path'];response=r.get('response',{});status=r.get('http_status');is_chat=path=='/lab/chat';retrieval=path=='/lab/retrieve';samples=[]
   if status==200 and is_chat:samples=[sample(response,r['end_to_end_ms'])]
   row=dict(run_id='hist-func-'+digest([str(file),i])[:20],origin='IMPORTED_HISTORICAL',status='IMPORTED_HISTORICAL' if status==200 else 'FAIL',timestamp=datetime.fromtimestamp(file.stat().st_mtime,timezone.utc).isoformat(),timestamp_basis='source result artifact mtime',model='Hydra Graph — retrieval' if retrieval else 'Qwen3-0.6B-Q8_0',model_hash=None if retrieval else p.get('model_sha256'),runtime='software retrieval / embedding, not generative runtime' if retrieval else p.get('runtime'),runtime_hash=None if retrieval else digest(p.get('runtime_manifest')),backend='retrieval' if retrieval else 'ROCm requested (offload not attested in this import)' if p.get('gpu_layers') else 'CPU',quantization='NOT_APPLICABLE' if retrieval else 'Q8_0',profile='functional-v1-'+x.get('scenario',file.parent.name),configuration={k:v for k,v in p.items() if k not in ('key','dense')},parameters={'functional_path':path,'original_request':r.get('request')},template_hash=None if retrieval else p.get('model_sha256'),prompt_id='functional-v1-'+path.split('/')[-1],prompt=json.dumps(r.get('request'),ensure_ascii=False),prompt_hash=digest(r.get('request')),warmup=[],samples=samples,summary=summary(samples),original_result=response,source_result=str(file),real_execution_kind='retrieval-only' if retrieval else 'functional raw scoring' if path=='/lab/score' else 'generation' if is_chat else 'startup only',quality_gate='NOT_APPLICABLE' if retrieval else 'NOT_AVAILABLE',actual_layers=None,total_layers=None,error=response.get('error') or x.get('error') if status!=200 else None,exit_code=x.get('exit_code'),cleanup=x.get('app_stopped') and not x.get('residual_owned_pids'),log_path=str(file.parent/'data/runtime.log'),artifacts=str(file.parent),events=[dict(at=now(),kind='historical_functional_import',detail='Single functional attempt, not repeated benchmark; original HTTP status '+str(status))])
   row['measurement_scope']='client_http_round_trip';row['comparison_key']=comparison_key(row);store.put(row,insert_only=True)
def catalog_evidence(entry,runs):
 row=dict(entry)
 matching=[r for r in runs if r.get('model')==row['id'] or row['id']=='local/Qwen3-0.6B-Q8_0' and r.get('model')=='Qwen3-0.6B-Q8_0']
 row['benchmarks']=[r['run_id'] for r in matching]
 attempts=sorted([r for r in matching if r.get('origin') in ('LIVE_APP','E2E_TEST','BENCHMARK') and r.get('parameters',{}).get('functional_path') not in ('/lab/ingest','/lab/retrieve','/lab/provider-off')],key=lambda r:r.get('timestamp',''),reverse=True)
 if any(r['status'] in ('PASS','COMPLETED') for r in attempts):row['status']='E2E_VERIFIED'
 elif row['status']=='FAILED':row['status']='ADAPTER_IMPLEMENTED'
 if attempts:row.update(last_execution_status=attempts[0]['status'],last_execution_error=attempts[0].get('error'))
 return row

class Workspace:
 def __init__(self,lab):
  self.lab=lab;self.store=Registry(lab.profile.get('benchmark_root',lab.data/'benchmark-history'));self.lock=threading.Lock();self.jobs_lock=threading.Lock();self.jobs={};self.current_cancel=None
  self.catalog_path=Path(lab.profile['benchmark_catalog']) if lab.profile.get('benchmark_catalog') else Path(__file__).with_name('hydra_lab_catalog.json')
  if lab.profile.get('historical_benchmark'):import_history(self.store,lab.profile['historical_benchmark'])
  if lab.profile.get('historical_app_campaign'):import_functional_history(self.store,lab.profile['historical_app_campaign'])
 def catalog(self):
  data=json.loads(self.catalog_path.read_text(encoding='utf-8')) if self.catalog_path else []
  runs=self.store.list()
  data=[catalog_evidence(row,runs) for row in data]
  from serve.hydra_lab_readiness import catalog_readiness
  for row in data:row['readiness']=catalog_readiness(row)
  with self.store.db() as c:
   for entry in data:c.execute('INSERT OR REPLACE INTO catalog_entries VALUES(?,?,?)',(entry['id'],json.dumps(entry,ensure_ascii=False),now()))
  return data
 def assess(self,body):
  if not isinstance(body,dict) or set(body)-{'model_id','test_type'} or not isinstance(body.get('model_id'),str) or body.get('test_type','CAPABILITY_AUDIT') not in ('CAPABILITY_AUDIT','ADMISSION_TEST'):raise ValueError('model_id and valid test_type required')
  candidate=next((r for r in self.catalog() if r['id']==body['model_id']),None)
  if candidate is None:raise ValueError('unknown model')
  key=uuid.uuid4().hex;folder=self.store.root/'runs'/key;folder.mkdir(parents=True)
  row=dict(run_id=key,origin=body.get('test_type','CAPABILITY_AUDIT'),status='RESOURCE_BLOCKED' if candidate['status']=='RESOURCE_BLOCKED' else 'BLOCKED' if candidate['status'] not in ('E2E_VERIFIED','ADAPTER_IMPLEMENTED','SMOKE_TESTED','RUNTIME_VERIFIED') else 'PASS',timestamp=now(),model=candidate['id'],model_hash=candidate.get('asset_hash'),runtime=candidate.get('runtime_path'),runtime_hash=candidate.get('runtime_hash'),backend='NOT_TESTED',quantization=candidate.get('quantization','UNKNOWN'),profile='availability-only',prompt_id='availability',prompt_hash=None,template_hash=None,parameters={},samples=[],summary={},quality_gate='NOT_APPLICABLE',cleanup=True,exit_code=0,error=candidate['reason'] if candidate['status'] not in ('E2E_VERIFIED','ADAPTER_IMPLEMENTED','SMOKE_TESTED','RUNTIME_VERIFIED') else None,log_path=str(folder/'availability.json'),artifacts=str(folder),events=[dict(at=now(),kind='availability_audit',detail={'inference_executed':False,'status':candidate['status']})],original_result=candidate,real_execution_kind='static capability audit; no model loaded')
  row['comparison_key']=comparison_key(row);row['finished_at']=now();self.store.put(row);(folder/'availability.json').write_text(json.dumps(candidate,ensure_ascii=False,indent=2),encoding='utf-8')
  if self.lab.profile.get('publish_existing_benchmarks'):
   from serve.hydra_lab_integration import publish_existing_registry
   publish_existing_registry(self,Path(__file__).resolve().parents[1])
  return row
 def submit(self,body):
  body=validate_runner_request(body)
  with self.jobs_lock:
   if any(job[0].is_alive() for job in self.jobs.values()) or self.lock.locked():
    key=uuid.uuid4().hex;folder=self.store.root/'runs'/key;folder.mkdir(parents=True)
    row=dict(run_id=key,origin='ADMISSION',status='BLOCKED_BUSY',timestamp=now(),finished_at=now(),model=body['model_id'],profile=body['profile'],backend='NOT_STARTED',quantization='NOT_VERIFIED',prompt_id=body['prompt_id'],prompt=body['prompt'],request_json=body,quality_gate='NOT_APPLICABLE',artifacts=str(folder),runtime_hash=None,comparison_key='INCOMPLETE:exclusive-lock',summary={},samples=[],cleanup=True,exit_code=None,error='Exclusive benchmark active; no runtime started',log_path=str(folder/'admission.json'),events=[dict(at=now(),kind='admission_rejected',detail='exclusive inference lock')])
    self.store.put(row);(folder/'admission.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8');return row
   key=uuid.uuid4().hex;cancel=threading.Event()
   catalog_path=getattr(self,'catalog_path',None);known=json.loads(catalog_path.read_text(encoding='utf8')) if catalog_path is not None and catalog_path.is_file() else []
   quantization=next((model.get('quantization','NOT_VERIFIED') for model in known if model['id']==body['model_id']),'Q8_0' if body['model_id']=='local/Qwen3-0.6B-Q8_0' else 'NOT_VERIFIED')
   row=dict(run_id=key,origin='LIVE_APP',status='QUEUED',timestamp=now(),model=body['model_id'],profile=body['profile'],backend='NOT_VERIFIED',quantization=quantization,prompt_id=body['prompt_id'],quality_gate='NOT_AVAILABLE',artifacts=str(self.store.root/'runs'/key),runtime_hash=None,events=[],owner_pid=os.getpid(),owner_created=__import__('psutil').Process().create_time())
   self.store.put(row)
   def work():
    try:self.execute(body,_key=key,_cancel=cancel)
    except Exception as exc:
     failed=self.store.get(key);failed.update(status='FAIL',error=str(exc),finished_at=now());self.store.put(failed)
   thread=threading.Thread(target=work,name='hydra-benchmark-'+key,daemon=False);self.jobs[key]=(thread,cancel);thread.start()
   return row
 def cancel(self,key):
  with self.jobs_lock:
   job=self.jobs.get(key)
   if not job or not job[0].is_alive():raise ValueError('no owned active benchmark')
   job[1].set()
  return dict(run_id=key,cancellation_requested=True)
 def shutdown(self):
  with self.jobs_lock:jobs=list(self.jobs.values())
  for thread,cancel in jobs:cancel.set()
  if self.current_cancel is not None:self.current_cancel.set()
  for thread,cancel in jobs:
   thread.join(50)
   if thread.is_alive():raise RuntimeError('owned benchmark did not stop; no foreign process terminated')
 @exclusive_execute
 def execute(self,body,_key=None,_cancel=None):
  body=validate_runner_request(body)
  if body.get('thinking') in ('on','off'):
   from serve.hydra_native_text_server import execute
   result=execute(self,body,_key,_cancel)
   if result.get('status')=='FAIL' and 'INCOMPLETE_OUTPUT' in str(result.get('error')):
    result['status']='TASK_INCOMPLETE';result['events'].append(dict(at=now(),kind='task_incomplete',detail='Native budget/answer completeness failure retained; not a full functional success'));self.store.put(result)
   return result
  if body['profile'].startswith('v8-') or body['profile']=='hydra-fastpath-v1':
   from serve.hydra_fastpath import execute
   return execute(self,body,_key,_cancel)
  if body['profile'].startswith('v7-qwen-'):
   from serve.hydra_v7_experiments import execute
   return execute(self,body,_key,_cancel)
  if body['profile'].startswith('prism-v6-'):
   from serve.hydra_prefill_campaign import execute
   return execute(self,body,_key,_cancel)
  if body['profile'].startswith('prism-v5-') or body['profile']=='prism-bonsai27b-vulkan-verified-v1':
   from serve.hydra_prism_campaign import execute
   return execute(self,body,_key,_cancel)
  if body['model_id'] in ('mudler/locate-anything.cpp-gguf','prism-ml/Ternary-Bonsai-2-27B-gguf','unsloth/Qwen-Image-2.1-GGUF','abenzerps/Qwen-Image-2.1-Uncensored-Quantized','unsloth/Z-Image-Turbo-GGUF','huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF','cdiamond/Qwen3.8-27B-iMatrix-NVFP4-MTP-GGUF','Serveurperso/YuE2-GGUF'):
   from serve.hydra_lab_native_tasks import execute_task
   return execute_task(self,body,_key,_cancel)
  if body['model_id']=='audio-cpp/audio.cpp-gguf':
   from serve.hydra_lab_audio_adapter import execute_audio
   return execute_audio(self,body,_key,_cancel)
  layers={'cpu':0,'gpu4':4,'qwen06b-gpu-full-verified-v1':29}[body['profile']]
  cancel=_cancel or threading.Event()
  def check_cancel():
   if cancel.is_set():raise BenchmarkCancelled('cancellation requested')
  if not self.lock.acquire(False):raise ValueError('benchmark already running')
  try:lease=acquire_runtime_lock(self.store.root)
  except Exception:self.lock.release();raise
  self.current_cancel=cancel
  lab=self.lab;original_data=lab.data;original_profile=lab.profile
  key=_key or uuid.uuid4().hex;folder=self.store.root/'runs'/key;folder.mkdir(parents=True)
  p={**original_profile,'offload_tuning':True,'gpu_layers':layers};p.pop('execution_profile',None)
  if layers==29:p['execution_profile']='qwen06b-gpu-full-verified-v1'
  parameters=dict(temperature=0,seed=42,max_tokens=body['max_tokens'],cache_prompt=False,context=2048,threads=2,batch_threads=2,parallel=1,graph=False,template_kwargs={'enable_thinking':False})
  if getattr(lab,'features',None):
   from serve.hydra_feature_control import runtime_options
   options=runtime_options(lab.features);parameters.update(seed=options['seed'],cache_prompt=options['cache_prompt'],context=options['context'],threads=options['threads'],batch_threads=options['threads'],mmap=options['mmap'])
  reuse_runtime=bool(layers or getattr(lab,'features',None) is None or lab.features.setting(3)['desired'])
  parameters['reuse_runtime_within_admission']=reuse_runtime
  row=dict(run_id=key,origin='LIVE_APP',status='RUNNING',timestamp=now(),model='Qwen3-0.6B-Q8_0',model_hash=p['model_sha256'],runtime=p['runtime'],runtime_hash=digest(p['runtime_manifest']),backend='NOT_VERIFIED',quantization='Q8_0',profile=body['profile'],configuration={k:v for k,v in p.items() if k not in ('key','dense')},parameters=parameters,template_hash=p['model_sha256'],prompt_id=body['prompt_id'],prompt=body['prompt'],prompt_hash=hashlib.sha256(body['prompt'].encode()).hexdigest(),warmup=[],samples=[],summary={},quality_gate='NOT_AVAILABLE',error=None,exit_code=None,cleanup=False,log_path=str(folder/'runtime.log'),artifacts=str(folder),events=[])
  row['started_at']=now();row['request_json']=body;row['measurement_scope']='server_lab_request_wrapper' if reuse_runtime else 'server_lab_request_wrapper_including_model_reload';row['comparison_key']=comparison_key(row);row['owner_pid']=os.getpid();row['owner_created']=__import__('psutil').Process().create_time()
  def event(kind,detail=None):row['events'].append(dict(at=now(),monotonic=time.monotonic(),kind=kind,detail=detail));self.store.put(row)
  system_lease=None;live_monitor=None
  try:
   event('admission');check_cancel();lab.benchmark_cancel=cancel
   if p.get('operational_loaded'):row['status']='BLOCKED';raise RuntimeError('Operational backend already loaded; no automatic stop')
   try:system_lease=reserve_system_runtime(Path(__file__).resolve().parents[1])
   except RuntimeError:row['status']='BLOCKED';raise
   event('system_reservation_acquired',{'owner':'hydra-benchmark-lab'});from serve.hydra_lab_live import LiveMonitor
   live_monitor=LiveMonitor(self,row);lab.stop_backend();lab.data=folder;lab.profile=p
   import psutil
   row['ram_before']=psutil.virtual_memory().available
   if row['ram_before']<12*1024**3:row['status']='BLOCKED';raise RuntimeError('RAM below12GiB')
   if row['model_hash']!=CANONICAL:row['status']='BLOCKED';raise RuntimeError('only canonical small Qwen permitted')
   # Native inventory contains no model loading and belongs exclusively to this call.
   probe=guarded_run([str(Path(p['runtime'])/'llama-server.exe'),'--list-devices'],cwd=p['runtime'],env=probe_environment(),capture_output=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));raw=probe.stdout.decode(errors='replace')+probe.stderr.decode(errors='replace');(folder/'devices.log').write_text(raw,encoding='utf-8')
   found=re.search(r'ROCm0:.*?\((\d+) MiB, (\d+) MiB free\)',raw);row['vram_free_before_mib']=int(found.group(2)) if found else None
   if layers and (probe.returncode or not found or row['vram_free_before_mib']<4096):row['status']='BLOCKED';raise RuntimeError('GPU capability/free VRAM admission failed')
   check_cancel();event('loading');lab.start();check_cancel();row['startup_ms']=lab.startup_ms
   from serve.hydra_lab_app import parse_offload
   text=(folder/'runtime.log').read_text(encoding='utf-8',errors='replace');offload=parse_offload(text,requested_layers=layers);row.update(actual_layers=offload['actual_layers'],total_layers=offload['total_layers'],backend=offload['backend']);row['backend_attestation']=offload
   if offload['actual_layers']!=layers or 'load_backend: failed' in text:raise RuntimeError('effective backend/offload not confirmed')
   row['memory_reported']=[s for s in text.splitlines() if 'buffer size' in s]
   event('loaded',offload)
   request={'messages':[{'role':'user','content':body['prompt']}],'max_tokens':body['max_tokens'],'graph':False}
   t=time.perf_counter();v=lab.chat(request);row['warmup'].append(sample(v,(time.perf_counter()-t)*1000));event('warmup_complete')
   row['runtime_sessions']=[dict(pid=lab.child.pid,created=psutil.Process(lab.child.pid).create_time(),scope='warmup and samples' if reuse_runtime else 'warmup only')]
   if not reuse_runtime:lab.stop_backend();event('runtime_closed_after_warmup')
   for index in range(body['samples']):
    check_cancel();event('request_start',{'repetition':index+1})
    if psutil.virtual_memory().available<12*1024**3:row['status']='BLOCKED';raise RuntimeError('RAM safety margin')
    t=time.perf_counter()
    if not reuse_runtime:
     lab.start();latest=next(item for item in reversed(lab.calls) if item['event']=='backend_start');current_log=Path(latest['log_path']).read_text(encoding='utf8',errors='replace')
     if parse_offload(current_log,requested_layers=0)['actual_layers']!=0:raise RuntimeError('reloaded CPU backend not attested')
     row['runtime_sessions'].append(dict(pid=lab.child.pid,created=psutil.Process(lab.child.pid).create_time(),scope='sample '+str(index+1),log_path=latest['log_path']))
    v=lab.chat(request);diag=lab.client.diagnostics[-1] if lab.client.diagnostics else {};check_cancel();s=sample(v,(time.perf_counter()-t)*1000,diag);s['repetition']=index+1;s['child_memory_info']=psutil.Process(lab.child.pid).memory_info()._asdict();row['samples'].append(s);event('generation_complete',{'repetition':index+1,'tokens':s['tokens']})
    if not reuse_runtime:lab.stop_backend();event('runtime_closed_after_sample',index+1)
   row['summary']=summary(row['samples']);refs=[r for r in self.store.list() if r['comparison_key']==row['comparison_key'] and r.get('actual_layers')==0 and r['status'] in ('COMPLETED','PASS','IMPORTED_HISTORICAL')]
   if layers==0:row['quality_gate']='BASELINE_STABLE' if len({s['output'] for s in row['samples']})==1 else 'QUALITY_GATE_FAILED'
   elif refs:
    baseline=refs[0]['samples'][0]['output'];row['baseline_run_id']=refs[0]['run_id'];row['quality_gate']='TEXT_IDENTICAL' if all(s['output']==baseline for s in row['samples']) else 'QUALITY_GATE_FAILED'
   check_cancel();event('generation_complete')
  except Exception as exc:
   from serve.hydra_task_completion import TaskIncomplete
   if isinstance(exc,TaskIncomplete):row['status']='TASK_INCOMPLETE';row['original_result']=exc.response
   if row['status']=='RUNNING':row['status']='CANCELLED' if cancel.is_set() else 'TIMEOUT' if isinstance(exc,(TimeoutError,subprocess.TimeoutExpired)) else 'OOM' if isinstance(exc,MemoryError) else 'FAIL'
   row['error']=type(exc).__name__+': '+str(exc);event('error',row['error'])
  finally:
   try:
    pid=lab.child.pid if lab.data==folder and lab.child else None
    if lab.data==folder:lab.stop_backend()
    from serve.hydra_lab_app import attest_model_loaders
    row['model_loaders']=attest_model_loaders(lab.calls,folder)
    if row['model_loaders']:row['configuration']['effective_model_loaders']=row['model_loaders']
    if any(x['mode']=='iocp' for x in row['model_loaders']):
     row['reference_runtime']=row['runtime'];row['runtime']=row['model_loaders'][0]['runtime'];row['runtime_hash']=row['model_loaders'][0]['manifest_sha256'];row['comparison_key']=comparison_key(row)
    row['exit_code']=next((v['exit_code'] for v in reversed(lab.calls) if v['event']=='backend_cleanup' and v.get('pid')==pid),None);row['cleanup']=not pid or not __import__('psutil').pid_exists(pid);event('cleanup',{'owned_pid':pid,'confirmed':row['cleanup']})
   except Exception as exc:
    row['status']='FAIL';row['error']='Cleanup failure: '+str(exc);row['cleanup']=False;event('cleanup_failed',row['error'])
   finally:
    if live_monitor is not None:live_monitor.close()
    if system_lease is not None:system_lease.release();event('system_reservation_released')
    self.current_cancel=None;lab.benchmark_cancel=None;lab.data=original_data;lab.profile=original_profile;release_runtime_lock(lease);self.lock.release()
  if row['status']=='RUNNING':
   row['status']='PASS' if row['cleanup'] else 'FAIL';event('completed_after_cleanup',{'locks_released':True,'cleanup':row['cleanup']})
  row['finished_at']=now();row['artifact_hashes']={}
  for session in row.get('runtime_sessions',[]):
   terminal=next((item for item in reversed(lab.calls) if item['event']=='backend_cleanup' and item['pid']==session['pid']),None)
   session.update(cleanup=bool(terminal and terminal['stopped']),exit_code=terminal['exit_code'] if terminal else None)
  for name in ('runtime.log','devices.log'):
   asset=folder/name
   if asset.is_file():row['artifact_hashes'][name]=hashlib.sha256(asset.read_bytes()).hexdigest()
  for asset in folder.glob('runtime-*.log'):row['artifact_hashes'][asset.name]=hashlib.sha256(asset.read_bytes()).hexdigest()
  self.store.put(row);(folder/'run.json').write_text(json.dumps(row,indent=2,ensure_ascii=False),encoding='utf-8')
  if original_profile.get('publish_existing_benchmarks'):
   from serve.hydra_lab_integration import publish_existing_registry
   publish_existing_registry(self,Path(__file__).resolve().parents[1])
  return row
 def record_application_run(self,path,body,result,error=None):
  p=self.lab.profile;key=uuid.uuid4().hex;output=result or {};samples=[]
  if path=='/lab/chat' and not error:samples=[sample(output,output['end_to_end_ms'])]
  row=dict(run_id=key,origin='LIVE_APP',status='FAIL' if error else 'COMPLETED',timestamp=now(),model='Qwen3-0.6B-Q8_0',model_hash=p['model_sha256'],runtime=p['runtime'],runtime_hash=digest(p['runtime_manifest']),backend=self.lab.status()['backend'],quantization='Q8_0',profile='functional-'+path.split('/')[-1],configuration={k:v for k,v in p.items() if k not in ('key','dense')},parameters={'functional_path':path},template_hash=p['model_sha256'],prompt_id='functional-'+path.split('/')[-1],prompt=json.dumps(body,ensure_ascii=False),prompt_hash=digest(body),samples=samples,summary=summary(samples),original_result=output,quality_gate='NOT_AVAILABLE',error=error,exit_code=None,cleanup='NOT_AVAILABLE: app session may still own backend',actual_layers=self.lab.status()['offload']['actual_layers'],log_path=str(self.lab.data/'runtime.log'),artifacts=str(self.lab.data),events=[dict(at=now(),kind='application_request',detail=path)])
  row['measurement_scope']='server_lab_request_wrapper';row['comparison_key']=comparison_key(row);self.store.put(row)
  if p.get('publish_existing_benchmarks'):
   from serve.hydra_lab_integration import publish_existing_registry
   publish_existing_registry(self,Path(__file__).resolve().parents[1])
  return key
 def log(self,key):
  row=self.store.get(key);p=Path(row['log_path']);return p.read_text(encoding='utf-8',errors='replace') if p.is_file() else 'NOT_AVAILABLE'

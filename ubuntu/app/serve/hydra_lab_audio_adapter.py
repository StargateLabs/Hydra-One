"""Lab-only Kokoro adapter, reusing LocalSpeech; never a chat-model loader."""
import base64,hashlib,json,os,threading,time,uuid
from pathlib import Path

def execute_audio(workspace,body,key=None,cancel=None):
 from serve.hydra_lab_benchmarks import now,digest,comparison_key,summary,acquire_runtime_lock,release_runtime_lock,reserve_system_runtime
 from serve.local_speech import LocalSpeech
 import psutil
 if not workspace.lock.acquire(False):raise ValueError('benchmark already running')
 try:lease=acquire_runtime_lock(workspace.store.root)
 except Exception:workspace.lock.release();raise
 key=key or uuid.uuid4().hex;cancel=cancel or threading.Event();folder=workspace.store.root/'runs'/key;folder.mkdir(parents=True)
 catalog=next(r for r in workspace.catalog() if r['id']==body['model_id']);asset=Path(catalog['assets'][0]['path']);binary=Path(catalog['runtime_path']);runtime=None;system=None;live_monitor=None;child=None;watch=None;finished=threading.Event();deadline=time.monotonic()+120
 row=dict(run_id=key,origin='E2E_TEST',status='RUNNING',timestamp=now(),started_at=now(),model=body['model_id'],model_hash=catalog['asset_hash'],runtime=str(binary),runtime_hash=catalog['runtime_hash'],backend='NOT_VERIFIED',quantization='Q8_0',profile='kokoro-cpu-diagnostic-v4',configuration={'threads':2,'device':'cpu','ram_margin_bytes':12*1024**3,'deadline_s':120,'memory_policy':'12GiB free admission; RSS monitored, not hard cap','timing':'absolute 120s incl startup; warmup and measured synthesis separate'},parameters={'speed':1,'language':'it','format':'wav','samples':body['samples']},prompt=body['prompt'],prompt_id=body['prompt_id'],prompt_hash=hashlib.sha256(body['prompt'].encode()).hexdigest(),template_hash=digest({'task':'tts','language':'it','speed':1}),measurement_scope='audio_native_http_request',request_json=body,samples=[],warmup=[],summary={},events=[],quality_gate='NOT_APPLICABLE: semantic audio quality not measured',exit_code=None,error=None,cleanup=False,log_path=str(folder/'data/speech-runtime/worker.log'),artifacts=str(folder),owner_pid=os.getpid(),owner_created=psutil.Process().create_time(),real_execution_kind='text-to-speech')
 row['comparison_key']=comparison_key(row)
 def event(kind,detail=None):row['events'].append(dict(at=now(),monotonic=time.monotonic(),kind=kind,detail=detail));workspace.store.put(row)
 def check():
  if cancel.is_set():raise RuntimeError('cancelled')
  if time.monotonic()>deadline:raise TimeoutError('audio deadline')
 def watchdog():
  while not finished.wait(.05):
   if cancel.is_set() or time.monotonic()>deadline:
    if runtime:runtime.stop()
    return
 try:
  event('admission')
  if body['profile']!='cpu':row['status']='BLOCKED';raise ValueError('Kokoro adapter is CPU-only')
  if workspace.lab.profile.get('operational_loaded'):row['status']='BLOCKED';raise RuntimeError('operational backend loaded')
  system=reserve_system_runtime(Path(__file__).resolve().parents[1]);from serve.hydra_lab_live import LiveMonitor
  live_monitor=LiveMonitor(workspace,row);workspace.lab.stop_backend()
  row['ram_before']=psutil.virtual_memory().available
  if row['ram_before']<12*1024**3:row['status']='BLOCKED';raise RuntimeError('RAM below12GiB')
  for path,expected in [(asset,catalog['asset_hash']),(binary,catalog['runtime_hash'])]:
   with path.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
   if actual!=expected:row['status']='BLOCKED';raise RuntimeError('asset identity changed')
  check();runtime=LocalSpeech(folder);runtime.models=asset.parent;runtime.binary=binary;runtime.candidate_validation=True
  watch=threading.Thread(target=watchdog,daemon=True);watch.start();event('loading');t=time.perf_counter();runtime.start({'model_path':str(asset)});child=runtime.child;psutil.Process(child.pid).cpu_affinity(psutil.Process(child.pid).cpu_affinity()[:2])
  while runtime.status()['status']!='ready':
   check()
   if child.poll() is not None or runtime.status()['status']=='error':raise RuntimeError('audio model startup failed')
   time.sleep(.1)
  row['startup_ms']=(time.perf_counter()-t)*1000;row['backend']='CPU';event('loaded',runtime.status())
  for i in range(body['samples']+1):
   check();event('request_start',{'warmup':i==0,'repetition':i});t=time.perf_counter();result=runtime.generate({'input':body['prompt'],'language':'it','response_format':'wav'});check();synthesis_ms=(time.perf_counter()-t)*1000;write_start=time.perf_counter();data=base64.b64decode(result.pop('audio_base64'));file=folder/('warmup.wav' if i==0 else f'output-{i}.wav');file.write_bytes(data);elapsed=(time.perf_counter()-t)*1000
   value={'e2e_ms':elapsed,'synthesis_ms':synthesis_ms,'wav_write_ms':(time.perf_counter()-write_start)*1000,'audio_seconds':result['audio_seconds'],'real_time_factor':elapsed/1000/result['audio_seconds'],'audio_bytes':len(data),'output':str(file),'output_sha256':hashlib.sha256(data).hexdigest(),'response':result,'child_memory_info':psutil.Process(child.pid).memory_info()._asdict()}
   (row['warmup'] if i==0 else row['samples']).append(value);event('warmup_complete' if i==0 else 'generation_complete',{'repetition':i})
  row['summary']=summary(row['samples'])
  import statistics
  for name in ('audio_seconds','real_time_factor','audio_bytes'):
   values=[v[name] for v in row['samples']];row['summary'][name]={'median':statistics.median(values),'min':min(values),'max':max(values),'stdev':statistics.stdev(values) if len(values)>1 else None,'n':len(values)}
  event('generation_complete')
 except Exception as exc:
  if row['status']=='RUNNING':row['status']='CANCELLED' if cancel.is_set() else 'TIMEOUT' if isinstance(exc,TimeoutError) or time.monotonic()>deadline else 'FAIL'
  row['error']=('Audio deadline 120s reached; owned CPU worker stopped. ' if row['status']=='TIMEOUT' else '')+type(exc).__name__+': '+str(exc);event('error',row['error'])
 finally:
  finished.set()
  if watch:watch.join(6)
  if runtime:runtime.stop()
  row['exit_code']=child.poll() if child else None;row['cleanup']=child is None or child.poll() is not None;event('cleanup',{'owned_pid':child.pid if child else None,'confirmed':row['cleanup']})
  if live_monitor:live_monitor.close()
  if system:system.release()
  release_runtime_lock(lease);workspace.lock.release()
 if row['status']=='RUNNING':
  row['status']='PASS' if row['cleanup'] else 'FAIL';event('completed_after_cleanup',{'locks_released':True,'cleanup':row['cleanup']})
 row['finished_at']=now();row['artifact_hashes']={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.glob('*.wav')};workspace.store.put(row);(folder/'run.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
 if workspace.lab.profile.get('publish_existing_benchmarks'):
  from serve.hydra_lab_integration import publish_existing_registry
  publish_existing_registry(workspace,Path(__file__).resolve().parents[1])
 return row

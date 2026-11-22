from serve.hydra_execution_v10 import apply_owned_affinity
from serve.hydra_execution_v10 import guarded_run
from serve.hydra_execution_v10 import guarded_popen
"""Opt-in Prism persistent-process experiments. Not an operational router."""
import hashlib,json,os,re,socket,subprocess,threading,time,urllib.request,uuid
from pathlib import Path

MODEL_ID='prism-ml/Ternary-Bonsai-2-27B-gguf'
VERIFIED_PROFILE='prism-bonsai27b-vulkan-verified-v1'
def profile_spec(name):
 if name in ('prism-v5-vulkan-2',VERIFIED_PROFILE):return 'Vulkan',2,99
 if name in tuple('prism-v5-cpu-'+str(n) for n in (2,4,8,16)):return 'CPU',int(name.rsplit('-',1)[1]),0
 raise ValueError('unknown bounded Prism profile')

def verified_profile_allowed(cfg,row):
 return row.get('status')=='PASS' and row.get('cleanup') is True and row.get('backend')=='Vulkan' and row.get('actual_layers',0)>0 and row.get('model_hash')==cfg['model_hash'] and row.get('runtime_hash')==cfg['runtimes']['Vulkan']['files']['llama-server.exe'] and row.get('quality_gate')=='TEXT_IDENTICAL' and len(row.get('samples',[]))==3 and row.get('controlled_comparison',{}).get('improvement_percent',0)>=15

def completion_request(prompt,tokens):
 return dict(prompt=prompt,n_predict=tokens,temperature=0,seed=42,cache_prompt=False,stream=False,id_slot=0)

def measured_response(response,elapsed):
 t=response.get('timings',{});count=response.get('tokens_predicted')
 if not isinstance(response.get('content'),str) or not response['content'] or type(count) is not int or count<1 or not t.get('predicted_ms') or not t.get('predicted_per_second'):raise ValueError('incomplete native completion/timings')
 return dict(e2e_ms=elapsed,output=response['content'],tokens=count,prefill_ms=t.get('prompt_ms'),prefill_tps=t.get('prompt_per_second'),decode_ms=t['predicted_ms'],decode_tps=t['predicted_per_second'],prompt_tokens=t.get('prompt_n'),ttft_ms=None,response=response,includes_model_load=False,output_sha256=hashlib.sha256(response['content'].encode()).hexdigest())

def backend_evidence(log,backend):
 layers=re.findall(r'offloaded (\d+)/(\d+) layers to GPU',log)
 buffers=[line for line in log.splitlines() if 'buffer size' in line]
 if not any('model buffer' in line for line in buffers):raise ValueError('native model allocation telemetry missing; stop before warm-up')
 if backend=='Vulkan' and (not layers or int(layers[-1][0])<1 or not any('Vulkan0' in x and 'model buffer' in x for x in buffers) or 'Radeon RX 7900 XTX' not in log):raise ValueError('actual Vulkan model offload not verified')
 return dict(backend=backend,actual_layers=int(layers[-1][0]) if layers else 0,total_layers=int(layers[-1][1]) if layers else None,memory_runtime_lines=buffers,device_lines=[x for x in log.splitlines() if 'ggml_vulkan:' in x or 'AMD Radeon RX 7900 XTX' in x])

def output_gate(base,candidate):
 a=[x['output'] for x in base.get('samples',[])];b=[x['output'] for x in candidate.get('samples',[])]
 return 'TEXT_IDENTICAL' if len(a)==len(b)==3 and len(set(a+b))==1 else 'QUALITY_GATE_FAILED'

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

def terminal_status(complete,cleanup,status):
 return ('PASS' if cleanup else 'FAIL') if complete and status=='RUNNING' else status

def execute(workspace,body,key=None,cancel=None):
 from serve.hydra_lab_benchmarks import now,summary,acquire_runtime_lock,release_runtime_lock,reserve_system_runtime,comparison_key
 from serve.hydra_lab_live import LiveMonitor
 import psutil
 backend,threads,layers=profile_spec(body['profile']);cfg=workspace.lab.profile.get('prism_campaign')
 if not cfg or os.environ.get('HYDRA_LAB_MODE')!='1':raise ValueError('explicit lab campaign profile required')
 if body['profile']==VERIFIED_PROFILE and (not cfg.get('verified_run_id') or not verified_profile_allowed(cfg,workspace.store.get(cfg['verified_run_id']))):raise ValueError('verified profile requires complete matching registry evidence')
 if body['model_id']!=MODEL_ID or body['prompt']!=cfg['prompt'] or body['max_tokens']!=cfg['max_tokens'] or body['samples']!=3:raise ValueError('frozen Prism workload mismatch')
 if not workspace.lock.acquire(False):raise ValueError('benchmark already running')
 lease=None;system=None;live=None;child=None;logfile=None;row=None;cancel=cancel or threading.Event();request_thread=None;complete=False
 try:
  lease=acquire_runtime_lock(workspace.store.root);key=key or uuid.uuid4().hex;folder=workspace.store.root/'runs'/key;folder.mkdir(parents=True)
  runtime=cfg['runtimes'][backend];binary=Path(runtime['path'])/'llama-server.exe';model=Path(cfg['model']);begin=time.monotonic()
  row=dict(run_id=key,origin='BENCHMARK',test_type='BENCHMARK',status='RUNNING',timestamp=now(),started_at=now(),model=MODEL_ID,model_hash=cfg['model_hash'],runtime=str(binary),runtime_hash=runtime['files']['llama-server.exe'],quantization='PTQ1_0',backend='NOT_VERIFIED',profile=body['profile'],configuration=dict(context=512,threads=threads,gpu_layers=layers,parallel=1,cache_prompt=False,source_commit=cfg['source_commit'],runtime_manifest=runtime['files'],memory_budget=cfg['memory_budget'],model_template='raw; native BOS handling; no chat rendering',startup_deadline_s=120,request_deadline_s=180,absolute_deadline_s=900),parameters=dict(temperature=0,seed=42,max_tokens=cfg['max_tokens'],samples_requested=3),prompt=body['prompt'],prompt_id=body['prompt_id'],prompt_hash=sha_text(body['prompt']),template_hash=sha_text('raw-native-bos-v5'),measurement_scope='persistent_native_completion_http_round_trip',request_json=body,samples=[],warmup=[],summary={},quality_gate='NOT_AVAILABLE',error=None,exit_code=None,cleanup=False,artifacts=str(folder),log_path=str(folder/'runtime.log'),events=[],owner_pid=os.getpid(),owner_created=psutil.Process().create_time(),real_execution_kind='text-generation-persistent-prism')
  row['comparison_key']=comparison_key(row)
  def event(kind,detail=None):row['events'].append(dict(at=now(),monotonic=time.monotonic(),kind=kind,detail=detail));workspace.store.put(row)
  def check():
   if cancel.is_set():row['status']='CANCELLED';raise RuntimeError('controlled cancellation')
   if time.monotonic()-begin>900:row['status']='TIMEOUT';raise TimeoutError('absolute campaign deadline')
   if child and child.poll() is not None:raise RuntimeError('owned runtime exited; no restart')
   if psutil.virtual_memory().available<12*1024**3:row['status']='RESOURCE_BLOCKED';raise RuntimeError('available RAM below 12GiB')
   if child:
    rss=psutil.Process(child.pid).memory_info().rss;row['peak_sampled_rss_bytes']=max(row.get('peak_sampled_rss_bytes',0),rss)
    if rss>20*1024**3:row['status']='RESOURCE_BLOCKED';raise RuntimeError('20GiB monitored RSS stop; not OS hard cap')
  event('admission');system=reserve_system_runtime(Path(__file__).resolve().parents[1]);workspace.lab.stop_backend();live=LiveMonitor(workspace,row);row['ram_before']=psutil.virtual_memory().available;check()
  if sha(model)!=cfg['model_hash']:raise ValueError('model identity mismatch')
  for name,expected in runtime['files'].items():
   if sha(binary.parent/name)!=expected:raise ValueError('runtime hash mismatch: '+name)
  env=dict(os.environ,OMP_NUM_THREADS=str(threads),OPENBLAS_NUM_THREADS=str(threads),MKL_NUM_THREADS=str(threads));env.pop('GGML_BACKEND_PATH',None)
  for name in ('CUDA_VISIBLE_DEVICES','HIP_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES'):env[name]='-1'
  if backend=='Vulkan':
   probe=guarded_run([str(binary),'--list-devices'],cwd=binary.parent,env=env,capture_output=True,timeout=10,creationflags=0x08000000);raw=(probe.stdout+probe.stderr).decode(errors='replace');(folder/'devices.log').write_text(raw);found=re.search(r'Vulkan0: AMD Radeon RX 7900 XTX \((\d+) MiB, (\d+) MiB free\)',raw)
   if probe.returncode or not found:raise ValueError('Vulkan device/free memory not attested')
   row['vram_free_before_mib']=int(found.group(2))
   if row['vram_free_before_mib']<cfg['memory_budget']['vram_admission_mib']:row['status']='RESOURCE_BLOCKED';raise RuntimeError('VRAM budget plus 4GiB reserve not available')
  else:row['vram_free_before_mib']=None
  with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
  url='http://127.0.0.1:'+str(port)
  args=[str(binary),'-m',str(model),'--host','127.0.0.1','--port',str(port),'-c','512','-t',str(threads),'-tb',str(threads),'-ngl',str(layers),'--parallel','1','--no-warmup','--device','Vulkan0' if backend=='Vulkan' else 'none','--log-timestamps','--verbosity','4']
  row['command']=args;event('startup');logfile=(folder/'runtime.log').open('wb');started=time.perf_counter();child=guarded_popen(args,cwd=binary.parent,env=env,stdout=logfile,stderr=logfile,stdin=subprocess.DEVNULL,creationflags=0x08000000);process=psutil.Process(child.pid);apply_owned_affinity(child.pid,psutil.Process().cpu_affinity()[:threads]);row['owned_pid']=child.pid;row['owned_created']=process.create_time();event('loading')
  deadline=time.monotonic()+120
  while True:
   check()
   try:
    with urllib.request.urlopen(url+'/health',timeout=.4) as f:ready=json.load(f)
    if ready.get('status')=='ok':break
   except OSError:pass
   if time.monotonic()>deadline:row['status']='TIMEOUT';raise TimeoutError('startup deadline')
   time.sleep(.1)
  row['startup_ms']=(time.perf_counter()-started)*1000
  row['backend_evidence']=backend_evidence((folder/'runtime.log').read_text(errors='replace'),backend);row['backend']=backend;row['actual_layers']=row['backend_evidence']['actual_layers'];row['total_layers']=row['backend_evidence']['total_layers'];row['memory_reported']=row['backend_evidence']['memory_runtime_lines'];row['model_load_ms']=None
  event('model_ready',row['backend_evidence'])
  payload=completion_request(body['prompt'],cfg['max_tokens']);(folder/'completion-request.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
  for index in range(4):
   check();event('warmup_start' if index==0 else 'request_start',{'index':index});result={};t=time.perf_counter()
   def request():
    try:
     req=urllib.request.Request(url+'/completion',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
     with urllib.request.urlopen(req,timeout=180) as f:result['response']=json.load(f)
    except Exception as exc:result['error']=exc
   request_thread=threading.Thread(target=request,name='owned-prism-single-request');request_thread.start();deadline=time.monotonic()+180
   while request_thread.is_alive():
    check()
    if time.monotonic()>deadline:row['status']='TIMEOUT';raise TimeoutError('request deadline')
    request_thread.join(.1)
   if 'error' in result:raise result['error']
   measured=measured_response(result['response'],(time.perf_counter()-t)*1000);(folder/('warmup.json' if index==0 else 'sample-'+str(index)+'.json')).write_text(json.dumps(measured,ensure_ascii=False,indent=2));row['warmup' if index==0 else 'samples'].append(measured);row['summary']=summary(row['samples']);event('warmup_complete' if index==0 else 'measurement',{'index':index,'e2e_ms':measured['e2e_ms'],'tokens':measured['tokens']})
  row['quality_gate']='TEXT_SELF_IDENTICAL' if len({s['output'] for s in row['samples']})==1 else 'QUALITY_GATE_FAILED'
  if cfg.get('baseline_run_id'):
   base=workspace.store.get(cfg['baseline_run_id'])
   if base['status']!='PASS' or not base.get('cleanup') or base.get('comparison_key')!=row['comparison_key']:raise ValueError('baseline not complete or workload mismatch')
   row['quality_gate']=output_gate(base,row);a=base['summary']['e2e_ms']['median'];b=row['summary']['e2e_ms']['median'];row['controlled_comparison']={'baseline_run_id':base['run_id'],'quality_gate':row['quality_gate'],'e2e_delta_ms':b-a,'improvement_percent':(1-b/a)*100,'threshold_percent':15,'sample_count':3,'scope':'local exploratory; text only, no token identity claim'};event('quality_comparison',row['controlled_comparison'])
  complete=True;event('generation_complete')
 except Exception as exc:
  if row:
   if row['status']=='RUNNING':row['status']='TIMEOUT' if isinstance(exc,TimeoutError) else 'FAIL'
   row['error']=type(exc).__name__+': '+str(exc);event('error',row['error'])
  else:raise
 finally:
  if child and child.poll() is None:
   child.terminate()
   try:child.wait(5)
   except subprocess.TimeoutExpired:child.kill();child.wait(3)
  if request_thread and request_thread.is_alive():request_thread.join(5)
  if logfile:logfile.close()
  if row:
   row['exit_code']=child.returncode if child else None;row['cleanup']=(child is None or child.poll() is not None) and not (request_thread and request_thread.is_alive());row['status']=terminal_status(complete,row['cleanup'],row['status']);row['finished_at']=now();event('cleanup',{'owned_pid':child.pid if child else None,'confirmed':row['cleanup'],'stop_method':'owned child TerminateProcess; Windows returns 1 for controlled stop' if child else 'not started'});row['artifact_hashes']={p.name:sha(p) for p in folder.iterdir() if p.is_file() and p.suffix=='.json'};workspace.store.put(row);(folder/'run.json').write_text(json.dumps(row,ensure_ascii=False,indent=2))
  if live:live.close()
  if system:system.release()
  if lease:release_runtime_lock(lease)
  workspace.lock.release()
 if workspace.lab.profile.get('publish_existing_benchmarks'):
  from serve.hydra_lab_integration import publish_existing_registry
  publish_existing_registry(workspace,Path(__file__).resolve().parents[1])
 return row

def sha_text(value):return hashlib.sha256(value.encode()).hexdigest()

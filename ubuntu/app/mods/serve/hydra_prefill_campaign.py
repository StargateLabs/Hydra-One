from serve.hydra_execution_v10 import apply_owned_affinity
from serve.hydra_execution_v10 import guarded_run
from serve.hydra_execution_v10 import guarded_popen
"""Bounded v6 lab sweep. Reuses v5 identity/metric helpers without changing v1."""
import hashlib,json,os,re,socket,statistics,subprocess,threading,time,urllib.request,uuid
from pathlib import Path
from serve.hydra_prism_campaign import MODEL_ID,sha,sha_text,completion_request,measured_response,backend_evidence

def configuration(name):
 choices={'prism-v6-control':([],512,512,'auto'),'prism-v6-control-end':([],512,512,'auto'),'prism-v6-fa-off':(['-fa','off'],512,512,'off'),'prism-v6-ub128':(['-ub','128'],512,128,'auto'),'prism-v6-faoff-ub128':(['-fa','off','-ub','128'],512,128,'off')}
 if name=='prism-v6-batch-only':return {'skip_reason':'context clamp makes logical batch above 512 a no-op; below 512 also clamps physical ubatch, confounding the single-variable test','flags':[]}
 if name not in choices:raise ValueError('unknown v6 configuration')
 flags,b,u,fa=choices[name];return dict(flags=flags,batch=b,ubatch=u,flash=fa)

def measure(response,elapsed,prepare):
 result=measured_response(response,elapsed)
 result.update(prefill_compute_ms=None,queue_wait_ms=None,request_prepare_ms=prepare,unattributed_external_ms=elapsed-result['prefill_ms']-result['decode_ms'],counter_semantics='prefill_ms is native slot prompt-stage wall time, not pure compute; residual is derived, not queue time')
 return result

def can_pass(complete,child_stopped,locks_released,persisted):return bool(complete and child_stopped and locks_released and persisted)

def repeat_guard(reference,control):
 delta={k:(control['summary'][k]['median']/reference['summary'][k]['median']-1)*100 for k in ('e2e_ms','prefill_ms','decode_ms')}
 return {'pass':all(abs(v)<=10 for v in delta.values()),'delta_percent':delta,'threshold_percent':10,'reason':'unexplained absolute stage drift blocks causal sweep, including faster measurements'}

def promotion_gate(base,candidate):
 result={'GO':False,'workloads':{},'minimum_prefill_improvement_percent':10,'max_e2e_regression_percent':5,'max_generation_regression_percent':5,'generation_threshold_basis':'preregistered 5% median stage regression bound'}
 if set(base)!=set('ABC') or set(candidate)!=set('ABC'):result['reason']='three workload records required';return result
 improves=False;good=True
 for key in 'ABC':
  a,b=base[key],candidate[key];valid=all(r.get('status')=='PASS' and r.get('cleanup') is True and r.get('actual_layers')==65 and len(r.get('samples',[]))>=7 for r in (a,b))
  if not valid:result['workloads'][key]={'pass':False,'reason':'complete seven-sample verified Vulkan records required'};good=False;continue
  def med(r,k):return statistics.median(s[k] for s in r['samples'])
  delta={k:(med(b,k)/med(a,k)-1)*100 for k in ('prefill_ms','e2e_ms','decode_ms')};texts={s['output'].encode('utf8') for s in a['samples']+b['samples']};identity=len(texts)==1;ok=identity and delta['e2e_ms']<=5 and delta['decode_ms']<=5;improves|=delta['prefill_ms']<=-10;good&=ok
  result['workloads'][key]={'pass':ok,'delta_percent':delta,'quality_gate':'TEXT_IDENTICAL' if identity else 'QUALITY_GATE_FAILED','samples':[len(a['samples']),len(b['samples'])]}
 result['GO']=bool(good and improves);return result

def http(url,path,body=None,timeout=15):
 req=urllib.request.Request(url+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=timeout) as f:return json.load(f)

def execute(workspace,body,key=None,cancel=None):
 from serve.hydra_lab_benchmarks import now,summary,comparison_key,acquire_runtime_lock,release_runtime_lock,reserve_system_runtime
 from serve.hydra_lab_live import LiveMonitor
 import psutil
 cfg=workspace.lab.profile.get('prism_prefill_campaign');spec=configuration(body['profile'])
 if os.environ.get('HYDRA_LAB_MODE')!='1' or not cfg:raise ValueError('explicit isolated prefill campaign required')
 if body['model_id']!=MODEL_ID or body['prompt']!=cfg['prompt'] or body['samples']!=7 or body['max_tokens']!=16:raise ValueError('frozen seven-sample v6 workload required')
 if not workspace.lock.acquire(False):raise ValueError('benchmark already active')
 key=key or uuid.uuid4().hex;cancel=cancel or threading.Event();rows={};lease=None;system=None;child=None;logfile=None;thread=None;live=None;error=None;complete=False;begin=time.monotonic();runtime=cfg['runtime'];binary=Path(runtime['path'])/'llama-server.exe';root=workspace.store.root/'runs';mainfolder=root/key;mainfolder.mkdir(parents=True);logpath=mainfolder/'runtime.log'
 def make_row(label,prompt,prompt_tokens):
  rid=key if label=='A' else uuid.uuid4().hex;folder=root/rid;folder.mkdir(exist_ok=True)
  r=dict(run_id=rid,campaign_id=key,origin='BENCHMARK',test_type='BENCHMARK',status='RUNNING',timestamp=now(),started_at=now(),model=MODEL_ID,model_hash=cfg['model_hash'],runtime=str(binary),runtime_hash=runtime['files']['llama-server.exe'],backend='NOT_VERIFIED',quantization='PTQ1_0',profile=body['profile'],configuration={'context':512,'threads':2,'parallel':1,'gpu_layers':99,'cache_prompt':False,'variant':spec,'source_commit':cfg['source_commit'],'runtime_manifest':runtime['files'],'memory_budget':cfg['memory_budget'],'logging_verbosity':4,'counter_semantics':'native prompt_ms measures slot prompt-stage wall time including preparation/checkpoints; pure compute, queue wait and TTFT NOT_AVAILABLE'},parameters={'temperature':0,'seed':42,'max_tokens':16,'samples_requested':7},prompt=prompt,prompt_id='v6-'+label+'-'+str(prompt_tokens),prompt_hash=sha_text(prompt),template_hash=sha_text('raw-native-bos-v5'),measurement_scope='persistent_native_completion_http_round_trip',request_json=body,input_token_count=prompt_tokens,workload=label,samples=[],warmup=[],summary={},events=[],quality_gate='NOT_AVAILABLE',error=None,exit_code=None,cleanup=False,owner_pid=os.getpid(),owner_created=psutil.Process().create_time(),log_path=str(logpath),artifacts=str(folder),real_execution_kind='text-generation-persistent-prism-prefill')
  r['comparison_key']=comparison_key(r);rows[label]=r;workspace.store.put(r);return r
 main=make_row('A',cfg['prompt'],cfg['canonical_tokens'])
 def event(r,kind,detail=None):r['events'].append({'at':now(),'monotonic':time.monotonic(),'kind':kind,'detail':detail});workspace.store.put(r)
 def check():
  if cancel.is_set():raise InterruptedError('cancelled by app')
  if time.monotonic()-begin>900:raise TimeoutError('absolute configuration deadline')
  if child and child.poll() is not None:raise RuntimeError('owned runtime exited; no restart')
  if psutil.virtual_memory().available<12*1024**3:raise MemoryError('RAM below 12GiB')
  if child:
   rss=psutil.Process(child.pid).memory_info().rss
   for r in rows.values():r['peak_sampled_rss_bytes']=max(r.get('peak_sampled_rss_bytes',0),rss)
   if rss>20*1024**3:raise MemoryError('monitored RSS exceeds 20GiB; not OS hard cap')
 try:
  lease=acquire_runtime_lock(workspace.store.root);system=reserve_system_runtime(Path(__file__).resolve().parents[1]);workspace.lab.stop_backend();live=LiveMonitor(workspace,main);event(main,'admission');check()
  if body['profile'] not in ('prism-v6-control','prism-v6-batch-only'):
   if not cfg.get('baseline_run_id') or not cfg.get('reference_run_id'):spec['skip_reason']='v5 repeat guard not attested; no model load authorized by this campaign profile'
   else:
    guard=repeat_guard(workspace.store.get(cfg['reference_run_id']),workspace.store.get(cfg['baseline_run_id']));main['control_guard']=guard
    if not guard['pass']:spec['skip_reason']='v5 repeat guard failed: '+json.dumps(guard['delta_percent'])+'; causal variant not executed'
  if spec.get('skip_reason'):main['status']='SKIP';main['error']=spec['skip_reason'];event(main,'unsupported_single_variable',spec['skip_reason'])
  else:
   foreign=[]
   for p in psutil.process_iter(['pid','name']):
    if (p.info['name'] or '').lower() in ('llama-server.exe','llama-cli.exe','qwen36.exe','native_score.exe','sd-cli.exe','yue2.exe'):foreign.append(p.info)
   if foreign:raise RuntimeError('another native runtime exists; no process was touched: '+json.dumps(foreign))
   if sha(cfg['model'])!=cfg['model_hash']:raise ValueError('model hash mismatch')
   for name,expected in runtime['files'].items():
    if sha(binary.parent/name)!=expected:raise ValueError('runtime hash mismatch: '+name)
   env=dict(os.environ,OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2');env.pop('GGML_BACKEND_PATH',None)
   for name in ('CUDA_VISIBLE_DEVICES','HIP_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES'):env[name]='-1'
   probe=guarded_run([str(binary),'--list-devices'],cwd=binary.parent,env=env,capture_output=True,timeout=10,creationflags=0x08000000);raw=(probe.stdout+probe.stderr).decode(errors='replace');(mainfolder/'devices.log').write_text(raw);match=re.search(r'Vulkan0: AMD Radeon RX 7900 XTX \((\d+) MiB, (\d+) MiB free\)',raw)
   if probe.returncode or not match or int(match.group(2))<cfg['memory_budget']['vram_admission_mib']:raise MemoryError('Vulkan budget plus 4GiB reserve not demonstrated')
   ram=psutil.virtual_memory().available;vram=int(match.group(2))
   with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
   url='http://127.0.0.1:'+str(port);args=[str(binary),'-m',cfg['model'],'--host','127.0.0.1','--port',str(port),'-c','512','-t','2','-tb','2','-ngl','99','--parallel','1','--no-warmup','--device','Vulkan0','--log-timestamps','--verbosity','4',*spec['flags']];main['command']=args;event(main,'startup');t=time.perf_counter();logfile=logpath.open('wb');child=guarded_popen(args,cwd=binary.parent,env=env,stdout=logfile,stderr=logfile,stdin=subprocess.DEVNULL,creationflags=0x08000000);process=psutil.Process(child.pid);apply_owned_affinity(child.pid,psutil.Process().cpu_affinity()[:2]);owned_created=process.create_time();end=time.monotonic()+120
   while True:
    check()
    try:
     if http(url,'/health',timeout=.4).get('status')=='ok':break
    except OSError:pass
    if time.monotonic()>end:raise TimeoutError('startup deadline')
    time.sleep(.1)
   startup=(time.perf_counter()-t)*1000;log=logpath.read_text(errors='replace');att=backend_evidence(log,'Vulkan')
   if att['actual_layers']!=65:raise ValueError('full 65-layer offload not verified')
   actual={name:int(re.findall(r'\b'+name+r'\s*=\s*(\d+)',log)[-1]) for name in ('n_batch','n_ubatch')};fa=re.findall(r'flash_attn\s*=\s*(\w+)',log)[-1]
   if actual!={'n_batch':spec['batch'],'n_ubatch':spec['ubatch']} or fa!=spec['flash']:raise ValueError('effective parameters differ from frozen variant')
   def tokenize(text):return http(url,'/tokenize',{'content':text,'add_special':True,'parse_special':True})['tokens']
   canonical=tokenize(cfg['prompt'])
   if len(canonical)!=cfg['canonical_tokens']:raise ValueError('canonical tokenizer input count changed')
   fixture_path=Path(cfg['evidence_root'])/'diagnostic-workloads.json'
   if fixture_path.exists():fixtures=json.loads(fixture_path.read_text())
   else:
    fixtures={}
    for label,n in [('B',128),('C',384)]:
     text='x'+' x'*(n-1);ids=tokenize(text)
     if len(ids)!=n:raise ValueError('deterministic text does not have requested token count; no substitution')
     fixtures[label]={'text':text,'utf8_hex':text.encode().hex(),'sha256':sha_text(text),'tokens':ids,'token_count':n,'runtime_hash':runtime['files']['llama-server.exe'],'model_hash':cfg['model_hash']}
    fixture_path.write_text(json.dumps(fixtures,ensure_ascii=False,indent=2));fixture_path.with_suffix('.sha256').write_text(sha(fixture_path))
   for label in 'BC':
    f=fixtures[label]
    if sha_text(f['text'])!=f['sha256'] or tokenize(f['text'])!=f['tokens']:raise ValueError('frozen diagnostic fixture/tokenization changed')
    make_row(label,f['text'],f['token_count'])
   for r in rows.values():r.update(command=args,startup_ms=startup,model_load_ms=None,ram_before=ram,vram_free_before_mib=vram,owned_pid=child.pid,owned_created=owned_created,backend='Vulkan',actual_layers=65,total_layers=65,backend_evidence=att,memory_reported=att['memory_runtime_lines'],effective_settings={**actual,'flash_attn':fa},campaign_run_ids={k:v['run_id'] for k,v in rows.items()});event(r,'model_ready',att)
   for label in cfg.get('orders',{}).get(body['profile'],list('ABC')):
    r=rows[label]
    if live:live.close()
    live=LiveMonitor(workspace,r);event(main,'workload_'+label)
    for index in range(8):
     check();event(r,'warmup_start' if index==0 else 'request_start',{'sample':index,'workload':label});result={};started=time.perf_counter();prepare=time.perf_counter();payload=completion_request(r['prompt'],16);prepare=(time.perf_counter()-prepare)*1000
     def request():
      try:result['response']=http(url,'/completion',payload,timeout=180)
      except Exception as exc:result['error']=exc
     thread=threading.Thread(target=request,name='single-owned-v6-request');thread.start();end=time.monotonic()+180
     while thread.is_alive():
      check()
      if time.monotonic()>end:raise TimeoutError('request deadline')
      thread.join(.05)
     if 'error' in result:raise result['error']
     sample=measure(result['response'],(time.perf_counter()-started)*1000,prepare)
     if sample['prompt_tokens']!=r['input_token_count']:raise ValueError('native processed prompt count mismatch')
     sample['workload']=label;folder=Path(r['artifacts']);(folder/('warmup.json' if index==0 else 'sample-'+str(index)+'.json')).write_text(json.dumps(sample,ensure_ascii=False,indent=2));r['warmup' if index==0 else 'samples'].append(sample);r['summary']=summary(r['samples']);event(r,'warmup_complete' if index==0 else 'measurement',{'index':index,'prompt_tokens':sample['prompt_tokens'],'e2e_ms':sample['e2e_ms']})
    r['quality_gate']='TEXT_SELF_IDENTICAL' if len({s['output'] for s in r['samples']})==1 else 'QUALITY_GATE_FAILED';event(r,'workload_complete',{'workload':label})
   complete=True
 except Exception as exc:
  error=type(exc).__name__+': '+str(exc)
  for r in rows.values():r['error']=error;r['status']='CANCELLED' if isinstance(exc,InterruptedError) else 'TIMEOUT' if isinstance(exc,TimeoutError) else 'RESOURCE_BLOCKED' if isinstance(exc,MemoryError) else 'FAIL';event(r,'error',error)
 finally:
  if child and child.poll() is None:
   child.terminate()
   try:child.wait(5)
   except subprocess.TimeoutExpired:child.kill();child.wait(3)
  if thread and thread.is_alive():thread.join(5)
  if logfile:logfile.close()
  stopped=child is None or child.poll() is not None
  if child and psutil.pid_exists(child.pid):
   try:stopped=abs(psutil.Process(child.pid).create_time()-owned_created)>.01
   except psutil.NoSuchProcess:pass
  if system:system.release()
  if lease:release_runtime_lock(lease)
  workspace.lock.release();locks=True
  clean=stopped and not (thread and thread.is_alive())
  for r in rows.values():
   r.update(cleanup=clean,exit_code=child.returncode if child else None,finished_at=now());event(r,'cleanup',{'child_stopped':stopped,'request_thread_stopped':not(thread and thread.is_alive()),'locks_released':locks,'available_ram_bytes':psutil.virtual_memory().available,'stop_method':'owned TerminateProcess; Windows exit 1 is controlled shutdown' if child else 'not started'})
   if complete and not error and can_pass(complete,clean,locks,True):r['status']='PASS'
   elif r['status']=='RUNNING':r['status']='FAIL';r['error']='incomplete configuration'
  if live:live.close()
  for r in rows.values():
   r['artifact_hashes']={p.name:sha(p) for p in Path(r['artifacts']).iterdir() if p.is_file() and p.suffix=='.json'}
   (Path(r['artifacts'])/'run.json').write_text(json.dumps(r,ensure_ascii=False,indent=2));workspace.store.put(r)
 if workspace.lab.profile.get('publish_existing_benchmarks'):
  from serve.hydra_lab_integration import publish_existing_registry
  publish_existing_registry(workspace,Path(__file__).resolve().parents[1])
 return main

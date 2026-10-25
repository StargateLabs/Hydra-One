from serve.hydra_execution_v10 import apply_owned_affinity
from serve.hydra_execution_v10 import guarded_run
from serve.hydra_execution_v10 import guarded_popen
"""Isolated app-runner experiments on canonical small Qwen; no operational hooks."""
import json,os,statistics,subprocess,time,threading,socket,uuid
from pathlib import Path
from serve.hydra_prism_campaign import sha,sha_text,measured_response,completion_request

def options(profile):
 values={'v7-qwen-control':[],'v7-qwen-cache':['--cache-prompt'],'v7-qwen-nommap':['--no-mmap'],'v7-qwen-faoff':['-fa','off'],'v7-qwen-gpu4':['-ngl','4'],'v7-qwen-cpu':['-ngl','0']}
 if profile not in values:raise ValueError('unknown isolated v7 profile')
 return values[profile]
def request(prompt,cache):return dict(completion_request(prompt,16),cache_prompt=cache)
def compare(a,b):
 valid=len(a.get('samples',[]))==len(b.get('samples',[]))==7;text=valid and len({s['output'].encode() for s in a['samples']+b['samples']})==1
 delta=(1-statistics.median(s['e2e_ms'] for s in b['samples'])/statistics.median(s['e2e_ms'] for s in a['samples']))*100 if valid else None
 return {'GO':bool(text and delta>=10),'improvement_percent':delta,'quality_gate':'TEXT_IDENTICAL' if text else 'QUALITY_GATE_FAILED','threshold_percent':10,'scope':'same-model exploratory seven-sample comparison; cache hit is a specialized repeated-prefix workload'}

def execute(workspace,body,key=None,cancel=None,_experiment=None):
 from serve.hydra_lab_benchmarks import now,summary,comparison_key,acquire_runtime_lock,release_runtime_lock,reserve_system_runtime
 from serve.hydra_prefill_campaign import http
 from serve.hydra_lab_live import LiveMonitor
 import psutil
 exp=_experiment;flags=exp['flags'] if exp else options(body['profile']);cfg=exp['runtime'] if exp else workspace.lab.profile.get('v7_runtime')
 if os.environ.get('HYDRA_LAB_MODE')!='1' or not cfg or (not exp and (body['model_id']!='local/Qwen3-0.6B-Q8_0' or body['samples']!=7 or body['max_tokens']!=16)):raise ValueError('explicit frozen v7 lab configuration required')
 if not workspace.lock.acquire(False):raise ValueError('benchmark active')
 lease=system=child=handle=live=None;cancel=cancel or threading.Event();key=key or uuid.uuid4().hex;folder=workspace.store.root/'runs'/key;folder.mkdir(parents=True);start=time.monotonic();complete=False
 cache=exp['cache'] if exp else body['profile']=='v7-qwen-cache';ngl=exp['layers'] if exp else 0 if body['profile']=='v7-qwen-cpu' else 4 if body['profile']=='v7-qwen-gpu4' else 29;binary=Path(cfg['runtime'])/'llama-server.exe'
 row=dict(run_id=key,origin='BENCHMARK',test_type='BENCHMARK',status='RUNNING',timestamp=now(),started_at=now(),model=body['model_id'],model_hash=cfg['model_hash'],runtime=str(binary),runtime_hash=cfg['files']['llama-server.exe'],backend='NOT_VERIFIED',quantization='Q8_0',profile=body['profile'],configuration={'context':512,'threads':2,'gpu_layers':ngl,'cache_prompt':cache,'logging':4,'affinity_logical_CPUs':2,'runtime_manifest':cfg['files'],'memory_policy':'12GiB RAM minimum; 4GiB VRAM reserve plus conservative 4GiB allocation; monitored RSS not hard cap'},parameters={'temperature':0,'seed':42,'max_tokens':16,'samples_requested':7},prompt=body['prompt'],prompt_id=body['prompt_id'],prompt_hash=sha_text(body['prompt']),template_hash=sha_text('raw-native-bos-v7-qwen'),measurement_scope='persistent_native_completion_http_round_trip',request_json=body,samples=[],warmup=[],summary={},events=[],quality_gate='NOT_AVAILABLE',error=None,exit_code=None,cleanup=False,log_path=str(folder/'runtime.log'),artifacts=str(folder),owner_pid=os.getpid(),owner_created=psutil.Process().create_time(),real_execution_kind='text-generation-native-v7')
 if exp:
  row.update(quantization=exp['quantization'],real_execution_kind='text-generation-native-v8',template_hash=sha_text(exp['template']));row['configuration'].update(context=exp['context'],gpu_layers=ngl,variant_flags=flags,backend=exp['backend'],memory_policy='12GiB RAM and at least4GiB VRAM reserve; sampled RSS not hard cap');row['parameters'].update(max_tokens=body['max_tokens'],samples_requested=body['samples'],ignore_eos=body['max_tokens']>=64);row['configuration'].update({k:exp[k] for k in ('selection_reason','manifest_sha256','gate_record_id') if k in exp})
 row['comparison_key']=comparison_key(row)
 def event(kind,detail=None):row['events'].append({'at':now(),'monotonic':time.monotonic(),'kind':kind,'detail':detail});workspace.store.put(row)
 def check():
  if cancel.is_set():raise InterruptedError('cancelled')
  if time.monotonic()-start>(exp['deadline_s'] if exp else 300):raise TimeoutError('absolute v7 configuration deadline')
  if psutil.virtual_memory().available<12*1024**3:raise MemoryError('RAM margin below12GiB')
  if child:
   if child.poll() is not None:raise RuntimeError('native child exited, no retry')
   row['peak_sampled_rss_bytes']=max(row.get('peak_sampled_rss_bytes',0),psutil.Process(child.pid).memory_info().rss)
   if row['peak_sampled_rss_bytes']>(exp['rss_limit_gib'] if exp else 4)*1024**3:raise MemoryError('small model RSS monitor exceeded4GiB; not OS hard cap')
 try:
  lease=acquire_runtime_lock(workspace.store.root);system=reserve_system_runtime(Path(__file__).resolve().parents[1]);workspace.lab.stop_backend();live=LiveMonitor(workspace,row);event('admission');check();row['ram_before']=psutil.virtual_memory().available
  if sha(cfg['model'])!=cfg['model_hash']:raise ValueError('canonical model hash mismatch')
  for n,h in cfg['files'].items():
   if sha(binary.parent/n)!=h:raise ValueError('runtime DLL identity mismatch')
  foreign=[p.info for p in psutil.process_iter(['pid','ppid','name','create_time']) if (p.info['name'] or '').lower() in ('llama-server.exe','llama-cli.exe','native_score.exe','qwen36.exe','sd-cli.exe','yue2.exe')]
  row['preflight_native_processes']=foreign
  if foreign:
   event('foreign_runtime_blocked',foreign);raise RuntimeError('foreign native runtime active; no process touched: '+json.dumps(foreign))
  env=dict(os.environ,OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2');env.pop('GGML_BACKEND_PATH',None)
  probe=guarded_run([str(binary),'--list-devices'],cwd=binary.parent,env=env,capture_output=True,timeout=10,creationflags=0x08000000);raw=(probe.stdout+probe.stderr).decode(errors='replace');(folder/'devices.log').write_text(raw)
  import re
  match=re.search(r'(?:Vulkan0|ROCm0): AMD Radeon RX 7900 XTX \((\d+) MiB, (\d+) MiB free\)',raw)
  if ngl and (not match or int(match.group(2))<(exp['minimum_free_vram_mib'] if exp else 8192)):raise MemoryError('Vulkan free VRAM budget/reserve unavailable')
  row['vram_free_before_mib']=int(match.group(2)) if match else None
  with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
  url='http://127.0.0.1:'+str(port);args=[str(binary),'-m',cfg['model'],'--host','127.0.0.1','--port',str(port),'-c',str(exp['context'] if exp else 512),'-t','2','-tb','2','-ngl',str(ngl),'--device',exp['device'] if exp else 'Vulkan0' if ngl else 'none','--parallel','1','--no-warmup','--verbosity','4','--log-timestamps']+[x for x in flags if x!='--cache-prompt'];row['command']=args;handle=(folder/'runtime.log').open('wb');t=time.perf_counter();event('startup');child=guarded_popen(args,cwd=binary.parent,env=env,stdin=subprocess.DEVNULL,stdout=handle,stderr=handle,creationflags=0x08000000);apply_owned_affinity(child.pid,psutil.Process().cpu_affinity()[:2]);row['owned_pid']=child.pid
  if exp:
   from serve.hydra_recovery_diagnostics import safe_environment
   process=psutil.Process(child.pid);row['process_identity']={'pid':child.pid,'ppid':process.ppid(),'creation_time':process.create_time(),'executable':process.exe(),'cwd':str(binary.parent),'whitelisted_environment':safe_environment(env),'loaded_DLL_map':'NOT_AVAILABLE; no full module collector installed'};event('owned_process_identity',row['process_identity'])
  if exp and (exp.get('recovery') or exp.get('campaign_v18')):
   # Capture mapped DLLs before readiness or error attribution, then again ready.
   try:row['loaded_modules_at_start']=[m.path for m in psutil.Process(child.pid).memory_maps() if m.path.lower().endswith('.dll')]
   except psutil.Error as exc:row['loaded_modules_at_start']='NOT_AVAILABLE: '+type(exc).__name__
  end=time.monotonic()+45
  while True:
   check()
   try:
    if http(url,'/health',timeout=.3).get('status')=='ok':break
   except OSError:pass
   if time.monotonic()>end:raise TimeoutError('startup deadline')
   time.sleep(.05)
  if exp and (exp.get('recovery') or exp.get('campaign_v18')):
   try:
    modules=[dict(path=p,sha256=sha(Path(p))) for p in sorted({m.path for m in psutil.Process(child.pid).memory_maps() if m.path.lower().endswith('.dll')}) if any(k in p.lower() for k in ('llama','ggml','vulkan','amd'))]
   except (psutil.Error,OSError) as exc:modules='NOT_AVAILABLE: '+type(exc).__name__
   # The first identity is already an immutable event payload. Replace, never mutate it.
   from serve.hydra_gpu_recovery_v16 import persist_module_evidence
   persist_module_evidence(row,modules,folder)
  row['startup_ms']=(time.perf_counter()-t)*1000;log=(folder/'runtime.log').read_text(errors='replace');off=re.findall(r'offloaded (\d+)/(\d+) layers to GPU',log)
  if not off or int(off[-1][0])!=ngl:raise ValueError('actual offload does not match requested configuration')
  row.update(backend=exp['backend'] if exp else 'Vulkan' if ngl else 'CPU',actual_layers=ngl,total_layers=int(off[-1][1]),memory_reported=[l for l in log.splitlines() if 'buffer size' in l]);event('ready')
  effective_prompt=body['prompt']
  if exp and exp.get('campaign_v18') and exp['campaign_item'].get('chat_template'):
   from serve.hydra_acceptance_campaign import template_request
   template_body=template_request(body['prompt']);rendered=http(url,'/apply-template',template_body,timeout=10)
   if not isinstance(rendered.get('prompt'),str) or body['prompt'] not in rendered['prompt']:raise ValueError('V18_TEMPLATE_DID_NOT_PRESERVE_USER_PROMPT')
   effective_prompt=rendered['prompt'];row['chat_template_request']=template_body;row['effective_prompt']=effective_prompt
   (folder/'effective-prompt.json').write_text(json.dumps(dict(request=template_body,response=rendered),ensure_ascii=False,indent=2),encoding='utf8')
  if exp:
   row['tokenizer_probe']=http(url,'/tokenize',{'content':effective_prompt,'add_special':True},timeout=10);row['input_token_count']=len(row['tokenizer_probe']['tokens']);(folder/'input-tokenization.json').write_text(json.dumps(row['tokenizer_probe']),encoding='utf8')
   if row['input_token_count']+body['max_tokens']>=exp['context']:raise ValueError('context budget exceeded without truncation')
   expected=exp['backend'];gpu_buffers=[x for x in row['memory_reported'] if ('Vulkan0' in x if expected=='Vulkan' else 'ROCm0' in x)]
   if ngl and (not gpu_buffers or 'AMD Radeon RX 7900 XTX' not in log):raise ValueError('GPU device/buffers not attested')
   amounts=[float(x) for line in gpu_buffers for x in re.findall(r'buffer size\s*=\s*([0-9.]+) MiB',line)]
   if ngl and amounts and sum(amounts)>row['vram_free_before_mib']-4096:raise MemoryError('native GPU buffer sum leaves less than4GiB reserve')
   row['counter_semantics']='native prompt_ms is slot prompt-stage wall time; pure compute, checkpoint split and TTFT NOT_AVAILABLE'
  payload=request(body['prompt'],cache) if not exp else dict(completion_request(effective_prompt,body['max_tokens']),cache_prompt=cache,ignore_eos=body['max_tokens']>=64)
  if exp and (exp.get('app_paths') or exp.get('campaign_v18')):
   from serve.hydra_fastpath import Session
   if exp.get('campaign_v18'):
    from serve.hydra_acceptance_campaign import sampling_payload
    payload.update(**sampling_payload(),ignore_eos=exp['campaign_item']['ignore_eos'])
    if exp['campaign_item'].get('reset'):payload['cache_prompt']=False
    row['measurement_scope']='application_fastpath_HTTP_round_trip; startup separate; TTFT unavailable'
   forward=lambda value:http(url,'/completion',value,timeout=40)
   if exp.get('campaign_v18'):
    from serve.hydra_acceptance_campaign import RequestGate
    request_gate=RequestGate(body,key,exp['campaign_item'],forward);forward=request_gate
   workspace.fastpath_session=Session(key,forward,expected=payload)
  if exp and exp.get('campaign_v18'):
   item=exp['campaign_item'];indices=range(0 if item['warmup'] else 1,body['samples']+1)
   row['parameters'].update(samplers=['temperature'],warmup_requests=int(item['warmup']),ignore_eos=item['ignore_eos'])
  elif exp and exp.get('recovery'):
   from serve.hydra_gpu_recovery_v16 import request_indices
   indices=request_indices(body['samples'])
   row['parameters'].update(samplers=['temperature'],warmup_requests=0)
  else:indices=range((body['samples'] if exp else 7)+1)
  for i in indices:
   check();event('warmup_start' if i==0 else 'request_start',i)
   payload=request(body['prompt'],cache) if not exp else dict(completion_request(effective_prompt,body['max_tokens']),cache_prompt=cache,ignore_eos=body['max_tokens']>=64)
   if exp and (exp.get('recovery') or exp.get('campaign_v18')):payload.update(samplers=['temperature'],return_tokens=True)
   if exp and exp.get('campaign_v18'):
    from serve.hydra_acceptance_campaign import sampling_payload
    payload.update(sampling_payload())
    payload['ignore_eos']=exp['campaign_item']['ignore_eos']
    if exp['campaign_item'].get('reset'):
     payload['cache_prompt']=False
    row.setdefault('effective_payloads',[]).append(dict(index=i,payload=payload.copy()))
    request_gate.authorize(i)
   t=time.perf_counter()
   if exp and exp.get('campaign_v18'):
    import urllib.request
    req=urllib.request.Request('http://127.0.0.1:'+str(workspace.lab.profile['port'])+'/lab/fastpath/completion',data=json.dumps({'run_id':key,'payload':payload}).encode(),headers={'X-Hydra-Lab':workspace.lab.profile['key'],'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=45) as answer:response=json.load(answer)
   else:response=workspace.fastpath_session.complete({'run_id':key,'payload':payload}) if exp and exp.get('app_paths') else http(url,'/completion',payload,timeout=40)
   native_elapsed=(time.perf_counter()-t)*1000;sample=measured_response(response,native_elapsed);sample['cache_tokens_reused']=response.get('timings',{}).get('cache_n');sample['prefill_compute_ms']=None;sample['queue_ms']=None
   if exp and (exp['campaign_item']['ignore_eos'] if exp.get('campaign_v18') else body['max_tokens']>=64) and sample['tokens']!=body['max_tokens']:raise ValueError('native output token count differs from frozen generation budget')
   (folder/('warmup.json' if i==0 else f'sample-{i}.json')).write_text(json.dumps(sample,ensure_ascii=False,indent=2),encoding='utf8');row['warmup' if i==0 else 'samples'].append(sample);row['summary']=summary(row['samples']);event('warmup_complete' if i==0 else 'measurement',{'e2e_ms':sample['e2e_ms'],'cache_tokens_reused':sample['cache_tokens_reused']});sample['runner_postprocess_persist_ms']=(time.perf_counter()-t)*1000-native_elapsed
   if exp and exp.get('app_paths') and i>0:
    app_url='http://127.0.0.1:'+str(workspace.lab.profile['port']);import urllib.request
    req=urllib.request.Request(app_url+'/lab/fastpath/completion',data=json.dumps({'run_id':key,'payload':payload}).encode(),headers={'X-Hydra-Lab':workspace.lab.profile['key'],'Content-Type':'application/json'});beg=time.perf_counter()
    with urllib.request.urlopen(req,timeout=45) as answer:app_response=json.load(answer)
    app_sample=measured_response(app_response,(time.perf_counter()-beg)*1000);app_sample['comparison_native_sample']=i;row.setdefault('application_path_samples',[]).append(app_sample);(folder/f'app-sample-{i}.json').write_text(json.dumps(app_sample,ensure_ascii=False,indent=2),encoding='utf8');event('app_path_measurement',{'sample':i,'e2e_ms':app_sample['e2e_ms']})
  row['quality_gate']='TEXT_SELF_IDENTICAL' if len({s['output'] for s in row['samples']})==1 else 'QUALITY_GATE_FAILED';complete=True
 except Exception as exc:
  if exp:
   from serve.hydra_recovery_diagnostics import persist_fault
   fault_log=(folder/'runtime.log').read_text(encoding='utf8',errors='replace') if (folder/'runtime.log').exists() else ''
   row['native_fault']=persist_fault(fault_log,Path(__file__).resolve().parents[1]/'data/hydra-v8-safety-stop.json',folder,{'run_id':key,'model_hash':row['model_hash'],'runtime_hash':row['runtime_hash'],'process':row.get('process_identity'),'command':row.get('command')})
  row['status']='CANCELLED' if isinstance(exc,InterruptedError) else 'TIMEOUT' if isinstance(exc,TimeoutError) else 'RESOURCE_BLOCKED' if isinstance(exc,MemoryError) else 'FAIL';row['error']=type(exc).__name__+': '+str(exc);event('error',row['error'])
  if row.get('native_fault',{}).get('stop_gpu_sequence') or 'ErrorDeviceLost' in str(exc):row['status']='FAILED_DEVICE_LOST'
 finally:
  if getattr(workspace,'fastpath_session',None):workspace.fastpath_session.active=False;workspace.fastpath_session=None
  if child and child.poll() is None:
   child.terminate()
   try:child.wait(5)
   except subprocess.TimeoutExpired:child.kill();child.wait(3)
  if handle:handle.close()
  if system:system.release()
  if lease:release_runtime_lock(lease)
  workspace.lock.release();row['cleanup']=child is None or child.poll() is not None;row['exit_code']=child.returncode if child else None;row['finished_at']=now();event('cleanup',{'child_stopped':row['cleanup'],'locks_released':True,'available_ram_bytes':psutil.virtual_memory().available,'method':'owned TerminateProcess; exit1 is controlled Windows service stop'})
  if live:live.close()
  if exp:
   from serve.hydra_fastpath import can_publish
   complete=can_publish(complete,row['cleanup'],True,True)
  if complete and row['cleanup'] and row['status']=='RUNNING':row['status']='PASS'
  if exp and exp.get('campaign_v18'):
   from serve.hydra_acceptance_campaign import finish,bind_comparison
   finish(body,row)
   bind_comparison(row)
  row['artifact_hashes']={p.name:sha(p) for p in folder.iterdir() if p.is_file() and p.suffix=='.json'};(folder/'run.json').write_text(json.dumps(row,ensure_ascii=False,indent=2));workspace.store.put(row)
 if workspace.lab.profile.get('publish_existing_benchmarks'):
  from serve.hydra_lab_integration import publish_existing_registry
  publish_existing_registry(workspace,Path(__file__).resolve().parents[1],**({'run_id':key} if exp else {}))
 return row

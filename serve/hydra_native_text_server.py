"""Native CPU server adapter for template-aware text generation; one owned child."""
import hashlib,json,os,secrets,threading,time,uuid
from pathlib import Path
import psutil
from serve.hydra_execution_v10 import guarded_popen,apply_owned_affinity

def request_deadline(model):
 return 600 if model=='prism-ml/Ternary-Bonsai-2-27B-gguf' else 180

def launch_context(binary,env):
 allowed=('CUDA_VISIBLE_DEVICES','HIP_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES','OMP_NUM_THREADS','HYDRA_MODEL_IO','STRATA_IO_THREADS')
 return dict(cwd=str(Path(binary).parent),environment_filtered={key:env[key] for key in allowed if key in env})

def server_request(body,options=None):
 if body.get('thinking') not in ('on','off'):raise ValueError('explicit thinking mode required')
 if type(body.get('max_tokens')) is not int or not 1<=body['max_tokens']<=128:raise ValueError('invalid output budget')
 options=options or {}
 return dict(messages=[dict(role='user',content=body['prompt'])],max_tokens=body['max_tokens'],stream=False,temperature=0,seed=options.get('seed',42),cache_prompt=options.get('cache_prompt',False),chat_template_kwargs=dict(enable_thinking=body['thinking']=='on'))
def server_arguments(binary,model,port,options=None):
 options=options or {}
 if options.get('gpu_layers',0)!=0:raise ValueError('CPU_PROFILE_GPU_PARAMETER')
 threads=str(options.get('threads',2))
 args=[str(binary),'-m',str(model),'--host','127.0.0.1','--port',str(port),'-ngl','0','--device','none','-c',str(options.get('context',512)),'-t',threads,'-tb',threads,'--parallel','1','--jinja','--verbosity','4']
 if not options.get('mmap',True):args.append('--no-mmap')
 return args

def loader_telemetry(log,tensor_bytes):
 import re
 if 'HYDRA_LOADER mode=iocp consumer=llama_file::read_raw' not in log:raise ValueError('PRISM_IOCP_NOT_APPLIED; no fallback')
 rows=re.findall(r'HYDRA_IOCP consumer_bytes=(\d+) physical_bytes=(\d+) completions=(\d+) cleanup=closed',log)
 totals=[sum(int(row[i]) for row in rows) for i in range(3)]
 if totals[0]!=tensor_bytes or totals[1]<totals[0] or totals[2]<1:raise ValueError('PRISM_IOCP_TENSOR_BYTES_NOT_VERIFIED')
 return dict(expected_tensor_bytes=tensor_bytes,consumer_bytes=totals[0],physical_bytes=totals[1],completions=totals[2],cleanup='closed',scope='Exact native tensor consumer bytes; GGUF file headers excluded from expected tensor total. Not physical RAM or a performance claim')

def select_loader(cat,options,hybrid=False,manifest=None):
 mode=options.get('model_io','standard')
 if mode=='standard':return cat
 if cat['id']!='prism-ml/Ternary-Bonsai-2-27B-gguf' or hybrid or options.get('mmap',True):raise ValueError('PRISM_LOADER_REQUIRES_NATIVE_CPU_AND_MMAP_OFF')
 if manifest is None:
  root=Path(__file__).resolve().parents[1]/'hydra-engine';candidate=root/'engine_completion_v22/prism-loader-manifest.json'
  manifest=candidate if candidate.is_file() else root/'engine_completion_v20/prism-loader-manifest.json'
 manifest=Path(manifest)
 data=json.loads(manifest.read_text(encoding='utf8'))
 if data.get('model_hash')!=cat.get('asset_hash') or type(data.get('tensor_bytes')) is not int or data['tensor_bytes']<1:raise ValueError('PRISM_LOADER_MODEL_IDENTITY_NOT_ADMITTED')
 if data.get('source_commit')!='e3de715222b2667c54a267441159a5729f11155e' or data.get('gpu_backends')!=[]:raise ValueError('PRISM_LOADER_IDENTITY_NOT_ADMITTED')
 for name,expected in data.get('helper_sha256',{}).items():
  source=Path(__file__).resolve().parents[1]/name
  if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:raise ValueError('PRISM_LOADER_SOURCE_IDENTITY_CHANGED; no legacy fallback')
 runtime=(manifest.parent/data['runtime_relative']).resolve()
 if not runtime.is_relative_to(manifest.parent.resolve()):raise ValueError('PRISM_LOADER_OUTSIDE_ISOLATED_ROOT')
 result=dict(cat,runtime_path=str(runtime/'llama-server.exe'),runtime_manifest=data['files'],loader_source_commit=data['source_commit'],loader_tensor_bytes=data['tensor_bytes'])
 return result

def retrieve_context(lab,body):
 messages=[dict(role='user',content=body['prompt'])]
 if not body.get('graph'):
  if getattr(lab,'graphify_index',None) is not None:lab.graphify_index.clear()
  return messages,None
 features=getattr(lab,'features',None)
 if features is not None:
  controller=features.setting(24)
  if controller['desired'] and len(body['prompt'])<controller['parameters']['min_query_chars']:
   return messages,dict(nodes=[],skipped=True,reason='retrieval_cost_not_justified',variant=body.get('variant','H0'))
 from serve.hydra_graphify_runtime import repository_context
 request=dict(query=body['prompt'],variant=body.get('variant','H0'))
 with repository_context(lab,dict(path='/lab/retrieve',request=request),section_chars=384) as graphify:
  result=dict(lab.retrieve(request));result['graphify']=graphify
  result['authorized_source_roots']=[str(root) for root in lab.g.roots];result['database']=str(lab.g.path)
 if result.get('provider_stopped') is False:raise ValueError('RETRIEVAL_PROVIDER_NOT_STOPPED')
 result['retrieved_node_count']=len(result['nodes'])
 limit=features.setting(20)['parameters']['max_nodes'] if features is not None else 2
 result['nodes']=result['nodes'][:limit]
 from serve.hydra_graph import source_context_block
 if result['nodes']:messages.insert(0,dict(role='user',content=source_context_block(result['nodes'],compact=True)))
 result['source_reference_map']=[dict(source_id=index+1,node=node['id'],source=node['source'],sha256=node['source_sha256'],source_span=node.get('source_span')) for index,node in enumerate(result['nodes'])]
 return messages,result

def verify_native_sources(trace,query):
 if not trace or not trace.get('nodes'):return True
 from serve.hydra_graph_memory import GraphMemory
 expected=trace['nodes'];graph=GraphMemory.open(trace['database'],roots=trace['authorized_source_roots'])
 actual=graph.retrieve('lab',query,allowed_sources=[row['source'] for row in expected],ranked_node_ids=[row['id'] for row in expected],max_nodes=len(expected),depth=0,deadline=time.monotonic()+2)
 fields=('id','source','source_sha256','content','source_span')
 if len(actual)!=len(expected) or any(any(a.get(key)!=b.get(key) for key in fields) for a,b in zip(actual,expected)):raise ValueError('NATIVE_SOURCE_CHANGED_OR_UNVERIFIED; no stale context forwarded')
 return True

def native_json(port,key,path,payload,*,pool=None,cancel=None):
 import http.client
 if cancel is not None and cancel.is_set():raise ValueError('NATIVE_API_CANCELLED')
 factory=pool.connection if pool is not None else http.client.HTTPConnection
 connection=factory('127.0.0.1',port,10)
 try:
  connection.request('POST',path,json.dumps(payload,ensure_ascii=False).encode(),{'Authorization':'Bearer '+key,'Content-Type':'application/json'})
  response=connection.getresponse();raw=response.read(8*1024**2+1)
  if len(raw)>8*1024**2:raise ValueError('NATIVE_API_RESPONSE_BUDGET')
  data=json.loads(raw)
  if response.status!=200:raise ValueError('NATIVE_CONTEXT_API_FAILED: '+path)
  if not isinstance(data,dict) or data.get('error'):raise ValueError('NATIVE_CONTEXT_API_INVALID_RESPONSE: '+path)
  if cancel is not None and cancel.is_set():raise ValueError('NATIVE_API_CANCELLED')
  response._hydra_body_consumed=True
  return data
 finally:connection.close()

def compile_native_context(port,key,messages,body,context,*,pool=None,cancel=None):
 extra=dict(pool=pool,cancel=cancel) if pool is not None or cancel is not None else {}
 prepared=native_json(port,key,'/apply-template',dict(messages=messages,add_generation_prompt=True,chat_template_kwargs=dict(enable_thinking=body['thinking']=='on')),**extra)['prompt']
 if not isinstance(prepared,str) or not prepared:raise ValueError('NATIVE_TEMPLATE_PROMPT_INVALID')
 tokens=native_json(port,key,'/tokenize',dict(content=prepared,add_special=True,parse_special=True),**extra)['tokens']
 if not isinstance(tokens,list) or not tokens or any(type(token) is not int or not 0<=token<2**31 for token in tokens):raise ValueError('NATIVE_TOKENIZER_IDS_INVALID')
 count=len(tokens)
 if count+body['max_tokens']+64>context:raise ValueError('NATIVE_CONTEXT_BUDGET_EXCEEDED')
 return dict(compiled_prompt_tokens=count,prepared_prompt_sha256=hashlib.sha256(prepared.encode()).hexdigest())

def repetition_count(body,reuse):
 count=body.get('samples',1)
 if type(count) is not int or count not in (1,2) or (count>1 and not reuse):raise ValueError('NATIVE_REUSE_REQUIRED; at most two serial requests')
 return count

def hybrid_arguments(binary,model,port,layers,options):
 if type(layers) is not int or not 1<=layers<=65:raise ValueError('UNSUPPORTED_OFFLOAD_RANGE_1_65')
 args=server_arguments(binary,model,port,options)
 args[args.index('-ngl')+1]=str(layers);args[args.index('--device')+1]='Vulkan0'
 return args+['--no-warmup']

def bind_native_comparison(row):
 import copy
 from serve.hydra_lab_benchmarks import comparison_key
 row.setdefault('measurement_scope','Native application request phase, excluding cold load/retrieval/context compilation; includes in-phase safety checks and response persistence')
 parameters=copy.deepcopy(row.get('parameters',{}))
 if row.get('applied_messages') is not None:parameters['messages']=copy.deepcopy(row['applied_messages'])
 parameters['native_settings']={key:row.get('configuration',{}).get(key) for key in ('context','threads','mmap','model_io','reuse_runtime_within_admission')}
 parameters['samples_requested']=row.get('request_json',{}).get('samples',1)
 if row.get('request_json',{}).get('checkpoint'):
  parameters['native_state']={key:row['request_json'].get(key) for key in ('checkpoint','state_mode','followup')}
 if row.get('effective_cpu_affinity') is not None:parameters['cpu_affinity']=row['effective_cpu_affinity']
 row['parameters']=parameters;row['comparison_key']=comparison_key(row)

def native_options(control,model):
 from serve.hydra_feature_control import runtime_options
 options=runtime_options(control) if control is not None else {}
 if model!='prism-ml/Ternary-Bonsai-2-27B-gguf' and (control is None or not control.setting(11)['desired']):options['context']=512
 return options

def execute(workspace,body,key=None,cancel=None):
 from serve.hydra_capability_contracts import guard_request,RuntimeOwnership
 guard_request(body)
 from serve.hydra_lab_benchmarks import now,comparison_key,acquire_runtime_lock,release_runtime_lock,reserve_system_runtime
 from serve.hydra_lab_app import free_port
 from serve.optional_inference import LocalOpenAIBackend
 options=native_options(getattr(workspace.lab,'features',None),body.get('model_id'))
 key=key or uuid.uuid4().hex;folder=workspace.store.root/'runs'/key;folder.mkdir(parents=True,exist_ok=True)
 cat=dict(next(item for item in workspace.catalog() if item['id']==body['model_id']));v21=body.get('profile')=='v21-bonsai-hybrid';hybrid=v21 or body.get('profile','').startswith('v20-bonsai-');layers=body.get('gpu_layers') if v21 else None;state_slot=None
 if hybrid:
  if v21:
   from serve.hydra_engine_v21 import validate,validate_native_options
   validate_native_options(body,options)
  else:
   from serve.hydra_engine_v20 import validate,PROFILES
   layers=PROFILES[body['profile']]
  grant,_=validate(body);cat['runtime_path']=str(Path(grant['runtime'])/'llama-completion.exe');cat['runtime_manifest']=grant['files']
 cat=select_loader(cat,options,hybrid)
 binary=Path(cat['runtime_path']).with_name('llama-server.exe');model=Path(cat['assets'][0]['path'])
 cancel=cancel or threading.Event();finished=threading.Event();child=None;system=None;watcher=None;live=None;pool=None;ownership=None;duration=request_deadline(cat['id']);deadline=time.monotonic()+duration;failures=[]
 row=dict(run_id=key,origin='E2E_TEST',status='RUNNING',timestamp=now(),model=cat['id'],model_hash=cat['asset_hash'],runtime=str(binary),runtime_hash=cat.get('runtime_manifest',{}).get(binary.name),backend='CPU',profile='native-text-server-cpu-v13',quantization=cat['quantization'],prompt_id=body['prompt_id'],prompt=body['prompt'],prompt_hash=hashlib.sha256(body['prompt'].encode()).hexdigest(),template_hash=cat['asset_hash'],parameters=server_request(body,options),configuration=dict(threads=2,gpu_layers=0,context=512,parallel=1,deadline_s=duration,ram_min_free_gib=32,rss_stop_gib=24),request_json=body,samples=[],summary={},events=[],cleanup=False,error=None,exit_code=None,quality_gate='NOT_VERIFIED',log_path=str(folder/'runtime.log'),artifacts=str(folder),real_execution_kind='native CPU server inference',owner_pid=os.getpid(),owner_created=psutil.Process().create_time())
 row['configuration'].update(model_io=options.get('model_io','standard'),threads=options.get('threads',2),context=options.get('context',512),mmap=options.get('mmap',True),cache_prompt=options.get('cache_prompt',False))
 if hybrid:row.update(profile=body['profile'],backend='NOT_VERIFIED',real_execution_kind='native Prism hybrid inference');row['configuration']['gpu_layers']=layers;row['requested_layers']=layers
 row['comparison_key']=comparison_key(row)
 if not workspace.lock.acquire(False):raise ValueError('BLOCKED_BUSY')
 try:lease=acquire_runtime_lock(workspace.store.root)
 except BaseException:workspace.lock.release();raise
 def event(kind,detail=None):
  from serve.hydra_native_state import frozen_detail
  row['events'].append(dict(at=now(),kind=kind,detail=frozen_detail(detail)));workspace.store.put(row)
 try:
  event('admission')
  ownership=RuntimeOwnership(key,cat['asset_hash'])
  if body['max_tokens']>options.get('max_tokens',128):raise ValueError('FEATURE_OUTPUT_BUDGET_EXCEEDED')
  repetitions=repetition_count(body,workspace.lab.features.setting(3)['desired'])
  row['configuration']['reuse_runtime_within_admission']=repetitions>1
  if (body['profile']!='cpu' and not hybrid) or workspace.lab.profile.get('operational_loaded'):raise ValueError('isolated CPU admission required')
  if psutil.virtual_memory().available<32*1024**3:raise MemoryError('32 GiB available RAM required')
  if not row['runtime_hash']:raise ValueError('SERVER_RUNTIME_NOT_ATTESTED')
  for path,expected in [(model,cat['asset_hash']),*[(binary.parent/name,value) for name,value in cat['runtime_manifest'].items()]]:
   with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
   if actual!=expected:raise ValueError('ASSET_RUNTIME_IDENTITY_CHANGED: '+path.name)
  system=reserve_system_runtime(Path(__file__).resolve().parents[1]);workspace.lab.stop_backend()
  messages,retrieval=retrieve_context(workspace.lab,body);row['retrieval']=retrieval;row['applied_messages']=messages
  row['prepared_messages_sha256']=hashlib.sha256(json.dumps(messages,ensure_ascii=False,sort_keys=True).encode()).hexdigest();bind_native_comparison(row)
  from serve.hydra_lab_live import LiveMonitor
  live=LiveMonitor(workspace,row)
  port=free_port();args=server_arguments(binary,model,port,options);row['effective_native_options']=options;row['command']=args
  api_key=secrets.token_urlsafe(32)
  env=dict(os.environ,LLAMA_API_KEY=api_key,CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1',OMP_NUM_THREADS=str(options.get('threads',2)));env.pop('GGML_BACKEND_PATH',None)
  env.pop('HYDRA_MODEL_IO',None)
  if options.get('model_io','standard')!='standard':
   env['HYDRA_MODEL_IO']='iocp' if options['model_io']=='iocp' else 'standard';env['STRATA_IO_THREADS']='1'
  if hybrid:
   if v21:
    from serve.hydra_engine_v21 import preflight,consume
   else:
    from serve.hydra_engine_v20 import preflight
   row['vram_free_before_mib']=preflight(body,key,binary,env)
   args=hybrid_arguments(binary,model,port,layers,options)

   if v21:consume(Path(grant['counter']),key+'-1')
   row['command']=args
  if body.get('checkpoint'):
   from serve.hydra_native_state import NativeSlot,session_identity
   budget=workspace.lab.features.setting(16)['parameters']['max_checkpoint_mib']*1024**2
   state_slot=NativeSlot(folder/'native-state',session_identity(cat['asset_hash'],row['runtime_hash'],key,options['context'],layers or 0,body['thinking'],options),budget)
   row['configuration'].update(native_state_mode=body.get('state_mode'),native_state_budget_bytes=budget)
   args+=['--slot-save-path',str(state_slot.root)];row['command']=args
  row['native_launch_context']=launch_context(binary,env)
  with (folder/'runtime.log').open('wb') as log:
   child=guarded_popen(args,cwd=binary.parent,env=env,stdout=log,stderr=log,creationflags=0x08000000)
  ownership.attach(child);row['runtime_ownership']=ownership.snapshot()
  process=psutil.Process(child.pid);row['effective_cpu_affinity']=apply_owned_affinity(child.pid,process.cpu_affinity()[:options.get('affinity_cpus',2)]);row.update(owned_pid=child.pid,owned_created=process.create_time());bind_native_comparison(row);event('startup')
  def monitor():
   while not finished.wait(.1):
    try:
     if time.monotonic()>deadline:failures.append('absolute native server deadline')
     elif process.memory_info().rss>(24 if cat['quantization']=='NVFP4' else 20)*1024**3 or psutil.virtual_memory().available<12*1024**3:failures.append('monitored memory resource stop')
     if failures:cancel.set();return
    except psutil.NoSuchProcess:return
  watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
  client=LocalOpenAIBackend('http://127.0.0.1:'+str(port)+'/v1',api_key=api_key,timeout=1)
  if workspace.lab.features.setting(35)['desired']:
   from serve.hydra_http_pool import SerialConnectionPool
   pool=SerialConnectionPool();client.connection_factory=pool.connection
  while True:
   if cancel.is_set():raise TimeoutError('; '.join(failures) or 'cancelled')
   if child.poll() is not None:raise RuntimeError('owned server exited during startup')
   try:models=client.models();break
   except OSError:time.sleep(.5)
   except Exception as exc:
    if 'HTTP 503' not in str(exc):raise
    time.sleep(.5)
  row['startup_ms']=(time.monotonic()-(deadline-duration))*1000
  from serve.hydra_prism_campaign import backend_evidence
  row['backend_evidence']=backend_evidence((folder/'runtime.log').read_text(errors='replace'),'Vulkan' if hybrid else 'CPU');row['memory_reported']=row['backend_evidence']['memory_runtime_lines'];row['actual_layers']=row['backend_evidence']['actual_layers'];row['total_layers']=row['backend_evidence']['total_layers'];row['backend']='Vulkan' if hybrid else 'CPU'
  if options.get('model_io')=='iocp':
   loader_log=(folder/'runtime.log').read_text(errors='replace')
   row['loader_counters']=loader_telemetry(loader_log,cat['loader_tensor_bytes'])
   row['loader_evidence']=[line for line in loader_log.splitlines() if 'HYDRA_LOADER' in line or 'HYDRA_IOCP' in line]
  row['cpu_layers']=row['total_layers']-row['actual_layers'] if row.get('total_layers') is not None and row.get('actual_layers') is not None else None
  if hybrid and row['actual_layers']!=layers:raise ValueError('V20_EFFECTIVE_LAYER_MISMATCH')
  if retrieval and retrieval['nodes']:
   verify_native_sources(retrieval,body['prompt']);row['source_revalidated_before_generation']=True
   block=messages[0]['content']
   parsed=native_json(port,api_key,'/tokenize',dict(content=block,add_special=False,parse_special=True),pool=pool,cancel=cancel)['tokens']
   plain=native_json(port,api_key,'/tokenize',dict(content=block,add_special=False,parse_special=False),pool=pool,cancel=cancel)['tokens']
   if parsed!=plain:raise ValueError('SOURCE_CONTAINS_NATIVE_SPECIAL_TOKEN')
  row.update(compile_native_context(port,api_key,messages,body,options.get('context',512),pool=pool,cancel=cancel))
  for repetition in range(repetitions):
   if retrieval and retrieval.get('nodes'):
    verify_native_sources(retrieval,body['prompt']);row['source_revalidation_count']=row.get('source_revalidation_count',0)+1
   active_messages=messages;compiled=dict(compiled_prompt_tokens=row['compiled_prompt_tokens'],prepared_prompt_sha256=row['prepared_prompt_sha256'])
   if state_slot is not None and repetition==1 and body.get('state_mode')=='continuation':
    from serve.hydra_native_state import continuation_messages
    active_messages=continuation_messages(messages,row['samples'][0]['output'],body['followup'])
    compiled=compile_native_context(port,api_key,active_messages,body,options.get('context',512),pool=pool,cancel=cancel);row['continuation_context']=compiled
   event('request_start');started=time.perf_counter()
   request=server_request(body,options);request.pop('stream');request.pop('messages');client.timeout=duration
   if hybrid:
    if v21:
     from serve.hydra_engine_v21 import preflight,consume
    else:
     from serve.hydra_engine_v20 import preflight,consume
    row['vram_free_before_request_mib']=preflight(body,key,binary,env)
    if not v21 or repetition>0:consume(Path(grant['counter']),key+'-'+str(repetition+1) if v21 else key)
   ownership.begin_sequence()
   response=next(client.chat(active_messages,models[0]['id'],cancel=cancel,**request),None)
   ownership.end_sequence();row['runtime_ownership']=ownership.snapshot()
   if pool is not None:row['http_pool']=dict(pool.stats)
   if not response:raise RuntimeError('; '.join(failures) or 'request cancelled without output')
   (folder/('response-'+str(repetition+1)+'.json')).write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding='utf8');row['original_result']=response
   choice=response['choices'][0];text=choice.get('message',{}).get('content') or '';reasoning=choice.get('message',{}).get('reasoning_content') or ''
   row['output_validity']=dict(nonempty_text=bool(text.strip()),finish_reason=choice.get('finish_reason'),thinking_requested=body['thinking'],reasoning_output_present=bool(reasoning or '<think>' in text),semantic_quality='NOT_VERIFIED')
   if not text.strip() or choice.get('finish_reason')=='length':raise ValueError('INCOMPLETE_OUTPUT; preserve native response')
   if body['thinking']=='off' and row['output_validity']['reasoning_output_present']:raise ValueError('THINKING_OFF_NOT_APPLIED')
   row['samples'].append(dict(e2e_ms=(time.perf_counter()-started)*1000,output=text,tokens=response.get('usage',{}).get('completion_tokens')));row['quality_gate']='COMPLETE_NONEMPTY_OUTPUT; semantic quality not automatically verified';row['samples'][-1].update(repetition=repetition+1,usage=response.get('usage'),timings=response.get('timings'),applied_messages=active_messages,**compiled);
   if response.get('usage',{}).get('prompt_tokens')!=compiled['compiled_prompt_tokens']:raise ValueError('NATIVE_COMPILED_PROMPT_COUNT_MISMATCH')
   if type(row['samples'][-1]['tokens']) is not int or row['samples'][-1]['tokens']<1:raise ValueError('NATIVE_TOKEN_COUNT_MISSING')
   from serve.hydra_lab_benchmarks import summary
   row['summary']=summary(row['samples']);event('request_complete')
   if state_slot is not None and repetition==0:
    # Native APIs serialize actual per-sequence KV/recurrent state. No model tensors move.
    row['native_state']=state_slot.cycle(lambda action,payload:native_json(port,api_key,'/slots/0?action='+action,payload,pool=pool,cancel=cancel),cancel,expected_bound=__import__('serve.hydra_native_state',fromlist=['state_size_bound']).state_size_bound(row['memory_reported']),destination_identity=session_identity(cat['asset_hash'],row['runtime_hash'],key,options['context'],layers or 0,body['thinking'],options))
    event('native_state_restored',row['native_state'])
   if state_slot is not None and repetition==1:
    from serve.hydra_native_state import native_cached_tokens
    cached=native_cached_tokens(response,compiled['compiled_prompt_tokens'],row['native_state']['saved_tokens'])
    row['native_state']['subsequent_cached_tokens']=cached
    if cached<1:raise ValueError('NATIVE_STATE_REUSE_NOT_OBSERVED')
 except Exception as exc:row.update(status='FAIL',error=type(exc).__name__+': '+str(exc));event('error',row['error'])
 finally:
  finished.set()
  cleanup_errors=[]
  def cleanup_error(stage,exc):
   detail=stage+': '+type(exc).__name__+': '+str(exc)
   cleanup_errors.append(detail);row['status']='FAIL'
   if not row.get('error'):row['error']=detail
  watcher_stopped=True
  if watcher:
   try:
    watcher.join(2);watcher_stopped=not watcher.is_alive()
    if not watcher_stopped:cleanup_error('WATCHER_CLEANUP',RuntimeError('watcher still active'))
   except Exception as exc:watcher_stopped=False;cleanup_error('WATCHER_CLEANUP',exc)
  row['watcher_cleanup']=watcher_stopped
  if pool is not None:
   try:pool.close();row['http_pool_after_cleanup']=dict(pool.stats)
   except Exception as exc:row['transport_cleanup']=False;cleanup_error('HTTP_POOL_CLEANUP',exc)
  child_stopped=child is None
  if child is not None:
   try:
    if child.poll() is None:
     try:child.terminate()
     except OSError as exc:cleanup_error('CHILD_TERMINATE',exc)
     try:child.wait(5)
     except __import__('subprocess').TimeoutExpired:child.kill();child.wait(3)
    child_stopped=child.poll() is not None
   except Exception as exc:cleanup_error('CHILD_CLEANUP',exc)
  row.update(exit_code=child.returncode if child else None,process_cleanup=child_stopped,finished_at=now())
  if child_stopped:
   if ownership is not None:
    try:ownership.close();row['runtime_ownership']=ownership.snapshot()
    except Exception as exc:row['runtime_ownership_cleanup']=False;cleanup_error('RUNTIME_OWNERSHIP_CLEANUP',exc)
   if state_slot is not None:
    try:state_slot.close();row['native_state_cleanup']=True
    except Exception as exc:row['native_state_cleanup']=False;cleanup_error('NATIVE_STATE_CLEANUP',exc)
  elif state_slot is not None:
   row['native_state_cleanup']=False
   cleanup_error('NATIVE_STATE_CLEANUP',RuntimeError('state retained while child completion is unknown'))
  if live:
   try:live.close()
   except Exception as exc:row['monitor_cleanup']=False;cleanup_error('MONITOR_CLEANUP',exc)
  if child_stopped and watcher_stopped:
   if system:
    try:system.release()
    except Exception as exc:cleanup_error('SYSTEM_LEASE_CLEANUP',exc)
   try:release_runtime_lock(lease)
   except Exception as exc:cleanup_error('RUNTIME_LOCK_CLEANUP',exc)
   try:workspace.lock.release()
   except Exception as exc:cleanup_error('WORKSPACE_LOCK_CLEANUP',exc)
  else:
   # Keep strong ownership of the original handles; no second coordinator or retry.
   workspace._hydra_retained_cleanup=(lease,system,child,state_slot,ownership,watcher)
  row['cleanup_errors']=cleanup_errors
  row['cleanup']=child_stopped and watcher_stopped and row.get('transport_cleanup',True) and not cleanup_errors
  event('cleanup',row['cleanup'])
 if hybrid:
  if v21:
   from serve.hydra_engine_v21 import finish
  else:
   from serve.hydra_engine_v20 import finish
  finish(body,row)
 if row['status']=='RUNNING':row['status']='PASS' if row['cleanup'] else 'FAIL'
 row['artifact_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()};workspace.store.put(row);return row

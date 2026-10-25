from serve.hydra_execution_v10 import guarded_popen,apply_owned_affinity
"""Explicit opt-in HYDRA lab application; no import-time startup or product route changes."""
import argparse,json,os,socket,sys,threading,time,subprocess,hashlib
from pathlib import Path
from types import SimpleNamespace
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler

class LabError(ValueError):pass
from serve.hydra_task_completion import TaskIncomplete,require_completed_task

def lab_session(key):
 import hmac
 return hmac.new(key.encode(),b'hydra-local-browser-session-v12',hashlib.sha256).hexdigest()

def lab_authenticated(headers,key,origin):
 import hmac
 from http.cookies import SimpleCookie,CookieError
 if headers.get('Origin') not in (None,origin):return False
 if hmac.compare_digest(headers.get('X-Hydra-Lab',''),key):return True
 try:cookie=SimpleCookie(headers.get('Cookie',''));value=cookie.get('hydra_lab_session')
 except CookieError:return False
 return bool(value and hmac.compare_digest(value.value,lab_session(key)))

def validate_chat(body):
 if not isinstance(body,dict) or set(body)-{'messages','max_tokens','graph','variant'}:raise LabError('unsupported request')
 if 'variant' in body and (body['variant'] not in ('H0','H1','H1v2') or body.get('graph') is not True):raise LabError('explicit graph required for retrieval variant')
 messages=body.get('messages');n=body.get('max_tokens',64)
 if not isinstance(messages,list) or not 1<=len(messages)<=12:raise LabError('messages required')
 if type(n) is not int or not 1<=n<=128:raise LabError('max_tokens must be1..128')
 for m in messages:
  if not isinstance(m,dict) or set(m)!={'role','content'} or m['role'] not in ('system','user','assistant') or not isinstance(m['content'],str) or not m['content'] or len(m['content'])>16384:raise LabError('invalid message')
 if sum(len(m['content']) for m in messages)>20000:raise LabError('request exceeds lab budget')
 if type(body.get('graph',False)) is not bool:raise LabError('graph boolean required')
 return n

def lab_gpu_layers(profile):
 named=profile.get('execution_profile')
 if named not in (None,'qwen06b-gpu-full-verified-v1'):raise LabError('unknown laboratory execution profile')
 if named and profile.get('gpu_layers',29)!=29:raise LabError('conflicting offload settings')
 layers=29 if named else profile.get('gpu_layers',0)
 tuning=profile.get('offload_tuning') is True
 if type(layers) is not int or layers not in ((0,4,29) if tuning else range(5)):raise LabError('unsupported isolated offload profile')
 if tuning and profile.get('model_sha256')!='9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031':raise LabError('tuning restricted to canonical small Qwen')
 return layers

def lab_device_arguments(profile):
 return ['--device','none' if lab_gpu_layers(profile)==0 else 'ROCm0']

def parse_offload(text,requested_layers=None):
 import re
 found=re.findall(r'offloaded (\d+)/(\d+) layers to GPU',text)
 if not found:
  if requested_layers==0 and ('HYDRA_LOADER mode=iocp consumer=llama_file::read_raw' in text or 'HYDRA_READER mode=standard' in text) and re.search(r'CPU\s+model buffer size',text) and re.search(r'CPU\s+compute buffer size',text):return dict(actual_layers=0,total_layers=None,backend='CPU',evidence='Attested CPU-only candidate plus native CPU model/compute buffers')
  if requested_layers==0 and 'no usable GPU found' in text and re.search(r'CPU(?:_Mapped)?\s+model buffer size',text) and re.search(r'CPU\s+compute buffer size',text):return dict(actual_layers=0,total_layers=None,backend='CPU',evidence='Native no-GPU report plus CPU model/compute buffers; no GPU layer total exposed')
  return dict(actual_layers=None,total_layers=None,backend='NOT_VERIFIED')
 actual,total=map(int,found[-1]);return dict(actual_layers=actual,total_layers=total,backend='ROCm' if actual else 'CPU')

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

def model_loader_runtime(reference,options,layers):
 """Attest an isolated CPU candidate; OFF returns the original loader exactly."""
 if options.get('model_io','standard')=='standard':return Path(reference),dict(mode='standard',runtime=str(reference),consumer='reference runtime loader'),{}
 if layers or options['mmap']:raise LabError('IOCP requires CPU and mmap OFF; no fallback')
 manifest_path=Path(__file__).resolve().parents[1]/'hydra-engine/runtime_integration_v14/loader-runtime-manifest.json'
 candidate=manifest_path.parents[1]/'cpu_fastpath_v15/loader-runtime-manifest.json'
 if candidate.is_file():manifest_path=candidate
 current=Path(__file__).resolve().parents[1]/'hydra-engine/engine_completion_v22/qwen-loader-manifest.json'
 if current.is_file():manifest_path=current;candidate=current
 if options['model_io']=='candidate-standard' and not candidate.is_file():raise LabError('v15 standard candidate missing; no fallback')
 manifest=json.loads(manifest_path.read_text(encoding='utf8'));runtime=(manifest_path.parent/manifest['runtime_relative']).resolve()
 if not runtime.is_relative_to(manifest_path.parent.resolve()):raise LabError('IOCP candidate outside owned runtime root')
 for name,expected in manifest.get('helper_sha256',{}).items():
  if sha(Path(__file__).resolve().parents[1]/name)!=expected:raise LabError('IOCP source identity changed; no legacy fallback')
 if manifest.get('gpu_backends')!=[]:raise LabError('IOCP candidate must be CPU only')
 for name,item in manifest['files'].items():
  if Path(name).name!=name or sha(runtime/name)!=item['sha256']:raise LabError('IOCP candidate identity mismatch')
 mode='standard' if options['model_io']=='candidate-standard' else 'iocp'
 return runtime,dict(mode=mode,candidate=True,runtime=str(runtime),manifest_sha256=sha(manifest_path),consumer='llama_file::read_raw',mmap=False),dict(HYDRA_MODEL_IO=mode,STRATA_IO_THREADS='1')

def attest_model_loaders(calls,folder):
 import re
 result=[]
 for call in calls:
  if call.get('event')!='backend_start' or Path(call.get('log_path','')).parent!=Path(folder):continue
  item=dict(call.get('model_loader') or {'mode':'standard','runtime':str(call['command'][0])});item['log_path']=call['log_path']
  text=Path(call['log_path']).read_text(encoding='utf8',errors='replace')
  if item.get('candidate'):
   counters=re.findall(r'HYDRA_READER mode='+item['mode']+r' consumer_bytes=(\d+) cleanup=closed',text)
   if not counters or sum(int(x) for x in counters)<=0:raise LabError('candidate consumer bytes/cleanup not attested')
   item['native_reader_bytes']=sum(int(x) for x in counters)
  if item['mode']=='iocp':
   counters=re.findall(r'HYDRA_IOCP consumer_bytes=(\d+) physical_bytes=(\d+) completions=(\d+) cleanup=closed',text)
   if 'HYDRA_LOADER mode=iocp consumer=llama_file::read_raw' not in text or not counters or sum(int(x[0]) for x in counters)<=0:raise LabError('IOCP consumer/cleanup not attested; no fallback')
   item.update(consumer_bytes=sum(int(x[0]) for x in counters),physical_bytes=sum(int(x[1]) for x in counters),completions=sum(int(x[2]) for x in counters),reader_cleanup='closed')
  result.append(item)
 return result

def free_port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def save_sources(corpus,sources):
 root=Path(corpus).resolve();items=[]
 for value in sources:
  p=Path(value)
  if p.is_symlink() or not p.resolve(strict=True).is_relative_to(root) or not p.is_file():raise LabError('source outside owned corpus')
  items.append({'path':str(p.resolve()),'sha256':sha(p)})
 from serve.hydra_execution_v10 import write
 write(root.parent/'lab-source-authorization.json',{'schema_version':1,'scope':'lab','sources':items,'updated_at':time.time()})

def restore_sources(corpus):
 root=Path(corpus).resolve();manifest=root.parent/'lab-source-authorization.json';allowed=[];rejected=[]
 if not manifest.exists():return allowed,rejected
 try:
  data=json.loads(manifest.read_text(encoding='utf8'))
  if data.get('schema_version')!=1 or data.get('scope')!='lab' or not isinstance(data.get('sources'),list):raise ValueError('invalid source authorization schema')
  for item in data['sources']:
   try:
    p=Path(item['path'])
    if p.is_symlink() or not p.resolve(strict=True).is_relative_to(root) or not p.is_file() or sha(p)!=item['sha256']:raise ValueError('source missing, changed or outside corpus')
    allowed.append(str(p.resolve()))
   except (OSError,ValueError,TypeError,KeyError) as ex:rejected.append(str(ex))
 except (OSError,ValueError,TypeError,KeyError) as ex:return [],[str(ex)]
 return allowed,rejected

def attach_http_pool(lab,backend):
 lab.http_pool=None
 if getattr(lab,'features',None) is not None and lab.features.setting(35)['desired']:
  from serve.hydra_http_pool import SerialConnectionPool
  lab.http_pool=SerialConnectionPool();backend.connection_factory=lab.http_pool.connection

class Lab:
 def __init__(self,profile):
  self.profile=profile;self.data=Path(profile['data']).resolve();self.data.mkdir(exist_ok=True);self.child=None;self.client=None;self.log=None;self.closed=False;self.calls=[];self.graph_options={};self.provider=None
  from serve.hydra_graph_memory import GraphMemory
  self.corpus=self.data/'corpus';self.corpus.mkdir(exist_ok=True);self.sources=[]
  self.g=(GraphMemory.open_writer if (self.data/'graph.sqlite').exists() else GraphMemory.create)(self.data/'graph.sqlite',roots=[self.corpus])
  from serve.hydra_lab_benchmarks import Workspace
  self.benchmarks=Workspace(self)
  from serve.hydra_feature_control import FeatureControl
  self.features=FeatureControl(self.benchmarks.store.root,catalog=self.benchmarks.catalog)
  self.sources,self.source_rejections=restore_sources(self.corpus)
  if self.sources:self.configure_graph()
  if self.profile.get('publish_existing_benchmarks'):
   from serve.hydra_lab_live import retained
   retained(self.benchmarks)
 def status(self):
  path=self.data/'runtime.log';actual=parse_offload(path.read_text(encoding='utf-8',errors='replace'),requested_layers=lab_gpu_layers(self.profile)) if path.is_file() else parse_offload('')
  running=self.child is not None and self.child.poll() is None
  with self.benchmarks.jobs_lock:worker_active=any(t.is_alive() for t,c in self.benchmarks.jobs.values())
  return dict(execution_admission=__import__('serve.hydra_execution_v10',fromlist=['admission_status']).admission_status(),benchmark_worker_active=worker_active,benchmark_reservation_active=self.benchmarks.lock.locked(),lab=True,model=self.profile['model'],backend=actual['backend'] if running else 'not started',running=running,gpu=bool(actual['actual_layers']),offload=actual,requested_layers=lab_gpu_layers(self.profile),source_count=len(self.sources),max_nodes=2,default_product_changed=False)
 def stop_backend(self):
  errors=[]
  if self.client is not None:
   try:self.client.close();self.client=None
   except Exception as exc:errors.append('client: '+str(exc))
  if getattr(self,'http_pool',None) is not None:
   try:self.http_pool.close();self.calls.append(dict(event='http_pool_cleanup',stats=dict(self.http_pool.stats)));self.http_pool=None
   except Exception as exc:errors.append('transport: '+str(exc))
  if self.child is not None:
   pid=self.child.pid
   try:
    if self.child.poll() is None:self.child.terminate()
    try:self.child.wait(5)
    except subprocess.TimeoutExpired:self.child.kill();self.child.wait(3)
    self.calls.append(dict(event='backend_cleanup',pid=pid,exit_code=self.child.returncode,stopped=True));self.child=None
   except Exception as exc:errors.append('child: '+str(exc))
  if self.log:
   try:self.log.close();self.log=None
   except Exception as exc:errors.append('log: '+str(exc))
  if errors:raise RuntimeError('BACKEND_CLEANUP_UNVERIFIED: '+'; '.join(errors))
 def start(self):
  if getattr(self,'closed',False):raise RuntimeError('provider unavailable')
  from serve.hydra_capability_contracts import guard_request
  guard_request(self.profile)
  if self.child is not None:
   if self.child.poll() is None:
    if self.client is None:raise RuntimeError('backend admission failed; no automatic retry')
    return
   raise RuntimeError('backend exited; no automatic restart')
  if self.closed:raise RuntimeError('provider unavailable')
  import psutil
  if psutil.virtual_memory().available<12*1024**3:raise RuntimeError('RAM below12GiB')
  p=self.profile
  from serve.hydra_feature_control import runtime_options
  options=runtime_options(getattr(self,'features',None))
  identity_started=time.perf_counter()
  if sha(p['model'])!=p['model_sha256']:raise RuntimeError('model identity mismatch')
  for name,row in p['runtime_manifest']['files'].items():
   if sha(Path(p['runtime'])/name)!=row['sha256']:raise RuntimeError('runtime identity mismatch')
  layers=lab_gpu_layers(p);startup_started=time.perf_counter()
  runtime,loader,loader_env=model_loader_runtime(p['runtime'],options,layers)
  self.identity_verification_ms=(time.perf_counter()-identity_started)*1000
  port=free_port();args=[str(runtime/'llama-server.exe'),'-m',p['model'],'--host','127.0.0.1','--port',str(port),'-c',str(options['context']),'-t',str(options['threads']),'-tb',str(options['threads']),'-ngl',str(layers),'--parallel','1','--alias','optional-model']
  if getattr(self,'features',None):args+=['--load-mode','mmap' if options['mmap'] else 'none']
  env=dict(os.environ,GGML_BACKEND_PATH=str(runtime),CUDA_VISIBLE_DEVICES='',HIP_VISIBLE_DEVICES='',ROCR_VISIBLE_DEVICES='',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2')
  env.pop('HYDRA_MODEL_IO',None);env.update(loader_env)
  if not layers:env.pop('GGML_BACKEND_PATH',None) # Native loader expects an optional backend file, not this directory.
  if layers:
   env.pop('GGML_BACKEND_PATH',None);env.update(HIP_VISIBLE_DEVICES='0',ROCR_VISIBLE_DEVICES='0')
  if layers or p.get('offload_tuning') is True or loader.get('candidate'):args+=lab_device_arguments(p)+['--verbosity','4']
  runtime_log=self.data/'runtime.log'
  if runtime_log.exists():runtime_log=self.data/('runtime-'+__import__('uuid').uuid4().hex+'.log')
  self.log=runtime_log.open('xb');self.child=guarded_popen(args,cwd=runtime,env=env,stdout=self.log,stderr=self.log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));affinity=apply_owned_affinity(self.child.pid,psutil.Process().cpu_affinity()[:options['affinity_cpus']]);self.calls.append(dict(event='backend_start',command=args,pid=self.child.pid,feature_options=options,cpu_affinity=affinity,log_path=str(runtime_log),model_loader=loader))
  from serve.optional_inference import LocalOpenAIBackend
  local=LocalOpenAIBackend('http://127.0.0.1:'+str(port)+'/v1',timeout=40);attach_http_pool(self,local);end=time.monotonic()+35
  while time.monotonic()<end:
   if getattr(self,'benchmark_cancel',None) is not None and self.benchmark_cancel.is_set():raise RuntimeError('benchmark cancelled during startup')
   if self.child.poll() is not None:raise RuntimeError('backend load failed; no retry')
   try:models=local.models();break
   except Exception:time.sleep(.1)
  else:raise TimeoutError('backend startup deadline')
  self.model_id=models[0]['id']
  from serve.hydra_one import HydraClient
  self.owner=SimpleNamespace(root=self.data,binary=runtime/'llama-server.exe',state={'context':options['context']},graph_config=lambda:self.graph_options)
  self.client=HydraClient(self.owner,local,dict(mode='gguf',gpu=False,model_path=p['model'],context=options['context'],runtime={'slots':1}));self.startup_ms=(time.perf_counter()-startup_started)*1000
 def ingest(self,body):
  if not isinstance(body,dict) or set(body)!={'id','text'} or not isinstance(body['id'],str) or not body['id'].isalnum() or not isinstance(body['text'],str) or len(body['text'])>8000:raise LabError('bounded synthetic document required')
  source=self.corpus/(body['id']+'.txt');source.write_text(body['text'],encoding='utf-8');node=self.g.ingest('lab',source)
  if str(source) not in self.sources:self.sources.append(str(source))
  save_sources(self.corpus,self.sources);self.configure_graph()
  return dict(id=node,source=str(source),sha256=sha(source))
 def configure_graph(self):
  self.graph_options=dict(graph_enabled=True,context_compiler_enabled=True,adaptive_controller_enabled=True,shared_corpus_authorized=True,database=str(self.g.path),source_roots=[str(self.corpus)],allowed_sources=list(self.sources),scope='lab',max_nodes=2,depth=1,token_budget=1600,min_query_chars=40,timeout_ms=1000)
 def retrieve(self,body):
  query=body.get('query');variant=body.get('variant','H0')
  if not isinstance(query,str) or not query or len(query)>16384:raise LabError('bounded query required')
  if variant not in ('H0','H1','H1v2'):raise LabError('unknown variant')
  start=time.perf_counter()
  if variant=='H0':nodes=self.g.retrieve('lab',query,allowed_sources=self.sources,max_nodes=self.features.setting(20)['parameters']['max_nodes'] if getattr(self,'features',None) else 2,depth=1,deadline=time.monotonic()+1);extra={}
  else:
   # Provider exists only for this retrieval; terminate before any generation.
   self.stop_backend()
   sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'hydra-engine'))
   from serve.hydra_lab_modules import load
   graph_module=load('graph_hybrid');LocalDenseProvider=graph_module.LocalDenseProvider;HybridLab=graph_module.HybridLab;HybridLabV2=load('graph_hybrid_v2').HybridLabV2
   a=self.profile['dense'];fp=a['fingerprint'];folder=a['folder']
   with LocalDenseProvider(a['python'],folder,fp,stderr_path=self.data/(variant+'-provider.stderr'),asset_hashes=a['files'],startup_s=25) as provider:
    pid=provider.proc.pid;out=(HybridLabV2 if variant=='H1v2' else HybridLab)(self.g,provider).retrieve('lab',query,self.sources,deadline=time.monotonic()+2,enabled=True);nodes=out.nodes;extra=dict(strategy=out.strategy,fallback=out.fallback,reason=out.reason,coverage=out.coverage,metrics=out.metrics,provider_pid=pid)
   import psutil
   extra['provider_stopped']=not psutil.pid_exists(pid)
   if not extra['provider_stopped']:raise RuntimeError('provider cleanup failed')
  return dict(nodes=[dict(n) for n in nodes],retrieval_ms=(time.perf_counter()-start)*1000,variant=variant,**extra)
 def chat(self,body,*,_performance=False,_transport='runner'):
  from serve.hydra_feature_control import runtime_options
  options=runtime_options(getattr(self,'features',None));n=validate_chat(body)
  if n>options['max_tokens']:raise LabError('feature configuration max_tokens exceeded')
  messages=body['messages'];hybrid=None
  if body.get('graph') and body.get('variant','H0')!='H0':
   # Finish and stop the dense provider before starting the generative runtime.
   query=next(m['content'] for m in reversed(messages) if m['role']=='user')
   hybrid=self.retrieve(dict(query=query,variant=body['variant']))
  self.start();start=time.perf_counter();saved=self.graph_options
  if body.get('graph') and getattr(self,'features',None):
   self.graph_options=dict(self.graph_options)
   self.graph_options['max_nodes']=self.features.setting(20)['parameters']['max_nodes']
   bypass=self.features.setting(24);self.graph_options['min_query_chars']=bypass['parameters']['min_query_chars'];self.graph_options['adaptive_controller_enabled']=bypass['desired']
   if hybrid is not None:self.graph_options['ranked_node_ids']=[row['id'] for row in hybrid['nodes']][:16]
  if not body.get('graph'):self.graph_options={}
  try:
   cancel=getattr(self,'benchmark_cancel',None) or threading.Event();timer=threading.Timer(40,cancel.set);timer.start()
   try:
    extra={'seed':options['seed'],'cache_prompt':options['cache_prompt']} if getattr(self,'features',None) or self.profile.get('offload_tuning') is True else {}
    if _performance:extra.update(ignore_eos=True,timings_per_token=True)
    if _transport=='direct':
     if not _performance:raise LabError('direct transport is performance-only')
     from serve.server import openai_collect
     packets=[];usage=timings=None
     # Direct SSE baseline retains the identical admission and RequestGuard.
     # Only response collection moves to this boundary; no unguarded shortcut.
     for packet in self.client.chat(messages,self.model_id,max_tokens=n,stream=True,cancel=cancel,temperature=0,chat_template_kwargs={'enable_thinking':False},**extra):
      usage=packet.get('usage') or usage;timings=packet.get('timings') or timings
      if packet.get('choices'):packets.append(packet)
     if not packets:raise LabError('native stream empty')
     packets[-1]=dict(packets[-1],usage=usage,timings=timings)
     response=openai_collect(packets)
    else:response=list(self.client.chat(messages,self.model_id,max_tokens=n,stream=False,cancel=cancel,temperature=0,chat_template_kwargs={'enable_thinking':False},**extra))[0]
   finally:timer.cancel();timer.join()
   if not _performance:require_completed_task(response)
   elif response.get('usage',{}).get('completion_tokens')!=n:raise LabError('PERFORMANCE_TOKEN_BUDGET_MISMATCH; no retry')
   metrics=self.client.graph.service if self.client.graph and self.client.graph.service else None
   from serve.hydra_graph import snapshot
   return dict(response=response,end_to_end_ms=(time.perf_counter()-start)*1000,identity_verification_ms=self.identity_verification_ms,graph=snapshot(metrics) if metrics else None,hybrid_retrieval=hybrid,guards_remaining=len(self.client.guards),actual_model=self.profile['model'],startup_ms=self.startup_ms,feature_options=options,effective_cpu_affinity=next((v.get('cpu_affinity') for v in reversed(self.calls) if v['event']=='backend_start'),None),runtime_command=next((v['command'] for v in reversed(self.calls) if v['event']=='backend_start'),None),lab=True)
  finally:self.graph_options=saved
 def performance(self,body):
  from serve.hydra_performance_v15 import execute
  return execute(self,body)
 def score(self,body):
  self.stop_backend();import psutil
  if psutil.virtual_memory().available<12*1024**3:raise RuntimeError('RAM below12GiB')
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'hydra-engine'))
  from serve.hydra_lab_modules import load
  scoring=load('decision_scoring');score_alternatives=scoring.score_alternatives;NativeCPUBackend=scoring.NativeCPUBackend
  request=dict(backend='llama.cpp-cpu-capi',model='Qwen3-0.6B-Q8_0',document=body.get('document'),question=body.get('question'),alternatives=body.get('alternatives'),normalize='sum',mode='continuation_logprobs',template='raw-continuation-v1',deadline=time.monotonic()+40,repeat=1)
  from serve.hydra_scoring_runtime import backend as scoring_backend
  backend=scoring_backend(self,scoring);start=time.perf_counter();out=score_alternatives(request,backend);out['lab']=True;out['duration_ms']=(time.perf_counter()-start)*1000;out['owned_child']=backend.last;return out
 def semantic_bridge(self,body):
  from serve.hydra_system_one_bridge import execute_bridge
  return execute_bridge(self,body)
 def prefix_score(self,body):
  from serve.hydra_prefix_scoring import execute_prefix
  return execute_prefix(self,body)
 def unavailable(self,body):
  if body!={}:raise LabError('empty control request required')
  self.stop_backend();self.closed=True;return dict(provider_available=False,lab=True)
 def close(self):
  self.benchmarks.shutdown()
  if getattr(self,'graphify_index',None) is not None:self.graphify_index.clear()
  self.stop_backend();(self.data/'ownership.json').write_text(json.dumps(self.calls,indent=2),encoding='utf-8')

def handler(lab,server_key):
 class Handler(BaseHTTPRequestHandler):
  def reply(self,status,data,kind='application/json'):
   raw=json.dumps(data,ensure_ascii=False).encode() if kind=='application/json' and not isinstance(data,bytes) else data
   self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Content-Length',str(len(raw)))
   if kind=='text/html':self.send_header('Set-Cookie','hydra_lab_session='+lab_session(server_key)+'; HttpOnly; SameSite=Strict; Path=/')
   self.end_headers();self.wfile.write(raw)
  def do_GET(self):
   from urllib.parse import urlsplit,unquote
   path=unquote(urlsplit(self.path).path)
   if path in ('/','/lab','/lab/benchmarks'):
    if path!='/':
     self.send_response(302);self.send_header('Location','/#prestazioni');self.end_headers();return
    from serve.hydra_lab_integration import render_lab_html
    return self.reply(200,render_lab_html(Path(__file__).with_name('web').joinpath('index.html').read_bytes()),'text/html')
   if path.startswith('/web/') or path.startswith('/lab/web/'):
    from mimetypes import guess_type
    name=path.split('/web/',1)[1];root=Path(__file__).with_name('web').resolve();target=(root/name).resolve()
    if not target.is_relative_to(root) or not target.is_file():return self.reply(404,{'error':'asset unavailable'})
    return self.reply(200,target.read_bytes(),guess_type(target.name)[0] or 'application/octet-stream')
   if path=='/benchmarks':
    from serve.hydra_lab_integration import existing_reports
    from serve.diagnostics import benchmark_reports
    legacy=benchmark_reports(Path(__file__).resolve().parents[1])['reports'];present={r.get('hydra_run_id') for r in legacy}
    return self.reply(200,{'reports':legacy+[r for r in existing_reports(lab.benchmarks) if r['hydra_run_id'] not in present],'persistent':True,'best_groups':[]})
   if self.path.startswith('/lab/benchmarks/api/'):
    if not lab_authenticated(self.headers,server_key,'http://127.0.0.1:'+str(getattr(getattr(self,'server',None),'server_address',('',0))[1])):return self.reply(403,{'error':'laboratory token required'})
    try:
     suffix=self.path.removeprefix('/lab/benchmarks/api/')
     if suffix.startswith('features/'):
      from serve.hydra_feature_control import features_api
      return self.reply(200,features_api(lab.features,suffix.split('/',1)[1]))
     if suffix=='readiness':
      from serve.hydra_lab_readiness import readiness
      return self.reply(200,readiness(lab))
     if suffix=='admission':
      from serve.hydra_execution_v10 import admission_status
      return self.reply(200,admission_status())
     if suffix=='runs':return self.reply(200,lab.benchmarks.store.list())
     if suffix=='catalog':return self.reply(200,lab.benchmarks.catalog())
     if suffix in ('export.json','export.csv'):
      raw,kind=lab.benchmarks.store.export(suffix.split('.')[-1]);return self.reply(200,raw,kind)
     if suffix.startswith('run/'):
      key=suffix.split('/')[1]
      if '/artifact/' in suffix:
       from serve.hydra_lab_benchmarks import read_artifact
       return self.reply(200,read_artifact(lab.benchmarks.store.get(key),suffix.split('/artifact/',1)[1]),__import__('mimetypes').guess_type(suffix.split('/artifact/',1)[1])[0] or 'application/octet-stream')
      if suffix.endswith('/log'):return self.reply(200,lab.benchmarks.log(key).encode(),'text/plain')
      if suffix.endswith('/samples.csv'):
       from serve.hydra_lab_benchmarks import export_samples
       return self.reply(200,export_samples(lab.benchmarks.store.get(key)),'text/csv')
      return self.reply(200,lab.benchmarks.store.get(key))
     return self.reply(404,{'error':'benchmark path unknown'})
    except (ValueError,OSError) as e:return self.reply(404,{'error':str(e)})
   if path=='/metrics':
    from serve.hydra_lab_live import monitor_metrics
    from serve.benchmark_monitor import snapshot
    result=monitor_metrics(lab.benchmarks.store.list());result['benchmark']=snapshot();return self.reply(200,result)
   if self.path=='/lab/status':return self.reply(200,lab.status())
   return self.reply(404,{'error':'lab path only'})
  def do_POST(self):
   if not lab_authenticated(self.headers,server_key,'http://127.0.0.1:'+str(getattr(getattr(self,'server',None),'server_address',('',0))[1])):return self.reply(403,{'error':'laboratory token required'})
   start=time.perf_counter();body=None
   try:
    size=int(self.headers.get('Content-Length','0'))
    if not 0<size<=32768:raise LabError('request bytes limit')
    body=json.loads(self.rfile.read(size));paths={'/lab/ingest':lab.ingest,'/lab/retrieve':lab.retrieve,'/lab/chat':lab.chat,'/lab/score':lab.score,'/lab/provider-off':lab.unavailable,'/lab/benchmarks/assess':lab.benchmarks.assess,'/lab/benchmarks/run':lab.benchmarks.execute,'/lab/benchmarks/submit':lab.benchmarks.submit,'/lab/benchmarks/cancel':lambda body:lab.benchmarks.cancel(body['run_id'])}
    if self.path.startswith('/lab/benchmarks/features/'):
     if self.path.endswith('/probe'):
      from serve.hydra_feature_control import probe
      return self.reply(200,probe(lab.benchmarks,body))
     from serve.hydra_feature_control import features_api
     return self.reply(200,features_api(lab.features,self.path.rsplit('/',1)[1],body))
    if self.path=='/lab/benchmarks/functional':
     from serve.hydra_lab_functional import execute,response
     status,value=response(execute(lab.benchmarks,body));return self.reply(status,value)
    if self.path=='/lab/fastpath/completion':
     from serve.hydra_fastpath import application_completion
     return self.reply(200,application_completion(lab.benchmarks,body))
    if self.path=='/lab/shutdown':
     self.reply(200,{'stopping':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
    if self.path not in paths:return self.reply(404,{'error':'unknown lab route'})
    functional=self.path in ('/lab/chat','/lab/score','/lab/retrieve','/lab/provider-off','/lab/ingest')
    if functional:
     from serve.hydra_lab_functional import execute
     row=execute(lab.benchmarks,{'path':self.path,'request':body})
     result=dict(row.get('original_result') or {},benchmark_run_id=row['run_id'],run_status=row['status'])
     if row.get('error'):result['error']=row['error']
     return self.reply(row.get('http_status') or (200 if row['status']=='PASS' else 409 if row['status']=='BLOCKED_BUSY' else 503),result)

    try:result=paths[self.path](body)
    finally:
     if functional:lab.benchmarks.lock.release()
    if self.path in ('/lab/chat','/lab/score','/lab/retrieve'):result['benchmark_run_id']=lab.benchmarks.record_application_run(self.path,body,result)
    self.reply(200,result)
   except (ValueError,TypeError,KeyError) as e:
    if self.path in ('/lab/chat','/lab/score','/lab/retrieve'):lab.benchmarks.record_application_run(self.path,body,None,str(e))
    self.reply(400,{'error':str(e),'lab':True})
   except Exception as e:
    if self.path in ('/lab/chat','/lab/score','/lab/retrieve'):lab.benchmarks.record_application_run(self.path,body,None,type(e).__name__+': '+str(e))
    self.reply(503,{'error':type(e).__name__+': '+str(e),'lab':True})
   finally:
    logged=({'configuration_payload_sha256':hashlib.sha256(json.dumps(body,ensure_ascii=False).encode()).hexdigest()} if self.path.startswith('/lab/benchmarks/features/') else body)
    with (lab.data/'requests.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(dict(path=self.path,request=logged,elapsed_ms=(time.perf_counter()-start)*1000),ensure_ascii=False)+'\n')
 return Handler

def main():
 if os.environ.get('HYDRA_LAB_MODE')!='1':raise SystemExit('Explicit HYDRA_LAB_MODE=1 required')
 ap=argparse.ArgumentParser();ap.add_argument('--profile',required=True);a=ap.parse_args();p=json.loads(Path(a.profile).read_text(encoding='utf-8'));lab=Lab(p);server=ThreadingHTTPServer(('127.0.0.1',p['port']),handler(lab,p['key']));print(json.dumps(dict(ready=True,port=p['port'],pid=os.getpid(),lab=True)),flush=True)
 try:server.serve_forever()
 finally:lab.close();server.server_close()
if __name__=='__main__':main()

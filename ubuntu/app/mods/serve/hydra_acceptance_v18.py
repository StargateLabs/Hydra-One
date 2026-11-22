"""Finite v18 application campaign. Historical recovery/quarantine stays unchanged.

The immutable plan admits exact requests/arguments. GPU slots are persisted before
HTTP generation, including failed requests; severe faults permanently halt ticket.
Only the existing exclusive coordinator may invoke native launch/request hooks.
"""
import hashlib,json,os,re,time
from pathlib import Path
MODEL='local/Qwen3-0.6B-Q8_0'
PROFILES=('v8-v18-cpu-qwen','v8-v18-gpu-qwen')

def digest(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def write_state(path,value):
 path=Path(path);temp=path.with_suffix('.pending')
 with temp.open('w',encoding='utf8') as f:
  json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())
 os.replace(temp,path)

def consume(path,run_id,index,warmup):
 path=Path(path);marker=path.parent/(run_id+'-request-'+str(index)+'.json')
 if marker.exists():raise FileExistsError('REQUEST_ALREADY_STARTED')
 state=json.loads(path.read_text(encoding='utf8'))
 if state['state']!='ARMED':raise ValueError('CAMPAIGN_HALTED_OR_CLOSED')
 if not warmup and state['measured_used']>=min(80,state['max_measured']):raise ValueError('GPU_BUDGET_EXHAUSTED')
 key='warmup_used' if warmup else 'measured_used';state[key]+=1
 # Persist budget first: failure between writes can only consume too many slots.
 write_state(path,state)
 with marker.open('x',encoding='utf8') as f:json.dump(dict(run_id=run_id,index=index,warmup=warmup,started_at=time.time(),budget_after=state[key]),f);f.flush();os.fsync(f.fileno())

def quality(case,text,truncated=False):
 normalized=text.strip();checks={}
 if case in ('Q1','Q2'):checks['exact_text']=normalized==('8' if case=='Q1' else '4')
 elif case=='Q3':checks['one_italian_word']=normalized.casefold() in ('sferica','sfera','rotonda','tonda')
 elif case=='Q4':
  checks['facts']=bool(re.search(r'roma',normalized,re.I)) and bool(re.search(r'parigi',normalized,re.I))
  checks['format']=re.fullmatch(r'Italia: Roma; Francia: Parigi',normalized,re.I) is not None
  checks['length']=len(normalized)<=40
 elif case=='repository':checks['exact_filename']=normalized=='loaded-modules.json'
 else:return dict(status='NOT_ASSESSED',pass_=None,**{'pass':None})
 checks['not_truncated']=not truncated
 return dict(status='QUALITY_PASS' if all(checks.values()) else 'QUALITY_FAIL',checks=checks,**{'pass':all(checks.values())})

def template_request(prompt):
 return dict(messages=[dict(role='user',content=prompt)],add_generation_prompt=True,chat_template_kwargs=dict(enable_thinking=False))

def sampling_payload():
 return dict(samplers=['temperature'],temperature=0,return_tokens=True)

def is_truncated(response):
 return bool(response.get('truncated') or response.get('stopped_limit') or response.get('stop_type')=='limit')

def validate(body,plan):
 spec=plan.get('runs',{}).get(body.get('prompt_id'))
 if not spec or any(body.get(k)!=spec.get(k) or type(body.get(k)) is not type(spec.get(k)) for k in ('profile','model_id','prompt','samples','max_tokens')):raise ValueError('V18_FROZEN_WORKLOAD_MISMATCH')
 return spec

def load():
 if os.environ.get('HYDRA_LAB_MODE')!='1' or not os.environ.get('HYDRA_V18_CAMPAIGN'):raise ValueError('V18_EXPLICIT_CAMPAIGN_REQUIRED')
 path=Path(os.environ['HYDRA_V18_CAMPAIGN']).resolve();ticket=json.loads(path.read_text(encoding='utf8'))
 if ticket['state']!='ARMED' or time.time()>ticket['expires_at']:raise ValueError('V18_CAMPAIGN_HALTED_CLOSED_OR_EXPIRED')
 if digest(ticket['plan'])!=ticket['plan_sha256']:raise ValueError('V18_PLAN_CHANGED')
 for p,h in ticket['protected_markers'].items():
  if digest(p)!=h:raise ValueError('V18_PROTECTED_MARKER_CHANGED')
 return path,ticket,json.loads(Path(ticket['plan']).read_text(encoding='utf8'))

def available():
 try:
  _,ticket,_=load();return ticket['measured_used']<min(80,ticket['max_measured'])
 except (OSError,ValueError,KeyError,TypeError):return False

def required_controls(body):
 _,_,plan=load();item=validate(body,plan)
 if not item['layers']:return []
 flags=item['flags'];mode=flags[flags.index('-fa')+1]
 return [2]+([7] if mode in ('on','auto') else [])

def bind_comparison(row):
 from serve.hydra_lab_benchmarks import comparison_key
 if row.get('effective_prompt'):
  row['template_hash']=hashlib.sha256(('model-apply-template-v18:'+row['effective_prompt']).encode()).hexdigest()
 key=comparison_key(row)
 if row.get('parameters',{}).get('samplers')!=['temperature']:
  key='INCOMPLETE:v18-unsupported-sampler:'+key
 row['comparison_key']=key

def verified_evidence():
 """Persisted generation proof only; never an execution grant or quality claim."""
 import sqlite3
 result={b:dict(run_ids=[],request_count=0) for b in ('CPU','Vulkan')}
 db=Path(__file__).resolve().parents[1]/'data/hydra-benchmark-registry/benchmarks.sqlite'
 if not db.is_file():return result
 with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as c:
  rows=c.execute("SELECT payload FROM runs WHERE json_extract(payload,'$.profile') IN (?,?) AND json_extract(payload,'$.status')='PASS'",PROFILES).fetchall()
 for payload, in rows:
  row=json.loads(payload);backend=row.get('backend');samples=row.get('samples',[])
  if backend not in result or not row.get('cleanup') or row.get('parameters',{}).get('samplers')!=['temperature']:continue
  if not row.get('process_identity',{}).get('loaded_DLL_map') or not samples:continue
  if not all(s.get('output') and s.get('tokens',0)>0 and len(s.get('response',{}).get('tokens',[]))==s['tokens'] for s in samples):continue
  result[backend]['run_ids'].append(row['run_id']);result[backend]['request_count']+=len(samples)
 return result

def selected(body,cfg):
 path,ticket,plan=load();item=validate(body,plan)
 if cfg!=plan['runtime_spec']:raise ValueError('V18_RUNTIME_SPEC_CHANGED')
 from serve.hydra_fastpath import spec
 result=spec('v8-qwen-full' if item['layers'] else 'v8-qwen-cpu',{'qwen':cfg},True)
 result.update(campaign_v18=True,context=1024,layers=item['layers'],backend='Vulkan' if item['layers'] else 'CPU',device='Vulkan0' if item['layers'] else 'none',flags=item['flags'],cache=item['cache'],deadline_s=item.get('deadline_s',240),app_paths=False,no_warmup=not item['warmup'],template='raw-native-bos-v18',selection_reason='Explicit finite v18 acceptance; not performance promotion',campaign_item=item)
 return result

def launch_item(request,plan):
 item=plan.get('runs',{}).get(request.get('workload'))
 if not item or request.get('profile')!=item['profile'] or request.get('model')!=item['model_id']:raise ValueError('V18_COMPACT_IDENTITY_MISMATCH')
 return item

def allow_spawn(request,argv):
 if request.get('profile') not in PROFILES:return False
 path,ticket,plan=load();item=launch_item(request,plan);cfg=plan['runtime_spec'];binary=Path(cfg['runtime'])/'llama-server.exe'
 if Path(argv[0]).resolve()!=binary.resolve():raise ValueError('V18_BINARY_MISMATCH')
 for n,h in cfg['files'].items():
  if digest(Path(cfg['runtime'])/n)!=h:raise ValueError('V18_RUNTIME_HASH_CHANGED')
 if argv[1:]==['--list-devices']:return True
 if digest(cfg['model'])!=cfg['model_hash']:raise ValueError('V18_MODEL_HASH_CHANGED')
 expected={'-m':cfg['model'],'-ngl':str(item['layers']),'--device':'Vulkan0' if item['layers'] else 'none','-c':'1024','-t':'2','-tb':'2','--parallel':'1','--host':'127.0.0.1'}
 for i in range(0,len(item['flags']),2):expected[item['flags'][i]]=item['flags'][i+1]
 for flag,value in expected.items():
  if argv.count(flag)!=1 or argv[argv.index(flag)+1]!=value:raise ValueError('V18_NATIVE_ARGUMENT_MISMATCH: '+flag)
 allowed=set(expected)|{'--port','--no-warmup','--verbosity','--log-timestamps'}
 for arg in argv[1:]:
  if str(arg).startswith('-') and arg not in allowed:raise ValueError('V18_UNPLANNED_FLAG')
 marker=path.parent/(request['workload']+'.launched.json')
 with marker.open('x',encoding='utf8') as f:json.dump(dict(run_id=request['run_id'],argv=argv,started_at=time.time()),f)
 return True

def before_request(body,run_id,index):
 path,ticket,plan=load();item=validate(body,plan)
 if item['layers']:consume(path,run_id,index,index==0)

class RequestGate:
 """One private permit per counted request; extra HTTP forwards fail closed.

 Counting stays before the measured HTTP round trip. The Session still verifies
 exact run ID/payload and serializes forwarding; this gate prevents replay in
 the gaps between requests, without adding another native request or retry.
 """
 def __init__(self,body,key,item,forward):
  import threading
  self.body=dict(body);self.key=key;self.forward=forward;self.next=0 if item['warmup'] else 1
  self.last=body['samples'];self.permit=False;self.lock=threading.Lock()
 def authorize(self,index):
  with self.lock:
   if type(index) is not int or index!=self.next or index>self.last:raise ValueError('V18_REQUEST_ORDER')
   if self.permit:raise ValueError('V18_REQUEST_PERMIT_PENDING')
   self.next+=1
   before_request(self.body,self.key,index)
   self.permit=True
 def __call__(self,payload):
  if not self.lock.acquire(False):raise ValueError('V18_REQUEST_PERMIT_BUSY')
  try:
   if not self.permit:raise ValueError('V18_REQUEST_PERMIT_REQUIRED')
   self.permit=False
   return self.forward(payload)
  finally:self.lock.release()

def finish(body,row):
 path=Path(os.environ['HYDRA_V18_CAMPAIGN']);ticket=json.loads(path.read_text(encoding='utf8'));plan=json.loads(Path(ticket['plan']).read_text(encoding='utf8'));item=validate(body,plan)
 for sample in row['samples']:
  response=sample.get('response',{});sample['quality']=quality(item.get('quality'),sample.get('output',''),is_truncated(response))
 if item.get('quality'):row['quality_gate']='QUALITY_PASS' if row['samples'] and all(s['quality']['pass'] for s in row['samples']) else 'QUALITY_FAIL'
 if item['layers'] and (not row.get('cleanup') or row.get('native_fault',{}).get('stop_gpu_sequence') or row['status'] in ('FAILED_DEVICE_LOST','RESOURCE_BLOCKED')):
  ticket.update(state='HALTED',halt_run=row['run_id'],halt_reason=row.get('error'));write_state(path,ticket)


def public_status():
 """Sanitized read-only campaign status. This summary never grants execution."""
 try:
  source=os.environ.get('HYDRA_V18_CAMPAIGN')
  path=Path(source) if source else Path(__file__).resolve().parents[1]/'data/hydra-v18-campaign-summary.json'
  data=json.loads(path.read_text(encoding='utf8'));used=data['measured_used'];warmup=data['warmup_used']
  if type(used) is not int or not 0<=used<=80 or type(warmup) is not int or warmup<0:raise ValueError('invalid public counter')
  return dict(state=data['state'],measured_used=used,warmup_used=warmup,measured_limit=80,remaining=80-used,available=available(),scope='Explicit finite v18 plan only; no automatic rearm; history is not permission')
 except (OSError,ValueError,KeyError,TypeError):return dict(state='NOT_ACTIVE',available=False,measured_limit=80)

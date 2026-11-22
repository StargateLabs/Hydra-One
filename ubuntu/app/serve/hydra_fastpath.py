"""Opt-in HYDRA Fast Path; measured profiles only, no operational defaults."""
import json,threading,statistics,time
from pathlib import Path
QWEN='local/Qwen3-0.6B-Q8_0'
BONSAI='prism-ml/Ternary-Bonsai-2-27B-gguf'

def check_cancel(cancel):
 if cancel.is_set():raise InterruptedError('controlled cancellation')
def can_publish(complete,stopped,released,persisted):return bool(complete and stopped and released and persisted)
def check_identity(profile,model_hash,runtime_hash):
 if not profile.get('promoted') or profile.get('model_hash')!=model_hash or profile.get('runtime_hash')!=runtime_hash:raise ValueError('Fast Path identity/capability mismatch; select explicit CPU or prior profile')
def cpu_alternative(model):
 if model==QWEN:return 'v8-qwen-cpu'
 if model==BONSAI:return 'prism-v5-cpu-2'
 raise ValueError('no attested explicit CPU alternative')
def spec(name,cfg,enabled):
 if not enabled:raise ValueError('HYDRA_LAB_MODE=1 and explicit v8 configuration required')
 table={'v8-qwen-cpu':('qwen',0,[],False),'v8-qwen-gpu4':('qwen',4,[],False),'v8-qwen-full':('qwen',29,[],False),'v8-qwen-cache':('qwen',29,[],True),'v8-qwen-faoff':('qwen',29,['-fa','off'],False),'v8-qwen-nommap':('qwen',29,['--no-mmap'],False),'v8-qwen-rocm':('rocm',29,[],False),'v8-bonsai-nocheckpoint':('bonsai',65,['--ctx-checkpoints','0'],False),'v8-bonsai-control':('bonsai',65,[],False),'v8-bonsai-faoff':('bonsai',65,['-fa','off'],False),'v8-bonsai-ub128':('bonsai',65,['-ub','128'],False)}
 if name not in table:raise ValueError('unknown bounded v8 profile')
 key,layers,flags,cache=table[name]
 if key not in cfg:raise ValueError('attested local runtime missing; no automatic backend fallback')
 return dict(runtime=cfg[key],layers=layers,flags=flags,cache=cache,backend='ROCm' if key=='rocm' else 'Vulkan' if layers else 'CPU',device='ROCm0' if key=='rocm' else 'Vulkan0' if layers else 'none',context=4096 if key=='bonsai' else 1024,quantization='PTQ1_0' if key=='bonsai' else 'Q8_0',expected_model=BONSAI if key=='bonsai' else QWEN,minimum_free_vram_mib=17408 if key=='bonsai' else 8192,rss_limit_gib=20 if key=='bonsai' else 4,deadline_s=1200,template='raw-native-v8')
def performance_gate(base,candidate):
 result={'GO':False,'workloads':{},'minimum_improvement_percent':15,'max_other_regression_percent':5,'token_ids_verified':False};good=True;gain=False
 if set(base)!=set(candidate) or not base:return result
 for k in base:
  a,b=base[k],candidate[k];valid=len(a)>=15 and len(b)>=15
  identical=valid and len({s['output'].encode('utf8') for s in a+b})==1 and len({s['tokens'] for s in a+b})==1
  delta=(1-statistics.median(s['e2e_ms'] for s in b)/statistics.median(s['e2e_ms'] for s in a))*100 if valid else None
  good &= bool(identical and delta>=-5);gain |= bool(valid and delta>=15)
  result['workloads'][k]={'samples':[len(a),len(b)],'improvement_percent':delta,'quality_gate':'TEXT_IDENTICAL' if identical else 'QUALITY_GATE_FAILED'}
 result['GO']=bool(good and gain);return result
class Session:
 def __init__(self,key,forward,expected=None):self.key=key;self.forward=forward;self.expected=expected;self.lock=threading.Lock();self.active=True
 def complete(self,body):
  if not self.active or set(body)!={'run_id','payload'} or body['run_id']!=self.key:raise ValueError('no owned active Fast Path session')
  if self.expected is not None and body['payload']!=self.expected:raise ValueError('payload outside the frozen model/context/output budget')
  if not self.lock.acquire(False):raise ValueError('single inference reservation busy')
  try:return self.forward(body['payload'])
  finally:self.lock.release()
def application_completion(workspace,body):
 session=getattr(workspace,'fastpath_session',None)
 if session is None:raise ValueError('no active admitted Fast Path session')
 return session.complete(body)
def resolve_profile(workspace,body):
 name=body['profile'];cfg=workspace.lab.profile.get('fastpath_v8',{})
 if name in ('v8-v18-cpu-qwen','v8-v18-gpu-qwen','v8-v19-cpu-qwen','v8-v19-gpu-qwen'):
  from serve.hydra_acceptance_campaign import selected
  return selected(body,cfg['qwen'])
 if name=='v8-recovery-qwen':
  from serve.hydra_gpu_recovery_v16 import selected
  return selected(body,cfg['qwen'])
 if name=='hydra-fastpath-v1':
  file=workspace.lab.profile.get('fastpath_manifest')
  if not file:raise ValueError('no measured Fast Path manifest selected')
  data=json.loads(Path(file).read_text(encoding='utf8'));p=data['models'].get(body['model_id'])
  if not p:raise ValueError('model not promoted; previous profiles remain explicit')
  name=p['configuration'];selected=spec(name,cfg,True);check_identity(p,selected['runtime']['model_hash'],selected['runtime']['files']['llama-server.exe'])
  if p.get('runtime_files')!=selected['runtime']['files']:raise ValueError('runtime DLL manifest differs from measured Fast Path')
  if body['max_tokens'] not in p.get('allowed_output_limits',[]):raise ValueError('output budget outside measured Fast Path scope')
  gate=workspace.store.get(p['gate_record_id'])
  if gate.get('status')!='PASS' or not gate.get('cleanup') or not gate.get('original_result',{}).get('GO') or gate.get('model_hash')!=p['model_hash'] or gate.get('runtime_hash')!=p['runtime_hash']:raise ValueError('persisted performance gate not verified')
  if p.get('allowed_prompt_hashes'):
   from serve.hydra_prism_campaign import sha_text
   if sha_text(body['prompt']) not in p['allowed_prompt_hashes']:raise ValueError('workload outside measured Fast Path scope')
 result=spec(name,cfg,__import__('os').environ.get('HYDRA_LAB_MODE')=='1')
 guard_safety(result,Path(__file__).resolve().parents[1]/'data/hydra-v8-safety-stop.json')
 if body['profile']=='hydra-fastpath-v1':
  result['selection_reason']=p['reason'];result['manifest_sha256']=__import__('hashlib').sha256(Path(file).read_bytes()).hexdigest();result['gate_record_id']=p['gate_record_id']
 return result
def execute(workspace,body,key=None,cancel=None):
 from serve.hydra_v7_experiments import execute as native_execute
 selected=resolve_profile(workspace,body)
 if not selected.get('recovery') and not selected.get('campaign_v18') and (body['model_id']!=selected['expected_model'] or body['samples'] not in (3,5,7,15) or body['max_tokens'] not in (16,64,96,128)):raise ValueError('bounded v8 model/samples/output mismatch')
 selected['app_paths']=not selected.get('recovery') and not selected.get('campaign_v18') and body['prompt_id'].endswith('-paths')
 return native_execute(workspace,body,key,cancel,_experiment=selected)


def may_advance(row,worker_active,native_processes):
 """A terminal row alone never authorizes the next native test."""
 return bool(row.get('status')=='PASS' and row.get('cleanup') and not worker_active and not native_processes and 'foreign native runtime' not in str(row.get('error','')))


def guard_safety(selected,marker):
 if selected['layers']>0 and Path(marker).is_file():raise ValueError('v8 GPU experiments suspended after native ErrorDeviceLost; no automatic retry; CPU remains explicit')

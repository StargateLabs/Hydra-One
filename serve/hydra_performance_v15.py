"""Frozen CPU performance protocol, reachable only through admitted lab requests."""
import hashlib,json,os,re,time
from pathlib import Path
PROTOCOL=Path(__file__).resolve().parents[1]/'hydra-engine/cpu_fastpath_v15/protocol-v15.1.json'
# Reconstructed protocol: old performance certificates cannot authorize this identity.
EXPECTED='8d4ef5d0f24d60b4b1a61bc07bc8f82f7be5930d4363987f58e2b220699d2654'
PROMOTION=PROTOCOL.parent/'promotion.json'
def verify_certified_assets(value):
 from serve.hydra_lab_app import sha
 try:
  if sha(value['model_path'])!=value['model_sha256']:raise ValueError('FASTPATH_MODEL_IDENTITY_CHANGED')
  runtime=Path(value['runtime_path']);files=value['runtime_manifest']['files']
  if not files:raise ValueError('FASTPATH_RUNTIME_MANIFEST_EMPTY')
  for name,item in files.items():
   if Path(name).name!=name or sha(runtime/name)!=item['sha256']:raise ValueError('FASTPATH_RUNTIME_IDENTITY_CHANGED: '+name)
 except OSError as exc:raise ValueError('FASTPATH_ASSET_UNAVAILABLE: '+str(exc)) from exc
def promoted_preset(control):
 """The central registry is the policy owner; this file is measured evidence."""
 from serve.hydra_feature_control import FeatureError,feature_number
 try:
  value=json.loads(PROMOTION.read_text());raw=(PROMOTION.parent/'candidate-profile-frozen.json').read_bytes();frozen=json.loads(raw)
 except (OSError,ValueError) as exc:raise FeatureError('FASTPATH_NOT_PROMOTED: measured manifest unavailable') from exc
 if value.get('promoted') is not True or value.get('state')!='PROMOTED':raise FeatureError('FASTPATH_NOT_PROMOTED: performance gate did not pass')
 expected=dict(runtime_reuse=True,cache_prompt=True,mmap=True,model_io='standard',checkpoint=False,http_pool=False,threads=2,affinity_cpus=2,context=2048,max_tokens=128,seed=42)
 fingerprint=hashlib.sha256(raw).hexdigest()
 if value.get('frozen_candidate_sha256')!=fingerprint or value.get('options')!=expected or value.get('protocol_sha256')!=EXPECTED or any(value.get(k)!=v for k,v in frozen.items() if k!='state'):raise FeatureError('FASTPATH_CERTIFICATION_MISMATCH')
 with control.db() as db:result=db.execute('SELECT payload FROM runs WHERE id=?',(value['gate_record_id'],)).fetchone()
 gate=json.loads(result[0]) if result else {};proof=gate.get('original_result',{})
 if gate.get('status')!='PASS' or not gate.get('cleanup') or gate.get('model_hash')!=value['model_sha256'] or gate.get('runtime_hash')!=value['runtime_hash'] or proof.get('frozen_candidate_sha256')!=fingerprint or proof.get('profile_gate')!=value.get('profile_gate') or proof.get('profile_gate',{}).get('GO') is not True:raise FeatureError('FASTPATH_GATE_NOT_VERIFIED')
 verify_certified_assets(value)
 base=control.preset('hydra-local-complete-v1');changes=base['changes'];ids={feature_number(k):k for k in control.defs() if feature_number(k)}
 changes.update({ids[3]:{'desired':True},ids[6]:{'desired':True},ids[28]:{'desired':True},ids[29]:{'desired':False,'parameters':{'loader_mode':0}},ids[9]:{'desired':True,'parameters':{'threads':2,'affinity_cpus':2}},ids[11]:{'desired':True,'parameters':{'context':2048,'max_tokens':128,'seed':42}}})
 plan=control.preview(changes,include_dependencies=True,include_dependents=True)
 plan.update(preset_id='hydra-cpu-fastpath-v2',certification={'gate_record_id':value['gate_record_id'],'scope':value['profile_gate'],'selection_reason':value.get('selection_reason'),'rollback':'hydra-local-complete-v1'},starts_inference=False)
 return plan
def require_complete(output):
 if not isinstance(output,dict) or output.get('status')!='complete':raise RuntimeError('PERFORMANCE_INCOMPLETE; preserve native output and error, no retry')
def validate(body):
 if not isinstance(body,dict) or set(body)!={'workload','transport','repetitions'}:raise ValueError('bounded frozen performance request required')
 if body['workload'] not in ('short','medium','prefix-pair','sequence','scoring') or body['transport'] not in ('runner','direct') or type(body['repetitions']) is not int or not 1<=body['repetitions']<=15:raise ValueError('unsupported performance workload/transport/count')
 raw=PROTOCOL.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=EXPECTED:raise ValueError('frozen protocol identity mismatch')
 return json.loads(raw)
def execute(lab,body):
 protocol=validate(body)
 if os.environ.get('HYDRA_LAB_MODE')!='1' or lab.profile['model_sha256']!=protocol['model_sha256']:raise ValueError('canonical CPU laboratory required')
 from serve.hydra_lab_app import lab_gpu_layers
 from serve.hydra_feature_control import runtime_options
 if lab_gpu_layers(lab.profile):raise ValueError('GPU_QUARANTINED')
 options=runtime_options(lab.features)
 if body['workload']=='scoring':
  if body['transport']!='runner' or body['repetitions']!=1:raise ValueError('scoring uses one admitted native helper per record')
  lab._performance_checkpoint=True
  try:
   started=time.perf_counter();out=lab.score(protocol['scoring']);elapsed=(time.perf_counter()-started)*1000
   return dict(status=out['status'],performance_contract='NATIVE_SCORING_PARITY',protocol_sha256=EXPECTED,samples=[dict(workload='scoring',output=json.dumps(out['alternatives'],sort_keys=True),tokens=0,e2e_ms=elapsed)],sequence_e2e_ms=elapsed,scoring=out)
  finally:del lab._performance_checkpoint
 for name in ('threads','affinity_cpus','context','seed'):
  if options[name]!=protocol['parameters'][name]:raise ValueError('frozen parameter mismatch: '+name)
 names=['prefix-a','prefix-b'] if body['workload']=='prefix-pair' else ['short','medium','prefix-a','prefix-b'] if body['workload']=='sequence' else [body['workload']]
 samples=[];start=time.perf_counter();reuse=lab.features.setting(3)['desired']
 for repeat in range(body['repetitions']):
  for name in names:
   request={k:v for k,v in protocol['workloads'][name].items() if k!='prompt_sha256'}
   was_reused=lab.child is not None;begun=time.perf_counter();out=lab.chat(request,_performance=True,_transport=body['transport']);request_ms=(time.perf_counter()-begun)*1000
   response=out['response'];text=response['choices'][0]['message']['content'];timings=response.get('timings') or {}
   item=dict(workload=name,repeat=repeat,output=text,tokens=response['usage']['completion_tokens'],e2e_ms=request_ms,request_ms=request_ms,identity_verification_ms=out['identity_verification_ms'],inference_wrapper_ms=out['end_to_end_ms'],startup_ms=out['startup_ms'],native_timings=timings,cache_tokens_reused=timings.get('cache_n',response.get('usage',{}).get('prompt_tokens_details',{}).get('cached_tokens')),response=response,guards_remaining=out['guards_remaining'],feature_options=out['feature_options'])
   samples.append(item)
   item.update(runtime_was_reused=was_reused,startup_incurred_ms=0 if was_reused else out['startup_ms'],identity_verification_incurred_ms=0 if was_reused else out['identity_verification_ms'],request_guard='existing HydraClient.chat; identical mandatory resource/context/cancellation guard in both transports')
   item['effective_cpu_affinity']=out['effective_cpu_affinity'];item['runtime_command']=out['runtime_command']
   import psutil
   item['process_memory_bytes']=psutil.Process(lab.child.pid).memory_info()._asdict()
   item['memory_metric']='Windows RSS=working set; private/commit and peak working set are separate fields; not weight residency attribution'
   if not reuse:lab.stop_backend()
 lab.stop_backend()
 elapsed=(time.perf_counter()-start)*1000
 logs=[]
 for call in lab.calls:
  if call.get('event')=='backend_start' and Path(call['log_path']).parent==lab.data:
   text=Path(call['log_path']).read_text(errors='replace');logs.append({'log_path':call['log_path'],'native_load_time_ms':[float(x) for x in re.findall(r'load time\s*=\s*([\d.]+) ms',text)],'cache_lines':[x for x in text.splitlines() if any(k in x for k in ('n_past','cache_n','tokens cached','tokens to eval'))]})
 return dict(status='complete',performance_contract='FIXED_BUDGET_ONLY',protocol_sha256=EXPECTED,samples=samples,sequence_e2e_ms=elapsed,runtime_reuse=reuse,transport=body['transport'],native_logs=logs)

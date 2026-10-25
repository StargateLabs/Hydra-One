"""Host identity and bounded runtime proposals, with explicit evidence scope."""
import hashlib,json,platform
import psutil
from pathlib import Path
import statistics
def host_profile(snapshot=None):
 snapshot=snapshot or {};static=snapshot.get('static') or {};now=snapshot.get('now') or {}
 identity={'cpu':static.get('cpu_name') or platform.processor(),'physical_cores':psutil.cpu_count(logical=False),'logical_threads':psutil.cpu_count(),'ram_total_bytes':getattr(psutil.virtual_memory(),'total',None),'gpu':static.get('gpu_name'),'gpu_total_bytes':now.get('gpu_mem_total'),'platform':platform.system(),'architecture':platform.machine()}
 return {'identity':identity,'fingerprint':hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest(),'ram_available_bytes':psutil.virtual_memory().available,'gpu_available_bytes':max(0,now['gpu_mem_total']-now['gpu_mem_used']) if isinstance(now.get('gpu_mem_total'),(int,float)) and isinstance(now.get('gpu_mem_used'),(int,float)) else None,'scope':'Current host topology and free resources; no throughput guarantee'}
def thread_proposal(snapshot=None,current=None):
 profile=host_profile(snapshot);identity=profile['identity'];physical=identity['physical_cores'] or identity['logical_threads'] or 1;logical=identity['logical_threads'] or physical
 # Preserve a valid explicit operating choice. Hybrid core topology is not
 # enough evidence to assert that all cores improve throughput.
 selected=current if type(current) is int and 1<=current<=logical else min(physical,16)
 return selected,min(logical,max(selected,physical)),profile

def measured_proposal(root,model_path,gpu,host,context):
 """Choose only recorded same-host/model/device profiles with equal work.

 Old reports lacking host identity remain observations, never recommendations.
 """
 candidates=[]
 for path in sorted((Path(root)/'data/benchmark-checks').glob('*.json'))[-100:]:
  try:
   if path.is_symlink() or path.stat().st_size>4*1024**2:continue
   report=json.loads(path.read_text(encoding='utf-8'));protocol=report.get('protocol',{});configuration=protocol.get('configuration') or {}
   if report.get('status')!='complete' or report.get('verification_fixture') or report.get('host',{}).get('fingerprint')!=host['fingerprint'] or str(Path(report.get('model_file','')).resolve())!=str(Path(model_path).resolve()) or configuration.get('gpu_requested') is not gpu or configuration.get('context')!=context:continue
   if protocol.get('runs',0)<3 or protocol.get('warmup',0)<1 or not protocol.get('model_sha256') or not protocol.get('prompt_sha256'):continue
   for arm in report.get('runs',[]):
    rows=[row for row in arm.get('rows',[]) if row.get('warmup') is False]
    if len(rows)!=protocol['runs'] or any(row.get('error') or row.get('output_tokens')!=protocol.get('tokens') for row in rows):continue
    speeds=[row.get('decode_tok_s') for row in rows]
    if any(type(value) not in (int,float) or not 0<value<100000 for value in speeds):continue
    key=json.dumps({name:protocol.get(name) for name in ('model_sha256','prompt_sha256','tokens','runs','warmup','stream','cache_prompt','generation_parameters')},sort_keys=True)+str(report.get('backend'))
    candidates.append({'source':path.name,'runtime':configuration.get('runtime') or {},'median':statistics.median(speeds),'protocol_key':key,'started_at':report.get('started_at',0)})
  except (OSError,ValueError,TypeError,KeyError):continue
 if not candidates:return None
 # Compare only profiles from the most recently recorded compatible protocol.
 latest=max(candidates,key=lambda row:row['started_at']);group=[row for row in candidates if row['protocol_key']==latest['protocol_key']]
 if len(group)<2:return None
 best=max(group,key=lambda row:row['median']);return {**best,'scope':'Best recorded median among compatible local profiles, not a universal optimum or causal ABBA proof','compared_profiles':len(group)}

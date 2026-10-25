"""Select the admitted scorer helper without replacing the historical runtime."""
import hashlib,json
from pathlib import Path

def attested_helper(manifest,error_code):
 manifest=Path(manifest).resolve(strict=True);record=json.loads(manifest.read_text(encoding='utf8'));helper=Path(record['executable']).resolve(strict=True)
 if not helper.is_relative_to(manifest.parent) or not helper.is_file():raise ValueError(error_code+'_IDENTITY_CHANGED')
 with helper.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
 if actual!=record['sha256']:raise ValueError(error_code+'_IDENTITY_CHANGED')
 return helper
def backend(lab,scoring):
 helper=lab.profile['helper'];enabled=False;limit=16*1024**2;tier='ram'
 features=getattr(lab,'features',None)
 if features is not None:
  enabled=features.setting(13)['desired'];budget=features.setting(14)
  if enabled and features.setting(13)['parameters'].get('checkpoint_tier',0)==1:tier='disk'
  if budget['desired']:limit=budget['parameters'].get('max_checkpoint_mib',16)*1024**2
  if enabled or budget['desired']:
   manifest=Path(__file__).resolve().parents[1]/'hydra-engine/implementation_closure_v13/native-cache-manifest.json'
   if tier=='disk':manifest=Path(__file__).resolve().parents[1]/'hydra-engine/runtime_integration_v14/native-tier-manifest.json'
   if not manifest.is_file():raise ValueError('CPU_CHECKPOINT_HELPER_MANIFEST_MISSING')
   helper=attested_helper(manifest,'CPU_CHECKPOINT_HELPER')
 if getattr(lab,'_performance_checkpoint',False):
  manifest=Path(__file__).resolve().parents[1]/'hydra-engine/cpu_fastpath_v15/native-metrics-manifest.json'
  helper=attested_helper(manifest,'CPU_PERFORMANCE_HELPER')
 runtime=lab.profile['runtime'];runtime_manifest=lab.profile['runtime_manifest']
 if not Path(helper).is_file() and not enabled and not getattr(lab,'_performance_checkpoint',False):
  # Recovered helper has a different ABI: bind it only to its own attested CPU runtime.
  receipt=Path(__file__).resolve().parents[1]/'hydra-engine/engine_completion_v22/native-score-recovery-manifest.json'
  helper=attested_helper(receipt,'RECOVERED_CPU_SCORER')
  loader=receipt.parent/'qwen-loader-manifest.json';record=json.loads(loader.read_text(encoding='utf8'))
  runtime=(loader.parent/record['runtime_relative']).resolve()
  if not runtime.is_relative_to(loader.parent.resolve()):raise ValueError('RECOVERED_SCORER_RUNTIME_OUTSIDE_ROOT')
  runtime_manifest={'files':record['files']}
 return scoring.NativeCPUBackend(helper,runtime,lab.profile['model'],runtime_manifest,lab.data,model_sha256=lab.profile['model_sha256'],prefix_cache=enabled,checkpoint_limit_bytes=limit,**({'checkpoint_tier':tier} if tier=='disk' else {}))

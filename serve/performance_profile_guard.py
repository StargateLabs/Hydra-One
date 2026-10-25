"""Detect operating-profile reductions without claiming an unmeasured optimum."""
import json
from pathlib import Path
FIELDS={'--pool-workers':('pool_workers','Worker CPU'),'--resident-budget-gib':('arena_mib','Cache RAM'),'--vram-reserve-mib':('vram_free_mib','Riserva VRAM')}
def arguments(config):
 args=config.get('args',[]);values={}
 for flag in FIELDS:
  try:values[flag]=float(args[args.index(flag)+1])
  except (ValueError,IndexError,TypeError):pass
 return values
def inspect_profile(root,config,engine,hardware,loaded):
 result={'state':'no_reference','warnings':[],'scope':'Operating profile comparison; not a benchmark-certified host optimum'}
 try:
  root=Path(root).resolve();selection=json.loads((root/'data/strata-runtime-selection.json').read_text(encoding='utf-8'));active=selection.get('active') or selection.get('previous')
  if not active:return result
  path=Path(active['previous_config']).resolve()
  if not path.is_relative_to(root/'output/updates/strata-configs'):return result
  import hashlib
  if hashlib.sha256(path.read_bytes()).hexdigest()!=active['previous_sha256']:return result
  previous=json.loads(path.read_text(encoding='utf-8-sig'))
  if previous.get('model_name')!=config.get('model_name') or previous.get('tokenizer')!=config.get('tokenizer'):return result
  before=arguments(previous);current=arguments(config);result['state']='consistent';result['reference']='Saved operating profile for the same local model; hardware applicability must be verified'
  for flag,(_,label) in FIELDS.items():
   old=before.get(flag);now=current.get(flag)
   if old is None or now is None:continue
   reduced=now<old if flag!='--vram-reserve-mib' else now>old
   if reduced:result['warnings'].append({'parameter':flag,'label':label,'current':now,'previous':old,'kind':'profile_reduction','message':label+' diverso dal profilo operativo precedente; richiede confronto prima di considerarlo più veloce'})
  if loaded and engine.get('pool_workers') is not None and current.get('--pool-workers') is not None and engine['pool_workers']!=current['--pool-workers']:result['warnings'].append({'kind':'reload_required','message':'Il pool del motore attivo non corrisponde al profilo salvato; ricaricamento necessario','current':engine['pool_workers'],'configured':current['--pool-workers']})
  if result['warnings']:result['state']='review_required'
  return result
 except (OSError,ValueError,KeyError,TypeError):return result

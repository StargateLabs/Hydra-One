"""Opt-in fixed-token throughput policy; never an execution grant or chat default."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'hydra-engine/acceptance_v19'
def validate_gate(result):
 if set(result)!= {'short','long'}:raise ValueError('V19_WORKLOAD_SET_MISMATCH')
 for name,value in result.items():
  if not value.get('protocol_complete') or not value.get('comparable') or value.get('verdict')!='THROUGHPUT_PASS':raise ValueError('V19_UNVERIFIED_THROUGHPUT')
  if value['ci95_gain_percent'][0]<15:raise ValueError('V19_GAIN_OR_COMPATIBLE_REGRESSION_GATE')
  if len(value['blocks'])<1 or any(v[b]['n']<7 for v in value['blocks'] for b in ('cpu','gpu')):raise ValueError('V19_INSUFFICIENT_SAMPLES')
 return True
def promoted_preset(control):
 from serve.hydra_feature_control import FeatureError
 try:
  promotion=json.loads((ROOT/'promotion.json').read_text(encoding='utf8'))
  for relative,expected in promotion['evidence_sha256'].items():
   if hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()!=expected:raise ValueError('V19_EVIDENCE_CHANGED')
  result=json.loads((ROOT/'performance-analysis.json').read_text(encoding='utf8'));validate_gate(result)
  # Reading proof never rearms its closed ticket. The resolver still enforces
  # an explicit finite grant, exact frozen request, runtime and request budget.
  base=control.preset('hydra-gpu-prepared-v1');changes=base['changes']
  changes.update({'runtime.vulkan':dict(desired=True),'V7-A-002':dict(desired=True),'V7-B-007':dict(desired=False)})
  preview=control.preview(changes,include_dependencies=True,include_dependents=True)
  preview.update(preset_id='hydra-gpu-throughput-v19',promotion=promotion,scope='Fixed16/64-token workloads only; long output diverges; not universal lossless or normal-stop quality',execution_requires='New explicit valid finite grant; proof and preset do not authorize generation',starts_inference=False)
  return preview
 except (OSError,ValueError,KeyError,TypeError) as exc:raise FeatureError('V19_PROMOTION_NOT_VERIFIED: '+str(exc)) from exc

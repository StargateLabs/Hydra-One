"""Require current structural CPU vision training proof; no image-quality claim."""
import hashlib,json
from pathlib import Path
from serve.python_inference_update import environment_fingerprint

def fingerprint(root):
 digest=hashlib.sha256()
 for name in ('tools/train_vlm_lora.py','tools/train_local_lora.py','serve/training_options.py','serve/transformers_vision.py'):
  digest.update(name.encode());digest.update((Path(root)/name).read_bytes())
 return digest.hexdigest()

def checked(root):
 root=Path(root).resolve();python=root/'data/trl-advanced-runtime/Scripts/python.exe'
 proof=json.loads((root/'data/trl-advanced-runtime/vision-validation.json').read_text(encoding='utf-8'))
 report=Path(proof['report']).resolve()
 if not report.is_relative_to(root/'output/verification') or hashlib.sha256(report.read_bytes()).hexdigest()!=proof['report_sha256']:raise ValueError('Vision training proof integrity mismatch')
 workflow=json.loads(report.read_text(encoding='utf-8'))
 if not python.is_file() or proof['source_sha256']!=fingerprint(root) or proof['environment_sha256']!=environment_fingerprint(python) or workflow.get('source_sha256')!=proof['source_sha256']:raise ValueError('Vision training runner or dependencies changed; validate again')
 if workflow.get('status')!='complete' or workflow.get('method')!='vlm' or not all(workflow.get(key) is True for key in ('assistant_only_labels','parameter_update_detected','export_logits_verified','export_greedy_tokens_equal')):raise ValueError('Vision training/update/export proof incomplete')
 return python

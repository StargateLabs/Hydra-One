"""Require current method-specific proof before advanced TRL is usable."""
import hashlib,json
from pathlib import Path
from serve.python_inference_update import environment_fingerprint
def source_fingerprint(root):
 digest=hashlib.sha256()
 for name in ('tools/train_trl_advanced.py','tools/train_local_lora.py','serve/training_options.py'):
  digest.update(name.encode());digest.update((Path(root)/name).read_bytes())
 return digest.hexdigest()
def checked(root,method):
 root=Path(root).resolve();folder=root/'data/trl-advanced-runtime';python=folder/'Scripts/python.exe'
 proof=json.loads((folder/'validation.json').read_text(encoding='utf-8'));metadata=json.loads((folder/'provenance.json').read_text(encoding='utf-8'))
 source=Path(metadata['source_site']);source_python=source.parent.parent/'Scripts/python.exe'
 if method not in ('dpo','grpo','kto','reward') or not python.is_file() or proof['source_sha256']!=source_fingerprint(root) or proof['environment_sha256']!=environment_fingerprint(python) or proof['shared_environment_sha256']!=environment_fingerprint(source_python):raise ValueError('Advanced training proof or dependencies changed; validate the method again')
 record=proof['methods'][method];report=Path(record['report']).resolve()
 if not report.is_relative_to(root/'output/verification') or hashlib.sha256(report.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Advanced method proof integrity failed')
 workflow=json.loads(report.read_text(encoding='utf-8'))
 if workflow.get('source_sha256')!=proof['source_sha256']:raise ValueError('Training report was produced with different sources')
 if workflow.get('status')!='complete' or workflow.get('method')!=method or workflow.get('options',{}).get('device')!='cpu' or workflow.get('export_scores_equal' if method=='reward' else 'export_greedy_tokens_equal') is not True or workflow.get('parameter_update_detected') is not True:raise ValueError('Advanced method training/update/export proof incomplete')
 return python

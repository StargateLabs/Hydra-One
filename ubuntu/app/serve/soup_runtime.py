"""Selected isolated Soup package; original environment remains available."""
import hashlib,json
from pathlib import Path

def selected_package(root,verify=False):
 root=Path(root).resolve();registry=root/'data/soup-package-selection.json'
 if not registry.is_file():return None
 active=json.loads(registry.read_text(encoding='utf-8')).get('active')
 if not active:return None
 package=Path(active['package_root']).resolve()
 if not package.is_relative_to(root/'output/updates/soup-candidates') or not (package/'soup_cli').is_dir():raise ValueError('Invalid Soup candidate directory')
 validation=active.get('validation',{})
 bridge=root/'tools'/('train_soup_candidate_0760.py' if active.get('version')=='0.76.0' else 'train_soup_candidate.py')
 if validation.get('cpu_verified') is not True or validation.get('bridge_sha256')!=hashlib.sha256(bridge.read_bytes()).hexdigest():raise ValueError('Soup candidate needs current training/export validation')
 if verify:
  for row in active['files']:
   path=(package/row['path']).resolve()
   if not path.is_relative_to(package) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Selected Soup package changed')
 return active


def activate_package(root,version='0.75.2'):
 from serve.configuration import atomic_json
 from serve.customization_backup import snapshot
 import re
 if not re.fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('Invalid Soup version')
 root=Path(root).resolve();folder=root/'output/updates/soup-candidates'/version
 manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'));package=Path(manifest['package_root']).resolve();wheel=Path(manifest['wheel']).resolve()
 if not package.is_relative_to(folder) or not wheel.is_relative_to(folder) or hashlib.sha256(wheel.read_bytes()).hexdigest()!=manifest['sha256']:raise ValueError('Soup wheel changed')
 bridge_hash=hashlib.sha256((root/'tools'/('train_soup_candidate_0760.py' if version=='0.76.0' else 'train_soup_candidate.py')).read_bytes()).hexdigest()
 proofs={}
 for device in ('cpu','gpu'):
  proof=json.loads((root/f'output/verification/soup-{version.replace(".","")}-{device}-real.json').read_text(encoding='utf-8'));workflow=proof.get('workflow',{})
  if proof.get('passed') is not True or proof.get('exit_code')!=0 or workflow.get('status')!='complete' or workflow.get('bridge_sha256')!=bridge_hash or workflow.get('soup_version')!=version or workflow.get('export_logits_verified') is not True or workflow.get('export_greedy_tokens_equal') is not True:raise ValueError('Soup needs current CPU/GPU training and export checks')
  proofs[device]=proof
 if version!='0.75.2':
  proof=json.loads((root/f'output/verification/soup-{version.replace(".","")}-streaming-real.json').read_text(encoding='utf-8'));workflow=proof.get('workflow',{})
  streaming_hash=hashlib.sha256((root/'tools/train_soup_streaming_candidate_0760.py').read_bytes()).hexdigest()
  if proof.get('passed') is not True or workflow.get('soup_version')!=version or workflow.get('bridge_sha256')!=streaming_hash or workflow.get('streaming_active') is not True or workflow.get('export_logits_verified') is not True:raise ValueError('Soup needs current streaming and export validation')
 # Verify the installed source against the downloaded wheel, before selection.
 import zipfile
 files=[]
 with zipfile.ZipFile(wheel) as archive:
  for member in archive.infolist():
   if member.is_dir() or member.filename.endswith('/RECORD'):continue
   path=(package/member.filename).resolve()
   if not path.is_relative_to(package) or not path.is_file():raise ValueError('Soup package incomplete')
   digest=hashlib.sha256(path.read_bytes()).hexdigest()
   if digest!=hashlib.sha256(archive.read(member)).hexdigest():raise ValueError('Soup source differs from verified wheel')
   files.append({'path':member.filename,'sha256':digest})
 registry=root/'data/soup-package-selection.json'
 previous=json.loads(registry.read_text(encoding='utf-8')).get('active') if registry.is_file() else None
 if previous and previous.get('version')==version and previous.get('validation',{}).get('bridge_sha256')==bridge_hash:return selected_package(root,verify=True)
 backup=snapshot(root)
 active={'version':version,'package_root':str(package),'files':files,'validation':{'cpu_verified':True,'gpu_verified':True,'bridge_sha256':bridge_hash},'original_environment_preserved':True}
 atomic_json(registry,{'active':active,'previous':previous,'backup':backup})
 return active

def rollback_package(root):
 from serve.configuration import atomic_json
 root=Path(root);registry=root/'data/soup-package-selection.json';saved=json.loads(registry.read_text(encoding='utf-8'))
 active=selected_package(root,verify=True)
 if not active:raise ValueError('No selected Soup candidate')
 atomic_json(registry,{'active':saved.get('previous'),'previous':active,'backup':saved.get('backup')})
 return {'restored':True,'version':saved.get('previous',{}).get('version') if saved.get('previous') else 'original environment'}

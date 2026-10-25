"""Select isolated training environments only after runner-specific local proof.

Prepared dependency plans are reused; no vendor environment is modified. CPU,
GPU, TRL and native NF4 proofs are independent and never certify one another.
"""
import hashlib,json,math,os,subprocess,time,uuid
from pathlib import Path
from serve.configuration import atomic_json
from serve.python_inference_update import folder_checked,environment_fingerprint

RUNNERS={'trl_cpu':'train_local_lora.py','unsloth_qlora':'train_unsloth_qlora.py'}

def scope(runner,device):
 if runner not in RUNNERS or device not in ('cpu','cuda') or runner=='unsloth_qlora' and device!='cuda':raise ValueError('Unsupported candidate training runner/device')
 return runner+':'+device

def fingerprint(root,runner):
 scope(runner,'cuda' if runner=='unsloth_qlora' else 'cpu')
 digest=hashlib.sha256()
 for name in ('tools/'+RUNNERS[runner],'tools/train_local_lora.py','serve/training_options.py','serve/training_runtime_candidates.py','serve/safetensors_runtime.py','serve/transformers_integration.py'):
  path=Path(root)/name;digest.update(name.encode());digest.update(path.read_bytes() if path.is_file() else b'missing')
 return digest.hexdigest()

def _python(folder,manifest):
 python=Path(manifest['python']).resolve()
 if not python.is_relative_to(folder) or not python.is_file() or manifest.get('dependency_health',{}).get('state')!='healthy':raise ValueError('Candidate dependency health or interpreter is invalid')
 return python

def candidate(root,folder,runner='trl_cpu',device='cpu'):
 key=scope(runner,device);folder=folder_checked(root,folder)
 manifest=json.loads((folder/'environment-manifest.json').read_text(encoding='utf-8'));python=_python(folder,manifest)
 proof=manifest.get('training_validation',{}).get(key,{})
 if proof.get('passed') is not True or proof.get('runner')!=runner or proof.get('device')!=device or proof.get('runtime_sha256')!=fingerprint(root,runner) or proof.get('python_sha256')!=hashlib.sha256(python.read_bytes()).hexdigest():raise ValueError('Validate the isolated training runtime before selection')
 report=Path(proof.get('report','')).resolve()
 if not report.is_relative_to(folder) or not report.is_file() or hashlib.sha256(report.read_bytes()).hexdigest()!=proof.get('report_sha256'):raise ValueError('Training proof report changed; validate again')
 if proof.get('environment_sha256')!=environment_fingerprint(python):raise ValueError('Candidate dependencies changed; validate training again')
 return python,manifest

def selected_python(root,default,runner='trl_cpu',device='cpu'):
 key=scope(runner,device);path=Path(root)/'data/training-python-selection.json'
 registry=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
 row=registry.get('selections',{}).get(key,{}).get('active')
 return candidate(root,row['plan_directory'],runner,device)[0] if row else Path(default)

def activate(root,folder,default,runner='trl_cpu',device='cpu',rollback=False):
 key=scope(runner,device);path=Path(root)/'data/training-python-selection.json'
 registry=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {};selections=registry.setdefault('selections',{});old=selections.get(key,{})
 if rollback:
  active=old.get('previous')
  if active:candidate(root,active['plan_directory'],runner,device)
 else:
  python,_=candidate(root,folder,runner,device)
  active=dict(python=str(python),plan_directory=str(Path(folder).resolve()),runner=runner,device=device,scope='One-step untrained fixture training/export; no quality or sustained hardware claim')
 selections[key]=dict(active=active,previous=old.get('active'),changed_at=time.time());path.parent.mkdir(parents=True,exist_ok=True);atomic_json(path,registry)
 return selected_python(root,default,runner,device)

def status(root):
 path=Path(root)/'data/training-python-selection.json'
 result=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'selections':{}}
 rows=[]
 for folder in sorted((Path(root)/'output/updates/python-plans').glob('*'))[:64]:
  manifest=folder/'environment-manifest.json'
  try:
   if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size>1024**2:continue
   metadata=json.loads(manifest.read_text(encoding='utf-8'))
   if not isinstance(metadata,dict):continue
   packages=metadata.get('source_packages') or {}
   rows.append({'directory':str(folder.resolve()),'name':'Transformers '+str(packages.get('transformers',''))+' · TRL '+str(packages.get('trl','')),
                'dependency_health':metadata.get('dependency_health',{}).get('state'),'runner':metadata.get('runner'),
                'validated_scopes':list(metadata.get('training_validation',{})),'validation_required_before_selection':True})
  except (OSError,ValueError,TypeError):continue
 result['candidates']=rows
 from serve.studio_inventory import installed_studio
 app=installed_studio();result['desktop_app']={'installed':bool(app),'version':app.get('installed_version') if app else None}
 return result

def validate(root,folder,runner='trl_cpu',device='cpu',model=None):
 key=scope(runner,device);root=Path(root).resolve();folder=folder_checked(root,folder);path=folder/'environment-manifest.json'
 manifest=json.loads(path.read_text(encoding='utf-8'));manifest.setdefault('training_validation',{}).pop(key,None);atomic_json(path,manifest)
 python=_python(folder,manifest)
 fixture=Path(model).resolve(strict=True) if model else root/'output/verification/safetensors-cpu-fixture'
 if model and not fixture.is_relative_to(root) and not fixture.is_relative_to((root.parent/'Strata-data/models').resolve()):raise ValueError('Choose a model within the managed local model roots')
 if not model and not (fixture/'FIXTURE-NOT-A-TRAINED-MODEL.txt').is_file():raise ValueError('Local untrained validation fixture unavailable')
 from serve.safetensors_runtime import inspect_model
 info=inspect_model(fixture)
 if info['bytes']>(1024**3 if model else 32*1024**2):raise ValueError('Training validation model exceeds bounded local weights limit')
 # Resolve/import the complete stack together; pip check retains version constraints
 # from PEFT/TRL/Unsloth rather than hardcoding a guessed compatibility matrix.
 check=subprocess.run([str(python),'-m','pip','check'],capture_output=True,text=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 if check.returncode:raise ValueError('Candidate dependency resolution failed: '+check.stdout[-1000:]+check.stderr[-500:])
 probe="import json,importlib.metadata as m;import torch,transformers,peft,trl;from trl import SFTTrainer,SFTConfig;print(json.dumps({n:m.version(n) for n in ('torch','transformers','peft','trl','accelerate','datasets')}))"
 if runner=='unsloth_qlora':probe="import unsloth;"+probe
 env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
 if device=='cpu':env.update(CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
 imports=subprocess.run([str(python),'-c',probe],capture_output=True,text=True,timeout=45,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 if imports.returncode:raise ValueError('Candidate training stack import failed: '+imports.stderr[-1000:])
 versions=json.loads(imports.stdout.strip().splitlines()[-1])
 if runner=='unsloth_qlora':
  package=subprocess.run([str(python),'-c',"import importlib.metadata as m;print(m.version('unsloth'))"],capture_output=True,text=True,timeout=15)
  if package.returncode:raise ValueError('Unsloth candidate version unavailable')
  versions['unsloth']=package.stdout.strip()
 proofdir=folder/('training-proof-'+uuid.uuid4().hex);proofdir.mkdir();train=proofdir/'train.jsonl';validation=proofdir/'validation.jsonl'
 train.write_text(json.dumps({'text':'hello world hello world hello world'})+'\n',encoding='utf-8');validation.write_text(json.dumps({'text':'world hello world hello'})+'\n',encoding='utf-8')
 output=proofdir/'result';command=[str(python),'-u',str(root/'tools'/RUNNERS[runner]),'--model',str(fixture),'--train',str(train),'--validation',str(validation),'--output',str(output),'--steps','1','--length','32']
 if runner=='trl_cpu':command+=['--device',device]
 before_env=environment_fingerprint(python);before_source=fingerprint(root,runner);started=time.time()
 from serve.gpu_lease import GpuLease
 lease=GpuLease(root,'training-candidate-validation-'+device);lease.acquire()
 try:
  with (proofdir/'training.log').open('w',encoding='utf-8') as log:
   result=subprocess.run(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if result.returncode:raise ValueError('Candidate training failed; inspect '+str(proofdir/'training.log'))
 finally:lease.release()
 reportpath=output/'workflow.json';report=json.loads(reportpath.read_text(encoding='utf-8'))
 loss=report.get('training_loss',report.get('train_loss'));after=report.get('validation_loss_after')
 if report.get('status')!='complete' or report.get('options',{}).get('device')!=device or not all(type(value) in (int,float) and math.isfinite(value) for value in (loss,after)) or report.get('export_greedy_tokens_equal') is not True:raise ValueError('Candidate training/export report incomplete')
 if before_env!=environment_fingerprint(python) or before_source!=fingerprint(root,runner):raise ValueError('Candidate changed during validation')
 proof=dict(passed=True,runner=runner,device=device,scope='One-step explicit local model; no quality or prolonged hardware validation' if model else 'One-step untrained local fixture; no quality or prolonged hardware validation',validation_model=str(fixture),runtime_versions=versions,runtime_sha256=before_source,python_sha256=hashlib.sha256(python.read_bytes()).hexdigest(),environment_sha256=before_env,report=str(reportpath),report_sha256=hashlib.sha256(reportpath.read_bytes()).hexdigest(),started_at=started,validated_at=time.time())
 # Preserve unrelated inference and other device proofs even after a long worker.
 manifest=json.loads(path.read_text(encoding='utf-8'));manifest.setdefault('training_validation',{})[key]=proof;atomic_json(path,manifest)
 return manifest

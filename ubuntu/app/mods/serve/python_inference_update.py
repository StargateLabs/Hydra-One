"""Reversible isolated Python inference selection; CPU proof never certifies GPU."""
import hashlib,json,os,socket,subprocess,time,urllib.request
from pathlib import Path

def fingerprint(root):
 digest=hashlib.sha256()
 for name in ('safetensors_runtime.py','transformers_vision.py'):
  path=Path(root)/'serve'/name;digest.update(name.encode());digest.update(path.read_bytes() if path.is_file() else b'missing')
 return digest.hexdigest()

def environment_fingerprint(python):
 script="import importlib.metadata as m,json;print(json.dumps(sorted((d.metadata['Name'],d.version) for d in m.distributions() if d.metadata['Name'])))"
 result=subprocess.run([str(python),'-I','-c',script],capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 if result.returncode or len(result.stdout)>1024*1024:raise ValueError('Candidate package inventory failed')
 return hashlib.sha256(json.dumps(json.loads(result.stdout),sort_keys=True).encode()).hexdigest()

def folder_checked(root,folder):
 folder=Path(folder).resolve()
 if not folder.is_relative_to((Path(root)/'output/updates/python-plans').resolve()):raise ValueError('Invalid candidate directory')
 return folder

def candidate(root,folder):
 folder=folder_checked(root,folder)
 manifest=json.loads((folder/'environment-manifest.json').read_text(encoding='utf-8'))
 python=Path(manifest['python']).resolve()
 if not python.is_relative_to(folder) or not python.is_file():raise ValueError('Invalid candidate Python')
 proof=manifest.get('inference_validation') or {}
 if manifest.get('dependency_health',{}).get('state')!='healthy' or not proof.get('passed') or proof.get('runtime_sha256')!=fingerprint(root) or proof.get('python_sha256')!=hashlib.sha256(python.read_bytes()).hexdigest():raise ValueError('Validate the isolated inference runtime before selection')
 if proof.get('environment_sha256')!=environment_fingerprint(python):raise ValueError('Candidate dependencies changed; validate again')
 if manifest.get('vendor_copy'):
  from serve.vendor_python_validation import fingerprint as vendor_fingerprint
  if not proof.get('cpu_verified') or not proof.get('gpu_verified') or proof.get('vendor_validation_sha256')!=vendor_fingerprint(root):raise ValueError('Validate the preserved vendor runtime on CPU and GPU before selection')
 return python,manifest

def selected_python(root,default,gpu=False):
 registry=Path(root)/'data/inference-python-selection.json'
 if not registry.is_file():return Path(default)
 row=json.loads(registry.read_text(encoding='utf-8')).get('active')
 if not row:return Path(default)
 python,manifest=candidate(root,row['plan_directory'])
 if gpu and manifest.get('inference_validation',{}).get('gpu_verified') is not True:return Path(default)
 return python

def activate(root,folder,default,rollback=False):
 from serve.configuration import atomic_json
 registry=Path(root)/'data/inference-python-selection.json'
 previous=json.loads(registry.read_text(encoding='utf-8')) if registry.is_file() else {}
 if rollback:
  active=previous.get('previous')
  if active:candidate(root,active['plan_directory'])
 else:
  python,manifest=candidate(root,folder)
  active={'python':str(python),'plan_directory':str(Path(folder).resolve()),'scope':'Transformers CPU/GPU with preserved ROCm build' if manifest['inference_validation'].get('gpu_verified') else 'Transformers CPU; native Unsloth GPU not validated'}
 registry.parent.mkdir(parents=True,exist_ok=True)
 atomic_json(registry,{'active':active,'previous':previous.get('active'),'changed_at':time.time()})
 return selected_python(root,default)

def validate(root,folder,model=None):
 from serve.configuration import atomic_json
 folder=folder_checked(root,folder);path=folder/'environment-manifest.json';manifest=json.loads(path.read_text(encoding='utf-8'))
 manifest.pop('inference_validation',None);atomic_json(path,manifest)
 python=Path(manifest['python']).resolve()
 if not python.is_relative_to(folder) or not python.is_file() or manifest.get('dependency_health',{}).get('state')!='healthy':raise ValueError('Candidate dependency health is invalid')
 fixture=Path(model).resolve(strict=True) if model is not None else Path(root)/'output/verification/safetensors-cpu-fixture'
 if model is None and not (fixture/'FIXTURE-NOT-A-TRAINED-MODEL.txt').is_file():raise ValueError('Local CPU validation fixture is unavailable')
 if model is not None:
  from serve.safetensors_runtime import inspect_model
  if not fixture.is_relative_to((Path(root).resolve().parent/'Strata-data/models').resolve()) or inspect_model(fixture)['bytes']>1024**3:raise ValueError('Choose a managed local text model under 1 GiB')
 sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
 env={**os.environ,'CUDA_VISIBLE_DEVICES':'-1','HIP_VISIBLE_DEVICES':'-1','ROCR_VISIBLE_DEVICES':'-1'}
 child=None
 with (folder/'inference-validation.log').open('w',encoding='utf-8') as log:
  try:
   child=subprocess.Popen([str(python),str(Path(root)/'serve/safetensors_runtime.py'),'--model',str(fixture),'--context','1024','--threads','2','--device','cpu','--port',str(port)],cwd=root,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   url=f'http://127.0.0.1:{port}';deadline=time.monotonic()+90
   while True:
    if child.poll() is not None:raise ValueError('Candidate inference startup failed; inspect inference-validation.log')
    try:metadata=json.load(urllib.request.urlopen(url+'/v1/models',timeout=1))['data'][0];break
    except (OSError,ValueError):
     if time.monotonic()>deadline:raise ValueError('Candidate readiness timeout')
     time.sleep(.2)
   req=urllib.request.Request(url+'/v1/chat/completions',data=json.dumps({'model':'optional-model','messages':[{'role':'user','content':'hello'}],'max_tokens':8,'temperature':0}).encode(),headers={'Content-Type':'application/json'})
   result=json.load(urllib.request.urlopen(req,timeout=20))
   if result.get('usage',{}).get('completion_tokens',0)<1:raise ValueError('Candidate generated no tokens')
   manifest['inference_validation']={'passed':True,'scope':'Bounded local text model CPU inference; no GPU or quality claim' if model is not None else 'Untrained CPU fixture only; no GPU or quality claim','metadata':metadata,'usage':result['usage'],'runtime_sha256':fingerprint(root),'python_sha256':hashlib.sha256(python.read_bytes()).hexdigest(),'environment_sha256':environment_fingerprint(python),'validated_at':time.time()}
   atomic_json(path,manifest);return manifest
  finally:
   if child and child.poll() is None:
    child.terminate()
    try:child.wait(timeout=10)
    except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)

"""Real CPU and ROCm inference gates for the preserved vendor candidate."""
import hashlib,json,os,socket,subprocess,time
from pathlib import Path
from urllib.request import Request,urlopen

def fingerprint(root):
 digest=hashlib.sha256()
 for name in ('vendor_python_validation.py','vendor_python_update.py','python_inference_update.py'):
  digest.update(name.encode());digest.update((Path(root)/'serve'/name).read_bytes())
 return digest.hexdigest()

def validation_model(root):
 from serve.safetensors_runtime import inspect_model
 base=(Path(root).resolve().parent/'Strata-data/models').resolve();found=[]
 if base.is_dir():
  for index,config in enumerate(base.rglob('config.json')):
   if index>=256:break
   try:
    folder=config.parent.resolve()
    if not folder.is_relative_to(base):continue
    info=inspect_model(folder)
    if 0<info['bytes']<=1024**3 and info.get('input_modalities',['text'])==['text'] and not info.get('checkpoint_quantization',{}).get('prequantized'):found.append((info['bytes'],folder))
   except (OSError,ValueError,KeyError,TypeError):continue
 if not found:raise ValueError('A managed local text Safetensors model under 1 GiB is required for CPU/GPU verification')
 return min(found,key=lambda row:row[0])[1]

def validate(root,folder):
 from serve.python_inference_update import validate as cpu_validate,environment_fingerprint
 from serve.configuration import atomic_json
 from serve.gpu_lease import GpuLease
 root=Path(root).resolve();folder=Path(folder).resolve();path=folder/'environment-manifest.json'
 saved=json.loads(path.read_text(encoding='utf-8'))
 if not saved.get('vendor_copy'):raise ValueError('Expected a preserved vendor candidate')
 model=validation_model(root)
 with GpuLease(root,'transformers-vendor-validation'):
  manifest=cpu_validate(root,folder,model=model);cpu=manifest['inference_validation'];python=Path(manifest['python']);proofs={}
  env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_DATASETS_OFFLINE':'1','OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2'}
  for name in ('CUDA_VISIBLE_DEVICES','HIP_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES'):env.pop(name,None)
  for loader in ('transformers','unsloth'):
   sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();base=f'http://127.0.0.1:{port}';child=None
   with (folder/f'gpu-{loader}-validation.log').open('w',encoding='utf-8') as log:
    try:
     child=subprocess.Popen([str(python),'-X','utf8',str(root/'serve/safetensors_runtime.py'),'--model',str(model),'--context','1024','--threads','2','--device','cuda','--loader',loader,'--port',str(port)],cwd=folder,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
     deadline=time.monotonic()+90
     while True:
      if child.poll() is not None:raise ValueError('Candidate '+loader+' GPU startup failed: '+str(folder/f'gpu-{loader}-validation.log'))
      try:
       with urlopen(base+'/v1/models',timeout=1) as response:metadata=json.load(response)['data'][0]
       break
      except (OSError,ValueError):
       if time.monotonic()>deadline:raise ValueError('GPU candidate readiness timeout')
       time.sleep(.25)
     if metadata.get('device')!='cuda' or metadata.get('native_loader')!=loader:raise ValueError('Candidate GPU loader/device mismatch')
     request=Request(base+'/v1/chat/completions',data=json.dumps({'model':'optional-model','messages':[{'role':'user','content':'Say hello briefly.'}],'max_tokens':4,'temperature':0}).encode(),headers={'Content-Type':'application/json'})
     with urlopen(request,timeout=30) as response:answer=json.load(response)
     if answer.get('usage',{}).get('completion_tokens',0)<1 or not answer.get('choices',[{}])[0].get('message',{}).get('content'):raise ValueError('GPU candidate returned no answer')
     proofs[loader]={'passed':True,'metadata':metadata,'usage':answer['usage'],'model':str(model),'scope':'Four generated tokens on a managed local text model; no performance claim'}
    finally:
     if child and child.poll() is None:
      child.terminate()
      try:child.wait(timeout=10)
      except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
  if cpu['environment_sha256']!=environment_fingerprint(python):raise ValueError('Candidate dependencies changed during validation')
  manifest['inference_validation']={**cpu,'cpu_verified':True,'gpu_verified':True,'gpu_loaders':proofs,'vendor_validation_sha256':fingerprint(root),'scope':'CPU fixture plus real trained-model GPU inference on Transformers and native Unsloth'}
  atomic_json(path,manifest);return manifest

"""Isolated generative-visual runtime selection with reversible native import contracts."""
import hashlib,json,os,subprocess,time
from pathlib import Path
from serve.configuration import atomic_json
from serve.python_inference_update import folder_checked,environment_fingerprint

def fingerprint(root):
 return hashlib.sha256((Path(root)/'tools/generate_local_visual.py').read_bytes()).hexdigest()

def probe(python):
 script="import json,inspect,torch,diffusers;from diffusers import StableDiffusionPipeline,StableDiffusionXLPipeline,StableDiffusionImg2ImgPipeline,StableDiffusionXLImg2ImgPipeline,StableDiffusionInpaintPipeline,StableDiffusionXLInpaintPipeline,TextToVideoSDPipeline,VideoToVideoSDPipeline,StableVideoDiffusionPipeline,ControlNetModel,DDIMScheduler,EulerDiscreteScheduler,DPMSolverMultistepScheduler;classes=(StableDiffusionPipeline,StableDiffusionXLPipeline,StableDiffusionImg2ImgPipeline,StableDiffusionXLImg2ImgPipeline,StableDiffusionInpaintPipeline,StableDiffusionXLInpaintPipeline,TextToVideoSDPipeline,VideoToVideoSDPipeline,StableVideoDiffusionPipeline,ControlNetModel);assert all(callable(c.from_pretrained) for c in classes);assert all(callable(c.from_config) for c in (DDIMScheduler,EulerDiscreteScheduler,DPMSolverMultistepScheduler));inspect.signature(StableDiffusionPipeline.__call__).bind(None,prompt='text',width=512,height=512,num_inference_steps=20,guidance_scale=7.5);inspect.signature(VideoToVideoSDPipeline.__call__).bind(None,prompt='text',video=[],strength=.6,num_inference_steps=20,guidance_scale=7.5,clip_skip=1);inspect.signature(StableVideoDiffusionPipeline.__call__).bind(None,image=None,num_frames=8,num_inference_steps=10,decode_chunk_size=1,motion_bucket_id=127,noise_aug_strength=.02,min_guidance_scale=1.,max_guidance_scale=3.,fps=8);print(json.dumps({'torch':torch.__version__,'cuda':torch.cuda.is_available(),'hip':torch.version.hip,'cuda_build':torch.version.cuda,'devices':[torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())],'diffusers':diffusers.__version__,'image':True,'video':True,'image_to_video':True}))"
 result=subprocess.run([str(python),'-I','-c',script],capture_output=True,text=True,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 if result.returncode:raise ValueError('Visual runtime import contract failed: '+result.stderr[-1200:])
 return json.loads(result.stdout.splitlines()[-1])

def validate(root,folder,source):
 folder=folder_checked(root,folder);path=folder/'environment-manifest.json';manifest=json.loads(path.read_text(encoding='utf-8'));manifest.pop('visual_validation',None);atomic_json(path,manifest)
 python=Path(manifest['python']).resolve()
 if not python.is_relative_to(folder) or not python.is_file() or manifest.get('dependency_health',{}).get('state')!='healthy':raise ValueError('Invalid isolated visual candidate')
 baseline=probe(source);contract=probe(python)
 if any(baseline[key]!=contract[key] for key in ('torch','cuda','hip','cuda_build','devices')):raise ValueError('Visual vendor build or device availability changed; current runtime preserved')
 manifest['visual_validation']={'passed':True,'contract':contract,'runtime_sha256':fingerprint(root),'python_sha256':hashlib.sha256(python.read_bytes()).hexdigest(),'environment_sha256':environment_fingerprint(python),'validated_at':time.time(),'scope':'Native imports and entrypoints; no generation or quality certification'}
 atomic_json(path,manifest);return manifest

def candidate(root,folder,full=True):
 folder=folder_checked(root,folder);manifest=json.loads((folder/'environment-manifest.json').read_text(encoding='utf-8'));python=Path(manifest['python']).resolve();proof=manifest.get('visual_validation',{})
 if not python.is_relative_to(folder) or not python.is_file() or manifest.get('dependency_health',{}).get('state')!='healthy' or not proof.get('passed') or proof.get('runtime_sha256')!=fingerprint(root) or proof.get('python_sha256')!=hashlib.sha256(python.read_bytes()).hexdigest():raise ValueError('Validate the isolated visual runtime before selection')
 if full and proof.get('environment_sha256')!=environment_fingerprint(python):raise ValueError('Visual candidate packages changed')
 return python

def selected_python(root,default):
 registry=Path(root)/'data/visual-python-selection.json'
 if not registry.is_file():return Path(default)
 row=json.loads(registry.read_text(encoding='utf-8')).get('active')
 return candidate(root,row['plan_directory'],full=False) if row else Path(default)

def activate(root,folder=None,rollback=False):
 registry=Path(root)/'data/visual-python-selection.json';previous=json.loads(registry.read_text(encoding='utf-8')) if registry.is_file() else {}
 if rollback:
  if 'previous' not in previous:raise ValueError('No previous visual runtime selection')
  active=previous['previous']
  if active:candidate(root,active['plan_directory'])
 else:
  python=candidate(root,folder);active={'python':str(python),'plan_directory':str(Path(folder).resolve()),'scope':'Diffusers image/video native entrypoints; original device build preserved'}
 atomic_json(registry,{'active':active,'previous':previous.get('active'),'changed_at':time.time()})
 return active

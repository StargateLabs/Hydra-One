"""Isolated generative-audio runtime selection with reversible native import contracts."""
import hashlib,json,os,subprocess,time
from pathlib import Path
from serve.configuration import atomic_json
from serve.python_inference_update import folder_checked,environment_fingerprint

def fingerprint(root):
 return hashlib.sha256((Path(root)/'tools/generate_local_audio.py').read_bytes()).hexdigest()

def probe(python):
 script="import json,torch,soundfile,scipy;from transformers import AutoProcessor,MusicgenForConditionalGeneration,MusicgenMelodyForConditionalGeneration;from openvoice.api import ToneColorConverter;assert callable(AutoProcessor.from_pretrained) and callable(MusicgenForConditionalGeneration.generate) and callable(ToneColorConverter.convert) and callable(MusicgenMelodyForConditionalGeneration.generate);print(json.dumps({'torch':torch.__version__,'cuda':torch.cuda.is_available(),'musicgen':True,'openvoice':True}))"
 result=subprocess.run([str(python),'-I','-c',script],capture_output=True,text=True,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 if result.returncode:raise ValueError('Audio runtime import contract failed: '+result.stderr[-1200:])
 return json.loads(result.stdout.splitlines()[-1])

def validate(root,folder,source):
 folder=folder_checked(root,folder);path=folder/'environment-manifest.json';manifest=json.loads(path.read_text(encoding='utf-8'));manifest.pop('audio_validation',None);atomic_json(path,manifest)
 python=Path(manifest['python']).resolve()
 if not python.is_relative_to(folder) or not python.is_file() or manifest.get('dependency_health',{}).get('state')!='healthy':raise ValueError('Invalid isolated audio candidate')
 baseline=probe(source);contract=probe(python)
 if baseline['torch']!=contract['torch'] or baseline['cuda']!=contract['cuda']:raise ValueError('Audio vendor build or device availability changed; current runtime preserved')
 manifest['audio_validation']={'passed':True,'contract':contract,'runtime_sha256':fingerprint(root),'python_sha256':hashlib.sha256(python.read_bytes()).hexdigest(),'environment_sha256':environment_fingerprint(python),'validated_at':time.time(),'scope':'Native imports and entrypoints; no synthesis or quality certification'}
 atomic_json(path,manifest);return manifest

def candidate(root,folder,full=True):
 folder=folder_checked(root,folder);manifest=json.loads((folder/'environment-manifest.json').read_text(encoding='utf-8'));python=Path(manifest['python']).resolve();proof=manifest.get('audio_validation',{})
 if not python.is_relative_to(folder) or not python.is_file() or manifest.get('dependency_health',{}).get('state')!='healthy' or not proof.get('passed') or proof.get('runtime_sha256')!=fingerprint(root) or proof.get('python_sha256')!=hashlib.sha256(python.read_bytes()).hexdigest():raise ValueError('Validate the isolated audio runtime before selection')
 if full and proof.get('environment_sha256')!=environment_fingerprint(python):raise ValueError('Audio candidate packages changed')
 return python

def selected_python(root,default):
 registry=Path(root)/'data/audio-python-selection.json'
 if not registry.is_file():return Path(default)
 row=json.loads(registry.read_text(encoding='utf-8')).get('active')
 return candidate(root,row['plan_directory'],full=False) if row else Path(default)

def activate(root,folder=None,rollback=False):
 registry=Path(root)/'data/audio-python-selection.json';previous=json.loads(registry.read_text(encoding='utf-8')) if registry.is_file() else {}
 if rollback:
  if 'previous' not in previous:raise ValueError('No previous audio runtime selection')
  active=previous['previous']
  if active:candidate(root,active['plan_directory'])
 else:
  python=candidate(root,folder);active={'python':str(python),'plan_directory':str(Path(folder).resolve()),'scope':'MusicGen/OpenVoice native entrypoints; original device build preserved'}
 atomic_json(registry,{'active':active,'previous':previous.get('active'),'changed_at':time.time()})
 return active

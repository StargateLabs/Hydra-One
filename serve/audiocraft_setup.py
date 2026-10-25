"""Prepare a separate official AudioCraft environment, never replace vendor Torch."""
import hashlib,json,os,shutil,subprocess,sys,threading,time,uuid
from pathlib import Path
from serve.configuration import atomic_json
class AudioCraftSetup:
 def __init__(self,root):
  self.root=Path(root).resolve();self.lock=threading.RLock();self.job={'state':'idle'};self.child=None
  self.job_path=self.root/'data/audiocraft-setup-last.json'
  try:self.job=json.loads(self.job_path.read_text(encoding='utf-8'))
  except (OSError,ValueError):pass
  if self.job.get('state')=='preparing':self.job.update(state='interrupted',error='Previous preparation interrupted; candidate not selected')
 def status(self):
  with self.lock:
   try:python=str(selected_python(self.root) or '');error=None
   except (OSError,ValueError,KeyError,TypeError) as failure:python='';error=str(failure)
   return dict(self.job,busy=self.job['state']=='preparing',active_python=python,selection_error=error,scope='Separate AudioCraft environment; original Unsloth and MusicGen interpreters preserved')
 def _uv(self):
  for path in (self.root/'.venv/Scripts/uv.exe',Path(sys.executable).parent/'uv.exe',Path(os.environ.get('USERPROFILE',str(Path.home())))/'AppData/Local/hermes/bin/uv.exe'):
   if path.is_file():return path
  raise ValueError('Managed uv executable unavailable')
 def prepare(self,channel="stable"):
  if channel not in ("stable","extended"):raise ValueError("Choose stable or extended AudioCraft")
  with self.lock:
   if self.job['state']=='preparing':raise ValueError('AudioCraft preparation already running')
   if shutil.disk_usage(self.root).free<8*1024**3:raise ValueError('Keep at least 8 GiB free for the isolated candidate')
   folder=self.root/'output/updates/audiocraft-candidates'/uuid.uuid4().hex;folder.mkdir(parents=True)
   self.job={'state':'preparing','channel':channel,'folder':str(folder),'started_at':time.time()}
   atomic_json(self.job_path,self.job)
   threading.Thread(target=self._run,args=(folder,channel),daemon=True).start()
  return self.status()
 def prepare_conditioning(self,encoder="t5-large"):
  if encoder not in ("t5-base","t5-large","mert"):raise ValueError("Choose t5-base or t5-large")
  with self.lock:
   if self.job['state']=='preparing':raise ValueError('Preparation already running')
   if shutil.disk_usage(self.root).free<5*1024**3:raise ValueError('Keep 5 GiB free for conditioning')
   folder=self.root/'output/updates/audiocraft-candidates'/uuid.uuid4().hex;folder.mkdir(parents=True)
   self.job={'state':'preparing','task':'conditioning','folder':str(folder),'started_at':time.time()};atomic_json(self.job_path,self.job)
   threading.Thread(target=self._conditioning,args=(folder,encoder),daemon=True).start()
  return self.status()
 def _conditioning(self,folder,encoder):
  try:
   import sys
   self._command([sys.executable,'-I',str(self.root/'tools/prepare_audiocraft_conditioning.py'),str(folder),encoder],folder,dict(os.environ))
   with self.lock:self.job.update(state='ready',finished_at=time.time())
  except Exception as error:
   with self.lock:self.job.update(state='failed',error=str(error),finished_at=time.time())
  finally:
   with self.lock:self.child=None;atomic_json(self.job_path,self.job)
 def _command(self,args,folder,env):
  with (folder/'prepare.log').open('ab') as log:
   self.child=subprocess.Popen(args,cwd=self.root,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   from serve.winjob import contain
   contain(self.child)
   try:code=self.child.wait(timeout=1200)
   except subprocess.TimeoutExpired:self.child.terminate();self.child.wait(timeout=10);raise ValueError('AudioCraft preparation timed out')
   if code:raise ValueError('Preparation failed; see '+str(folder/'prepare.log'))
 def _run(self,folder,channel="stable"):
  try:
   uv=self._uv()
   env=dict(os.environ,UV_PYTHON_INSTALL_DIR=str(self.root/'data/audiocraft-python'),UV_CACHE_DIR=str(self.root/'output/updates/audiocraft-cache'),UV_DEFAULT_INDEX='https://pypi.org/simple',CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
   self._command([str(uv),'venv','--python','3.11','--managed-python',str(folder/'environment')],folder,env)
   python=folder/'environment/Scripts/python.exe'
   # Upstream's torch2.1 stack lives only in this dedicated candidate.
   override=folder/'compatibility-overrides.txt';override.write_text('av==12.0.0\n',encoding='utf-8')
   source='audiocraft==1.3.0' if channel=='stable' else 'git+https://github.com/facebookresearch/audiocraft.git@896ec7c47f5e5d1e5aa1e4b260c4405328bf009d'
   self._command([str(uv),'pip','install','--python',str(python),'--index-url','https://pypi.org/simple','--override',str(override),source,'numpy<2','transformers>=4.31,<4.42','huggingface-hub<1','psutil'],folder,env)
   self._validate_candidate(folder,channel,source,env,uv)
   with self.lock:self.job.update(state='ready',finished_at=time.time())
  except Exception as error:
   with self.lock:self.job.update(state='failed',error=str(error),finished_at=time.time())
  finally:
   with self.lock:
    self.child=None
    atomic_json(self.job_path,self.job)
 def _validate_candidate(self,folder,channel,source,env,uv):
   python=folder/'environment/Scripts/python.exe'
   if channel=='extended':self._command([str(uv),'pip','install','--python',str(python),'--index-url','https://pypi.org/simple','--no-deps','audioseal==0.2.0'],folder,env)
   health=subprocess.run([str(uv),'pip','check','--python',str(python)],capture_output=True,text=True,env=env,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   (folder/'dependency-check.txt').write_text(health.stdout+health.stderr,encoding='utf-8')
   issues=[line.strip() for line in (health.stdout+health.stderr).splitlines() if 'requires' in line.lower() or 'incompatible' in line.lower() or 'not installed' in line.lower()]
   if health.returncode and (len(issues)!=1 or 'av' not in issues[0] or '11.0.0' not in issues[0] or '12.0.0' not in issues[0]):raise ValueError('Unexpected dependency mismatch; candidate not selected')
   script="import inspect;from audiocraft.models import AudioGen;assert callable(AudioGen.get_pretrained);assert callable(AudioGen.generate_unconditional);assert callable(AudioGen.generate_continuation);inspect.signature(AudioGen.set_generation_params).bind(None,duration=5,two_step_cfg=False,extend_stride=2)"
   if channel=='extended':script+=';from audiocraft.models import JASCO,MultiBandDiffusion,MAGNeT,MusicGen;from audiocraft.models.watermark import AudioSeal;import audioseal;assert callable(JASCO.get_pretrained);assert callable(AudioSeal.get_pretrained);assert callable(MultiBandDiffusion.get_mbd_24khz);assert callable(MusicGen.set_style_conditioner_params)'
   self._command([str(python),'-I','-c',script],folder,env)
   atomic_json(folder/'manifest.json',{'python':str(python),'version':'1.3.0' if channel=='stable' else '896ec7c47f5e5d1e5aa1e4b260c4405328bf009d','channel':channel,'source':source,'compatibility_overrides':{'av':'12.0.0 instead of upstream11.0.0; official Windows wheel; import contract only'},'validated':True,'python_sha256':hashlib.sha256(python.read_bytes()).hexdigest(),'scope':'Dependency/import/signature contract only; no generation'})
   registry=self.root/'data/audiocraft-selection.json';old=json.loads(registry.read_text(encoding='utf-8')) if registry.is_file() else {}
   atomic_json(registry,{'active':str(folder),'previous':old.get('previous') if old.get('active')==str(folder) else old.get('active'),'changed_at':time.time()})
 def resume(self,folder):
  folder=Path(folder).resolve();base=(self.root/'output/updates/audiocraft-candidates').resolve()
  if not folder.is_relative_to(base) or folder.is_symlink() or not (folder/'environment/Scripts/python.exe').is_file():raise ValueError('Choose an existing managed AudioCraft candidate')
  with self.lock:
   if self.job['state']=='preparing':raise ValueError('Preparation already running')
   if self.job.get('folder')!=str(folder) or self.job.get('channel') not in ('stable','extended'):raise ValueError('Candidate has no recorded preparation channel')
   channel=self.job['channel'];self.job.update(state='preparing',error=None);atomic_json(self.job_path,self.job)
   threading.Thread(target=self._resume,args=(folder,channel),daemon=True).start()
  return self.status()
 def _resume(self,folder,channel):
  try:
   uv=self._uv()
   source='audiocraft==1.3.0' if channel=='stable' else 'git+https://github.com/facebookresearch/audiocraft.git@896ec7c47f5e5d1e5aa1e4b260c4405328bf009d'
   self._validate_candidate(folder,channel,source,dict(os.environ,CUDA_VISIBLE_DEVICES='-1'),uv)
   with self.lock:self.job.update(state='ready',finished_at=time.time())
  except Exception as error:
   with self.lock:self.job.update(state='failed',error=str(error),finished_at=time.time())
  finally:
   with self.lock:atomic_json(self.job_path,self.job)
 def rollback(self):
  with self.lock:
   if self.job['state']=='preparing':raise ValueError('Wait for preparation to finish')
   registry=self.root/'data/audiocraft-selection.json';row=json.loads(registry.read_text(encoding='utf-8'))
   old=row.get('previous')
   if old:checked(self.root,old)
   atomic_json(registry,{'active':old,'previous':row.get('active'),'changed_at':time.time()})
  return self.status()
def checked(root,folder):
 folder=Path(folder).resolve();base=(Path(root)/'output/updates/audiocraft-candidates').resolve()
 if not folder.is_relative_to(base) or folder.is_symlink():raise ValueError('Invalid AudioCraft candidate')
 manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'));python=Path(manifest['python']).resolve()
 if not manifest.get('validated') or not python.is_relative_to(folder) or not python.is_file() or manifest.get('python_sha256')!=hashlib.sha256(python.read_bytes()).hexdigest():raise ValueError('AudioCraft candidate not validated')
 return python
def selected_python(root):
 registry=Path(root)/'data/audiocraft-selection.json'
 if not registry.is_file():return None
 row=json.loads(registry.read_text(encoding='utf-8'))
 return checked(root,row['active']) if row.get('active') else None

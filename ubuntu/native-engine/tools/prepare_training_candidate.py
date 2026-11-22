"""Clone only a runner's installed dependency closure into an isolated venv.

Copies installed files read-only, then runs pip check. A failed dependency check
is a candidate to repair, never an active environment or a successful proof.
"""
import argparse,json,shutil,subprocess,uuid
from pathlib import Path

INVENTORY=r'''
import importlib.metadata as m,json,sysconfig
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
pending=json.loads(__import__('sys').argv[1]);found={};base=__import__('pathlib').Path(sysconfig.get_paths()['purelib']).resolve()
while pending:
 name=canonicalize_name(pending.pop())
 if name in found:continue
 dist=m.distribution(name);files=[]
 for item in dist.files or []:
  path=__import__('pathlib').Path(dist.locate_file(item)).resolve()
  if path.is_relative_to(base) and path.is_file():files.append(str(path.relative_to(base)))
 found[name]={'version':dist.version,'files':files}
 for text in dist.requires or []:
  requirement=Requirement(text)
  if requirement.marker is None or requirement.marker.evaluate({'extra':''}):pending.append(requirement.name)
print(json.dumps({'base':str(base),'packages':found}))
'''

INVENTORY_ALL=r'''
import importlib.metadata as m,json,sysconfig
from pathlib import Path
base=Path(sysconfig.get_paths()['purelib']).resolve()
found={}
for dist in m.distributions():
    name=dist.metadata.get('Name')
    if not name:continue
    key=name.lower().replace('_','-')
    files=[]
    for item in dist.files or []:
        path=Path(dist.locate_file(item)).resolve()
        if path.is_relative_to(base) and path.is_file():files.append(str(path.relative_to(base)))
    found[key]={'version':dist.version,'files':files}
print(json.dumps({'base':str(base),'packages':found}))
'''

def prepare(root,source_python,runner='trl_cpu',extra_roots=None):
 root=Path(root).resolve();source_python=Path(source_python).resolve(strict=True)
 if runner not in ('trl_cpu','unsloth_qlora','full'):raise ValueError('Unsupported training candidate runner')
 if runner!='full':
  roots=['torch','transformers','peft','trl','accelerate','datasets','psutil']
  if extra_roots:roots+=list(extra_roots)
  # ROCm device kernels are separate installed distributions, not Torch's
  # normal dependency metadata. Preserve exactly the installed device closure.
  devices=subprocess.run([str(source_python),'-I','-c',"import importlib.metadata as m,json;print(json.dumps([d.metadata['Name'] for d in m.distributions() if d.metadata.get('Name','').replace('_','-').startswith(('amd-torch-device-','rocm-sdk-device-'))]))"],capture_output=True,text=True,timeout=15)
  if devices.returncode:raise ValueError('Device inventory failed: '+devices.stderr[-500:])
  roots+=json.loads(devices.stdout)
  if runner=='unsloth_qlora':roots+=['unsloth','bitsandbytes']
 flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
 if runner=='full':result=subprocess.run([str(source_python),'-I','-c',INVENTORY_ALL],capture_output=True,text=True,timeout=30,creationflags=flags)
 else:result=subprocess.run([str(source_python),'-I','-c',INVENTORY,json.dumps(roots)],capture_output=True,text=True,timeout=30,creationflags=flags)
 if result.returncode:raise ValueError('Source dependency inventory failed: '+result.stderr[-1000:])
 inventory=json.loads(result.stdout);source=Path(inventory['base']).resolve()
 folder=root/'output/updates/python-plans'/('training-'+uuid.uuid4().hex);folder.mkdir(parents=True)
 try:
  environment=folder/'environment'
  if runner=='full':
   # An exact venv copy keeps every distribution and its metadata, including
   # packages whose name lookup is broken (the source `pip check` stays valid).
   source_env=Path(source_python).resolve().parents[1]
   shutil.copytree(source_env,environment,symlinks=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  else:
   result=subprocess.run([str(source_python),'-I','-m','venv',str(environment)],capture_output=True,text=True,timeout=60,creationflags=flags)
   if result.returncode:
    # uv-managed standalone Pythons may not ship the `venv` module.
    source_env=Path(source_python).resolve().parents[1]
    shutil.rmtree(environment,ignore_errors=True)
    shutil.copytree(source_env,environment,symlinks=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  python=environment/('Scripts/python.exe' if __import__('os').name=='nt' else 'bin/python')
  result=subprocess.run([str(python),'-I','-c',"import sysconfig;print(sysconfig.get_paths()['purelib'])"],capture_output=True,text=True,timeout=15,creationflags=flags)
  if result.returncode:raise ValueError('Candidate interpreter unavailable')
  target=Path(result.stdout.strip()).resolve()
  if not target.is_relative_to(folder.resolve()):raise ValueError('Candidate library directory escapes isolated folder')
  copied=0;bytecount=0
  if runner=='full':
   files=[path for path in target.rglob('*') if path.is_file()]
   copied=len(files);bytecount=sum(path.stat().st_size for path in files)
  else:
   for name,package in inventory['packages'].items():
    for filename in package['files']:
     current=(source/filename).resolve();destination=(target/filename).resolve()
     if not current.is_relative_to(source) or not destination.is_relative_to(target):raise ValueError('Dependency file escapes library directory')
     destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(current,destination);copied+=1;bytecount+=current.stat().st_size
   # Some ROCm wheels omit their namespace library files from RECORD. Copy
   # those installed directories explicitly rather than dropping device code.
   for name in ('_rocm_sdk_core','_rocm_sdk_libraries','_rocm_sdk_libraries_gfx110X_all','rocm_sdk_core','rocm_sdk_libraries','rocm_sdk_libraries_gfx110X-all'):
    origin=source/name
    if origin.is_dir():shutil.copytree(origin,target/name,dirs_exist_ok=True)
  health=subprocess.run([str(python),'-I','-m','pip','check'],capture_output=True,text=True,timeout=30,creationflags=flags)
  manifest=dict(python=str(python),plan_directory=str(folder),source_python=str(source_python),installed=True,activated=False,runner=runner,dependency_health=dict(state='healthy' if health.returncode==0 else 'conflicts',details=(health.stdout+health.stderr)[-4000:]),source_packages={name:package['version'] for name,package in inventory['packages'].items()},provenance='Read-only copy of installed runner dependency closure; not a fresh wheel release or GPU validation',copied_files=copied,copied_bytes=bytecount)
  (folder/'environment-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
  (folder/'requirements.txt').write_text('\n'.join(name+'=='+package['version'] for name,package in inventory['packages'].items())+'\n',encoding='utf-8')
  return manifest
 finally:
  if not (folder/'environment-manifest.json').is_file():shutil.rmtree(folder,ignore_errors=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--source-python',required=True);parser.add_argument('--runner',default='trl_cpu',choices=('trl_cpu','unsloth_qlora','full'));args=parser.parse_args()
 print(json.dumps(prepare(Path(__file__).resolve().parents[1],args.source_python,args.runner),indent=2))

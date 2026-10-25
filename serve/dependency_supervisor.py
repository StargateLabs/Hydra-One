"""Local dependency audit; repairs use the update centre's verified candidates."""
import json
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

BUSY = {'downloading','preparing','validating','resolving','installing_candidate','validating_python'}
PROFILES = {
    'dashboard': ('jinja2','numpy','regex','yaml','requests','PIL','psutil','jsonschema','huggingface_hub','tqdm'),
    'training': ('torch','transformers','trl','peft','datasets','accelerate','safetensors'),
    'visual': ('torch','diffusers','PIL'),
    'audio': ('torch','soundfile','imageio_ffmpeg'),
}
PROBE = """import importlib,importlib.metadata as m,json,sys
modules=json.loads(sys.argv[1]); missing=[]; errors={}
for name in modules:
 try: importlib.import_module(name)
 except Exception as error: missing.append(name);errors[name]=str(error)[:1000]
print(json.dumps({'missing':missing,'import_errors':errors,'packages':{d.metadata['Name']:d.version for d in m.distributions() if d.metadata['Name']}}))
"""

def probe(python,modules=None):
    result=subprocess.run([str(python),'-I','-c',PROBE,json.dumps(list(modules) if modules is not None else sorted({m for v in PROFILES.values() for m in v}))],
        capture_output=True,text=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode: raise ValueError('Python probe failed: '+result.stderr[-1200:])
    return json.loads(result.stdout)

def pinned_requirements(path):
    lines=[]
    for raw in Path(path).read_text(encoding='utf-8').splitlines():
        line=raw.split('#',1)[0].strip()
        if not line:continue
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*==[A-Za-z0-9_.+!-]+(?:\s*;\s*python_version\s*(?:>=|<=|==|>|<)\s*[\"\'][0-9.]+[\"\'])?',line):
            raise ValueError('Repair requires pinned PyPI package names, without URLs or pip options')
        lines.append(line)
    if not lines:raise ValueError('No pinned requirements')
    return lines

def audit(root,python,configuration=None):
    root=Path(root).resolve();rows=[];environments={}
    def check(identity,label,missing,**extra):
        rows.append(dict(id=identity,name=label,state='missing' if missing else 'ready',missing=missing,**extra))
    data=probe(python);environments[str(python)]=data
    check('core','Dashboard Python',[m for m in PROFILES['dashboard'] if m in data['missing']],repair='core')
    selected_python=python
    registry=root/'data/inference-python-selection.json'
    if registry.is_file():
        active=json.loads(registry.read_text(encoding='utf-8')).get('active') or {}
        selected_python=active.get('python') or python
    if Path(selected_python).is_file():
        runtime=environments.setdefault(str(selected_python),data if str(selected_python)==str(python) else probe(selected_python))
        for name in ('training','visual','audio'):
            check(name,name.capitalize(),[m for m in PROFILES[name] if m in runtime['missing']],python=str(selected_python),repair='compatible_environment')
    else:check('runtime-python','Python training / inferenza',[str(selected_python)],repair='compatible_environment')
    for filename in ('strata-runtime-selection.json','runtime-selection.json','runtime-gpu-selection.json','audio-runtime-selection.json','whisper-runtime-selection.json','soup-package-selection.json'):
        path=root/'data'/filename
        if not path.is_file():continue
        try:
            active=json.loads(path.read_text(encoding='utf-8')).get('active') or {}
            paths=[active[k] for k in ('binary','directory','package_root','previous_config') if isinstance(active.get(k),str)]
            missing=[p for p in paths if not Path(p).exists()]
            check(filename,filename.removesuffix('.json'),missing,repair='official_component')
        except (OSError,ValueError,TypeError) as error:check(filename,filename,[str(error)],repair=None)
    try:
        from serve.soup_runtime import selected_package
        soup=selected_package(root,verify=True)
        if soup:check('soup-integrity','SOUP integrità pacchetto',[],version=soup['version'])
    except (OSError,ValueError,KeyError,TypeError) as error:check('soup-integrity','SOUP integrità pacchetto',[str(error)],repair='official_component')
    harness_registry=root/'data/harness-runtime-selection.json'
    if harness_registry.is_file():
        try:
            active=json.loads(harness_registry.read_text(encoding='utf-8')).get('active') or {}
            for kind,entry in active.items():
                paths=[entry[key] for key in ('binary','site','venv') if isinstance(entry.get(key),str)]
                check('component:'+kind,kind,[p for p in paths if not Path(p).exists()],repair='official_component')
        except (OSError,ValueError,TypeError,AttributeError) as error:check('harness-registry','Strumenti integrati',[str(error)],repair=None)
    if (root/'data/audiocraft-selection.json').is_file():
        try:
            from serve.audiocraft_setup import selected_python as audio_python
            selected=audio_python(root)
            missing=probe(selected,('audiocraft.models','audioseal'))['missing'] if selected else ['No selected AudioCraft runtime']
            check('audiocraft','AudioCraft',missing,repair='official_audiocraft')
        except (OSError,ValueError,KeyError,TypeError) as error:check('audiocraft','AudioCraft',[str(error)],repair='official_audiocraft')
    hydra=root.parent/'HYDRA'
    hydra_files=('experimental_validation_v7_20261018_095534/feature-matrix.json','cpu_fastpath_v15/protocol-v15.1.json','performance_optimization_e2e_v1_retest_20261018_012618/protocol.json','hydra_lab/graph_hybrid.py','engine_completion_v22/prism-loader-manifest.json')
    if (root/'HYDRA/recovery/manifest.json').is_file():
        try:
            from serve.hydra_recovery import inspect
            recovered=inspect(root)
            missing=recovered['missing']+['Changed custom file, preserved: '+p for p in recovered['changed']]
            check('hydra-external','HYDRA: protocolli, moduli e runtime CPU',missing,repair='local_hydra_capsule',automatic_download=False,files_checked=recovered['files'])
        except (OSError,ValueError,KeyError,TypeError) as error:
            check('hydra-external','HYDRA: pacchetto locale di recupero',[str(error)],repair=None,automatic_download=False)
    else:
        check('hydra-external','HYDRA: protocolli e implementazioni esterne',[str(hydra/name) for name in hydra_files if not (hydra/name).is_file()],repair='recover_original_backup',automatic_download=False)
    configs=[Path(configuration)] if configuration else sorted(root.glob('strata-*.json'))
    for path in configs:
        try:
            cfg=json.loads(path.read_text(encoding='utf-8-sig'))
            if not cfg.get('exe') or not isinstance(cfg.get('args'),list):continue
            cwd=Path(cfg.get('cwd') or root)
            values=[cfg['exe'],cfg.get('tokenizer')]+cfg.get('lib_dirs',[])
            flags={'--pack','--native','--ple-gguf','--mtp','--expert-profile'}
            values += [cfg['args'][i+1] for i,x in enumerate(cfg['args'][:-1]) if x in flags]
            missing=[]
            for value in filter(None,values):
                target=Path(value);target=target if target.is_absolute() else cwd/target
                if not target.exists():missing.append(str(target))
            check('model:'+path.name,path.name,missing,repair='model_setup',automatic_download=False)
        except (OSError,ValueError,TypeError) as error:check('model:'+path.name,path.name,[str(error)],repair=None)
    return dict(state='attention' if any(r['state']=='missing' for r in rows) else 'ready',checked_at=time.time(),checks=rows,
                scope='Dependency discovery and selected file integrity; runtime execution requires feature validation.',
                official_sources=['https://pypi.org/simple','https://github.com/Niko1221/Strata','https://github.com/MakazhanAlpamys/Soup','https://pytorch.org','https://rocm.docs.amd.com'],
                automatic_model_download=False)

class DependencySupervisor:
    def __init__(self,root):
        self.root=Path(root);self.lock=threading.Lock();self.running=False
        self.result={'state':'not_checked','checks':[],'checked_at':0}
    def status(self):
        with self.lock:return json.loads(json.dumps({**self.result,'checking':self.running}))
    def scan(self,python,configuration=None):
        with self.lock:
            if self.running:return self.status_unlocked()
            self.running=True
        threading.Thread(target=self._scan,args=(python,configuration),daemon=True,name='dependency-health').start()
        return self.status()
    def status_unlocked(self):return json.loads(json.dumps({**self.result,'checking':self.running}))
    def _scan(self,python,configuration):
        try:
            result=audit(self.root,python,configuration)
            from serve.configuration import atomic_json
            atomic_json(self.root/'data/dependency-health.json',result)
        except Exception as error:result={'state':'error','error':str(error),'checks':[],'checked_at':time.time()}
        with self.lock:self.result=result;self.running=False

def prepare_core_repair(center):
    """Feed exact core requirements into the existing official resolver/installer."""
    if not center.operational_idle():raise ValueError('Stop active engines before dependency repair')
    lines=pinned_requirements(center.root/'requirements.txt')
    installed=probe(sys.executable)['packages']
    if any(name.lower() in ('torch','torchvision','torchaudio') and 'rocm' in version.lower() for name,version in installed.items()):
        raise ValueError('Preserve the AMD vendor runtime: repair its isolated compatible environment instead')
    names={re.split(r'==',line,1)[0].lower().replace('_','-') for line in lines}
    for name,version in installed.items():
        if name.lower().replace('_','-') not in names and name.lower() not in ('pip','setuptools'):
            if not re.fullmatch(r'[A-Za-z0-9_.-]+',name) or not re.fullmatch(r'[A-Za-z0-9_.+!-]+',version):raise ValueError('Invalid installed package metadata')
            lines.append(name+'=='+version)
    with center.lock:
        if center.job.get('state') in BUSY:raise ValueError('An update operation is already running')
        folder=center.folder/'python-plans'/('repair-'+uuid.uuid4().hex);folder.mkdir(parents=True)
        (folder/'requirements.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        center.job={'state':'resolving','name':'Strata','started_at':time.time(),'owner_pid':__import__('os').getpid(),
                    'plan_directory':str(folder),'source_python':sys.executable,'protected_packages':[],'repair_missing':True}
        center._persist_job()
    threading.Thread(target=center._resolve_dependencies,args=(sys.executable,folder),daemon=True).start()
    return center.status()

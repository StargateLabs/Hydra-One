"""Isolated, offline AirLLM CPU streaming. Original checkpoints are retained."""
import hashlib,json,os,re,shutil,subprocess,time,urllib.request,venv
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

_inventory_cache={}

def _inventory(python):
    script="import importlib.metadata as m,json;print(json.dumps(sorted((d.metadata['Name'],d.version) for d in m.distributions() if d.metadata['Name'])))"
    result=subprocess.run([str(python),'-I','-c',script],capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError('AirLLM package inventory failed')
    return hashlib.sha256(json.dumps(json.loads(result.stdout),sort_keys=True).encode()).hexdigest()

def validate_options(device,adapter,draft,quantization,attention,cache):
    if device!='cpu':raise ValueError('AirLLM GPU is not validated on this machine; select CPU')
    if adapter or draft or quantization!='none' or attention!='auto' or cache!='auto':
        raise ValueError('AirLLM CPU requires a base model, no draft/compression and automatic attention/cache')

def inspect_checkpoint(model):
    model=Path(model).resolve()
    # AirLLM prioritizes the pickle index over the Safetensors index upstream.
    if (model/'pytorch_model.bin.index.json').exists():raise ValueError('AirLLM requires a Safetensors-only checkpoint without a pickle index')
    index=model/'model.safetensors.index.json'
    if index.is_file():
        mapping=json.loads(index.read_text(encoding='utf-8')).get('weight_map')
        if not isinstance(mapping,dict) or not mapping:raise ValueError('Invalid Safetensors index')
        names=set(mapping.values())
        if any(not isinstance(name,str) or Path(name).name!=name or not name.endswith('.safetensors') or not (model/name).is_file() for name in names):raise ValueError('Invalid or missing local Safetensors shard')
        weights=[model/name for name in sorted(names)]
    elif (model/'model.safetensors').is_file():weights=[model/'model.safetensors']
    else:raise ValueError('AirLLM needs model.safetensors or a complete model.safetensors.index.json')
    largest=max(p.stat().st_size for p in weights)
    # Conversion can retain tensors from an earlier shard while loading another.
    # A layer spanning all shards is conservatively bounded by their total bytes.
    total=sum(p.stat().st_size for p in weights)
    layer_bytes=largest
    if index.is_file():
        groups={}
        for key,name in mapping.items():
            match=re.match(r'model\.layers\.\d+\.',key)
            owner=match.group(0) if match else key.split('.')[0]
            groups.setdefault(owner,set()).add(name)
        layer_bytes=max(sum((model/name).stat().st_size for name in names) for names in groups.values())
    return dict(weights=weights,conversion_ram_bytes=2*(largest+layer_bytes),total_bytes=total)

def cache_directory(root,model):
    model=Path(model).resolve();info=inspect_checkpoint(model)
    identity=[str(model),hashlib.sha256((model/'config.json').read_bytes()).hexdigest()]
    for weight in info['weights']:
        stat=weight.stat();identity.append((weight.name,stat.st_size,stat.st_mtime_ns))
    digest=hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]
    return Path(root).resolve()/'data/airllm-layer-cache'/digest

def environment_directory(root):return Path(root).resolve()/'output/updates/airllm-runtime'

def selected_python(root):
    base=environment_directory(root)
    try:version=json.loads((base/'selection.json').read_text(encoding='utf-8'))['active_version']
    except (OSError,ValueError,KeyError):raise ValueError('Prepare the isolated AirLLM CPU environment in Updates first')
    if not isinstance(version,str) or not re.fullmatch(r'4\.\d+\.\d+',version):raise ValueError('Invalid AirLLM environment selection')
    folder=base/'environments'/version;python=folder/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    manifest=folder/'environment-manifest.json'
    if not python.is_file() or not manifest.is_file():raise ValueError('Prepare the isolated AirLLM CPU environment in Updates first')
    row=json.loads(manifest.read_text(encoding='utf-8'))
    if row.get('dependency_health',{}).get('state')!='healthy' or row.get('device')!='cpu':raise ValueError('AirLLM environment has not passed dependency/import checks')
    return python

def _probe_python(python):
    script="import torch,importlib.metadata as m,json;from airllm import AirLLMBaseModel;assert torch.version.cuda is None and torch.version.hip is None;assert int(m.version('airllm').split('.')[0])==4;print(json.dumps({'airllm':m.version('airllm'),'torch':m.version('torch')}))"
    result=subprocess.run([str(python),'-I','-c',script],capture_output=True,text=True,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError('AirLLM CPU dependency check failed; prepare the isolated environment again')
    return python

def verify_environment(root):
    checked=status(root)
    if not checked['installed']:raise ValueError(checked['error'] or 'AirLLM environment failed verification')
    return _probe_python(Path(checked['python']))

def status(root):
    folder=environment_directory(root);row={};error=None
    try:
        python=selected_python(root)
        manifest=python.parent.parent.parent/'environment-manifest.json'
        row=json.loads(manifest.read_text(encoding='utf-8'))
        identity=(str(python),python.stat().st_mtime_ns,manifest.stat().st_mtime_ns)
        cached=_inventory_cache.get(identity)
        if cached and time.monotonic()-cached[0]<30:inventory=cached[1]
        else:
            inventory=_inventory(python);_inventory_cache.clear();_inventory_cache[identity]=(time.monotonic(),inventory)
        if not row.get('imports_verified') or inventory!=row.get('environment_sha256'):raise ValueError('AirLLM dependencies changed; validate the isolated environment again')
        installed=True
    except (ValueError,OSError,subprocess.SubprocessError) as problem:
        python=None;installed=False;error=str(problem)
    try:selection=json.loads((environment_directory(root)/'selection.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):selection={}
    return dict(previous_version=selection.get('previous_version'),can_rollback=bool(selection.get('previous_version') and selection.get('previous_version')!=selection.get('active_version')),installed=installed,python=str(python) if python else None,version=row.get('airllm_version'),
        device='cpu',gpu_validated=False,inference_verified=False,scope='CPU layer streaming; local model inference must be verified separately',
        directory=str(folder),manifest=row,error=error,source='https://github.com/lyogavin/airllm')

def prepare(root,version=None):
    """Explicit setup only: installs in a new CPU venv, never in Unsloth/global Python."""
    from serve.configuration import atomic_json
    with urllib.request.urlopen('https://pypi.org/pypi/airllm/json',timeout=30) as response:release=json.load(response)
    version=version or release['info']['version']
    if not isinstance(version,str) or not re.fullmatch(r'\d+\.\d+\.\d+',version) or int(version.split('.')[0])!=4 or version not in release['releases']:
        raise ValueError('AirLLM requires an official stable 4.x release')
    base=environment_directory(root);folder=base/'environments'/version;folder.mkdir(parents=True,exist_ok=True)
    # A healthy version is immutable. Installing it again only rechecks imports.
    existing=folder/'environment-manifest.json'
    if existing.is_file():
        saved=json.loads(existing.read_text(encoding='utf-8'))
        if saved.get('dependency_health',{}).get('state')=='healthy':
            python=folder/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            _probe_python(python)
            return select_version(root,version)
    envdir=folder/'venv';python=envdir/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    manifest=folder/'environment-manifest.json'
    atomic_json(manifest,dict(device='cpu',airllm_version=version,dependency_health=dict(state='preparing')))
    if not python.is_file():venv.EnvBuilder(with_pip=True).create(envdir)
    env={**os.environ,'PYTHONNOUSERSITE':'1','CUDA_VISIBLE_DEVICES':'-1','HIP_VISIBLE_DEVICES':'-1','ROCR_VISIBLE_DEVICES':'-1'}
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    commands=[['-m','pip','--isolated','install','--only-binary=:all:','--index-url','https://download.pytorch.org/whl/cpu','torch>=2.4'],
              ['-m','pip','--isolated','install','--only-binary=:all:','--index-url','https://pypi.org/simple',f'airllm=={version}'],['-m','pip','--isolated','check'],
              ['-I','-c',"import torch,airllm;from airllm import AirLLMBaseModel;assert torch.version.cuda is None and torch.version.hip is None;print('CPU imports verified')"]]
    with (folder/'installation.log').open('w',encoding='utf-8') as log:
        for command in commands:
            result=subprocess.run([str(python),*command],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1800,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:raise ValueError('AirLLM preparation failed; inspect installation.log')
    atomic_json(manifest,dict(python=str(python),airllm_version=version,device='cpu',dependency_health=dict(state='healthy'),
        imports_verified=True,environment_sha256=_inventory(python),inference_verified=False,prepared_at=time.time(),source='https://pypi.org/project/airllm/'))
    selection=base/'selection.json'
    try:previous=json.loads(selection.read_text(encoding='utf-8')).get('active_version')
    except (OSError,ValueError):previous=None
    return select_version(root,version)

def select_version(root,version,rollback=False):
    from serve.configuration import atomic_json
    base=environment_directory(root);path=base/'selection.json'
    try:previous=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):previous={}
    if rollback:version=previous.get('previous_version')
    if not isinstance(version,str) or not re.fullmatch(r'4\.\d+\.\d+',version):raise ValueError('No valid previous AirLLM environment is available')
    folder=base/'environments'/version;manifest=json.loads((folder/'environment-manifest.json').read_text(encoding='utf-8'))
    python=folder/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if manifest.get('dependency_health',{}).get('state')!='healthy' or not manifest.get('imports_verified') or _inventory(python)!=manifest.get('environment_sha256'):raise ValueError('AirLLM candidate dependencies changed; prepare again')
    _probe_python(python)
    old=previous.get('active_version')
    if old!=version:atomic_json(path,dict(active_version=version,previous_version=old,selected_at=time.time()))
    return status(root)


def load_cpu_model(root,model_path,context,torch):
    """Guard upstream's permissive remote-code fallback within the owned child."""
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    import transformers
    from airllm import AirLLMBaseModel
    info=inspect_checkpoint(model_path)
    cache=cache_directory(root,model_path);cache.mkdir(parents=True,exist_ok=True)
    if not (cache/'strata-conversion-complete.json').is_file() and shutil.disk_usage(cache).free<info['total_bytes']+1024**3:
        raise ValueError('AirLLM layer conversion needs additional disk space for a copy of the original weights plus 1 GiB')
    # Do not call AirLLM AutoModel: it unconditionally enables remote model code.
    def local_factory(original,pretrained=True):
        def guarded(*args,**kwargs):
            kwargs.update(trust_remote_code=False)
            if pretrained:kwargs['local_files_only']=True
            return original(*args,**kwargs)
        return guarded
    with ExitStack() as guards:
        from serve.safetensors_runtime import load_local_tokenizer
        original_tokenizer=transformers.AutoTokenizer.from_pretrained
        guards.enter_context(patch.object(transformers.AutoTokenizer,'from_pretrained',side_effect=lambda path,*args,**kwargs:load_local_tokenizer(path,original_tokenizer)))
        for factory in (transformers.AutoConfig,transformers.GenerationConfig):
            guards.enter_context(patch.object(factory,'from_pretrained',side_effect=local_factory(factory.from_pretrained)))
        for name in ('AutoModelForCausalLM','AutoModelForSeq2SeqLM','AutoModelForImageTextToText','AutoModelForVision2Seq'):
            factory=getattr(transformers,name,None)
            if factory is not None:
                guards.enter_context(patch.object(factory,'from_config',side_effect=local_factory(factory.from_config,False)))
        wrapper=AirLLMBaseModel(str(model_path),device='cpu',dtype=torch.float32,max_seq_len=context,
            layer_shards_saving_path=str(cache),compression=None,prefetching=False,delete_original=False)
    (cache/'strata-conversion-complete.json').write_text(json.dumps(dict(model=str(model_path),completed_at=time.time())),encoding='utf-8')
    # The wrapped Transformers model has AirLLM's weight-streaming hooks attached.
    return wrapper.model,wrapper.tokenizer,wrapper

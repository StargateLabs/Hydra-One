"""Reversible document runtime candidates; the original verified runtime stays intact."""
import hashlib,json,os,re,shutil,subprocess,time
from pathlib import Path
from serve.configuration import atomic_json
from serve.python_inference_update import folder_checked,environment_fingerprint

def fingerprint(root):
    digest=hashlib.sha256()
    for name in ('open_webui_candidate_worker.py','open_webui_runtime.py','document_reranker.py','open_webui_reranker_worker.py'):
        digest.update(name.encode());digest.update((Path(root)/'serve'/name).read_bytes())
    return digest.hexdigest()

def probe(root,python,storage):
    metadata=subprocess.run([str(python),'-I','-c',"import importlib.metadata,json;print(json.dumps({'version':importlib.metadata.version('open-webui')}))"],capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if metadata.returncode:raise ValueError('Open WebUI package is unavailable in this candidate')
    version=json.loads(metadata.stdout)['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('Unsupported Open WebUI release channel')
    env={**os.environ,'STRATA_OPEN_WEBUI_VERSION':version,'STRATA_OPEN_WEBUI_DATA':str(storage),'PYTHONNOUSERSITE':'1'}
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    result=subprocess.run([str(python),'-I',str(Path(root)/'serve/open_webui_candidate_worker.py')],input='{"action":"contract"}',capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60,env=env,cwd=root,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    lines=[line.partition('STARGATE_RESULT:')[2] for line in result.stdout.splitlines() if line.startswith('STARGATE_RESULT:')]
    if result.returncode or not lines:raise ValueError('Open WebUI native contract failed: '+(lines[-1] if lines else result.stderr[-1200:]))
    return json.loads(lines[-1])

def validate(root,folder,source):
    folder=folder_checked(root,folder);path=folder/'environment-manifest.json';manifest=json.loads(path.read_text(encoding='utf-8'))
    previous_proof=manifest.pop('document_validation',{});atomic_json(path,manifest)
    python=Path(manifest['python']).resolve()
    if not python.is_relative_to(folder) or not python.is_file() or manifest.get('dependency_health',{}).get('state')!='healthy':raise ValueError('Invalid isolated document candidate')
    baseline=probe(root,source,folder/'contract-baseline-data');contract=probe(root,python,folder/'private-document-data')
    if baseline['torch']!=contract['torch']:raise ValueError('CPU Torch build changed; current document runtime preserved')
    from serve.open_webui_runtime import ocr_models
    retained={}
    try:original_ocr=ocr_models(root)
    except (OSError,ValueError,KeyError):
        original_ocr={}
        for name,row in previous_proof.get('ocr_models',{}).items():
            original_path=Path(row['path']).resolve()
            if original_path.is_relative_to(folder) and original_path.is_file() and hashlib.sha256(original_path.read_bytes()).hexdigest()==row.get('sha256'):original_ocr[name]=str(original_path)
    for name,original in original_ocr.items():
        original_path=Path(original);target=folder/'retained-ocr'/original_path.name;target.parent.mkdir(parents=True,exist_ok=True)
        if original_path.resolve()!=target.resolve():shutil.copyfile(original_path,target)
        retained[name]={'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    manifest['document_validation']={'passed':True,'contract':contract,'runtime_sha256':fingerprint(root),'python_sha256':hashlib.sha256(python.read_bytes()).hexdigest(),'environment_sha256':environment_fingerprint(python),'validated_at':time.time(),'scope':contract['scope']}
    manifest['document_validation']['ocr_models']=retained
    atomic_json(path,manifest);return manifest

def candidate(root,folder,full=True):
    folder=folder_checked(root,folder);manifest=json.loads((folder/'environment-manifest.json').read_text(encoding='utf-8'));python=Path(manifest['python']).resolve();proof=manifest.get('document_validation',{})
    if not python.is_relative_to(folder) or not python.is_file() or manifest.get('dependency_health',{}).get('state')!='healthy' or not proof.get('passed') or proof.get('runtime_sha256')!=fingerprint(root) or proof.get('python_sha256')!=hashlib.sha256(python.read_bytes()).hexdigest():raise ValueError('Validate the isolated document runtime before selection')
    if full and proof.get('environment_sha256')!=environment_fingerprint(python):raise ValueError('Document candidate packages changed')
    for row in proof.get('ocr_models',{}).values():
        path=Path(row['path']).resolve()
        if not path.is_relative_to(folder) or not path.is_file() or path.is_symlink():raise ValueError('Retained OCR weights are unavailable')
        if full and hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Retained OCR weights changed')
    return python,proof['contract']['version']

def selection(root,full=False):
    registry=Path(root)/'data/document-python-selection.json'
    if not registry.is_file():return None
    row=json.loads(registry.read_text(encoding='utf-8')).get('active')
    if not row:return None
    python,version=candidate(root,row['plan_directory'],full)
    manifest=json.loads((Path(row['plan_directory'])/'environment-manifest.json').read_text(encoding='utf-8'))
    return {**row,'python':str(python),'version':version,'ocr_models':{name:value['path'] for name,value in manifest['document_validation'].get('ocr_models',{}).items()}}

def activate(root,folder=None,rollback=False):
    from serve.open_webui_runtime import _lock
    if not _lock.acquire(blocking=False):raise ValueError('Finish document processing before runtime selection')
    try:
        if (Path(root)/'data/open-webui/worker.lock').exists() or (Path(root)/'data/open-webui/setup.lock').exists():raise ValueError('Document runtime is in use')
        registry=Path(root)/'data/document-python-selection.json';previous=json.loads(registry.read_text(encoding='utf-8')) if registry.is_file() else {}
        if rollback:
            if 'previous' not in previous:raise ValueError('No previous document runtime selection')
            active=previous['previous']
            if active:candidate(root,active['plan_directory'])
            else:
                from serve.open_webui_runtime import baseline_ready
                if not baseline_ready(root):raise ValueError('Original document runtime is no longer valid')
        else:
            python,version=candidate(root,folder);active={'python':str(python),'version':version,'plan_directory':str(Path(folder).resolve())}
        atomic_json(registry,{'active':active,'previous':previous.get('active'),'changed_at':time.time()});return active
    finally:_lock.release()

"""Private Open WebUI functions, no separate HTTP server or UI."""
import base64, hashlib, json, os, re, shutil, subprocess, tempfile, threading, time, uuid, zipfile
from pathlib import Path

_lock=threading.Lock()
_child_lock=threading.Lock()
_active_child=None
MAX_UPLOAD=8*1024*1024
FORMATS={'.pdf':'application/pdf','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
         '.txt':'text/plain','.md':'text/markdown','.csv':'text/csv','.json':'application/json'}

def directory(root):return Path(root)/'output/updates/open-webui-runtime/environments/0.12.0'

def python_executable(root):
    if not (Path(root)/'data/document-python-selection.json').is_file():return directory(root)/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    from serve.open_webui_python_update import selection
    selected=selection(root)
    return Path(selected['python']) if selected else directory(root)/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')

def baseline_ready(root):
    folder=directory(root);python=folder/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    try:manifest=json.loads((folder/'integration-manifest.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return False
    return python.is_file() and manifest.get('passed') is True and manifest.get('source_sha256')==source_hash(root) and manifest.get('runtime_sha256')==runtime_hash(root)

def source_hash(root):return hashlib.sha256((Path(root)/'serve/open_webui_worker.py').read_bytes()).hexdigest()

def runtime_hash(root):
    venv=directory(root)/'venv'
    folders=[venv/'Lib/site-packages'] if os.name=='nt' else list((venv/'lib').glob('python*/site-packages'))
    if len(folders)!=1:return 'invalid_runtime_layout'
    folder=folders[0]
    digest=hashlib.sha256()
    for name in ('retrieval/loaders/main.py','retrieval/utils.py','utils/context_compaction.py'):
        path=folder/'open_webui'/name;digest.update(path.read_bytes() if path.is_file() else b'missing')
    for distribution in sorted(folder.glob('*.dist-info')):digest.update(distribution.name.encode())
    return digest.hexdigest()

def ocr_models(root):
    if (Path(root)/'data/document-python-selection.json').is_file():
        from serve.open_webui_python_update import selection
        selected=selection(root)
        if selected and selected.get('ocr_models'):return selected['ocr_models']
    venv=python_executable(root).parent.parent
    folders=[venv/'Lib/site-packages'] if os.name=='nt' else list((venv/'lib').glob('python*/site-packages'))
    if len(folders)!=1:return {}
    package=folders[0]/'rapidocr/models'
    names={'Det':'PP-OCRv6_det_small.onnx','Rec':'PP-OCRv6_rec_small.onnx','Cls':'ch_ppocr_mobile_v2.0_cls_mobile.onnx'}
    paths={key:package/name for key,name in names.items()}
    if not all(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=256*1024**2 for path in paths.values()):return {}
    return {key:str(path.resolve()) for key,path in paths.items()}

def embedding_models(root, bases=None):
    rows=[];allowed={'sentence_transformers.models.'+name for name in ('Transformer','Pooling','Normalize','Dense','WeightedLayerPooling','LayerNorm')}
    for base in bases if bases is not None else (Path(root)/'models/embeddings',Path(root).parent/'Strata-data/models/embeddings'):
        if not base.is_dir() or base.is_symlink():continue
        for modules in base.rglob('modules.json'):
            try:
                folder=modules.parent.resolve()
                if modules.stat().st_size>65536 or any(p.is_symlink() for p in folder.rglob('*')):continue
                config=json.loads(modules.read_text(encoding='utf-8'))
                if not isinstance(config,list) or not config or len(config)>16 or any(not isinstance(row,dict) or row.get('type') not in allowed or not isinstance(row.get('path',''),str) or not (folder/row.get('path','')).resolve().is_relative_to(folder) for row in config):continue
                weights=list(folder.rglob('*.safetensors'));size=sum(p.stat().st_size for p in weights)
                if not weights or not 0<size<=1024**3:continue
                safe=True
                for module in config:
                    path=folder/module.get('path','')
                    if module['type']=='sentence_transformers.models.Transformer' and not list(path.glob('*.safetensors')):safe=False
                    if module['type']=='sentence_transformers.models.Dense':
                        if not (path/'model.safetensors').is_file():safe=False
                        dense=json.loads((path/'config.json').read_text(encoding='utf-8'))
                        if not str(dense.get('activation_function','')).startswith('torch.nn.'):safe=False
                if not safe:continue
                rows.append({'path':str(folder),'name':folder.name,'bytes':size})
            except (OSError,ValueError,TypeError):continue
    return rows

def import_embedding(root,payload):
    """Copy a user-selected local model; never modify its original folder."""
    raw=payload.get('path')
    if not isinstance(raw,str) or not raw.strip() or len(raw)>4096:raise ValueError('Indica la cartella locale del modello embedding.')
    source=Path(raw.strip())
    if not source.is_absolute() or str(source).startswith(('\\\\','//')) or source.is_symlink() or not source.is_dir():raise ValueError('Serve una cartella locale assoluta, senza collegamenti.')
    source=source.resolve()
    existing=next((row for row in embedding_models(root) if row['path']==str(source)),None)
    if existing:return {'ok':True,'model':existing}
    if not any(row['path']==str(source) for row in embedding_models(root,(source,))):raise ValueError('Modello SentenceTransformer locale non compatibile: richiesti modules.json e pesi Safetensors.')
    files=[]
    for entry in source.rglob('*'):
        files.append(entry)
        if len(files)>2048:raise ValueError('Cartella troppo grande: massimo 2048 elementi.')
    if len(files)>2048 or any(p.is_symlink() for p in files):raise ValueError('Cartella troppo grande o contenente collegamenti.')
    size=sum(p.stat().st_size for p in files if p.is_file())
    if not 0<size<=2*1024**3:raise ValueError('La cartella deve contenere al massimo 2 GiB.')
    target=Path(root)/'models/embeddings';target.mkdir(parents=True,exist_ok=True)
    if target.is_symlink() or target.resolve().is_relative_to(source):raise ValueError('Origine e destinazione devono essere cartelle distinte.')
    if shutil.disk_usage(target).free<size+128*1024**2:raise ValueError('Spazio insufficiente per conservare una copia del modello.')
    if not _lock.acquire(blocking=False):raise RuntimeError('Completa prima l’elaborazione documenti in corso.')
    staging=Path(tempfile.mkdtemp(prefix='.embedding-',dir=Path(root)/'output'))
    try:
        copied=0
        for path in files:
            if not path.is_file():continue
            if path.is_symlink() or not path.resolve().is_relative_to(source):raise ValueError('Origine del modello modificata durante la copia.')
            destination=staging/path.relative_to(source);destination.parent.mkdir(parents=True,exist_ok=True)
            with path.open('rb') as original,destination.open('wb') as output:
                while chunk:=original.read(1024*1024):
                    copied+=len(chunk)
                    if copied>size or copied>2*1024**3:raise ValueError('Origine del modello modificata durante la copia.')
                    output.write(chunk)
        if copied!=size:raise ValueError('Origine del modello modificata durante la copia.')
        if not embedding_models(root,(staging,)):raise ValueError('Copia del modello non compatibile.')
        name=re.sub(r'[^A-Za-z0-9._-]','-',source.name).strip('.-')[:80] or 'embedding'
        final=target/(name+'-'+uuid.uuid4().hex[:8]);staging.rename(final)
        return {'ok':True,'model':{'path':str(final.resolve()),'name':final.name,'bytes':size}}
    finally:
        if staging.exists():shutil.rmtree(staging)
        _lock.release()

def reranker_status(root):
    from serve.document_reranker import model
    try:return {**model(root),'ready':True}
    except (OSError,ValueError,KeyError):return {'ready':False}

def status(root):
    from serve.open_webui_python_update import selection
    try:selected=selection(root);python=python_executable(root)
    except (OSError,ValueError,KeyError) as error:
        return {'ready':False,'installed':True,'processor':'Open WebUI','functions':[],'formats':list(FORMATS),'max_upload_bytes':MAX_UPLOAD,'offline':True,'external_ui':False,'semantic_embeddings':False,'embedding_models':[],'embedding_import':False,'ocr':False,'busy':_lock.locked(),'error':str(error),'requires_validation':True,'setup_busy':(Path(root)/'data/open-webui/setup.lock').exists()}
    verified=bool(selected) or baseline_ready(root)
    try:job=json.loads((Path(root)/'data/open-webui/setup-job.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):job=None
    embeddings=embedding_models(root)
    return {'job':job,'setup_busy':(Path(root)/'data/open-webui/setup.lock').exists(),'installed':python.is_file(),'ready':bool(verified and not (Path(root)/'data/open-webui/setup.lock').exists()),'version':selected['version'] if selected else '0.12.0','processor':'Open WebUI','runtime_selection':selected,
            'functions':(['document_extraction','lexical_document_retrieval','context_analysis']+(['semantic_document_retrieval','hybrid_document_retrieval'] if embeddings else [])+(['pdf_ocr'] if ocr_models(root) else [])) if verified else [],
            'formats':list(FORMATS),'max_upload_bytes':MAX_UPLOAD,'offline':True,'external_ui':False,
            'semantic_embeddings':bool(verified and embeddings),'embedding_models':embeddings,'reranker':reranker_status(root),'embedding_import':True,'ocr':bool(verified and ocr_models(root)),'busy':_lock.locked() or (Path(root)/'data/open-webui/worker.lock').exists()}

def worker(root,payload):
    python=python_executable(root)
    if not python.is_file():raise ValueError('Open WebUI isolated runtime is not installed')
    if not _lock.acquire(blocking=False):raise ValueError('Open WebUI is processing another document; try again shortly')
    lease=Path(root)/'data/open-webui/worker.lock';lease.parent.mkdir(parents=True,exist_ok=True);token=uuid.uuid4().hex;owned=False
    try:
        import psutil
        for attempt in range(2):
            try:
                with lease.open('x',encoding='utf-8') as stream:json.dump({'pid':os.getpid(),'created_at':psutil.Process().create_time(),'token':token},stream)
                owned=True;break
            except FileExistsError:
                try:
                    owner=json.loads(lease.read_text(encoding='utf-8'));process=psutil.Process(owner['pid'])
                    alive=process.create_time()==owner['created_at']
                except (OSError,ValueError,KeyError,psutil.Error):alive=False
                if alive:raise ValueError('Open WebUI is processing another request; try again shortly')
                lease.unlink(missing_ok=True)
        if not owned:raise ValueError('Open WebUI worker reservation unavailable')
        env={**os.environ,'PYTHONNOUSERSITE':'1'};env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
        script='open_webui_semantic_worker.py' if payload.get('action')=='semantic' else 'open_webui_ocr_worker.py' if payload.get('action')=='ocr_extract' else 'open_webui_worker.py'
        from serve.open_webui_python_update import selection
        selected=selection(root)
        python=python_executable(root)
        if selected:
            script='open_webui_reranker_worker.py' if payload.get('action')=='rerank' else 'open_webui_candidate_worker.py'
            env.update(STRATA_OPEN_WEBUI_VERSION=selected['version'],STRATA_OPEN_WEBUI_DATA=str(Path(selected['plan_directory'])/'private-document-data'))
        global _active_child
        process=subprocess.Popen([str(python),'-I',str(Path(root)/'serve'/script)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',env=env,cwd=root,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        from serve.winjob import contain
        contain(process)
        cancelled=threading.Event()
        with _child_lock:_active_child=(str(Path(root).resolve()),process,cancelled)
        try:
            stdout,stderr=process.communicate(json.dumps(payload,ensure_ascii=True),timeout=45)
        except subprocess.TimeoutExpired:
            process.kill();process.communicate();raise
        finally:
            with _child_lock:
                if _active_child and _active_child[1] is process:_active_child=None
        if cancelled.is_set():raise ValueError('Document processing cancelled; stored documents retained')
        result=subprocess.CompletedProcess(process.args,process.returncode,stdout,stderr)
        lines=[line.partition('STARGATE_RESULT:')[2] for line in result.stdout.splitlines() if line.startswith('STARGATE_RESULT:')]
        if not lines or len(lines[-1])>2*1024*1024:raise ValueError('Open WebUI worker did not return a bounded result')
        data=json.loads(lines[-1])
        if result.returncode or data.get('error'):raise ValueError(data.get('error') or 'Open WebUI processing failed')
        return data
    except subprocess.TimeoutExpired:raise ValueError('Open WebUI document processing exceeded 45 seconds') from None
    finally:
        if 'process' in locals() and process.poll() is None:
            process.kill();process.communicate()
        if owned:
            try:
                if json.loads(lease.read_text(encoding='utf-8')).get('token')==token:lease.unlink()
            except (OSError,ValueError):pass
        _lock.release()

def cancel(root):
    with _child_lock:
        if not _active_child or _active_child[0]!=str(Path(root).resolve()) or _active_child[1].poll() is not None:return {'ok':True,'cancellation_requested':False}
        _active_child[2].set();_active_child[1].terminate()
    return {'ok':True,'cancellation_requested':True}

def require_ready(root):
    if not status(root)['ready']:raise ValueError('Open WebUI internal integration has not passed its checks')

def upload(root,payload):
    require_ready(root)
    if not isinstance(payload,dict):raise ValueError('Invalid document upload')
    name=payload.get('name');encoded=payload.get('data')
    if not isinstance(name,str) or not 1<=len(name)<=160 or '/' in name or '\\' in name:raise ValueError('Invalid document filename')
    suffix=Path(name).suffix.lower()
    if suffix not in FORMATS:raise ValueError('Supported documents: PDF, DOCX, TXT, MD, CSV and JSON')
    if not isinstance(encoded,str) or len(encoded)>MAX_UPLOAD*4//3+8:raise ValueError('Document exceeds 8 MiB')
    try:raw=base64.b64decode(encoded,validate=True)
    except ValueError:raise ValueError('Invalid document data') from None
    if not raw or len(raw)>MAX_UPLOAD:raise ValueError('Document must contain between 1 byte and 8 MiB')
    ocr=payload.get('ocr',False)
    if type(ocr) is not bool:raise ValueError('OCR must be a boolean')
    if ocr and (suffix!='.pdf' or not ocr_models(root)):raise ValueError('Local PDF OCR models are unavailable')
    storage=Path(root)/'data/open-webui/documents';storage.mkdir(parents=True,exist_ok=True)
    if len(list(storage.glob('*.json')))>=50:raise ValueError('Document library is full; remove a document before uploading another')
    with tempfile.TemporaryDirectory(prefix='upload-',dir=storage) as temporary:
        path=Path(temporary)/('document'+suffix);path.write_bytes(raw)
        if suffix=='.docx':
            with zipfile.ZipFile(path) as archive:
                files=archive.infolist()
                if len(files)>2000 or sum(f.file_size for f in files)>32*1024*1024:raise ValueError('DOCX archive exceeds extraction limits')
                if 'word/document.xml' not in archive.namelist():raise ValueError('Invalid DOCX document')
        result=worker(root,{'action':'ocr_extract' if ocr else 'extract','name':name,'path':str(path),'mime':FORMATS[suffix]})
    document_id=uuid.uuid4().hex
    record={**result,'id':document_id,'name':name,'created_at':time.time(),'sha256':hashlib.sha256(raw).hexdigest()}
    from serve.configuration import atomic_json
    atomic_json(storage/(document_id+'.json'),record)
    return {'id':document_id,'name':name,'processor':result['processor'],'pages':result['pages'],
            'chunks':len(result['chunks']),'preview':result['chunks'][0]['text'][:1200],
            'method':'BM25 lexical retrieval','original_uploaded_file_retained':False}

def document(root,identity):
    if not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{32}',identity):raise ValueError('Invalid document identity')
    path=Path(root)/'data/open-webui/documents'/(identity+'.json')
    if not path.is_file():raise ValueError('Document is no longer available; attach it again')
    return path

def fuse_rankings(*rankings):
    merged={}
    for result in rankings:
        seen=set()
        for rank,match in enumerate(result.get('matches',[]),1):
            key=match.get('chunk')
            if type(key) is not int or key in seen:continue
            seen.add(key)
            if key not in merged:merged[key]={**match,'rrf_score':0.0}
            merged[key]['rrf_score']+=1/(60+rank)
    return sorted(merged.values(),key=lambda row:(-row['rrf_score'],row['chunk']))[:4]


def _retrieve(root,payload,chunks):
    require_ready(root)
    if not isinstance(payload,dict):raise ValueError('Invalid document query')
    query=payload.get('query')
    if not isinstance(query,str) or not 1<=len(query)<=4000:raise ValueError('Document question must contain 1 to 4000 characters')
    method=payload.get('method','lexical')
    if method not in ('lexical','semantic','hybrid'):raise ValueError('Choose lexical, semantic or hybrid document retrieval')
    request={'action':'search','query':query,'chunks':chunks}
    if method in ('semantic','hybrid'):
        model=next((model for model in embedding_models(root) if model['path']==payload.get('embedding_model')),None)
        if model is None:raise ValueError('Choose a locally installed Safetensors embedding model')
        import psutil
        if psutil.virtual_memory().available<model['bytes']*4+512*1024**2:raise ValueError('Insufficient available RAM for local document embeddings')
        request.update(action='semantic',embedding_model=model['path'])
    rerank=payload.get('rerank',False)
    if type(rerank) is not bool:raise ValueError('Rerank must be boolean')
    if rerank and not reranker_status(root)['ready']:raise ValueError('Local reranker is unavailable')
    result=worker(root,request)
    if method=='hybrid':
        lexical=worker(root,{'action':'search','query':query,'chunks':chunks})
        result=dict(processor='Open WebUI',method='Hybrid BM25 + local embeddings · reciprocal rank fusion',matches=fuse_rankings(lexical,result),embedding_model=result.get('embedding_model'),version=result.get('version'))
    if rerank and result.get('matches'):
        ranking=worker(root,{'action':'rerank','query':query,'matches':result['matches']})
        result={**result,**ranking,'method':result.get('method','')+' + local cross-encoder'}
    return result

def search(root,payload):
    row=json.loads(document(root,payload.get('id')).read_text(encoding='utf-8'))
    result=_retrieve(root,payload,row['chunks']);result.update(id=row['id'],name=row['name'])
    return result


def metadata(root,payload):
    collection=payload.get('collection','')
    if not isinstance(collection,str) or len(collection)>80 or any(ord(c)<32 for c in collection):raise ValueError('Raccolta: massimo 80 caratteri, senza caratteri di controllo.')
    from serve.configuration import atomic_json
    with _lock:
        path=document(root,payload.get('id'));row=json.loads(path.read_text(encoding='utf-8'))
        row['collection']=collection.strip();atomic_json(path,row)
    return {'id':row['id'],'collection':row['collection']}

def read(root,payload):
    row=json.loads(document(root,payload.get('id')).read_text(encoding='utf-8'))
    chunks=row.get('chunks',[])
    if sum(len(c.get('text','')) for c in chunks)>24000:raise ValueError('Documento oltre 24.000 caratteri: usa la ricerca mirata. Nessun testo troncato.')
    return {'id':row['id'],'name':row['name'],'method':'Documento completo · testo estratto','matches':[dict(c,chunk=i) for i,c in enumerate(chunks)]}

def search_library(root,payload):
    collection=payload.get('collection','')
    if not isinstance(collection,str) or len(collection)>80:raise ValueError('Raccolta non valida.')
    rows=[row for row in library(root)['items'] if not collection or row.get('collection','')==collection]
    if len(rows)>10:raise ValueError('Ricerca limitata a 10 documenti: scegli una raccolta piu piccola.')
    chunks=[];sources=[]
    for row in rows:
        record=json.loads(document(root,row['id']).read_text(encoding='utf-8'))
        for index,chunk in enumerate(record.get('chunks',[])):
            chunks.append(chunk);sources.append({'document_id':row['id'],'name':row['name'],'chunk':index})
    if sum(len(c.get('text','')) for c in chunks)>1000000:raise ValueError('Raccolta oltre un milione di caratteri: scegli una raccolta piu piccola.')
    result=_retrieve(root,payload,chunks) if chunks else {'matches':[],'method':payload.get('method','lexical')}
    matches=[]
    for match in result.get('matches',[]):
        index=match.get('chunk')
        if type(index) is int and 0<=index<len(sources):matches.append({**match,**sources[index]})
    return {**result,'matches':matches,'documents_searched':len(rows),'ranking':'Ricerca unica sui passaggi della raccolta'}


def remove(root,payload):
    if not isinstance(payload,dict):raise ValueError('Invalid document removal')
    document(root,payload.get('id')).unlink()
    return {'removed':True}

def context(root,messages):
    require_ready(root)
    if not isinstance(messages,list) or len(messages)>2000 or len(json.dumps(messages))>1500000:raise ValueError('Context analysis exceeds limits')
    return worker(root,{'action':'context','messages':messages})


def library(root):
    storage=Path(root)/'data/open-webui/documents';items=[]
    for path in list(storage.glob('*.json'))[:50]:
        try:
            if path.stat().st_size>2*1024*1024:continue
            row=json.loads(path.read_text(encoding='utf-8'))
            chunks=[chunk for chunk in (row.get('chunks') or []) if isinstance(chunk,dict)]
            facts={key:row.get(key) for key in ('id','name','pages','created_at','processor','collection','sha256')}
            facts.update(chunks=len(chunks),characters=sum(len(chunk.get('text','')) for chunk in chunks),
                         format=Path(str(row.get('name') or '')).suffix.removeprefix('.').lower())
            items.append(facts)
        except (OSError,ValueError,TypeError):continue
    return {'items':sorted(items,key=lambda row:row.get('created_at') or 0,reverse=True),'limit':50}

def attach(root,payload):
    require_ready(root)
    row=json.loads(document(root,payload.get('id')).read_text(encoding='utf-8'))
    return {'id':row['id'],'name':row['name'],'pages':row['pages'] if row['name'].lower().endswith('.pdf') else None,'preview':row['chunks'][0]['text'][:1200],'processor':'Open WebUI'}


def prepare(root,version=None):
    """Prepare the API-validated release only; leave all other Python environments alone."""
    import shutil,sys,urllib.request,venv
    from packaging.specifiers import SpecifierSet
    from serve.configuration import atomic_json
    from serve.open_webui_python_update import selection
    if selection(root):raise ValueError('Use the update centre for the selected document runtime; original setup remains untouched')
    if version not in (None,'0.12.0'):raise ValueError('This integration currently validates Open WebUI 0.12.0')
    folder=directory(root);storage=Path(root)/'data/open-webui';storage.mkdir(parents=True,exist_ok=True)
    lease=storage/'setup.lock';owned=False;token=uuid.uuid4().hex
    try:
        try:
            with lease.open('x',encoding='utf-8') as stream:json.dump({'pid':os.getpid(),'token':token},stream)
            owned=True
        except FileExistsError:
            import psutil
            try:alive=psutil.pid_exists(json.loads(lease.read_text(encoding='utf-8'))['pid'])
            except (OSError,ValueError,KeyError):alive=True
            if alive:raise ValueError('Open WebUI setup is already running')
            lease.unlink();return prepare(root,version)
        atomic_json(storage/'setup-job.json',{'state':'preparing','step':'checking','started_at':time.time(),'owner_pid':os.getpid()})
        if (storage/'worker.lock').exists():raise ValueError('Wait for the current Open WebUI document operation to finish')
        if shutil.disk_usage(root).free<8*1024**3:raise ValueError('Open WebUI needs 8 GiB of free disk reserve')
        folder.mkdir(parents=True,exist_ok=True);python=folder/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        healthy=False
        if python.is_file():
            probe=subprocess.run([str(python),'-I','-c',"import importlib.metadata as m;assert m.version('open-webui')=='0.12.0'"],capture_output=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            health=subprocess.run([str(python),'-I','-m','pip','check'],capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            healthy=probe.returncode==0 and health.returncode==0
        if not healthy:
            request=urllib.request.Request('https://pypi.org/pypi/open-webui/0.12.0/json',headers={'User-Agent':'StargateLab-Internal-Setup'})
            with urllib.request.urlopen(request,timeout=20) as response:metadata=json.loads(response.read(2*1024*1024))
            info=metadata['info']
            if info['name'].lower()!='open-webui' or info['version']!='0.12.0':raise ValueError('Official Open WebUI package identity mismatch')
            if not SpecifierSet(info['requires_python']).contains('.'.join(map(str,sys.version_info[:3]))):raise ValueError('This Open WebUI release requires Python '+info['requires_python'])
            wheels=[row for row in metadata['urls'] if row['filename']=='open_webui-0.12.0-py3-none-any.whl']
            if len(wheels)!=1:raise ValueError('Official Open WebUI universal wheel unavailable')
            wheel=wheels[0];url=wheel['url'];digest=wheel['digests']['sha256']
            from urllib.parse import urlparse
            if urlparse(url).hostname!='files.pythonhosted.org' or urlparse(url).scheme!='https' or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('Unverified Open WebUI wheel source')
            if not python.is_file():venv.EnvBuilder(with_pip=True).create(folder/'venv')
            atomic_json(storage/'setup-job.json',{'state':'preparing','step':'installing','owner_pid':os.getpid()})
            uv=shutil.which('uv');commands=[]
            if uv:commands=[[uv,'pip','install','--python',str(python),'--index-url','https://pypi.org/simple','--torch-backend','cpu','--only-binary',':all:',url+'#sha256='+digest]]
            else:commands=[[str(python),'-m','pip','--isolated','install','--only-binary=:all:','--index-url','https://download.pytorch.org/whl/cpu','torch>=2.8'],[str(python),'-m','pip','--isolated','install','--only-binary=:all:','--index-url','https://pypi.org/simple',url+'#sha256='+digest]]
            with (folder/'installation.log').open('w',encoding='utf-8') as log:
                for command in commands:
                    process=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=900,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    if process.returncode:raise ValueError('Open WebUI isolated installation failed; inspect installation.log')
        # Reuse an existing environment without modifying its installed packages.
        check=subprocess.run([str(python),'-I','-m','pip','check'],capture_output=True,text=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if check.returncode:
            atomic_json(folder/'integration-manifest.json',{'passed':False,'error':'Dependency check failed'})
            raise ValueError('Open WebUI dependency check failed; existing environments were not replaced')
        atomic_json(storage/'setup-job.json',{'state':'preparing','step':'validating','owner_pid':os.getpid()})
        with tempfile.TemporaryDirectory(prefix='probe-',dir=storage) as temporary:
            path=Path(temporary)/'probe.txt';path.write_text('Local document source citations remain readable.',encoding='utf-8')
            docx=Path(temporary)/'probe.docx'
            with zipfile.ZipFile(docx,'w') as archive:archive.writestr('word/document.xml','<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Local source citations remain readable.</w:t></w:r></w:p></w:body></w:document>')
            content=b'BT /F1 12 Tf 50 700 Td (Local source citations remain readable.) Tj ET'
            objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'\nendstream']
            pdf=b'%PDF-1.4\n';offsets=[0]
            for index,obj in enumerate(objects,1):offsets.append(len(pdf));pdf+=str(index).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
            xref=len(pdf);pdf+=b'xref\n0 6\n0000000000 65535 f \n'+b''.join(f'{i:010d} 00000 n \n'.encode() for i in offsets[1:])+f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
            (Path(temporary)/'probe.pdf').write_bytes(pdf)
            (Path(temporary)/'probe.csv').write_text('source,citation\nlocal,readable',encoding='utf-8')
            (Path(temporary)/'probe.json').write_text('{"source":"local","citation":"readable"}',encoding='utf-8')
            jobs={suffix:{'action':'extract','name':'probe.'+suffix,'mime':FORMATS['.'+suffix],'path':str(Path(temporary)/('probe.'+suffix))} for suffix in ('txt','docx','pdf','csv','json')}
            jobs['search']={'action':'search','query':'source citations','chunks':[{'text':'Local source citations remain readable.','page':1},{'text':'Penguins eat fish.','page':2}]}
            jobs['context']={'action':'context','messages':[{'role':'user','content':'hello'}]};jobs['device']={'action':'device'}
            try:proof=worker(root,{'action':'verify','jobs':jobs})
            except Exception:
                atomic_json(folder/'integration-manifest.json',{'passed':False,'error':'Native function validation failed'})
                raise
        if any(not proof[key]['chunks'][0]['text'].strip() for key in ('txt','docx','pdf','csv','json')) or proof['search']['matches'][0]['page']!=1 or proof['context']['estimated_tokens']<=0 or proof['device']['device']!='cpu':raise ValueError('Open WebUI internal function validation failed')
        atomic_json(folder/'integration-manifest.json',{'passed':True,'source_sha256':source_hash(root),'runtime_sha256':runtime_hash(root),'version':'0.12.0','device':'cpu','offline':True,'external_ui':False,'validated_at':time.time(),'validation':proof})
        atomic_json(storage/'setup-job.json',{'state':'prepared','step':'complete','finished_at':time.time(),'version':'0.12.0'})
    except Exception as error:
        if owned:atomic_json(storage/'setup-job.json',{'state':'error','error':str(error)[:1000],'finished_at':time.time()})
        raise
    finally:
        if 'process' in locals() and process.poll() is None:
            process.kill();process.communicate()
        if owned:
            try:
                if json.loads(lease.read_text(encoding='utf-8')).get('token')==token:lease.unlink()
            except (OSError,ValueError):pass
    return status(root)

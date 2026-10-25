"""Owned public model downloads, pinned to repository revision and file hashes."""
import copy,json,re,shutil,subprocess,sys,threading,uuid
from pathlib import Path,PurePosixPath
from serve.configuration import atomic_json

_lock=threading.RLock();_jobs={};_plans={};_children={}

def status(root):
    with _lock:return copy.deepcopy(_jobs.get(str(Path(root).resolve()),{'state':'idle'}))

def inspect(root,payload):
    repo=payload.get('repo');kind=payload.get('kind')
    if kind not in ('visual','controlnet','music','effects','magnet','watermark','mbd','codec24','adapter','embedding','style','jasco') or not isinstance(repo,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('Repository Hugging Face o tipo di modello non valido.')
    if kind=='effects' and repo!='facebook/audiogen-medium':raise ValueError('AudioGen usa soltanto la pubblicazione originale facebook/audiogen-medium.')
    if kind=='magnet' and repo not in ('facebook/audio-magnet-small','facebook/audio-magnet-medium','facebook/magnet-small-10secs','facebook/magnet-medium-10secs','facebook/magnet-small-30secs','facebook/magnet-medium-30secs'):raise ValueError('Choose an original Meta MAGNeT publication.')
    if kind=='watermark' and repo!='facebook/audioseal':raise ValueError('AudioSeal requires the original Meta publication.')
    if kind=='mbd' and repo!='facebook/multiband-diffusion':raise ValueError('Choose original Meta MultiBand Diffusion weights')
    if kind=='codec24' and repo!='facebook/encodec_24khz':raise ValueError('Choose the original Meta 24 kHz codec')
    from huggingface_hub import HfApi,get_token,get_hf_file_metadata,hf_hub_url
    if kind in ('style','jasco'):
        from serve.audiocraft_native import REPOSITORIES
        if repo not in REPOSITORIES[kind]:raise ValueError('Usa la pubblicazione Meta originale per '+kind)
    token=get_token()
    info=HfApi(token=token or False).model_info(repo,files_metadata=True,timeout=20)
    if info.gated:
        if not token:raise ValueError('Accesso approvato da Meta, ma Hugging Face non è collegato su questo PC. Esegui l’accesso locale e riprova; nessuna condizione viene accettata automaticamente.')
        try:get_hf_file_metadata(hf_hub_url(repo,'state_dict.bin',revision=info.sha),token=token,timeout=15)
        except Exception as error:raise ValueError('L’account Hugging Face locale non dispone ancora dell’accesso ai pesi richiesti.') from error
    if not re.fullmatch(r'[a-f0-9]{40}',info.sha or ''):raise ValueError('Revisione originale non verificabile.')
    files=[];total=0
    for row in info.siblings or []:
        path=PurePosixPath(row.rfilename)
        if path.is_absolute() or '..' in path.parts or '\\' in row.rfilename or re.search(r'[:<>"|?*\x00-\x1f]',row.rfilename):raise ValueError('Percorso repository non sicuro.')
        if any(part.startswith('.') for part in path.parts):continue
        if kind=='mbd' and row.rfilename not in ('mbd_comp_2.pt','mbd_comp_4.pt','mbd_comp_8.pt','README.md','LICENSE'):continue
        if kind=='watermark' and row.rfilename not in ('generator_base.pth','detector_base.pth','base.yaml','README.md','LICENSE'):continue
        if kind in ('effects','magnet','style','jasco') and row.rfilename not in ('state_dict.bin','compression_state_dict.bin','README.md','LICENSE'):continue
        if kind=='mbd' and path.suffix.lower()=='.pt':pass
        elif kind=='watermark' and path.suffix.lower() in ('.pth','.yaml'):pass
        elif kind in ('effects','magnet','style','jasco') and path.suffix.lower()=='.bin':pass
        elif path.suffix.lower() not in ('.safetensors','.json','.txt','.model','.md'):continue
        size=row.size
        if not isinstance(size,int) or size<0:raise ValueError('Dimensione del file non verificabile.')
        lfs=row.lfs;digest=lfs.sha256 if lfs else None
        if path.suffix in ('.safetensors','.bin','.pth','.pt') and not re.fullmatch(r'[a-f0-9]{64}',digest or ''):raise ValueError('Hash originale dei pesi non disponibile.')
        total+=size;files.append({'path':row.rfilename,'bytes':size,'sha256':digest})
    if not files or len(files)>4096 or not 0<total<=20*1024**3 or not (all(any(row['path']==name for row in files) for name in ('state_dict.bin','compression_state_dict.bin')) if kind in ('effects','magnet','style','jasco') else all(any(row['path']==name for row in files) for name in ('generator_base.pth','detector_base.pth')) if kind=='watermark' else all(any(row['path']==name for row in files) for name in ('mbd_comp_2.pt','mbd_comp_4.pt','mbd_comp_8.pt')) if kind=='mbd' else any(row['path'].endswith('.safetensors') for row in files)):raise ValueError('Serve un repository Safetensors fino a 20 GiB/4096 file.')
    if kind=='watermark':
        import urllib.request,base64,hashlib
        revision='896ec7c47f5e5d1e5aa1e4b260c4405328bf009d'
        url='https://api.github.com/repos/facebookresearch/audiocraft/contents/config/model/watermark/default.yaml?ref='+revision
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Strata'}),timeout=20) as response:asset=json.loads(response.read(65536))
        content=base64.b64decode(asset['content'])
        if not 0<len(content)<=32768 or hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()!=asset['sha']:raise ValueError('Original AudioSeal configuration identity mismatch')
        files.append({'path':'base.yaml','bytes':len(content),'sha256':hashlib.sha256(content).hexdigest(),'inline_base64':base64.b64encode(content).decode(),'source':url,'git_blob_sha1':asset['sha']});total+=len(content)
    if kind=='jasco':
        import urllib.request,base64,hashlib
        revision='896ec7c47f5e5d1e5aa1e4b260c4405328bf009d'
        url='https://api.github.com/repos/facebookresearch/audiocraft/contents/assets/chord_to_index_mapping.pkl?ref='+revision
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Strata'}),timeout=20) as response:asset=json.loads(response.read(1024*1024))
        content=base64.b64decode(asset['content'])
        if not 0<len(content)<=512*1024 or hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()!=asset['sha']:raise ValueError('Identità della mappa accordi originale non verificata')
        files.append({'path':'chord_to_index_mapping.pkl','bytes':len(content),'sha256':hashlib.sha256(content).hexdigest(),'inline_base64':base64.b64encode(content).decode(),'source':url,'git_blob_sha1':asset['sha']});total+=len(content)
    license_value=(info.card_data or {}).get('license')
    plan={'id':uuid.uuid4().hex,'repo':repo,'kind':kind,'revision':info.sha,'bytes':total,'files':files,'license':license_value,'source':'https://huggingface.co/'+repo,'requires_auth':bool(info.gated)}
    with _lock:
        while len(_plans)>=32:_plans.pop(next(iter(_plans)))
        _plans[plan['id']]={**plan,'root':str(Path(root).resolve())}
    return {key:value for key,value in plan.items() if key!='files'}

def start(root,payload):
    root=Path(root).resolve();key=str(root)
    with _lock:
        plan=_plans.get(payload.get('plan_id'))
        if not plan or plan['root']!=key:raise ValueError('Controlla prima repository, licenza e dimensioni dalla stessa app.')
        if _jobs.get(key,{}).get('state') in ('downloading','verifying'):raise ValueError('Preparazione modelli già in corso.')
        from serve.studio_model_import import status as import_status
        if import_status(root).get('state')=='copying':raise ValueError('Completa prima la copia locale nello Studio.')
        if shutil.disk_usage(root).free<plan['bytes']+1024**3:raise ValueError('Spazio insufficiente per il modello e 1 GiB di riserva.')
        folder=root/'output/studio-model-downloads'/plan['id']
        if not folder.resolve().is_relative_to(root):raise ValueError('Cartella download non gestita da Strata.')
        folder.mkdir(parents=True,exist_ok=False);atomic_json(folder/'plan.json',plan)
        _jobs[key]={'state':'downloading','repo':plan['repo'],'kind':plan['kind'],'total':plan['bytes'],'bytes':0,'license':plan['license']}
    threading.Thread(target=_run,args=(root,folder),daemon=True,name='studio-model-download').start()
    return status(root)

def cancel(root):
    key=str(Path(root).resolve())
    with _lock:
        job=_jobs.get(key,{});active=job.get('state') in ('downloading','verifying')
        if active:
            job['cancel_requested']=True
            child=_children.get(key)
            if child and child.poll() is None:child.terminate()
    return {'cancellation_requested':active}

def _run(root,folder):
    key=str(root)
    try:
        with (folder/'download.log').open('w',encoding='utf-8') as log:
            child=subprocess.Popen([sys.executable,'-I',str(root/'tools/download_studio_model.py'),str(folder/'plan.json')],cwd=root,stdout=subprocess.PIPE,stderr=log,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            from serve.winjob import contain
            contain(child)
            with _lock:
                _children[key]=child
                if _jobs[key].get('cancel_requested'):child.terminate()
            for line in child.stdout:
                if len(line)>8192 or not line.startswith('STRATA_DOWNLOAD:'):continue
                value=json.loads(line.partition(':')[2])
                with _lock:_jobs[key].update(value)
            code=child.wait()
        with _lock:
            if _jobs[key].get('cancel_requested'):_jobs[key].update(state='cancelled',error='Download annullato; nessun modello parziale registrato.')
            elif code or _jobs[key].get('state')!='complete':_jobs[key].update(state='failed',error=(folder/'download.log').read_text(encoding='utf-8',errors='replace')[-1200:] or 'Download non completato.')
    except Exception as error:
        with _lock:_jobs[key].update(state='failed',error=str(error)[:800])
    finally:
        if 'child' in locals() and child.poll() is None:child.kill();child.wait()
        with _lock:_children.pop(key,None)

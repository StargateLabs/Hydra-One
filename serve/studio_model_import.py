"""Copy local Studio models into managed storage without running their code."""
import copy,hashlib,json,re,shutil,threading,uuid
from pathlib import Path

_lock=threading.RLock()
_jobs={}
LIMIT=20*1024**3

def status(root):
    with _lock:return copy.deepcopy(_jobs.get(str(Path(root).resolve()),{'state':'idle'}))

def validate(folder,kind):
    def config(name):
        path=folder/name
        if not path.is_file() or path.stat().st_size>1024**2:raise ValueError('Configurazione locale mancante o troppo grande: '+name)
        return json.loads(path.read_text(encoding='utf-8'))
    if kind=='music':
        if config('config.json').get('model_type') not in ('musicgen','musicgen_melody') or not (folder/'tokenizer_config.json').is_file() or not list(folder.glob('*.safetensors')):raise ValueError('Serve un modello MusicGen/Melody Safetensors completo.')
    elif kind in ('style','jasco'):
        from serve.audiocraft_native import model_contract
        model_contract(folder,kind)
    elif kind in ('effects','magnet'):
        spec=config('audiogen.json')
        allowed=('facebook/audiogen-medium',) if kind=='effects' else ('facebook/audio-magnet-small','facebook/audio-magnet-medium','facebook/magnet-small-10secs','facebook/magnet-medium-10secs','facebook/magnet-small-30secs','facebook/magnet-medium-30secs')
        if spec.get('repository') not in allowed or not re.fullmatch('[a-f0-9]{40}',spec.get('revision','')):raise ValueError('Serve la pubblicazione AudioGen originale con revisione verificabile.')
        for name in ('state_dict.bin','compression_state_dict.bin'):
            path=folder/name
            if not path.is_file() or not re.fullmatch('[a-f0-9]{64}',spec.get('sha256',{}).get(name,'')):raise ValueError('Pesi AudioGen o hash originali mancanti.')
    elif kind=='watermark':
        spec=config('audiogen.json')
        if spec.get('repository')!='facebook/audioseal' or not re.fullmatch('[a-f0-9]{40}',spec.get('revision','')):raise ValueError('Original AudioSeal revision required')
        for name in ('generator_base.pth','detector_base.pth','base.yaml'):
            if not (folder/name).is_file() or not re.fullmatch('[a-f0-9]{64}',spec.get('sha256',{}).get(name,'')):raise ValueError('AudioSeal weights, configuration and hashes required')
    elif kind=='mbd':
        spec=config('audiogen.json')
        if spec.get('repository')!='facebook/multiband-diffusion' or not re.fullmatch('[a-f0-9]{40}',spec.get('revision','')):raise ValueError('Original MBD revision required')
        for name in ('mbd_comp_2.pt','mbd_comp_4.pt','mbd_comp_8.pt'):
            if not (folder/name).is_file() or not re.fullmatch('[a-f0-9]{64}',spec.get('sha256',{}).get(name,'')):raise ValueError('Original MBD weights and hashes required')
    elif kind=='codec24':
        spec=config('config.json')
        if spec.get('model_type')!='encodec' or spec.get('sampling_rate')!=24000 or spec.get('audio_channels')!=1 or not (folder/'model.safetensors').is_file():raise ValueError('Original mono 24 kHz EnCodec Safetensors required')
    elif kind=='visual':
        from serve.local_visual_generation import FAMILIES
        family=config('model_index.json').get('_class_name')
        if family not in FAMILIES or not all(list((folder/component).glob('*.safetensors')) for component in (('unet','vae','image_encoder') if family=='StableVideoDiffusionPipeline' else ('unet','vae','text_encoder'))):raise ValueError('Serve una pipeline immagini/video Safetensors supportata e completa.')
    elif kind=='controlnet':
        if config('config.json').get('_class_name')!='ControlNetModel' or not list(folder.glob('*.safetensors')):raise ValueError('Serve un modello ControlNet Safetensors completo.')
    elif kind=='adapter':
        weights=list(folder.glob('*.safetensors'))
        if not weights or any(not 0<path.stat().st_size<=256*1024**2 for path in weights):raise ValueError('Serve una cartella con adattatori LoRA Safetensors fino a 256 MiB per file.')
    else:raise ValueError('Tipo di modello non supportato.')

def start(root,payload):
    root=Path(root).resolve();key=str(root);raw=payload.get('path');kind=payload.get('kind')
    from serve.studio_model_download import status as download_status
    if download_status(root).get('state') in ('downloading','verifying'):raise ValueError('Completa prima il download dei modelli nello Studio.')
    if not isinstance(raw,str) or not raw.strip() or len(raw)>4096:raise ValueError('Indica la cartella locale del modello.')
    source=Path(raw.strip())
    if not source.is_absolute() or str(source).startswith(('\\\\','//')) or not source.is_dir() or source.is_symlink():raise ValueError('Serve una cartella locale assoluta, senza collegamenti.')
    source=source.resolve();validate(source,kind)
    destination=root/({'style':'models/audio/style','jasco':'models/audio/jasco','music':'models/audio/music','effects':'models/audio/effects','magnet':'models/audio/magnet','watermark':'models/audio/watermark','mbd':'models/audio/mbd','codec24':'models/audio/codec24','visual':'models/visual','controlnet':'models/controlnet','adapter':'models/image-adapters'}[kind])
    if not destination.resolve().is_relative_to(root):raise ValueError('Destinazione non gestita da Strata.')
    if source.is_relative_to(destination.resolve()):
        with _lock:
            if _jobs.get(key,{}).get('state')=='copying':raise ValueError('Importazione Studio già in corso.')
            _jobs[key]={'state':'complete','kind':kind,'name':source.name,'path':str(source),'reused':True,'original_retained':True}
        return status(root)
    if destination.resolve().is_relative_to(source):raise ValueError('Origine e destinazione devono essere distinte.')
    entries=[];size=0
    for path in source.rglob('*'):
        if len(entries)>=4096 or path.is_symlink():raise ValueError('Massimo 4096 elementi; collegamenti non ammessi.')
        entries.append(path)
        if path.is_file():size+=path.stat().st_size
        if size>LIMIT:raise ValueError('Modello oltre il limite di 20 GiB.')
    if not size or shutil.disk_usage(root).free<size+1024**3:raise ValueError('Spazio insufficiente: serve una copia del modello e 1 GiB di riserva.')
    with _lock:
        if _jobs.get(key,{}).get('state')=='copying':raise ValueError('Importazione Studio già in corso.')
        _jobs[key]={'state':'copying','kind':kind,'name':source.name,'bytes':0,'total':size}
    threading.Thread(target=_copy,args=(root,source,destination,kind,entries,size),daemon=True,name='studio-model-import').start()
    return status(root)

def cancel(root):
    key=str(Path(root).resolve())
    with _lock:
        job=_jobs.get(key,{})
        requested=job.get('state')=='copying'
        if requested:job['cancel_requested']=True
    return {'cancellation_requested':requested}

def _copy(root,source,destination,kind,entries,size):
    key=str(root);staging=root/'output/studio-model-imports'/uuid.uuid4().hex
    try:
        if not staging.resolve().is_relative_to(root) or staging.is_symlink():raise ValueError('Cartella temporanea non gestita da Strata.')
        staging.mkdir(parents=True);copied=0;hashes={}
        for path in entries:
            if not path.is_file():continue
            if path.is_symlink() or not path.resolve().is_relative_to(source):raise ValueError('Origine cambiata durante la copia.')
            relative=path.relative_to(source);target=staging/relative;target.parent.mkdir(parents=True,exist_ok=True);digest=hashlib.sha256()
            with path.open('rb') as original,target.open('wb') as output:
                while chunk:=original.read(1024*1024):
                    with _lock:
                        if _jobs[key].get('cancel_requested'):raise InterruptedError('Importazione annullata; originale conservato.')
                    copied+=len(chunk)
                    if copied>size:raise ValueError('Dimensioni origine cambiate durante la copia.')
                    output.write(chunk);digest.update(chunk)
                    with _lock:_jobs[key]['bytes']=copied
            hashes[relative.as_posix()]=digest.hexdigest()
        if copied!=size:raise ValueError('Dimensioni origine cambiate durante la copia.')
        validate(staging,kind)
        destination.mkdir(parents=True,exist_ok=True)
        if destination.is_symlink() or not destination.resolve().is_relative_to(root):raise ValueError('Destinazione non gestita da Strata.')
        name=re.sub(r'[^A-Za-z0-9._-]','-',source.name).strip('.-')[:80] or 'model'
        final=destination/(name+'-'+uuid.uuid4().hex[:8])
        from serve.configuration import atomic_json
        atomic_json(staging/'strata-import-manifest.json',{'source':str(source),'kind':kind,'bytes':copied,'sha256':hashes,'original_retained':True})
        with _lock:
            if _jobs[key].get('cancel_requested'):raise InterruptedError('Importazione annullata; originale conservato.')
            staging.rename(final);_jobs[key].update(state='complete',path=str(final),original_retained=True)
    except InterruptedError as error:
        with _lock:_jobs[key].update(state='cancelled',error=str(error))
    except Exception as error:
        with _lock:_jobs[key].update(state='failed',error=str(error)[:800])
    finally:
        if staging.exists() and not staging.is_symlink() and staging.resolve().is_relative_to(root/'output/studio-model-imports'):shutil.rmtree(staging)

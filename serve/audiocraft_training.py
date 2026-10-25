"""Owned AudioCraft datasets and bounded native CPU training requests."""
import hashlib,io,json,shutil,uuid,wave
from pathlib import Path
from serve.configuration import atomic_json
from serve.audio_library import AudioLibrary

REVISION='896ec7c'
def source(root):
    folder=Path(root)/'output/updates/audiocraft-cache/git-v0/checkouts/ea1a06374650c65b'/REVISION
    if not (folder/'audiocraft/train.py').is_file() or not (folder/'config/solver/musicgen/debug.yaml').is_file():raise ValueError('Sorgente AudioCraft originale completo non disponibile')
    return folder

def prepare_dataset(root,payload):
    root=Path(root).resolve();items=payload.get('items')
    if not isinstance(items,list) or not 2<=len(items)<=100:raise ValueError('Seleziona da 2 a 100 audio distinti')
    library=AudioLibrary(root);prepared=[];seen=set();size=0
    for item in items:
        if not isinstance(item,dict) or not isinstance(item.get('description'),str) or not 1<=len(item['description'].strip())<=2000:raise ValueError('Ogni audio richiede una descrizione di 1–2000 caratteri')
        raw=library.read(item.get('id'));digest=hashlib.sha256(raw).hexdigest();size+=len(raw)
        if digest in seen:raise ValueError('Audio duplicati: training e validazione devono restare distinti')
        if size>512*1024**2:raise ValueError('Dataset oltre 512 MiB')
        seen.add(digest)
        with wave.open(io.BytesIO(raw)) as w:
            duration=w.getnframes()/w.getframerate();rate=w.getframerate()
            if not 1<=duration<=600 or w.getnchannels() not in (1,2):raise ValueError('Audio WAV mono/stereo di 1–600 secondi richiesto')
        prepared.append((item,raw,digest,duration,rate))
    folder=root/'output/audio-training-datasets'/uuid.uuid4().hex;folder.mkdir(parents=True)
    validation=max(1,len(prepared)//5);proof=[]
    for index,(item,raw,digest,duration,rate) in enumerate(prepared):
        split='valid' if index>=len(prepared)-validation else 'train';assets=folder/split;assets.mkdir(exist_ok=True)
        path=assets/(str(index)+'.wav');path.write_bytes(raw);atomic_json(path.with_suffix('.json'),{'description':item['description'].strip()})
        with (assets/'data.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps({'path':str(path),'duration':duration,'sample_rate':rate})+'\n')
        proof.append({'id':item['id'],'sha256':digest,'caption_sha256':hashlib.sha256(path.with_suffix('.json').read_bytes()).hexdigest(),'path':str(path),'duration':duration,'split':split})
    row={'version':1,'items':proof,'train_rows':len(prepared)-validation,'validation_rows':validation,'minimum_seconds':min(r[3] for r in prepared),'split_policy':'ordine selezionato; ultimo 20 percento in validazione; hash distinti','manifests':{split:hashlib.sha256((folder/split/'data.jsonl').read_bytes()).hexdigest() for split in ('train','valid')}}
    atomic_json(folder/'dataset.json',row)
    return dict(dataset=str(folder/'dataset.json'),train_rows=row['train_rows'],validation_rows=validation)

def dataset(root,path):
    path=Path(path).resolve();base=(Path(root)/'output/audio-training-datasets').resolve()
    if not path.is_relative_to(base) or path.name!='dataset.json' or path.is_symlink() or not path.is_file() or path.stat().st_size>1024**2:raise ValueError('Scegli un dataset audio preparato dalla nostra interfaccia')
    row=json.loads(path.read_text(encoding='utf-8'))
    for item in row['items']:
        audio=Path(item['path'])
        if audio.is_symlink() or not audio.resolve().is_relative_to(path.parent) or hashlib.sha256(audio.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Dataset audio modificato')
        caption=audio.with_suffix('.json')
        if caption.is_symlink() or hashlib.sha256(caption.read_bytes()).hexdigest()!=item['caption_sha256']:raise ValueError('Descrizioni del dataset modificate')
    for split,digest in row.get('manifests',{}).items():
        if split not in ('train','valid') or hashlib.sha256((path.parent/split/'data.jsonl').read_bytes()).hexdigest()!=digest:raise ValueError('Manifesto del dataset modificato')
    return path,row

def preflight(root,payload):
    from serve.audiocraft_setup import selected_python
    from serve.audiocraft_conditioning import selected_cache
    root=Path(root);python=selected_python(root)
    if not python:raise ValueError('Prepara AudioCraft esteso prima del training')
    path,row=dataset(root,payload.get('dataset',''));source_path=source(root);cache=selected_cache(root,'t5-base')
    options={}
    for key,default,low,high in [('steps',1,1,1000),('epochs',1,1,50),('batch',1,1,4),('seconds',1,1,30)]:
        value=payload.get(key,default)
        if type(value) is not int or not low<=value<=high:raise ValueError('Parametro audio '+key+' fuori intervallo')
        options[key]=value
    if options['seconds']>row['minimum_seconds']:raise ValueError('La durata del segmento supera il campione piu breve')
    recipe=payload.get('recipe','debug')
    if recipe not in ('debug','musicgen'):raise ValueError('Ricetta audio non supportata')
    model=None
    if recipe=='musicgen':
        model=Path(payload.get('model','')).resolve();bases=[root/'models/audio',root.parent/'Strata-data/models/audio']
        if not any(model.is_relative_to(b.resolve()) for b in bases) or not all((model/n).is_file() for n in ('state_dict.bin','compression_state_dict.bin')):raise ValueError('Checkpoint AudioCraft MusicGen locale completo richiesto')
        if 'style' in str(model).lower():raise ValueError('Training Style richiede una ricetta con metadati di stile: non usare la ricetta MusicGen testuale')
    import psutil
    reserve=4*1024**3;weight=(model/'state_dict.bin').stat().st_size if model else 64*1024**2;estimated=weight*10+reserve
    ready=psutil.virtual_memory().available>=estimated
    return {'ready':ready,'reasons':[] if ready else ['RAM disponibile insufficiente con riserva di 4 GiB'],'runner':'audiocraft','device':'cpu','recipe':recipe,'dataset':str(path),'python':str(python),'source':str(source_path),'cache':str(cache),'model':str(model) if model else None,'options':options,'train_rows':row['train_rows'],'validation_rows':row['validation_rows'],'estimated_ram_bytes':estimated,'scope':'Trainer originale; debug verifica la pipeline e non produce un modello musicale di qualita'}

def start(manager,payload):
    import os,subprocess,threading,time
    from serve.gpu_lease import GpuLease
    checked=preflight(manager.root,payload)
    if not checked['ready']:raise ValueError('; '.join(checked['reasons']))
    folder=manager.root/'output/training'/uuid.uuid4().hex;folder.mkdir(parents=True);atomic_json(folder/'request.json',checked)
    lease=GpuLease(manager.root,'audiocraft-training-cpu');lease.acquire();log=folder/'worker.log'
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
    try:
        with log.open('wb') as stream:manager.process=subprocess.Popen([checked['python'],'-u',str(manager.root/'tools/train_audiocraft_native.py'),str(folder/'request.json')],cwd=manager.root,env=env,stdout=stream,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except BaseException:lease.release();raise
    manager.lease=lease;manager.state={'status':'running','device':'cpu','runner':'audiocraft','output':str(folder),'log':str(log),'started_at':time.time(),'steps':checked['options']['steps'],'model':checked['model'] or 'AudioCraft debug','options':checked}
    threading.Thread(target=manager._watch,args=(manager.process,),daemon=True).start()
    return manager.status()

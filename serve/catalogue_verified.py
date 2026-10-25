"""Hugging Face discovery with a fail-closed Strata/HIP/host compatibility gate."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import struct
import threading
import time
import urllib.parse
import urllib.request
from serve import catalogue as legacy
from serve.model_inventory import inventory

CURATED=[dict(repo='shefowl/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-Hybrid-GGUF',quant='Q2_0')]
SUPPORTED={'Q2_0','IQ2_XS','IQ3_XXS','IQ3_S','IQ1_M'}
_cache={};_lock=threading.Lock()

def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Strata-verified-catalogue'}),timeout=20) as response:
        return json.load(response)

def parse_metadata(buf,with_tensors=False):
    if len(buf)<24 or buf[:4]!=b'GGUF':raise ValueError('Intestazione GGUF non valida')
    version,tensors,count=struct.unpack_from('<IQQ',buf,4)
    if version not in (2,3) or tensors<1 or tensors>20000 or count>100000:raise ValueError('Intestazione GGUF non supportata')
    at=24;meta={};required={'general.architecture','qwen4exp.block_count','qwen4exp.expert_count','qwen4exp.embedding_length'}
    def need(size):
        if size<0 or at+size>len(buf):raise EOFError('Intestazione incompleta')
    def scalar(fmt):
        nonlocal at
        size=struct.calcsize(fmt);need(size);value=struct.unpack_from(fmt,buf,at)[0];at+=size;return value
    def string():
        nonlocal at
        size=scalar('<Q');need(size);value=buf[at:at+size].decode('utf-8');at+=size;return value
    for _ in range(count):
        key=string();kind=scalar('<I')
        if kind==8:value=string()
        elif kind==9:
            subtype=scalar('<I');length=scalar('<Q')
            if length>4000000:raise ValueError('Array GGUF non valido')
            if subtype==8:
                for _ in range(length):string()
            elif subtype in legacy._FIXED:
                size=length*legacy._FIXED[subtype];need(size);at+=size
            else:raise ValueError('Tipo GGUF non supportato')
            value=None
        elif kind in legacy._T_FMT:value=scalar(legacy._T_FMT[kind])
        else:raise ValueError('Tipo GGUF non supportato')
        if value is not None:meta[key]=value
        if meta.get('general.architecture') not in (None,'qwen4exp'):return meta
        if not with_tensors and required<=meta.keys():return meta
    if not with_tensors and not required<=meta.keys():raise ValueError('Geometria del modello non verificabile')
    if with_tensors:
        records=[]
        for _ in range(tensors):
            name=string();dimensions=scalar('<I')
            if not 1<=dimensions<=4:raise ValueError('Dimensioni tensoriali non supportate')
            shape=[scalar('<Q') for _ in range(dimensions)]
            if any(d<1 or d>2**32 for d in shape):raise ValueError('Forma tensoriale non valida')
            kind=scalar('<I');offset=scalar('<Q');records.append(dict(name=name,shape=shape,type=kind,offset=offset))
        alignment=meta.get('general.alignment',32)
        if not isinstance(alignment,int) or alignment<1 or alignment>4096 or alignment&(alignment-1):raise ValueError('Allineamento GGUF non valido')
        meta['__data_start']=(at+alignment-1)//alignment*alignment
        meta['__tensors']=records
    return meta

def header(repo,revision,path):
    url=f'https://huggingface.co/{repo}/resolve/{revision}/{urllib.parse.quote(path,safe="/")}'
    for size in (512<<10,4<<20,16<<20):
        try:return parse_metadata(legacy._range_bytes(url,size,20),with_tensors=True)
        except EOFError:continue
    raise ValueError('Intestazione oltre il limite di verifica')

def complete_group(items):
    shards=[re.search(r'-(\d{5})-of-(\d{5})\.gguf$',i['path'],re.IGNORECASE) for i in items]
    if not any(shards):return len(items)==1
    if not all(shards):return False
    totals={int(m.group(2)) for m in shards}
    return len(totals)==1 and len(items)==next(iter(totals)) and {int(m.group(1)) for m in shards}==set(range(1,len(items)+1))

def repo_info(repo):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo or '') or '..' in repo:raise ValueError('Repository non valido')
    with _lock:cached=_cache.get(repo)
    if cached and time.time()-cached['at']<1800:return cached
    info=get_json('https://huggingface.co/api/models/'+repo+'?blobs=true')
    revision=info.get('sha')
    if not isinstance(revision,str) or not re.fullmatch(r'[a-f0-9]{40}',revision):raise ValueError('Revisione non verificabile')
    files=[]
    for item in info.get('siblings',[]):
        name=item.get('rfilename','')
        if '..' in Path(name).parts or Path(name).is_absolute():continue
        size=item.get('size') or item.get('lfs',{}).get('size')
        files.append({'path':name,'size':size,'type':'file','sha256':item.get('lfs',{}).get('sha256')})
    grouped={}
    for item in files:
        name=item['path']
        if not name.lower().endswith('.gguf') or any(s in name.lower() for s in ('mmproj','/mtp','mtp/')):continue
        match=re.search(r'((?:UD-)?(?:IQ|Q)\d[A-Z0-9_]*)(?:-\d{5}-of-\d{5})?\.gguf$',name,re.IGNORECASE)
        quant=match.group(1).upper() if match else None
        if quant in SUPPORTED:grouped.setdefault(quant,[]).append(item)
    grouped={quant:items for quant,items in grouped.items() if complete_group(items)}
    result=dict(at=time.time(),revision=revision,groups=grouped,headers={},layouts={},author=info.get('author') or repo.split('/')[0])
    with _lock:_cache[repo]=result
    return result

def validate_layout(headers,experts,sizes=None):
    import math
    records={}
    if len(headers)>1 and ({m.get('split.no') for m in headers}!=set(range(len(headers))) or any(m.get('split.count')!=len(headers) for m in headers)):
        raise ValueError('Identità degli shard GGUF incoerente')
    if sizes is not None:
        import math
        from tools.gguf_reader import BLOCK_GEOMETRY,GGML_TYPES
        for meta,size in zip(headers,sizes):
            for tensor in meta.get('__tensors',[]):
                block=BLOCK_GEOMETRY.get(GGML_TYPES.get(tensor['type']))
                elements=math.prod(tensor['shape'])
                if not block or elements%block[0] or meta['__data_start']+tensor['offset']+elements//block[0]*block[1]>size:raise ValueError('Payload tensoriale troncato o non supportato')
    for meta in headers:
        if meta.get('general.architecture') not in (None,'qwen4exp'):raise ValueError('Architettura degli shard non coerente')
        for tensor in meta.get('__tensors',[]):
            name=tensor['name']
            if name in records:raise ValueError('Tensore duplicato tra shard')
            records[name]=tensor
    if not records:raise ValueError('Layout tensoriale non verificato')
    types={16,17,18,19,20,21,22,29,42}
    for layer in range(48):
        router=records.get(f'blk.{layer}.ffn_gate_inp.weight')
        if not router or router['shape']!=[2560,experts]:raise ValueError('Router non compatibile o pruning non uniforme')
        roles=[]
        for role in ('gate','up','down'):
            tensor=records.get(f'blk.{layer}.ffn_{role}_exps.weight')
            expected=[640,2560,experts] if role=='down' else [2560,640,experts]
            if not tensor or tensor['shape']!=expected or tensor['type'] not in types:raise ValueError('Forma o formato esperti non supportato dal profilo HIP')
            roles.append(tensor)
        if roles[0]['type']!=roles[1]['type']:raise ValueError('Formati gate/up differenti')
    ple=records.get('per_layer_token_embd.weight')
    if not ple or ple['type']!=20:raise ValueError('Formato PLE non validato per questo catalogo')
    known_types={0,1,2,3,6,7,8,10,11,12,13,14,16,17,18,19,20,21,22,23,29,30,42}
    if any(t['type'] not in known_types for t in records.values()):raise ValueError('Codifica tensoriale non supportata')
    return dict(tensors=len(records),expert_tensors=144,experts_per_layer=experts,core_parameters=sum(math.prod(t['shape']) for name,t in records.items() if name!='per_layer_token_embd.weight' and not name.startswith('mtp.')),checked=True)

def fit_host(quant,size,host,backend,installed=False,family='custom'):
    requirement=legacy.HOST_TABLE.get(quant)
    if quant not in SUPPORTED or not requirement:return False,'Formato non verificato per questo backend'
    if backend!='hip':return False,'Questo catalogo richiede il backend HIP verificato'
    if quant=='Q2_0' and family=='swift':return False,'Pack Swift Q2_0 non supportato'
    ram=host.get('ram_total_gib');vram=host.get('vram_total_gib')
    if ram is None or vram is None:return False,'Risorse della macchina non verificabili'
    if ram<requirement['ram_gb'] or vram<8:return False,'RAM o VRAM sotto i requisiti'
    if host.get('ram_free_gib') is None or host['ram_free_gib']<8:return False,'Margine RAM insufficiente'
    if not isinstance(size,(int,float)) or size<=0:return False,'Dimensione del download non verificabile'
    if size>requirement['download_gb']*1.3:return False,'Checkpoint oltre il profilo di memoria verificato'
    if not installed and legacy.space_needed(size)>host.get('free_gib',0):return False,'Spazio disco insufficiente'
    return True,'Architettura, formato HIP e requisiti host verificati'

def inspect(repo,quant,host,backend,root):
    info=repo_info(repo);group=info['groups'].get(quant,[])
    if not group:raise ValueError('Quantizzazione GGUF non disponibile o non supportata')
    if any(not isinstance(f.get('size'),int) or f['size']<=0 for f in group):raise ValueError('Dimensioni dei file non verificate')
    if any(not isinstance(f.get('sha256'),str) or not re.fullmatch(r'[a-f0-9]{64}',f['sha256']) for f in group):raise ValueError('Hash SHA256 dei pesi non verificabile')
    shard=legacy._first_shard(group,quant)
    with _lock:meta=info['headers'].get(quant)
    if meta is None:
        meta=header(repo,info['revision'],shard['path'])
        with _lock:info['headers'][quant]=meta
    geometry=(meta.get('general.architecture'),meta.get('qwen4exp.block_count'),meta.get('qwen4exp.embedding_length'),meta.get('qwen4exp.expert_count'))
    if geometry[:3]!=('qwen4exp',48,2560) or geometry[3] not in (256,512):raise ValueError('Architettura o geometria non supportata da Strata')
    layout=info.setdefault('layouts',{}).get(quant)
    if layout is None:
        all_headers=[meta]+[header(repo,info['revision'],f['path']) for f in group if f['path']!=shard['path']]
        layout=validate_layout(all_headers,geometry[3],[shard['size']]+[f['size'] for f in group if f['path']!=shard['path']]);info['layouts'][quant]=layout
    family=next((e['family'] for e in legacy.OFFICIAL if e['repo'].lower()==repo.lower()),'custom')
    if family=='unsloth':raise ValueError('Quantizzazioni dinamiche non validate per il backend HIP corrente')
    key=legacy.key_for(repo,quant,family) if family!='custom' else 'hf_'+hashlib.sha256(repo.encode()).hexdigest()[:8]+'_'+quant.lower()
    local=next((m for m in inventory(root) if m['key']==key),None);installed=bool(local and local['ready'])
    size=round(sum(f['size'] for f in group)/2**30,2)
    ok,why=fit_host(quant,size,host,backend,installed,family)
    if not ok:raise ValueError(why)
    return dict(repo=repo,quant=quant,dir=quant,key=key,title=meta.get('general.name') or repo.split('/')[-1],author=info['author'],
        revision=info['revision'],architecture=geometry[0],layers=geometry[1],experts=geometry[3],download_gib=size,download_bytes=sum(f['size'] for f in group),
        compatible=True,verified=True,layout=layout,on_disk=installed,files=[f['path'] for f in group],file_metadata=[dict(path=f['path'],bytes=f['size'],sha256=f.get('sha256')) for f in group],
        fit=dict(level='piena',ram_gb=legacy.HOST_TABLE[quant]['ram_gb'],host=host,estimated=False,why=why))

def search(query,host,backend,root):
    query=(query or 'Qwen3.8-Flash-Next').strip()[:100]
    found=get_json('https://huggingface.co/api/models?'+urllib.parse.urlencode(dict(search=query,filter='gguf',limit=12,sort='downloads',direction=-1)))
    repos=[row['id'] for row in found if isinstance(row.get('id'),str)]
    if query.lower() in ('qwen3.8-flash-next','qwen3.8'):
        repos=list(dict.fromkeys([e['repo'] for e in legacy.OFFICIAL]+[e['repo'] for e in CURATED]+repos))[:12]
    rejected=[]
    installed_keys={m['key'] for m in inventory(root) if m['ready']}
    def check(repo):
        entries=[]
        try:
            info=repo_info(repo)
            for quant in ('IQ3_XXS','IQ2_XS','Q2_0','IQ3_S','IQ1_M'):
                if quant not in info['groups']:continue
                # Avoid header reads for formats that cannot fit this host.
                size=sum(f.get('size') or 0 for f in info['groups'][quant])/2**30
                family=next((e['family'] for e in legacy.OFFICIAL if e['repo'].lower()==repo.lower()),'custom')
                key=legacy.key_for(repo,quant,family) if family!='custom' else 'hf_'+hashlib.sha256(repo.encode()).hexdigest()[:8]+'_'+quant.lower()
                if not fit_host(quant,size,host,backend,key in installed_keys,family)[0]:continue
                try:entries.append(inspect(repo,quant,host,backend,root))
                except (OSError,ValueError,EOFError,struct.error) as exc:rejected.append({'repo':repo,'reason':str(exc)[:160]})
        except (OSError,ValueError) as exc:rejected.append({'repo':repo,'reason':str(exc)[:160]})
        return entries
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        entries=[entry for batch in pool.map(check,repos) for entry in batch]
    entries.sort(key=lambda e:(not e['on_disk'],e['quant']!='IQ3_XXS',e['download_gib']))
    return dict(query=query,results=entries,checked_repositories=len(repos),excluded=len(rejected),checked_at=time.time(),host=host,backend=backend)

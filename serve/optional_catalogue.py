"""Public GGUF catalogue for the installed llama.cpp runtime; no remote Python code."""

import copy

import hashlib

import json

import os

import re

import shutil

import threading

import time

import urllib.parse

import urllib.request

import uuid

from concurrent.futures import ThreadPoolExecutor

from pathlib import Path

from functools import lru_cache

from serve.catalogue import host, read_gguf_header



CATEGORIES={'chat','code','reasoning','compact','all'}



ARCHITECTURES={'llama','qwen2','qwen3','qwen3moe','minicpm','minicpm3','gemma','gemma2','gemma3','phi2','phi3','starcoder2','smollm3','spark2_5','qwen35','qwen35moe','gpt-oss','glm4'}



def model_category(repo,metadata=None):

    name=repo.lower()

    if re.search(r'coder|coding|codegen|devstral|starcoder|code-',name):return 'code'

    if re.search(r'reason|deepseek-r1|qwq|qvq',name):return 'reasoning'

    size=(metadata or {}).get('general.parameter_count')

    if type(size) in (int,float) and size<=4*10**9:return 'compact'

    if re.search(r'(?:^|[-_])(?:0[.p]\d+|[1234](?:[.p]\d+)?)[bB](?:[-_]|$)',repo):return 'compact'

    return 'chat'



@lru_cache(maxsize=128)

def model_card_sections(text):
    """Extract bounded source sections; do not infer capabilities from prose."""
    if not isinstance(text,str):return []
    sections=[];heading='';lines=[];fenced=False
    def append():
        content='\n'.join(lines).strip()
        if heading and content:sections.append(dict(title=heading[:160],text=content[:4000]))
    for line in text[:14000].splitlines():
        if line.lstrip().startswith(('```','~~~')):fenced=not fenced
        match=None if fenced else re.match(r'^#{1,4}\s+(.+?)\s*#*$',line)
        if match:
            append();heading=match.group(1);lines=[]
        else:lines.append(line)
    append()
    return sections[:24]

def author_metadata(info):
    card=info.get('cardData') if isinstance(info,dict) else None
    if not isinstance(card,dict):return {}
    result={}
    for key in ('language','datasets','library_name','license_name'):
        value=card.get(key)
        values=[value] if isinstance(value,str) else value if isinstance(value,list) else []
        cleaned=list(dict.fromkeys(item[:200] for item in values[:32] if isinstance(item,str) and item.strip()))
        if cleaned:result[key]=cleaned
    return result

def declared_bases(info):
    card=info.get('cardData') if isinstance(info,dict) else None
    base=card.get('base_model') if isinstance(card,dict) else None
    values=[base] if isinstance(base,str) else base if isinstance(base,list) else []
    return list(dict.fromkeys(value for value in values[:64] if isinstance(value,str) and re.fullmatch(r'[\w.-]+/[\w.-]+',value) and all(part not in ('.','..') for part in value.split('/'))))

def publisher_icon(author):

    for kind in ('organizations','users'):

        try:

            data=get_json(f'https://huggingface.co/api/{kind}/{author}/overview')

            url=data.get('avatarUrl');parsed=urllib.parse.urlsplit(url or '')

            if parsed.scheme=='https' and (parsed.hostname=='huggingface.co' or (parsed.hostname or '').endswith('.huggingface.co')):

                return url

        except (OSError,ValueError):continue

    return None



@lru_cache(maxsize=256)

def upstream_identity(repo):

    visited=set();current=repo;lineage=[]

    for _ in range(4):

        if current in visited:break

        visited.add(current);lineage.append(current)

        try:

            info=get_json('https://huggingface.co/api/models/'+current)

            bases=declared_bases(info)

            base=bases[0] if bases else None

            if not isinstance(base,str) or not re.fullmatch(r'[\w.-]+/[\w.-]+',base):break

            current=base

        except (OSError,ValueError,TypeError):break

    author=current.split('/')[0]

    return dict(base_repo=current,base_author=author,icon_url=publisher_icon(author),lineage=lineage)



def base_identity(info):
    bases=declared_bases(info)
    if not bases:return dict(base_repo=None,base_author=None,icon_url=None,declared_bases=[],author_metadata=author_metadata(info))
    return {**upstream_identity(bases[0]),'derived_from':bases[0],'declared_bases':bases,'author_metadata':author_metadata(info)}


def get_json(url):

    with urllib.request.urlopen(url,timeout=20) as response:return json.load(response)



def get_json_page(url):

    """Follow only pagination links issued by the public Hub model API."""

    with urllib.request.urlopen(url,timeout=20) as response:

        data=json.load(response);link=response.headers.get('Link','')

    match=re.search(r'<([^>]+)>;\s*rel="next"',link)

    next_url=match[1] if match else None

    if next_url:

        parsed=urllib.parse.urlsplit(next_url)

        if parsed.scheme!='https' or parsed.netloc!='huggingface.co' or not parsed.path.startswith('/api/models'):

            raise ValueError('Invalid Hub pagination link')

    return data,next_url



class OptionalCatalogue:

    def __init__(self,manager):

        self.manager=manager;self.lock=threading.RLock();self.entries={};self.cancel=threading.Event()

        self.job={'state':'idle'}

        self.search_cache={}

        self.search_pages={}

        self.card_cache={}

        self.local_identities={}
        self.local_identity_checked={}

        self.local_pending=set()

        self.header_cache_path=self.manager.root/'data/catalogue-headers.json'

        self.header_cache={}

        try:

            if self.header_cache_path.stat().st_size<=2*1024*1024:

                stored=json.loads(self.header_cache_path.read_text(encoding='utf8'))

                if isinstance(stored,dict):self.header_cache=dict(list(stored.items())[-256:])

        except (OSError,ValueError):pass

        self.header_cache_dirty=False

        self.architectures=set(ARCHITECTURES)

        library=self.manager.binary.with_name('llama.dll')

        if library.is_file():

            symbols=library.read_bytes()

            for name in ('gemma4','qwen4exp','qwen3next','afmoe','nemotron_h','nemotron_h_moe','glm4moe','lfm2'):

                if name.encode()+b'\0' in symbols:self.architectures.add(name)

            source=manager.binary.parents[3]/'src/llama-arch.cpp' if len(manager.binary.parents)>3 else None

            if source and source.is_file():

                for name in re.findall(r'\{\s*LLM_ARCH_\w+\s*,\s*"([\w.-]+)"',source.read_text(encoding='utf-8')):

                    if name.encode()+b'\0' in symbols:self.architectures.add(name)





    def delete_local(self,path,operational_idle=True,training_model=None):

        if not operational_idle:raise ValueError('Arresta il motore Strata prima di rimuovere modelli')

        with self.manager.lock,self.lock:

            if self.job.get('state') in ('downloading','verifying'):raise ValueError('Attendi la conclusione del download')

            registered=self.manager.status().get('local_models',[])

            row=next((row for row in registered if row['path']==path),None)

            if not row:raise ValueError('Seleziona un modello locale registrato')

            target=Path(path).absolute();resolved=target.resolve(strict=True)

            roots=[Path(root).resolve() for root in self.manager.models_roots]

            if not any((resolved!=root and resolved.is_relative_to(root)) or (resolved==root and row.get('format')=='Safetensors' and root in [Path(p).resolve() for p in self.manager.models_roots[4:]]) for root in roots):raise ValueError('Percorso fuori dalle cartelle modelli')

            current=self.manager.status()

            protected=[current.get('model_path') if current.get('status') in ('ready','loading') else None,current.get('adapter_path') if current.get('status') in ('ready','loading') else None,training_model]

            for active in protected:

                if active:

                    active=Path(active).resolve()

                    if active==resolved or active.is_relative_to(resolved) or resolved.is_relative_to(active):raise ValueError('Il modello è in uso: arrestalo prima di rimuoverlo')

            if target.is_dir():

                if target.is_symlink() or target.is_junction():raise ValueError('Directory collegata: rimozione non consentita')

                if not (target/'config.json').is_file() or not list(target.glob('*.safetensors')):raise ValueError('Cartella non riconosciuta come modello Safetensors')

                for parent,dirs,files in os.walk(target):

                    for name in dirs:

                        child=Path(parent)/name

                        if child.is_symlink() or child.is_junction():raise ValueError('La cartella contiene directory collegate')

                shutil.rmtree(target)

            elif target.suffix.lower()=='.gguf':
                from serve.gguf_parts import local_parts
                parts=local_parts(target)
                if any(not any(part.resolve().is_relative_to(root) for root in roots) for part in parts):raise ValueError('Part outside configured model folders')
                for part in parts:part.unlink()

            else:raise ValueError('Formato locale non rimovibile da questo catalogo')

            self.manager.model_cache_at=0;self.local_identities.pop(path,None);self.local_identity_checked.pop(path,None)

            return {'removed':True,'path':path,'name':row.get('name'),'bytes':row.get('bytes')}



    def _header(self,url):

        # Revision-pinned URLs are immutable; retain only catalogue facts, never weights.

        with self.lock:

            cached=self.header_cache.get(url)

            if isinstance(cached,dict):return copy.deepcopy(cached)

        metadata=read_gguf_header(url,nbytes=4<<20)['meta']

        if not metadata.get('tokenizer.chat_template'):

            metadata=read_gguf_header(url,nbytes=16<<20)['meta']

        wanted=('general.architecture','general.name','general.size_label','general.parameter_count')

        compact={key:value for key,value in metadata.items() if key in wanted or key.endswith('.context_length')}

        compact['tokenizer.chat_template']=bool(metadata.get('tokenizer.chat_template'))

        with self.lock:

            self.header_cache[url]=compact

            while len(self.header_cache)>256:self.header_cache.pop(next(iter(self.header_cache)))

            self.header_cache_dirty=True

        return compact



    def _save_headers(self):

        from serve.configuration import atomic_json

        with self.lock:

            if not self.header_cache_dirty:return

            # Enforce a hard limit even if an upstream name contains unexpected data.

            while self.header_cache and len(json.dumps(self.header_cache).encode('utf8'))>2*1024*1024:

                self.header_cache.pop(next(iter(self.header_cache)))

            try:

                self.header_cache_path.parent.mkdir(parents=True,exist_ok=True)

                atomic_json(self.header_cache_path,self.header_cache)

            except OSError:return

            self.header_cache_dirty=False



    def details(self,identity):

        with self.lock:

            entry=copy.deepcopy(self.entries.get(identity))

        if not entry:

            row=next((row for row in self.manager.status().get('local_models',[]) if row['path']==identity),None)

            if row:

                with self.lock:origin=copy.deepcopy(self.local_identities.get(identity,{}))

                if origin.get('repo'):entry={**row,**origin,'revision':'main'}

        if not entry:raise ValueError('Provenienza del modello non disponibile; aggiorna il catalogo')

        cache_key=(entry['repo'],entry['revision'],entry.get('base_repo'))

        with self.lock:

            cached=self.card_cache.get(cache_key)

            complete=bool(cached and cached[1].get('readme') and (not entry.get('base_repo') or entry.get('base_repo')==entry['repo'] or cached[1].get('base_readme')))
            ttl=(900 if entry['revision']=='main' or entry.get('base_repo') and entry.get('base_repo')!=entry['repo'] else 86400) if complete else 60
            if cached and time.monotonic()-cached[0]<ttl:

                self.card_cache.pop(cache_key);self.card_cache[cache_key]=cached

                result=copy.deepcopy(cached[1])
                for key in ('license','declared_bases','lineage','author_metadata','base_author'):
                    if key in entry:result[key]=copy.deepcopy(entry[key])
                return result

        url=f"https://huggingface.co/{entry['repo']}/resolve/{entry['revision']}/README.md"

        try:

            if cached and not complete and cached[1].get('readme'):
                text=cached[1]['readme']
            else:
                with urllib.request.urlopen(url,timeout=15) as response:text=response.read(65536).decode('utf-8',errors='replace')

            if text.startswith('---'):text=re.sub(r'^---\s*\n.*?\n---\s*\n','',text,count=1,flags=re.S)

            # Display source text as data, never execute its HTML or embedded assets.

            text=re.sub(r'<[^>]*>',' ',text)

            result=dict(repo=entry['repo'],revision=entry['revision'],author=entry['repo'].split('/')[0],base_repo=entry.get('base_repo'),base_author=entry.get('base_author'),license=entry.get('license'),source='https://huggingface.co/'+entry['repo'],readme=text[:14000],truncated=len(text)>14000)

        except OSError:result=dict(repo=entry['repo'],revision=entry['revision'],author=entry['repo'].split('/')[0],base_repo=entry.get('base_repo'),base_author=entry.get('base_author'),license=entry.get('license'),source='https://huggingface.co/'+entry['repo'],readme=None)

        if cached and not complete and cached[1].get('readme'):
            result['truncated']=cached[1].get('truncated',False)
        result['sections']=model_card_sections(result.get('readme'))
        result['declared_bases']=entry.get('declared_bases',[])
        result['lineage']=entry.get('lineage',[])
        result['author_metadata']=entry.get('author_metadata',{})

        base=entry.get('base_repo')

        if isinstance(base,str) and re.fullmatch(r'[\w.-]+/[\w.-]+',base) and base!=entry['repo']:

            try:

                with urllib.request.urlopen('https://huggingface.co/'+base+'/raw/main/README.md',timeout=15) as response:

                    original=response.read(65536).decode('utf-8',errors='replace')

                if original.startswith('---'):original=re.sub(r'^---\s*\n.*?\n---\s*\n','',original,count=1,flags=re.S)

                result.update(base_readme=re.sub(r'<[^>]*>',' ',original)[:14000],base_source='https://huggingface.co/'+base)

            except OSError:result['base_readme']=None

        with self.lock:

            self.card_cache.pop(cache_key,None)

            self.card_cache[cache_key]=(time.monotonic(),copy.deepcopy(result))

            while len(self.card_cache)>64:self.card_cache.pop(next(iter(self.card_cache)))

        return result



    def _local_identity(self,row):

        path=row['path'];repo=row.get('repo')

        try:

            if not repo and row.get('format')=='GGUF':

                metadata=read_gguf_header(Path(path).as_uri(),nbytes=16<<20)['meta']

                repo=metadata.get('general.source.huggingface.repository') or metadata.get('general.base_model.0.repo_url')

                if isinstance(repo,str):repo=repo.removeprefix('https://huggingface.co/').rstrip('/')

            identity={}

            if isinstance(repo,str) and re.fullmatch(r'[\w.-]+/[\w.-]+',repo):

                info=get_json('https://huggingface.co/api/models/'+repo)

                identity=base_identity(info)

                # Official publications may have no base_model entry.

                if not identity.get('icon_url'):

                    identity.update(icon_url=publisher_icon(repo.split('/')[0]),base_author=repo.split('/')[0])

                identity.update(repo=repo,author=repo.split('/')[0],category=model_category(repo),

                                license=(info.get('cardData') or {}).get('license'))

            with self.lock:
                self.local_identities[path]=identity
                self.local_identity_checked[path]=time.monotonic()+900

        except (OSError,ValueError,TypeError,KeyError):

            with self.lock:
                self.local_identities.setdefault(path,{})
                self.local_identity_checked[path]=time.monotonic()+60

        finally:

            with self.lock:self.local_pending.discard(path)



    def status(self):

        rows=self.manager.status().get('local_models',[]) if hasattr(self.manager,'status') else []

        with self.lock:
            present={row['path'] for row in rows}
            for path in list(self.local_identities):
                if path not in present and path not in self.local_pending:
                    self.local_identities.pop(path,None);self.local_identity_checked.pop(path,None)

            for row in rows:

                path=row['path']

                if path not in self.local_pending and len(self.local_pending)<2 and time.monotonic()>=self.local_identity_checked.get(path,0):

                    self.local_pending.add(path)

                    threading.Thread(target=self._local_identity,args=(copy.deepcopy(row),),daemon=True).start()

                row.update(copy.deepcopy(self.local_identities.get(path,{})))

            return {**copy.deepcopy(self.job),'local_models':rows,'identities_loading':bool(self.local_pending)}



    def search(self,payload):

        category=payload.get('category','chat')

        if category not in CATEGORIES:raise ValueError('Categoria non valida')

        query=payload.get('query') or ''

        if not isinstance(query,str):raise ValueError('Ricerca non valida')

        query=query.strip()

        author=payload.get('author') or ''

        if author not in ('','unsloth','community'):raise ValueError('Origine catalogo non supportata')

        sort=payload.get('sort','downloads')

        if sort not in ('downloads','lastModified','createdAt'):raise ValueError('Ordine catalogo non supportato')

        if not isinstance(query,str) or len(query)>120:raise ValueError('Ricerca non valida')

        resources=host()

        cursor=payload.get('cursor') or ''

        if not isinstance(cursor,str):raise ValueError('Pagina catalogo non valida')

        search_key=(category,query,author,sort)

        cache_key=(*search_key,resources.get('vram_total_gib'),resources.get('ram_total_gib'),cursor)

        with self.lock:

            cached=self.search_cache.get(cache_key)

            if cached and not payload.get('refresh') and time.monotonic()-cached[0]<900:
                result=copy.deepcopy(cached[1]);result['host']=resources
                for entry in result['results']:entry['download_space_available']=entry['bytes']+2**30<=(resources.get('free_gib') or 0)*2**30
                return result

        if not self.manager.binary.is_file():raise RuntimeError('Il runtime GGUF non è installato')

        terms=[query] # Discover live publications; no hard-coded model generation.

        errors=[];next_urls=[]

        direct=bool(re.fullmatch(r'[\w.-]+/[\w.-]+',query))

        if cursor:

            with self.lock:page=self.search_pages.get(cursor)

            if not page or time.monotonic()-page[0]>900 or page[1]!=search_key:

                raise ValueError('Pagina scaduta: ripeti la ricerca')

            urls=page[2];direct=False

        else:

            params=dict(search=query,filter='gguf',sort=sort,direction=-1,limit=16)

            if author=='unsloth':params['author']='unsloth'

            if query.lower()=='unsloth':params.update(search='',author='unsloth')

            urls=['https://huggingface.co/api/models?'+urllib.parse.urlencode(params)]

            if author=='' and params.get('author')!='unsloth':

                urls.append('https://huggingface.co/api/models?'+urllib.parse.urlencode({**params,'author':'unsloth'}))

        def discover(url):

            try:

                found,next_url=get_json_page(url)

                if next_url:

                    with self.lock:next_urls.append(next_url)

                return found

            except (OSError,ValueError) as error:

                with self.lock:errors.append(type(error).__name__)

                return []

        if direct:

            try:discovered=[get_json('https://huggingface.co/api/models/'+query)]

            except urllib.error.HTTPError as error:

                if error.code==404:discovered=[]

                else:raise RuntimeError('Hugging Face non raggiungibile: '+str(error.code)) from error

            except OSError as error:raise RuntimeError('Hugging Face non raggiungibile: riprova la ricerca') from error

        else:

            with ThreadPoolExecutor(max_workers=3) as pool:

                discovered=[row for group in pool.map(discover,urls) for row in group]

            if errors and not discovered:raise RuntimeError('Hugging Face non raggiungibile: riprova la ricerca ('+', '.join(errors)+')')

        candidates=list({row.get('id'):row for row in discovered if row.get('id')}.values())

        excluded=[]

        def reject(repo,reason):

            with self.lock:excluded.append(dict(repo=repo,reason=reason))



        def inspect(candidate):

            repo=candidate.get('id','')

            if not re.fullmatch(r'[\w.-]+/[\w.-]+',repo):return []

            if author=='unsloth' and repo.split('/')[0].lower()!='unsloth':return []

            if author=='community' and repo.split('/')[0].lower()=='unsloth':return []

            if re.search(r'(embedding|reranker|rerank|speech|tts)',repo,re.I):return []

            try:

                info=get_json('https://huggingface.co/api/models/'+repo)

                revision=info.get('sha')

                if not re.fullmatch('[a-f0-9]{40}',revision or '') or info.get('pipeline_tag') not in (None,'text-generation','image-text-to-text'):reject(repo,'Pipeline o revisione non supportata');return []

                files=[];tree_url=f'https://huggingface.co/api/models/{repo}/tree/{revision}?recursive=true'

                visited=set()

                while tree_url:

                    if tree_url in visited:raise ValueError('Repeated Hub file page')

                    visited.add(tree_url)

                    page,tree_url=get_json_page(tree_url);files.extend(page)

                files=[f for f in files if f.get('type')=='file' and f['path'].lower().endswith('.gguf') and not re.search(r'(mmproj|mtp|embedding|vocab)',f['path'],re.I)]

                declared=info.get('gguf') or {}

                declared_arch=declared.get('architecture')

                hub_metadata=None

                if declared_arch and declared.get('chat_template'):

                    hub_metadata={'general.architecture':declared_arch,'tokenizer.chat_template':True,

                        'general.parameter_count':declared.get('total'),declared_arch+'.context_length':declared.get('context_length')}

                    if declared_arch not in self.architectures:reject(repo,'Architettura non supportata dal runtime installato: '+str(declared_arch));return []

                matched=[]

                for file in sorted(files,key=lambda f:(0 if 'Q4_K_M' in f['path'].upper() else 1 if 'Q8_0' in f['path'].upper() else 2,f.get('size',0))):
                    from serve.gguf_runtime_compatibility import unsupported_reason
                    reason=unsupported_reason(file['path'])
                    if reason:reject(repo,reason);continue

                    from serve.gguf_parts import remote_parts
                    try:parts=remote_parts(file,files)
                    except ValueError as error:reject(repo,str(error));continue
                    if not parts or any(part.get('size',0)<=0 or not re.fullmatch('[a-f0-9]{64}',(part.get('lfs') or {}).get('oid','')) for part in parts):continue
                    size=sum(part['size'] for part in parts);gib=size/2**30

                    ram_capacity=max(0,(resources.get('ram_total_gib') or 0)-8)
                    # Discovery is a capacity estimate. The native loader must
                    # still verify actual available RAM, KV and placement.
                    # The installed loader still maps base weights in RAM;
                    # do not treat GPU memory as additional host RAM here.
                    if size<=0 or gib>ram_capacity:continue

                    gpu_fit=gib+4<=(resources.get('vram_total_gib') or 0)

                    name=file['path'];url=f'https://huggingface.co/{repo}/resolve/{revision}/'+urllib.parse.quote(name,safe='/')

                    metadata=hub_metadata or self._header(url);arch=metadata.get('general.architecture')

                    if arch not in self.architectures or not metadata.get('tokenizer.chat_template'):continue

                    actual_category=model_category(repo,metadata)

                    if category!='all' and actual_category!=category:continue

                    checksum=(file.get('lfs') or {}).get('oid')

                    if not re.fullmatch('[a-f0-9]{64}',checksum or ''):continue

                    key=hashlib.sha256((repo+revision+name).encode()).hexdigest()[:24]

                    if Path(name).is_absolute() or '..' in Path(name).parts or ':' in name:continue
                    destination=self.manager.models_root/'optional'/repo.replace('/','--')/revision/Path(name)
                    if not destination.resolve().is_relative_to(self.manager.models_root.resolve()):continue

                    entry=dict(id=key,repo=repo,author=repo.split('/')[0],name=metadata.get('general.name') or repo.split('/')[1],file=name,

                        revision=revision,bytes=size,sha256=checksum,architecture=arch,category=actual_category,download_space_available=gib+1<=(resources.get('free_gib') or 0),**base_identity(info),

                        quantization=re.search(r'(?:IQ|Q)\d[^.]*',Path(name).stem,re.I).group(0) if re.search(r'(?:IQ|Q)\d[^.]*',Path(name).stem,re.I) else 'BF16' if re.search(r'BF16',Path(name).stem,re.I) else 'F16' if re.search(r'(?:^|[-_.])F16(?:$|[-_.])',Path(name).stem,re.I) else 'GGUF',

                        context=metadata.get(arch+'.context_length'),license=(info.get('cardData') or {}).get('license') or 'Non dichiarata',

                        model_size=metadata.get('general.size_label'),parameters=metadata.get('general.parameter_count'),

                        downloads=info.get('downloads'),updated_at=info.get('lastModified'),created_at=info.get('createdAt') or candidate.get('createdAt'),url=url,path=str(destination),

                        likes=info.get('likes'),tags=info.get('tags',[])[:20],pipeline=info.get('pipeline_tag'),base_model=(info.get('cardData') or {}).get('base_model'),

                        installed=destination.is_file() and destination.stat().st_size==size,

                        execution_mode='gpu' if gpu_fit else 'hybrid' if (resources.get('vram_total_gib') or 0)>0 else 'cpu',fit='GPU · file + 4 GiB di margine' if gpu_fit else 'GPU + RAM tramite fit nativo; posizionamento verificato al caricamento',verification='hub_metadata_and_capacity' if hub_metadata else 'header_and_capacity')

                    if len(parts)>1:
                        entry['parts']=len(parts)
                        entry['shards']=[dict(path=str(destination.with_name(Path(part['path']).name)),file=part['path'],bytes=part['size'],sha256=part['lfs']['oid'],url=f'https://huggingface.co/{repo}/resolve/{revision}/'+urllib.parse.quote(part['path'],safe='/'),architecture=arch,verification=entry['verification'] if index==0 else 'split_part') for index,part in enumerate(parts)]
                        entry['installed']=all(Path(part['path']).is_file() and Path(part['path']).stat().st_size==part['bytes'] for part in entry['shards'])
                        entry['quantization']=re.sub(r'-\d{5}-of-\d{5}$','',entry['quantization'])
                    matched.append(entry)

                if not matched:reject(repo,'Nessun GGUF singolo con template chat e margine RAM/VRAM sufficiente; oppure architettura non ammessa')

                return matched

            except (OSError,ValueError,KeyError,TypeError) as error:

                reject(repo,'Verifica non completata: '+type(error).__name__);return []

        with ThreadPoolExecutor(max_workers=3) as pool:

            rows=[entry for group in pool.map(inspect,candidates) for entry in group]

        with self.lock:self.entries.update({entry['id']:entry for entry in rows})

        self._save_headers()

        next_cursor=None

        with self.lock:

            self.search_pages={key:page for key,page in self.search_pages.items() if time.monotonic()-page[0]<900}

            if next_urls:

                next_cursor=uuid.uuid4().hex;self.search_pages[next_cursor]=(time.monotonic(),search_key,list(dict.fromkeys(next_urls)))

            while len(self.search_pages)>256:self.search_pages.pop(next(iter(self.search_pages)))

        result=dict(results=rows,host=resources,checked_repositories=len(candidates),category=category,excluded=excluded,search_terms=terms,

                    next_cursor=next_cursor,has_more=bool(next_cursor),discovery_errors=errors,variants_limited=False)

        if not errors:

            with self.lock:

                self.search_cache[cache_key]=(time.monotonic(),copy.deepcopy(result))

                while len(self.search_cache)>128:self.search_cache.pop(next(iter(self.search_cache)))

        return result



    def download(self,identity):

        with self.lock:

            if self.job['state'] in ('downloading','verifying'):raise RuntimeError('Un download è già in corso')

            entry=copy.deepcopy(self.entries.get(identity))

            if not entry:raise ValueError('Aggiorna il catalogo prima del download')

            destination=Path(entry['path']).resolve()
            if not destination.is_relative_to(self.manager.models_root.resolve()):raise ValueError('Percorso download fuori dalle cartelle modelli')
            volume=destination.parent
            while not volume.exists() and volume!=volume.parent:volume=volume.parent
            if shutil.disk_usage(volume).free<entry['bytes']+2**30:raise ValueError('Spazio disco insufficiente nella destinazione del modello')

            self.cancel=threading.Event();self.job=dict(state='downloading',id=identity,name=entry['name'],bytes_done=0,bytes_total=entry['bytes'],speed_bps=0,eta_s=None)

            threading.Thread(target=self._download_shards if entry.get('shards') else self._download,args=(entry,),daemon=True).start()

        return self.status()



    def _download_shards(self,entry):
        created=[];offset=0;started=time.monotonic()
        try:
            for index,part in enumerate(entry['shards']):
                target=Path(part['path'])
                if target.exists():raise ValueError('A GGUF part already exists; no file is overwritten')
                if not self._download(part,offset,entry['bytes'],started,final=False):return
                created.append(target);offset+=part['bytes']
                with self.lock:self.job.update(state='downloading',parts_done=index+1,parts_total=len(entry['shards']))
            from serve.gguf_parts import local_parts
            if len(local_parts(entry['path']))!=len(entry['shards']):raise ValueError('Incomplete downloaded GGUF part set')
            with self.lock:self.job.update(state='complete',path=entry['path'],bytes_done=entry['bytes'],parts_done=len(created),parts_total=len(created))
            created=[]
        except Exception as error:
            with self.lock:self.job.update(state='failed',error=str(error))
        finally:
            for target in created:
                if target.resolve().is_relative_to(self.manager.models_root.resolve()):target.unlink(missing_ok=True)

    def _download(self,entry,offset=0,total=None,started=None,final=True):

        destination=Path(entry['path']);partial=destination.with_suffix('.gguf.download')

        try:

            destination.parent.mkdir(parents=True,exist_ok=True)

            if destination.exists():raise ValueError('Il file esiste già; non viene sovrascritto')

            digest=hashlib.sha256();done=0;started=started or time.monotonic();total=total or entry['bytes']

            with urllib.request.urlopen(entry['url'],timeout=30) as response,partial.open('wb') as output:

                while not self.cancel.is_set():

                    block=response.read(2**20)

                    if not block:break

                    done+=len(block)

                    if done>entry['bytes']:raise ValueError('Dimensione del download inattesa')

                    output.write(block);digest.update(block);speed=(offset+done)/max(.001,time.monotonic()-started)

                    with self.lock:self.job.update(bytes_done=offset+done,speed_bps=speed,eta_s=(total-offset-done)/speed)

            if self.cancel.is_set():

                with self.lock:self.job['state']='cancelled'

                return

            with self.lock:self.job['state']='verifying'

            if done!=entry['bytes'] or digest.hexdigest()!=entry['sha256']:raise ValueError('Verifica dimensioni o SHA-256 fallita')

            with partial.open('rb') as source:

                if source.read(4)!=b'GGUF':raise ValueError('File GGUF non valido')

            if entry.get('verification')=='hub_metadata_and_capacity':

                metadata=read_gguf_header(partial.resolve().as_uri(),nbytes=16<<20)['meta']

                if metadata.get('general.architecture')!=entry['architecture'] or not metadata.get('tokenizer.chat_template'):

                    raise ValueError('Il GGUF scaricato non conferma architettura e template dichiarati dal catalogo')

            os.rename(partial,destination)

            self.manager.model_cache_at=0

            if final:
                with self.lock:self.job.update(state='complete',path=str(destination),sha256=entry['sha256'])
            return True

        except Exception as error:

            with self.lock:self.job.update(state='failed',error=str(error))
            return False

        finally:

            if partial.is_file():partial.unlink()


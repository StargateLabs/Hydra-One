"""Verify isolated official Colibri releases; preserve model and user settings."""
import hashlib,json,os,socket,subprocess,time,urllib.request,http.client,sys
from pathlib import Path
from serve.configuration import atomic_json
from serve.gpu_lease import GpuLease

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def file_hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _config(root):return json.loads((Path(root)/'data/colibri/setup.json').read_text(encoding='utf-8'))

def _checked(root,candidate):
    directory=Path(candidate['candidate_directory']).resolve()
    if not directory.is_relative_to((Path(root)/'output/updates/candidates').resolve()):raise ValueError('Candidato Colibri fuori dalla cartella isolata')
    source=candidate.get('source','');version=candidate.get('published_version','')
    if not version or not source.startswith('https://github.com/JustVugg/colibri/releases/download/'+version+'/'):raise ValueError('Origine ufficiale Colibri non verificata')
    files=candidate.get('files')
    if not isinstance(files,list) or not files:raise ValueError('Inventario candidato assente')
    for row in files:
        path=directory/row['path']
        if path.is_symlink() or not path.resolve().is_relative_to(directory) or not path.is_file() or file_hash(path)!=row['sha256']:raise ValueError('File Colibri modificati dopo la preparazione')
    return directory

def _runtime_files(directory):
    return [{'path':str(p.resolve()),'sha256':file_hash(p)} for p in sorted(directory.rglob('*')) if p.is_file() and not p.is_symlink() and not {'__pycache__','strata-validation'}.intersection(p.relative_to(directory).parts)]

def _verify_files(files):
    if not files:raise ValueError('Inventario del runtime precedente assente')
    for row in files:
        path=Path(row['path'])
        if path.is_symlink() or not path.is_file() or file_hash(path)!=row['sha256']:raise ValueError('Runtime di ripristino modificato')

def _next_config(config,directory,version):
    new=json.loads(json.dumps(config));name=Path(config['engine']).name
    engines=list(directory.rglob(name))
    if len(engines)!=1:raise ValueError('Il pacchetto non contiene un solo motore '+name)
    runtime=engines[0].parent
    new.update(engine=str(engines[0]),launcher=str(runtime/'coli'),engine_source='release '+version)
    if 'COLI_VK_SHADERS' in new.get('env',{}):
        if not (runtime/'shaders').is_dir():raise ValueError('Shader Vulkan mancanti nel candidato')
        new['env']['COLI_VK_SHADERS']=str(runtime/'shaders')
    return new

def _model_identity(config):
    path=Path(config['model_dir'])/'config.json'
    return {'directory':config['model_dir'],'config_sha256':file_hash(path) if path.is_file() else None}

def _exercise(root,config,directory,version):
    import psutil
    new=_next_config(config,directory,version)
    if config.get('host')!='127.0.0.1' or not Path(config['model_dir']).is_dir():raise ValueError('Modello locale e host loopback richiesti')
    with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    args=list(new['args'])
    if '--host' not in args or args[args.index('--host')+1]!='127.0.0.1' or '--port' not in args:raise ValueError('Argomenti rete Colibri non riconosciuti')
    args[args.index('--port')+1]=str(port)
    state=directory/'strata-validation';state.mkdir(exist_ok=True)
    env={**os.environ,**new.get('env',{}),'COLI_SETUP_HOME':str(state)}
    child=None;started=time.monotonic();base='http://127.0.0.1:'+str(port)
    def request(path,payload=None,timeout=2):
        req=urllib.request.Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)
    with (state/'engine.log').open('w',encoding='utf-8') as log:
        try:
            if '--no-browser' not in args:args.append('--no-browser')
            child=subprocess.Popen([sys.executable,new['launcher'],*args],cwd=Path(new['engine']).parent,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            while time.monotonic()-started<100:
                if child.poll() is not None:raise ValueError('Il candidato Colibri non si avvia: consulta engine.log')
                if psutil.virtual_memory().available<8*1024**3:raise ValueError('Validazione fermata: meno di 8 GiB RAM disponibili')
                try:
                    health=request('/health')
                    if health.get('status')=='ok':break
                except (OSError,ValueError,http.client.HTTPException):pass
                time.sleep(.3)
            else:raise ValueError('Avvio Colibri oltre 100 secondi')
            model=request('/v1/models')['data'][0]['id']
            answer=request('/v1/chat/completions',dict(model=model,messages=[dict(role='user',content='Reply with one word: ready')],max_tokens=8,temperature=0,stream=False),timeout=30)
            if answer.get('usage',{}).get('completion_tokens',0)<1 or not answer.get('choices',[{}])[0].get('message',{}).get('content'):raise ValueError('Candidato senza risposta valida')
            startup=(state/'engine.log').read_text(encoding='utf-8',errors='replace')
            if config['backend']=='vulkan' and '[VK] ready:' not in startup:raise ValueError('Il candidato non conferma il backend Vulkan richiesto')
            return dict(passed=True,backend=config['backend'],usage=answer['usage'],health=health,reply=answer['choices'][0]['message']['content'],elapsed_seconds=time.monotonic()-started,scope='Breve inferenza reale con modello e backend operativi; non benchmark o prova del contesto massimo')
        finally:
            if child and child.poll() is None:
                try:owned=psutil.Process(child.pid).children(recursive=True)
                except psutil.Error:owned=[]
                for process in reversed(owned):
                    try:process.terminate()
                    except psutil.Error:pass
                child.terminate()
                _,remaining=psutil.wait_procs(owned,timeout=5)
                for process in remaining:
                    try:process.kill()
                    except psutil.Error:pass
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)

def validate(root,candidate):
    root=Path(root).resolve();directory=_checked(root,candidate);config=_config(root)
    with GpuLease(root,'colibri-release-validation'):
        proof=_exercise(root,config,directory,candidate['published_version'])
        proof.update(configuration_sha256=digest(config),model=_model_identity(config),files_sha256=digest(candidate['files']),validator_sha256=file_hash(__file__),validated_at=time.time())
        result={**candidate,'runtime_validated':True,'validation':proof}
        atomic_json(directory/'COLIBRI-VALIDATION.json',result)
        return result

def _apply(root,current,next_setup,active,previous):
    home=Path(root)/'data/colibri';registry=home/'runtime-selection.json'
    # The journal is written first. A crash leaves both configurations recoverable.
    if _config(root)!=current:raise ValueError('Configurazione cambiata durante l’attivazione')
    saved=json.loads(registry.read_text(encoding='utf-8')) if registry.is_file() else {'active':None,'previous':None}
    row=dict(active=active,previous=previous,transition={'before':current,'after':next_setup,'registry_before':saved},changed_at=time.time())
    atomic_json(registry,row);atomic_json(home/'setup.json',next_setup)
    row.pop('transition');atomic_json(registry,row)
    return row

def recover_transition(root):
    registry=Path(root)/'data/colibri/runtime-selection.json'
    if not registry.is_file():return
    row=json.loads(registry.read_text(encoding='utf-8'));transition=row.get('transition')
    if not transition:return
    current=_config(root)
    if current==transition['after']:
        _verify_files(row['active']['files']);row.pop('transition');atomic_json(registry,row)
    elif current==transition['before']:atomic_json(registry,transition['registry_before'])
    else:raise ValueError('Transizione Colibri interrotta: configurazione modificata, ripristino automatico sospeso')

def activate(root,candidate):
    recover_transition(root)
    root=Path(root).resolve();directory=_checked(root,candidate);config=_config(root);proof=candidate.get('validation') or {}
    if (root/'data/.gpu-campaign.lock').exists():raise ValueError('Arresta i motori prima di applicare Colibri')
    if not candidate.get('runtime_validated') or proof.get('passed') is not True or proof.get('configuration_sha256')!=digest(config) or proof.get('files_sha256')!=digest(candidate['files']) or proof.get('validator_sha256')!=file_hash(__file__) or proof.get('model')!=_model_identity(config):raise ValueError('Ripeti la validazione Colibri: file, modello o configurazione modificati')
    next_setup=_next_config(config,directory,candidate['published_version'])
    baseline=dict(setup=config,files=_runtime_files(Path(config['engine']).parent))
    _verify_files(baseline['files'])
    active=dict(setup=next_setup,files=[{'path':str(directory/r['path']),'sha256':r['sha256']} for r in candidate['files']],validation=proof)
    return _apply(root,config,next_setup,active,baseline)

def rollback(root):
    recover_transition(root)
    root=Path(root).resolve();home=root/'data/colibri';row=json.loads((home/'runtime-selection.json').read_text(encoding='utf-8'));current=_config(root)
    if (root/'data/.gpu-campaign.lock').exists():raise ValueError('Arresta i motori prima del ripristino Colibri')
    previous=row.get('previous')
    if not previous:raise ValueError('Versione Colibri precedente non disponibile')
    _verify_files(previous['files']);old=previous['setup']
    if any(current.get(key)!=old.get(key) for key in ('family','model_dir')):raise ValueError('Modello cambiato: prepara un ripristino compatibile')
    next_setup=json.loads(json.dumps(current))
    for key in ('engine','launcher','engine_source'):next_setup[key]=old[key]
    if 'COLI_VK_SHADERS' in old.get('env',{}):next_setup.setdefault('env',{})['COLI_VK_SHADERS']=old['env']['COLI_VK_SHADERS']
    return _apply(root,current,next_setup,{**previous,'setup':next_setup},dict(setup=current,files=_runtime_files(Path(current['engine']).parent)))

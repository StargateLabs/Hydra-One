"""Apply the verified catalogue integration to the existing service without editing configs."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'serve/server.py'
source=path.read_text(encoding='utf-8')

def replace_method(name,next_name,body):
    global source
    start=source.index('    def '+name+'(');end=source.index('    def '+next_name+'(',start)
    source=source[:start]+body+'\n\n'+source[end:]

replace_method('catalogue_state','catalogue_inspect','''    def catalogue_state(self) -> dict:
        from serve import catalogue as cat
        from serve.catalogue_verified import fit_host
        host=cat.host();backend=getattr(self,'cfg',{}).get('backend','unknown')
        entries=[]
        for entry in getattr(self,'cat_entries',[]):
            if fit_host(entry['quant'],entry['download_gib'],host,backend,entry['on_disk'])[0]:
                entries.append({**entry,'fit':{**entry['fit'],'host':host}})
        return {'entries':entries,'official':[],'job':dict(getattr(self,'cat_job',{}) or {}),
                'host':host,'backend':backend,'prepared':self.prepared_models(),
                'disk':{'free_gib':host['free_gib']},'checked_at':getattr(self,'cat_checked_at',None)}''')
replace_method('catalogue_inspect','catalogue_search','''    def catalogue_inspect(self,repo: str,quant: str=None) -> dict:
        from serve import catalogue as cat
        from serve import catalogue_verified as verified
        if quant is None:
            groups=verified.repo_info(repo)['groups']
            quant=next((q for q in ('IQ3_XXS','IQ2_XS','Q2_0','IQ3_S','IQ1_M') if q in groups),None)
        if not quant:raise ValueError('Nessuna quantizzazione supportata')
        return verified.inspect(repo,quant,cat.host(),getattr(self,'cfg',{}).get('backend','unknown'),ROOT)''')
replace_method('catalogue_search','start_catalogue_fetch','''    def catalogue_search(self,query: str) -> dict:
        from serve import catalogue as cat
        from serve import catalogue_verified as verified
        result=verified.search(query,cat.host(),getattr(self,'cfg',{}).get('backend','unknown'),ROOT)
        self.cat_entries=result['results'];self.cat_checked_at=result['checked_at']
        return result''')
replace_method('start_catalogue_fetch','_catalogue_worker','''    def start_catalogue_fetch(self,repo: str,quant: str,key: str=None,mtp: bool=False) -> dict:
        from serve import catalogue as cat
        if mtp:raise ValueError('Le teste MTP separate non sono validate in questo flusso; nessun download avviato')
        if self.benchmark_lab.active():raise ValueError('Attendi la fine della campagna Benchmark')
        with self.status_lock:
            if getattr(self,'cat_job',{}).get('state') in ('starting','downloading','packing','registering'):
                raise ValueError('Una preparazione è già in corso')
            self.cat_job={'state':'starting','repo':repo,'quant':quant,'started':time.time()}
        try:
            info=self.catalogue_inspect(repo,quant)
            chiave=key or info['key']
            if not re.fullmatch(r'[a-z0-9_]{1,32}',chiave):raise ValueError('Identificatore del modello non valido')
            if (ROOT/f'strata-{chiave}.json').exists():raise ValueError('Configurazione già presente; non viene sovrascritta')
            pack=cat.DATA/'packs'/chiave
            if pack.exists():raise ValueError('Pack già presente; non viene sovrascritto')
            self.cat_job.update(key=chiave,revision=info['revision'],files=info['files'],inspection=info,
                                download_gib=info['download_gib'],log=str(ROOT/f'strata-catalogo-{chiave}.log'))
            threading.Thread(target=self._catalogue_worker,args=(repo,quant,chiave,False),daemon=True).start()
            return dict(self.cat_job)
        except Exception as exc:
            self.cat_job.update(state='failed',error=str(exc));raise''')
replace_method('_catalogue_worker','_catalogue_register','''    def _catalogue_worker(self,repo: str,quant: str,chiave: str,mtp: bool=False) -> None:
        from serve import catalogue as cat
        log=Path(self.cat_job['log']);files=list(self.cat_job['files']);revision=self.cat_job['revision']
        try:
            self.cat_job.update(state='downloading',step=1)
            dest=cat.DATA/'models'/chiave;dest.mkdir(parents=True,exist_ok=True)
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id=repo,revision=revision,allow_patterns=files,local_dir=str(dest),max_workers=4)
            self.cat_job.update(state='packing',step=2)
            first=next((f for f in files if re.search(r'-00001-of-\\d{5}\\.gguf$',f)),files[0])
            final=cat.DATA/'packs'/chiave;staging=cat.DATA/'packs'/('.'+chiave+'-'+uuid.uuid4().hex[:8])
            command=[sys.executable,str(ROOT/'tools/iq_pack.py'),'--gguf',str(dest/first),'--out',str(staging),'--compat-bf16']
            with log.open('ab') as output:subprocess.run(command,cwd=str(ROOT),stdout=output,stderr=subprocess.STDOUT,check=True)
            if final.exists():raise ValueError('Pack creato da un altro lavoro; non viene sovrascritto')
            staging.rename(final)
            self.cat_job.update(state='registering',step=3)
            config=self._catalogue_register(chiave,dest,files)
            self.cat_job.update(state='done',step=3,config=config,pack=str(final))
        except Exception as exc:self.cat_job.update(state='failed',error=str(exc))''')
replace_method('_catalogue_register','prepared_models','''    def _catalogue_register(self,chiave: str,dest: pathlib.Path,files: list) -> str:
        from serve.model_inventory import inspect_config
        from gguf_reader import GGUFFile
        from make_profile import read_profile,write_profile
        model=json.loads((ROOT/'strata-iq3_xxs.json').read_text(encoding='utf-8-sig'))
        args=list(model['args']);shards=sorted(f for f in files if f.lower().endswith('.gguf') and 'mmproj' not in f.lower() and 'mtp/' not in f.lower())
        if not shards:raise ValueError('Shard del modello mancanti')
        first=next((f for f in shards if re.search(r'-00001-of-\\d{5}\\.gguf$',f)),shards[0])
        ple=next((f for f in shards if GGUFFile(dest/f).find('per_layer_token_embd.weight')),None)
        if ple is None:raise ValueError('Tabella PLE non trovata negli shard')
        def setf(flag,value):
            if flag in args:args[args.index(flag)+1]=str(value)
            else:args.extend([flag,str(value)])
        pack=ROOT.parent/'Strata-data/packs'/chiave
        setf('--pack',pack);setf('--native',dest/first);setf('--ple-gguf',dest/ple)
        experts=self.cat_job['inspection']['experts'];directory=ROOT/'data/catalogue'/chiave;directory.mkdir(parents=True,exist_ok=True)
        base_pairs=read_profile(ROOT/'data/expert-profile.bin')
        pairs=[p for p in base_pairs if p[1]<experts];profile=directory/'expert-profile.bin'
        if profile.exists():raise ValueError('Profilo già presente; non viene sovrascritto')
        write_profile(profile,pairs,n_expert=experts);setf('--expert-profile',profile)
        # A newly downloaded checkpoint must not silently inherit another model's draft or encoder.
        for flag in ('--mtp','--mtp-draft-vocab'):
            if flag in args:i=args.index(flag);del args[i:i+2]
        model.pop('vision',None);model.pop('expert_profile_save',None)
        model.update(args=args,tokenizer=str(pack/'tokenizer'),model_name='qwen3.8-flash-next-'+chiave,log=str(ROOT/f'strata-{chiave}.log'))
        model.pop('model',None)
        out=ROOT/f'strata-{chiave}.json'
        with out.open('x',encoding='utf-8') as output:json.dump(model,output,ensure_ascii=False,indent=2)
        ready=inspect_config(out)
        if not ready['ready']:raise ValueError('Preparazione incompleta: '+ready['error'])
        return str(out)''')
replace_method('prepared_models','start_switch','''    def prepared_models(self) -> list:
        from serve.model_inventory import inventory
        return inventory(ROOT)''')
path.write_text(source,encoding='utf-8')

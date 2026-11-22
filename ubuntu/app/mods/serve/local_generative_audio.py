"""Owned, offline MusicGen/OpenVoice workers. No model or package downloads."""
import base64, hashlib, io, json, math, os, shutil, subprocess, threading, time, uuid, wave
from pathlib import Path
from serve.audio_library import AudioLibrary
from serve.configuration import atomic_json

class LocalGenerativeAudio:
    def __init__(self, root):
        self.root=Path(root).resolve();self.models=self.root.parent/'Strata-data/models/audio'
        self.default_python=self.root/'tools/local-generative-audio/.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        self.lock=threading.RLock();self.child=None;self.job={'status':'idle'};self.closed=False;self.worker=None;self.batch={'status':'idle'};self.batch_worker=None
    @property
    def python(self):
        from serve.audio_python_update import selected_python
        return selected_python(self.root,self.default_python)
    def model_choices(self):
        rows=[]
        for base in (self.models,self.root/'models/audio'):
            for task,folder in (('music','music'),('voice_conversion','conversion'),('effects','effects'),('magnet','magnet'),('watermark','watermark'),('mbd','mbd'),('codec24','codec24'),('style','style'),('jasco','jasco')):
                for p in sorted((base/folder).glob('*')):
                    if not p.is_dir() or p.is_symlink() or not p.resolve().is_relative_to(base.resolve()):continue
                    try:
                        config=p/('audiogen.json' if task in ('effects','magnet','watermark','mbd','style','jasco') else 'config.json')
                        if config.is_symlink() or config.stat().st_size>1024*1024:continue
                        spec=json.loads(config.read_text(encoding='utf-8'))
                        valid=(spec.get('model_type') in ('musicgen','musicgen_melody') and (p/'tokenizer_config.json').is_file() and bool(list(p.glob('*.safetensors')))) if task=='music' else (spec.get('_version_')=='v2' and spec.get('model',{}).get('gin_channels')==256 and (p/'checkpoint.pth').is_file())
                        if task=='magnet':valid=spec.get('repository') in ('facebook/audio-magnet-small','facebook/audio-magnet-medium','facebook/magnet-small-10secs','facebook/magnet-medium-10secs','facebook/magnet-small-30secs','facebook/magnet-medium-30secs') and all((p/name).is_file() for name in ('state_dict.bin','compression_state_dict.bin'))
                        if task=='mbd':valid=spec.get('repository')=='facebook/multiband-diffusion' and all((p/name).is_file() for name in ('mbd_comp_2.pt','mbd_comp_4.pt','mbd_comp_8.pt'))
                        if task=='codec24':valid=spec.get('model_type')=='encodec' and spec.get('sampling_rate')==24000 and spec.get('audio_channels')==1 and (p/'model.safetensors').is_file()
                        if task=='watermark':valid=spec.get('repository')=='facebook/audioseal' and all((p/name).is_file() for name in ('generator_base.pth','detector_base.pth','base.yaml'))
                        if task=='effects':valid=spec.get('repository')=='facebook/audiogen-medium' and all((p/name).is_file() for name in ('state_dict.bin','compression_state_dict.bin'))
                        if task in ('style','jasco'):
                            from serve.audiocraft_native import model_contract
                            valid=bool(model_contract(p,task))
                        if not valid or any(f.is_symlink() for f in p.rglob('*')):continue
                        rows.append({'id':folder+'/'+p.name,'name':p.name,'task':task,'model_type':spec.get('model_type'),'format':'transformers-safetensors' if task=='music' else 'audiocraft-native' if task in ('effects','magnet','watermark','mbd','style','jasco') else 'openvoice-converter','path':str(p.resolve()),'bytes':sum(f.stat().st_size for f in p.rglob('*') if f.is_file())})
                        if task in ('magnet','style','jasco'):
                            from serve.audiocraft_conditioning import checkpoint_encoder, selected_cache
                            try:
                                encoder=checkpoint_encoder(p/'state_dict.bin');selected_cache(self.root,encoder)
                                if task=='style':
                                    from serve.audiocraft_conditioning import style_dependency
                                    style_dependency(self.root)
                                rows[-1].update(conditioning_ready=True,conditioning_encoder=encoder)
                            except (OSError,ValueError) as error:rows[-1].update(conditioning_ready=False,conditioning_error=str(error))
                        provenance=p/'provenance.json'
                        if provenance.is_file() and provenance.stat().st_size<=1024**2:
                            info=json.loads(provenance.read_text(encoding='utf-8'));rows[-1].update(license=info.get('license'),repository=info.get('repository'),revision=info.get('revision'))
                    except (OSError,ValueError):continue
        return rows
    def status(self):
        evidence={}
        try:
            path=self.root/'data/generative-audio-runtime.json'
            if path.stat().st_size<=8192:
                row=json.loads(path.read_text(encoding='utf-8'))
                if isinstance(row,dict) and row.get('python')==str(self.python) and row.get('python_sha256')==hashlib.sha256(self.python.read_bytes()).hexdigest():evidence=row
        except (OSError,ValueError):pass
        from serve.audiocraft_setup import selected_python
        effects_python=selected_python(self.root) or self.python
        audiogen_present=(effects_python.parent.parent/'Lib/site-packages/audiocraft/models/audiogen.py').is_file()
        conditioning_ready=False
        try:
            conditioning=json.loads((self.root/'data/audiocraft-conditioning.json').read_text(encoding='utf-8'))
            cache=Path(conditioning['cache']).resolve()
            conditioning_ready=conditioning.get('validated') is True and conditioning.get('repository')=='google-t5/t5-large' and cache.is_relative_to((self.root/'output/updates/audiocraft-candidates').resolve()) and (cache/'models--t5-large/refs/main').is_file()
        except (OSError,ValueError,KeyError):pass
        devices=['cpu']+(['cuda'] if evidence.get('cuda_available') is True else [])
        with self.lock:return dict(self.job,batch=dict(self.batch),batch_supported=True,audiogen={'runtime_present':audiogen_present,'conditioning_ready':conditioning_ready,'conditioning_model':'google-t5/t5-large','state':'runtime_and_conditioning_ready' if audiogen_present and conditioning_ready else 'conditioning_missing' if audiogen_present else 'runtime_missing','source':'https://github.com/facebookresearch/audiocraft','reason':'AudioCraft original runtime and local AudioGen/conditioning weights required; existing vendor Torch is preserved'},runtime_installed=self.python.is_file(),runtime_python=str(self.python),models=self.model_choices(),devices=devices,device_evidence=evidence,busy=self.job['status'] in ('queued','running') or self.batch['status'] in ('queued','running'),offline=True,effects_modes=['text','unconditional','continuation'],music_modes=['text','unconditional','continuation','melody'])
    def reference_audio(self,value,minimum_seconds=1):
        if not isinstance(value,str) or not Path(value).is_absolute():raise ValueError('Choose an absolute local PCM16 WAV path')
        p=Path(value)
        if p.is_symlink() or p.suffix.lower()!='.wav':raise ValueError('Choose a regular WAV file')
        p=p.resolve()
        if not p.is_file() or not 44<p.stat().st_size<=10*1024**2:raise ValueError('Use a WAV below 10 MiB')
        try:
            with wave.open(str(p)) as w:
                n=w.getnframes();duration=n/w.getframerate()
                if w.getsampwidth()!=2 or w.getnchannels() not in (1,2) or not 8000<=w.getframerate()<=48000 or not minimum_seconds<=duration<=30 or len(w.readframes(n))!=n*w.getnchannels()*2:raise ValueError(f'Use complete PCM16 WAV, {minimum_seconds}–30 seconds, mono/stereo, 8–48 kHz')
        except wave.Error as e:raise ValueError('Invalid PCM WAV') from e
        return p
    def _validate(self,payload):
        task=payload.get('task');device=payload.get('device','cpu')
        if task not in ('music','voice_conversion','effects','codec','magnet','watermark','mbd','style','jasco') or device not in ('cpu','cuda'):raise ValueError('Supported tasks: music, voice_conversion; devices: cpu, cuda')
        if task in ('effects','codec','magnet','watermark','mbd','style','jasco') and device!='cpu':raise ValueError('The dedicated AudioCraft candidate is configured for CPU; GPU requires its own device validation')
        if device=='cuda' and 'cuda' not in self.status()['devices']:raise ValueError('GPU audio runtime is not validated; choose CPU or prepare a compatible GPU runtime')
        matches=[r for r in self.model_choices() if r['id']==payload.get('model') and (r['task']==task or task=='codec' and r['task']=='effects')]
        if len(matches)!=1:raise ValueError('Choose a supported installed model; remote model IDs are refused')
        request={'task':task,'device':device,'model_path':matches[0]['path'],'model':matches[0]['id']}
        if task in ('style','jasco'):
            from serve.audiocraft_native import validate_options
            from serve.audiocraft_conditioning import checkpoint_encoder,selected_cache
            if not self.status()['audiogen']['runtime_present']:raise ValueError('Prepara AudioCraft esteso prima di usare Style o JASCO')
            request.update(validate_options(task,payload,self.reference_audio))
            if task=='style':
                from serve.audiocraft_conditioning import style_dependency
                style_dependency(self.root)
            encoder=checkpoint_encoder(Path(matches[0]['path'])/'state_dict.bin');request['conditioning_cache']=str(selected_cache(self.root,encoder))
            if request.get('melody_salience') is not None and 'melody' not in matches[0]['name']:raise ValueError('Scegli un checkpoint JASCO con condizionamento melodico')
            return request
        if task=='magnet':
            from serve.audiocraft_conditioning import checkpoint_encoder, selected_cache
            encoder=checkpoint_encoder(Path(matches[0]['path'])/'state_dict.bin')
            request['conditioning_cache']=str(selected_cache(self.root,encoder))
            if not self.status()['audiogen']['runtime_present']:raise ValueError('Prepare the separate AudioCraft runtime')
            prompt=payload.get('prompt','')
            if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=1000:raise ValueError('Use a text prompt up to 1000 characters')
            seed=payload.get('seed',0)
            if type(seed) is not int or not 0<=seed<=2147483647:raise ValueError('Invalid seed')
            request.update(prompt=prompt,seed=seed,seconds=30 if '30secs' in matches[0]['name'] else 10)
            for key,default,low,high in [('temperature',3.,.01,5),('top_p',.9,0,1),('min_cfg_coef',1.,0,20),('max_cfg_coef',10.,0,20)]:
                value=payload.get(key,default)
                if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:raise ValueError('Invalid MAGNeT '+key)
                request[key]=value
            top_k=payload.get('top_k',0);steps=payload.get('decoding_steps',[20,10,10,10]);sampling=payload.get('do_sample',True)
            if type(top_k) is not int or not 0<=top_k<=4096 or type(sampling) is not bool:raise ValueError('Invalid MAGNeT sampling')
            if not isinstance(steps,list) or len(steps)!=4 or any(type(x) is not int or not 1<=x<=100 for x in steps):raise ValueError('Use four codebook decoding step counts in 1–100')
            span=payload.get('span_arrangement','nonoverlap')
            if span not in ('nonoverlap','stride1'):raise ValueError('Invalid MAGNeT span arrangement')
            if request['min_cfg_coef']>request['max_cfg_coef']:raise ValueError('Minimum guidance exceeds maximum')
            request.update(top_k=top_k,do_sample=sampling,decoding_steps=steps,span_arrangement=span)
        elif task in ('music','effects'):
            if task=='effects' and not self.status()['audiogen']['runtime_present']:raise ValueError('AudioCraft runtime missing; prepare a separate compatible candidate without replacing vendor Torch')
            if task=='effects' and not self.status()['audiogen']['conditioning_ready']:raise ValueError('Prepare the original local T5-large conditioning encoder')
            prompt=payload.get('prompt','');seconds=payload.get('seconds',5);seed=payload.get('seed',0);mode=payload.get('music_mode','text')
            if task=='effects' and mode not in ('text','unconditional','continuation'):raise ValueError('AudioGen supports text, unconditional or continuation')
            if mode not in ('text','unconditional','continuation','melody'):raise ValueError('Choose text, unconditional or continuation music mode')
            if not isinstance(prompt,str) or len(prompt)>1000 or (mode=='text' and not prompt.strip()):raise ValueError('Use 1–1000 prompt characters for text mode')
            if type(seconds) not in (int,float) or not 1<=seconds<=30:raise ValueError('Use 1–30 music seconds')
            if type(seed)!=int or not 0<=seed<=2147483647:raise ValueError('Use an integer seed 0–2147483647')
            request.update(prompt=prompt,seconds=seconds,seed=seed)
            family=matches[0].get('model_type','musicgen')
            if mode=='melody' and family!='musicgen_melody':raise ValueError('Choose a locally installed MusicGen Melody model')
            if family=='musicgen_melody' and mode in ('continuation','unconditional'):raise ValueError('MusicGen Melody supports text or melody conditioning in this runtime')
            request['music_mode']=mode
            if task=='effects':
                if 'two_step_cfg' in payload:
                    if type(payload['two_step_cfg']) is not bool:raise ValueError('two_step_cfg must be boolean')
                    request['two_step_cfg']=payload['two_step_cfg']
                if 'extend_stride' in payload:
                    value=payload['extend_stride']
                    if type(value) not in (int,float) or not math.isfinite(value) or not .1<=value<10:raise ValueError('extend_stride must be finite in [0.1,10)')
                    request['extend_stride']=value
            if 'do_sample' in payload:
                if type(payload['do_sample']) is not bool:raise ValueError('do_sample must be a boolean')
                request['do_sample']=payload['do_sample']
            if mode in ('continuation','melody'):
                audio=self.reference_audio(payload.get('music_prompt_path'),minimum_seconds=0.1)
                with wave.open(str(audio)) as clip:prompt_seconds=clip.getnframes()/clip.getframerate()
                if mode=='continuation' and prompt_seconds+0.1>seconds:raise ValueError('Total music duration must exceed the input clip by at least 0.1 seconds, up to 30 seconds')
                request.update(music_prompt_path=str(audio),music_prompt_seconds=prompt_seconds)
            for key,low,high in (('temperature',0.01,5),('top_p',0 if task=='effects' else .01,1),('guidance_scale',0,20)):
                if key not in payload:continue
                value=payload[key]
                if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:raise ValueError(f'{key} must be finite and in {low}..{high}')
                request[key]=value
            if 'top_k' in payload:
                value=payload['top_k']
                if type(value) is not int or not 0<=value<=4096:raise ValueError('top_k must be an integer in 0..4096')
                request['top_k']=value
        elif task=='mbd':
            codecs=[row for row in self.model_choices() if row['task']=='codec24']
            if not codecs:raise ValueError('Prepare the original 24 kHz codec for MBD')
            request['codec_path']=codecs[0]['path'];request['source_path']=str(self.reference_audio(payload.get('source_path')))
            with wave.open(request['source_path']) as audio:
                if audio.getnframes()/audio.getframerate()>10:raise ValueError('MBD CPU input is limited to 10 seconds')
            bandwidth=payload.get('mbd_bandwidth',3.0);seed=payload.get('seed',0)
            if type(bandwidth) not in (int,float) or bandwidth not in (1.5,3.,6.) or type(seed) is not int or not 0<=seed<=2147483647:raise ValueError('Choose bandwidth 1.5, 3 or 6 kbps and a valid seed')
            request.update(mbd_bandwidth=bandwidth,mbd_codebooks={1.5:2,3.:4,6.:8}[bandwidth],seed=seed)
        elif task=='watermark':
            from serve.audiocraft_setup import selected_python
            python=selected_python(self.root)
            if not python or not (python.parent.parent/'Lib/site-packages/audiocraft/models/watermark.py').is_file():raise ValueError('Prepare the extended AudioCraft runtime')
            request['source_path']=str(self.reference_audio(payload.get('source_path')))
            action=payload.get('watermark_action','detect');alpha=payload.get('watermark_alpha',1.0);message=payload.get('watermark_message','')
            if action not in ('detect','embed','both') or type(alpha) not in (int,float) or not math.isfinite(alpha) or not .1<=alpha<=2:raise ValueError('Invalid AudioSeal action or strength')
            if not isinstance(message,str) or len(message)>32 or any(bit not in '01' for bit in message):raise ValueError('Watermark message must be a binary string up to 32 bits')
            request.update(watermark_action=action,watermark_alpha=alpha,watermark_message=message)
        elif task=='codec':
            if not self.status()['audiogen']['runtime_present']:raise ValueError('Prepare the isolated AudioCraft runtime first')
            request['source_path']=str(self.reference_audio(payload.get('source_path')))
            count=payload.get('codec_codebooks',0)
            if type(count) is not int or not 0<=count<=32:raise ValueError('Codec codebooks must be 0–32; zero uses native default')
            request['codec_codebooks']=count
        else:
            request.update(source_path=str(self.reference_audio(payload.get('source_path'))),reference_path=str(self.reference_audio(payload.get('reference_path'))))
            if 'tau' in payload:
                value=payload['tau']
                if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:raise ValueError('tau must be finite and in 0..1')
                request['tau']=value
        return request
    def _command(self,request_path):
        from serve.audiocraft_setup import selected_python
        request=json.loads(Path(request_path).read_text(encoding='utf-8'))
        python=(selected_python(self.root) or self.python) if request.get('task') in ('effects','codec','magnet','watermark','mbd','style','jasco') else self.python
        return [str(python),str(self.root/'tools/generate_local_audio.py'),'--request',str(request_path)]
    def start(self,payload,*,batch_item=False):
        if not isinstance(payload,dict):raise ValueError('Send a JSON object')
        request=self._validate(payload)
        with self.lock:
            if self.closed:raise RuntimeError('Audio manager closed')
            if not batch_item and self.batch['status'] in ('queued','running'):raise RuntimeError('OpenVoice batch already running')
            if self.job['status'] in ('queued','running') or (self.worker and self.worker.is_alive()):raise RuntimeError('Local audio job already running')
            if not self.python.is_file():raise RuntimeError('Install the isolated tools/local-generative-audio/.venv runtime first')
            identity=uuid.uuid4().hex;work=self.root/'data/generative-audio'/identity;work.mkdir(parents=True)
            # Snapshot clips: UI/user edits cannot change a running request.
            for key in ('source_path','reference_path','music_prompt_path'):
                if key in request:
                    data=Path(request[key]).read_bytes();target=work/(key+'.wav');target.write_bytes(data)
                    request[key]=str(target);request[key+'_sha256']=hashlib.sha256(data).hexdigest()
            request.update(output_path=str(work/'result.wav'),report_path=str(work/'result.json'))
            atomic_json(work/'request.json',request)
            self.job={'id':identity,'status':'queued','task':request['task'],'model':request['model'],'device':request['device'],'started_at':time.time()}
            from serve.gpu_lease import GpuLease
            lease=GpuLease(self.root,'generative-audio')
            try:lease.acquire()
            except BaseException:self.job['status']='error';raise
            self.worker=threading.Thread(target=self._run,args=(identity,work,request,lease),daemon=True)
            try:self.worker.start()
            except BaseException:lease.release();self.job['status']='error';raise
            return self.status()
    def start_batch(self,payload):
        sources=payload.get('source_paths')
        if not isinstance(sources,list) or not 1<=len(sources)<=16:raise ValueError('Choose 1–16 library source clips')
        if len(set(sources))!=len(sources):raise ValueError('Choose distinct source clips')
        requests=[self._validate(dict(payload,task='voice_conversion',source_path=source)) for source in sources]
        with self.lock:
            if self.closed or self.status()['busy'] or (self.worker and self.worker.is_alive()) or (self.batch_worker and self.batch_worker.is_alive()):raise RuntimeError('Finish the current audio operation first')
            if not self.python.is_file():raise RuntimeError('Prepare the audio runtime first')
            needed=sum(Path(request[key]).stat().st_size for request in requests for key in ('source_path','reference_path'))
            if shutil.disk_usage(self.root).free<needed+512*1024**2:raise ValueError('Keep 512 MiB free beyond batch snapshots')
            identity=uuid.uuid4().hex;work=self.root/'data/generative-audio-batches'/identity;work.mkdir(parents=True)
            items=[]
            for index,request in enumerate(requests):
                for key in ('source_path','reference_path'):
                    data=Path(request[key]).read_bytes();target=work/(str(index)+'-'+key+'.wav');target.write_bytes(data);request[key]=str(target)
                items.append(dict(model=request['model'],device=request['device'],task='voice_conversion',source_path=request['source_path'],reference_path=request['reference_path'],**({'tau':request['tau']} if 'tau' in request else {})))
            self.batch={'id':identity,'status':'queued','total':len(items),'completed':0,'results':[]}
            atomic_json(work/'batch.json',self.batch)
            self.batch_worker=threading.Thread(target=self._run_batch,args=(identity,work,items),daemon=True)
            self.batch_worker.start()
            return self.status()
    def _run_batch(self,identity,work,items):
        try:
            for index,payload in enumerate(items):
                with self.lock:
                    if self.batch['status']=='cancelled' or self.closed:break
                    self.batch.update(status='running',current=index+1)
                    self.start(payload,batch_item=True)
                    worker=self.worker
                worker.join()
                with self.lock:
                    result={key:self.job[key] for key in ('id','status','artifact','error') if key in self.job}
                    result['index']=index+1;self.batch['results'].append(result);self.batch['completed']=index+1
                    atomic_json(work/'batch.json',self.batch)
                    if self.batch['status']=='cancelled':break
            with self.lock:
                if self.batch['status']!='cancelled':self.batch['status']='done' if all(r['status']=='done' for r in self.batch['results']) else 'completed_with_errors'
                atomic_json(work/'batch.json',self.batch)
        except Exception as error:
            with self.lock:
                if self.batch['status']!='cancelled':self.batch.update(status='error',error=str(error)[:1000])
                atomic_json(work/'batch.json',self.batch)

    def _run(self,identity,work,request,lease):
        started=time.monotonic()
        try:
            env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',TOKENIZERS_PARALLELISM='false',OMP_NUM_THREADS='2')
            if request['task'] in ('effects','magnet','style','jasco'):
                conditioning=self.root/'data/audiocraft-conditioning.json'
                if request['task']=='effects' and not conditioning.is_file():raise ValueError('Prepare the local T5 conditioning encoder first')
                cache=Path(request['conditioning_cache']).resolve() if request['task'] in ('magnet','style','jasco') else Path(json.loads(conditioning.read_text(encoding='utf-8'))['cache']).resolve()
                if not cache.is_relative_to((self.root/'output/updates/audiocraft-candidates').resolve()):raise ValueError('Invalid conditioning cache')
                env.update(HF_HUB_CACHE=str(cache),HUGGINGFACE_HUB_CACHE=str(cache),TRANSFORMERS_CACHE=str(cache),HF_MODULES_CACHE=str(cache.parent/'model-code-cache'))
            if request['device']=='cpu':env.update(CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
            with self.lock:
                if self.job.get('id')!=identity or self.job['status']=='cancelled':return
                with (work/'worker.log').open('wb') as log:self.child=subprocess.Popen(self._command(work/'request.json'),cwd=self.root,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                from serve.winjob import contain
                contain(self.child)
                child=self.child;self.job['status']='running'
            try:code=child.wait(timeout=600)
            except subprocess.TimeoutExpired:
                self._terminate(child);raise RuntimeError('Audio worker timed out after 600 seconds')
            with self.lock:
                if self.job['status']=='cancelled':return
                if code:raise RuntimeError('Audio worker failed; inspect '+str(work/'worker.log'))
                p=work/'result.wav'
                if p.stat().st_size>32*1024**2:raise RuntimeError('Audio output exceeds 32 MiB')
                data=p.read_bytes()
                with wave.open(io.BytesIO(data)) as w:
                    n=w.getnframes();duration=n/w.getframerate();frames=w.readframes(n)
                    if w.getsampwidth()!=2 or w.getnchannels() not in (1,2) or not 0<duration<=35 or len(frames)!=n*w.getnchannels()*2 or not any(frames):raise RuntimeError('Worker produced invalid or silent WAV')
                report=json.loads((work/'result.json').read_text(encoding='utf-8'))
                if report.get('task')!=request['task'] or report.get('device')!=request['device']:raise RuntimeError('Worker provenance mismatch')
                operation={'task':request['task'],'engine':report.get('engine'),'seed':request.get('seed'),'prompt_sha256':hashlib.sha256(request.get('prompt','').encode()).hexdigest(),'source_sha256':request.get('source_path_sha256'),'reference_sha256':request.get('reference_path_sha256'),'model_path':request['model_path'],'model_files':report.get('model_files'),'license':report.get('license'),'native_options':report.get('native_options',{}),'offline':True}
                if request['task'] in ('music','effects'):operation.update(music_mode=request.get('music_mode','text'),music_prompt_seconds=request.get('music_prompt_seconds',0),music_prompt_sha256=request.get('music_prompt_path_sha256'))
                artifact=AudioLibrary(self.root).save(data,dict(model=request['model'],device=request['device'],audio_seconds=duration,elapsed_seconds=time.monotonic()-started,operation=operation))
                self.job.update(status='done',artifact=artifact,codec=report.get('codec'),watermark=report.get('watermark'),audio_seconds=duration,elapsed_seconds=time.monotonic()-started)
        except Exception as e:
            with self.lock:
                if self.job.get('id')==identity and self.job['status']!='cancelled':self.job.update(status='error',error=str(e)[:1000])
        finally:
            lease.release()
            with self.lock:
                if self.job.get('id')==identity:self.child=None
    def _terminate(self,child):
        if child and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
    def stop(self):
        with self.lock:
            if self.batch['status'] in ('queued','running'):self.batch['status']='cancelled'
            if self.job['status'] in ('queued','running'):self.job['status']='cancelled'
            child=self.child
        self._terminate(child)
        return self.status()
    def close(self):
        with self.lock:self.closed=True
        state=self.stop()
        # The worker releases the GPU lease in its own finally block; without waiting for it
        # the lock file survives and blocks the next start on this project.
        batch_worker=self.batch_worker
        if batch_worker and batch_worker.is_alive():batch_worker.join(timeout=10)
        worker=self.worker
        if worker and worker.is_alive():
            worker.join(timeout=10)
            if worker.is_alive():state['worker_shutdown_timeout']=True
        return state



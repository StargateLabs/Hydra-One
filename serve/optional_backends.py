"""Optional model lifecycle. Only the explicitly owned child may be stopped."""
import atexit
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time

from serve.gpu_lease import GpuLease,recover_stale_optional_reservation
from serve.optional_inference import LocalOpenAIBackend,BackendError


class OptionalBackends:
    def __init__(self, root, *, discover_models=True):
        self.root = Path(root)
        self.dashboard_port=8090
        recover_stale_optional_reservation(self.root)
        self.lock = threading.RLock()
        self.request_lock = threading.Lock()
        self.conversation_lock = threading.Lock()
        self.child = None
        self.lease = None
        self.cancel_load = threading.Event()
        self.state = dict(status='idle', model=None, backend=None, error=None, requests=0)
        self.client = None
        self.binary = Path.home()/'.unsloth/llama.cpp/build/bin/Release/llama-server.exe'
        self.python_runtime=Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe'
        self.training_python_runtime=self.python_runtime
        self.models_root=self.root.parent/'Strata-data/models'
        hf_root=Path(os.environ.get('HF_HOME',str(Path.home()/'.cache/huggingface')))
        self.models_roots=[self.models_root,Path(os.environ.get('HF_HUB_CACHE',str(hf_root/'hub'))),Path.home()/'.unsloth/.cache',self.root/'output/model-exports']
        self.model_cache=[];self.model_cache_at=0
        self.active_cancel=None
        self.discovery=None
        if discover_models and (self.root/'serve/web/index.html').is_file():
            from serve.local_model_discovery import LocalModelDiscovery
            self.discovery=LocalModelDiscovery(self)
        atexit.register(self.close)

    def status(self, *, include_models=True):
        with self.lock:
            if self.child and self.child.poll() is not None and self.state['status']=='ready':
                self.state.update(status='error', error='Il processo del backend Ã¨ terminato')
                self._release()
            result = copy.deepcopy(self.state)
            if self.client is not None and getattr(self.client,'_hydra_owned',False):
                graph=getattr(self.client,'graph',None)
                if graph is not None:result['graph_inference']=graph.snapshot()
                if getattr(self.client,'graph_hook_error',None):
                    result['graph_inference']={'enabled':False,'last':{'strategy':'standard',
                        'fallback':True,'reason':'hook_unavailable','error_type':self.client.graph_hook_error}}
            result.update(installed=self.binary.is_file(), supported_formats=['GGUF', 'Safetensors tramite API locale'],
                          owned_process=bool(self.child), busy=self.request_lock.locked() or self.conversation_lock.locked())
            result['python_runtime_installed']=self.python_runtime.is_file()
            result['supported_formats']=['GGUF','Safetensors Â· CPU FP32 / GPU FP16','LoRA locale Â· Python CPU / GPU','API locale']
            result['context_per_slot']=(result.get('context')//(result.get('runtime') or {}).get('slots',1)) if result.get('context') else None
            result['public_model']='local/'+str(result['model']) if result.get('model') else None
            result['capabilities']=dict(text=True,images=False,mcp_bridge=True,web_tools=True,
                tool_calling='model_dependent',strata_expert_cache=False,strata_speculation=False)
            if result.get('mode')=='safetensors' and result.get('status')=='ready':
                result['capabilities'].update(tool_calling=result.get('native_tool_calling',False),mcp_bridge=result.get('native_tool_calling',False))
            inputs=result.get('input_modalities') or ['text']
            result['capabilities'].update(images='image' in inputs,audio_input='audio' in inputs,
                video_input='video' in inputs,image_generation=False,audio_generation=False,
                modality_source='api_model_metadata' if result.get('input_modalities') else 'text_only_integration')
            result['model_discovery']=dict(self.discovery.state) if self.discovery else None
            result['models_root']=str(self.models_root)
            result['models_roots']=[str(path) for path in self.models_roots]
            try:
                result['training_preflight']=json.loads((self.root/'data/unsloth-preflight.json').read_text(encoding='utf-8'))
            except (OSError,ValueError):result['training_preflight']=None
            if include_models and time.monotonic()-self.model_cache_at>120:
                self.model_cache=[]
                seen=set()
                for path in (p for folder in self.models_roots for p in (folder.rglob('*.gguf') if folder in self.models_roots[:4] else folder.glob('*.gguf'))):
                    import re
                    if path.is_relative_to(self.models_root/'audio'):continue
                    if path.name.lower().startswith(('mtp','mmproj','ggml-vocab')):continue
                    from serve.gguf_parts import identity,local_parts,weight_bytes
                    try:split=identity(path.name)
                    except ValueError:continue
                    if split and split[1]!=1:continue
                    try:
                        pieces=local_parts(path);size=sum(piece.stat().st_size for piece in pieces)
                        if str(path.resolve()) in seen:continue
                        with path.open('rb') as stream:
                            if stream.read(4)!=b'GGUF':continue
                        seen.add(str(path.resolve()))
                        source='Unsloth / Hugging Face' if path.is_relative_to(self.models_roots[1]) or path.is_relative_to(self.models_roots[2]) else 'Strata-data' if path.is_relative_to(self.models_roots[0]) else 'Disco locale'
                        repo=next((part.removeprefix('models--').replace('--','/') for part in path.parts if part.startswith('models--')),None)
                        from serve.gguf_runtime_compatibility import unsupported_reason
                        reason=unsupported_reason(path,self.root)
                        projectors=[str(p.resolve()) for p in path.parent.glob('*mmproj*.gguf')]
                        from serve.model_engine_requirements import requirement
                        engine=requirement(self.root,path)
                        from serve.gguf_runtime_compatibility import file_role,requires_prism
                        self.model_cache.append(dict(name=path.stem,path=str(path.resolve()),bytes=size,source=source,repo=repo,format='GGUF',file_role=file_role(path),runtime_family='prism' if requires_prism(path) else 'standard',parts=len(pieces),part_files=[{'file':piece.name,'bytes':piece.stat().st_size} for piece in pieces],runtime_supported=(reason is None or engine.get('strata_ready',False)),runtime_error=reason,paired_projectors=projectors,**engine))
                    except (OSError,ValueError):continue
                from serve.safetensors_runtime import inspect_model
                for folder in self.models_roots:
                    for config in (folder.rglob('config.json') if folder in self.models_roots[:4] else folder.glob('config.json')):
                        try:
                            info=inspect_model(config.parent.resolve(),allow_unsupported=True)
                            if info['path'] in seen:continue
                            seen.add(info['path'])
                            repository=next((part.removeprefix('models--').replace('--','/') for part in config.parts if part.startswith('models--')),None)
                            if not repository:
                                candidate=config.parent.parent.name
                                if '--' in candidate:repository=candidate.replace('--','/',1)
                            self.model_cache.append(dict(name=repository.split('/')[-1] if repository else config.parent.name,path=info['path'],bytes=info['bytes'],
                                source='Safetensors locale',repo=repository,format='Safetensors',model_max_context=info['model_max_context'],checkpoint_quantization=info['checkpoint_quantization'],runtime_supported=info['runtime_supported'],runtime_error=info['runtime_error']))
                        except (OSError,ValueError,KeyError,TypeError):continue
                self.model_cache.sort(key=lambda row:row['name'])
                self.model_cache_at=time.monotonic()
            result['local_models']=copy.deepcopy(self.model_cache)
            result['load_seconds']=max(0,(result.get('ready_at') or time.time())-result['started_at']) if result.get('started_at') and result['status'] in ('loading','ready') else None
            result['process_resources']=None
            if self.child and self.child.poll() is None:
                try:
                    import psutil
                    memory=psutil.Process(self.child.pid).memory_info()
                    result['process_resources']=dict(pid=self.child.pid,rss_bytes=memory.rss,virtual_bytes=memory.vms,
                        private_bytes=getattr(memory,'private',None),scope='owned_backend_process',sampled_at=time.time())
                except (OSError,psutil.Error):pass
            result['gpu_process_resources']=None
            if self.child and self.child.poll() is None and result.get('mode')=='safetensors':
                try:
                    sample=json.loads((self.root/'output/verification/optional-gpu-memory.json').read_text(encoding='utf-8'))
                    owned_pids={self.child.pid}|{p.pid for p in psutil.Process(self.child.pid).children(recursive=True)}
                    if sample.get('pid') in owned_pids and 0<=time.time()-sample.get('sampled_at',0)<=10 and sample.get('device')=='cuda':result['gpu_process_resources']=sample
                except (OSError,ValueError,TypeError,psutil.Error):pass
            result['device_requested']='ROCm GPU' if result.get('gpu_requested') else 'CPU' if result.get('mode') in ('gguf','safetensors') else 'API'
            log=self.root/'output/verification/optional-backend-server.log'
            if log.is_file() and result.get('mode') in ('gguf','safetensors') and result['status']!='idle':
                with log.open('rb') as stream:
                    stream.seek(max(0,log.stat().st_size-4096))
                    result['diagnostic_log']=stream.read().decode('utf-8',errors='replace')
            return result

    def _release(self):
        if self.lease:
            self.lease.release()
            self.lease=None

    def api_client(self,payload):
        key=payload.get('api_key') or None
        if key is not None and (not isinstance(key,str) or len(key)>4096 or '\n' in key or '\r' in key):
            raise ValueError('Chiave API non valida')
        client=LocalOpenAIBackend(payload.get('url',''),api_key=key,timeout=10)
        from urllib.parse import urlsplit
        if (urlsplit(payload['url']).port or 80)==self.dashboard_port:raise ValueError('Collega il backend esterno, non lâ€™endpoint della dashboard stessa')
        return client

    def probe_api(self,payload):
        # Model discovery does not load weights or claim ownership of the app.
        return {'models':[dict(id=row['id'],**LocalOpenAIBackend.model_metadata(row)) for row in self.api_client(payload).models()][:200]}

    def python_context_plan(self,payload):
        from serve.safetensors_runtime import inspect_model
        import psutil
        info=inspect_model(Path(payload.get('model_path','')).expanduser());free=psutil.virtual_memory().available/2**30
        gpu=payload.get('gpu') is True;weights=info['bytes']*(1 if gpu else 2)/2**30;kv=info['kv_bytes_per_token'];kv=kv//2 if gpu and kv else kv
        weights+=info.get('image_memory_reserve_bytes',0)/2**30
        airllm=(payload.get('runtime') or {}).get('python_loader')=='airllm'
        if airllm:
            from serve.airllm_runtime import inspect_checkpoint,validate_options
            runtime=payload.get('runtime') or {}
            validate_options('cuda' if gpu else 'cpu',payload.get('adapter_path'),runtime.get('python_draft_path'),runtime.get('python_quantization','none'),runtime.get('python_attention','auto'),runtime.get('python_cache','auto'))
            weights=inspect_checkpoint(payload['model_path'])['conversion_ram_bytes']/2**30
        draft=(payload.get('runtime') or {}).get('python_draft_path')
        if draft:
            draft_info=inspect_model(Path(draft).expanduser())
            if draft_info['bytes']>1024**3:raise ValueError('Draft Python limit: 1 GiB')
            info['model_max_context']=min(info['model_max_context'],draft_info['model_max_context'])
            weights+=draft_info['bytes']*(1 if gpu else 2)/2**30
            if kv and draft_info['kv_bytes_per_token']:kv+=draft_info['kv_bytes_per_token']//2 if gpu else draft_info['kv_bytes_per_token']
            else:kv=None
        snapshot=self.memory_snapshot() if gpu else {};now=snapshot.get('now') or {};gpu_free=((now.get('gpu_mem_total') or 0)-(now.get('gpu_mem_used') or 0))/2**30 if gpu else None
        if gpu and (not gpu_free or gpu_free<=4):raise ValueError('Memoria GPU disponibile non rilevabile o margine inferiore a 4 GiB')
        maximum=min(info['model_max_context'],4194304)
        contexts=sorted(set([c for c in (1024,2048,4096,8192,16384,32768,65536,131072,262144,524288,1048576,maximum) if c<=maximum]))
        rows=[]
        for context in contexts:
            cache=context*kv/2**30 if kv else None
            estimated=weights+(cache if cache is not None else 2)+2
            rows.append(dict(context=context,context_per_slot=context,kv_gib=cache,weights_gib=weights,
                compute_buffers_gib=2,checkpoint_ram_gib=0,cache_ram_gib=0,gpu_estimated_alloc_gib=estimated if gpu else 0,ram_estimated_upper_gib=weights+2 if gpu else estimated,
                ram_required_gib=estimated+8,fits=(estimated+4<=gpu_free and weights+10<=free if gpu else estimated+8<=free) and (kv is not None or context<=4096),
                mixed_cpu_gpu=False,gpu_required_gib=estimated+4 if gpu else 0))
        eligible=[r['context'] for r in rows if r['fits']]
        return dict(model_max_context=info['model_max_context'],recommended_context=max(eligible,default=None),
            options=rows,kv_bytes_per_token=kv,kv_type='f16' if gpu else 'f32',slots=1,ram_free_gib=free,gpu_free_gib=gpu_free,gpu_budget_gib=max(0,gpu_free-4) if gpu else None,
            weights_gib=weights,quantization=(payload.get('runtime') or {}).get('python_quantization','none'),scope='GPU FP16 upper-bound estimate with 4 GiB GPU margin' if gpu else 'Conservative CPU FP32 estimate, 2 GiB compute buffers and 8 GiB system margin; not a speed optimum')

    def context_plan(self,payload):
        from serve.model_engine_requirements import assert_optional_engine
        assert_optional_engine(self.root,payload)
        if payload.get('mode')=='safetensors':return self.python_context_plan(payload)
        path=Path(payload.get('model_path','')).expanduser()
        if not path.is_absolute() or not path.is_file():raise ValueError('Seleziona un file GGUF locale')
        with path.open('rb') as stream:
            if stream.read(4)!=b'GGUF':raise ValueError('File non GGUF')
        from serve.catalogue import read_gguf_header
        from serve.context_profiles import plan
        import psutil,re
        metadata=read_gguf_header(path.as_uri(),nbytes=16<<20)['meta']
        gpu_free=None;gpu_total=None;memory_source='runtime'
        runtime=payload.get('runtime') or {}
        if payload.get('gpu'):
            result=subprocess.run([str(self.binary),'--list-devices'],cwd=self.binary.parent,capture_output=True,text=True,timeout=15)
            match=re.search(r'(\d+) MiB free',result.stdout+result.stderr)
            if result.returncode or not match:raise ValueError('Memoria GPU disponibile non rilevabile')
            gpu_free=int(match[1])*2**20
            total=re.search(r'\((\d+) MiB,',result.stdout+result.stderr) or re.search(r'(\d+) MiB total',result.stdout+result.stderr)
            gpu_total=int(total[1])*2**20 if total else None
            snapshot=getattr(self,'memory_snapshot',lambda:{})()
            hardware=snapshot.get('now',{});name=snapshot.get('static',{}).get('gpu_name')
            used=hardware.get('gpu_mem_used');physical=hardware.get('gpu_mem_total')
            import math
            if (name and name.lower() in (result.stdout+result.stderr).lower() and
                all(type(value) in (int,float) and math.isfinite(value) for value in (used,physical)) and
                used>=0 and physical>0 and gpu_total and abs(physical/gpu_total-1)<.05):
                gpu_free=min(gpu_free,max(0,int(physical-used)));memory_source='runtime_and_system_telemetry'
        from serve.gguf_parts import weight_bytes
        resources=plan(metadata,weight_bytes(path),psutil.virtual_memory().available,gpu_free,kv_type=runtime.get('kv_type','f16'),slots=runtime.get('slots',1),cache_ram_mib=runtime.get('cache_ram_mib',1024),checkpoints=runtime.get('checkpoints',8),gpu_total=gpu_total,vram_percent=runtime.get('vram_percent',85))
        resources['gpu_memory_source']=memory_source if gpu_free is not None else None
        from serve.local_vision import budget
        return budget(resources,payload)

    def fit_model(self,payload):
        from serve.model_engine_requirements import assert_optional_engine
        assert_optional_engine(self.root,payload)
        import os
        from serve.host_adaptation import thread_proposal
        selected_runtime=payload.get('runtime') or {}
        if not isinstance(selected_runtime,dict):raise ValueError('Configurazione runtime non valida')
        threads,threads_batch,host=thread_proposal(getattr(self,'memory_snapshot',lambda:{})(),selected_runtime.get('threads'))
        if payload.get('mode')=='safetensors':
            resources=self.python_context_plan(payload)
            goal=payload.get('fit_goal','context')
            if goal not in ('speed','context','balanced','compact'):raise ValueError('PrioritÃ  fit non valida')
            eligible=[row['context'] for row in resources['options'] if row['fits']]
            if not eligible:raise ValueError('RAM disponibile insufficiente per il modello Python e i margini protetti')
            # Older saved goal names remain readable, but cannot cap model context.
            goal='speed' if goal=='speed' else 'context'
            requested=payload.get('context',4096)
            if type(requested) is not int or requested<1024:raise ValueError('Contesto richiesto non valido')
            target=(max((value for value in eligible if value<=requested),default=min(eligible)) if goal=='speed' else max(eligible))
            resources['recommended_context']=target
            resources['host']=host
            resources['recommended']=dict(gpu=payload.get('gpu') is True,profile='balanced',runtime=dict(threads=threads),
                context=target,context_mode='auto',fit_mode='auto',fit_goal=goal)
            for name in ('python_loader','python_quantization','python_attention','python_draft_path','python_cache'):
                if name in (payload.get('runtime') or {}):resources['recommended']['runtime'][name]=payload['runtime'][name]
            resources['recommendation_note']='Conservative GPU FP16 resource estimate; not a benchmark-certified performance optimum' if payload.get('gpu') else 'Conservative CPU FP32 resource estimate; not a benchmark-certified performance optimum'
            return resources
        selected=payload.get('runtime',{})
        if not isinstance(selected,dict):raise ValueError('Configurazione runtime non valida')
        runtime=dict(batch=512 if payload.get('gpu',True) else 128,micro_batch=128,
                     threads=threads,threads_batch=threads_batch,
                     flash_attention='auto',kv_type='f16',slots=1,cache_ram_mib=1024,checkpoints=8,
                     vram_percent=selected.get('vram_percent',85),load_mode='auto',spec_type='none',reasoning_budget=-1)
        if selected.get('kv_type','f16') not in ('f16','q8_0','q4_0'):raise ValueError('Formato KV non supportato')
        if type(selected.get('slots',1)) is not int or selected.get('slots',1) not in (1,2,4):raise ValueError('Slot supportati: 1, 2, 4')
        for name,minimum,maximum in [('vram_percent',50,95),('cache_ram_mib',0,8192),('checkpoints',0,32)]:
            if name in selected and (type(selected[name]) is not int or not minimum<=selected[name]<=maximum):raise ValueError('Parametro risorse non valido: '+name)
        for name in ('kv_type','slots','vram_percent','cache_ram_mib','checkpoints'):
            if name in selected:runtime[name]=selected[name]
        use_gpu=payload.get('gpu',True)
        proposed={**payload,'gpu':use_gpu,'runtime':runtime}
        try:resources=self.context_plan(proposed)
        except ValueError:
            if not use_gpu or payload.get('fit_goal')=='speed':raise
            use_gpu=False;proposed['gpu']=False;resources=self.context_plan(proposed)
        if not resources['recommended_context'] and use_gpu:
            if payload.get('fit_goal')=='speed':raise ValueError('Il profilo velocitÃ  richiede risorse GPU disponibili; riduci il contesto o scegli una quantizzazione piÃ¹ piccola')
            use_gpu=False;proposed['gpu']=False;runtime['batch']=128;resources=self.context_plan(proposed)
        if not resources['recommended_context']:raise ValueError('Il modello non entra nelle risorse disponibili con i margini protetti; scegli una quantizzazione piÃ¹ piccola')
        if not use_gpu:runtime['batch']=128
        goal=payload.get('fit_goal','context')
        if goal not in ('speed','context','balanced','compact'):raise ValueError('PrioritÃ  fit non valida')
        eligible=[row['context'] for row in resources['options'] if row['fits']]
        goal='speed' if goal=='speed' else 'context'
        requested=payload.get('context',4096)
        if type(requested) is not int or requested<1024:raise ValueError('Contesto richiesto non valido')
        target=(max((value for value in eligible if value<=requested),default=min(eligible)) if goal=='speed' else max(eligible))
        resources['recommended_context']=target
        resources['recommended']=dict(gpu=use_gpu,profile='rocm' if use_gpu else 'balanced',runtime=runtime,
            context=resources['recommended_context'],context_mode='auto',fit_mode='auto',fit_goal=goal)
        resources['recommendation_note']='Balanced resource heuristic, not a benchmark-certified performance optimum; sampling and tool choices are preserved'
        resources['host']=host
        from serve.host_adaptation import measured_proposal
        measured=measured_proposal(self.root,payload.get('model_path',''),use_gpu,host,resources['recommended_context'])
        if measured:
            for key in ('threads','threads_batch','batch','micro_batch','flash_attention','spec_type'):
                if key in measured['runtime']:resources['recommended']['runtime'][key]=measured['runtime'][key]
            resources['measured_recommendation']={key:measured[key] for key in ('source','median','scope','compared_profiles')}
        return resources

    def start(self, payload, operational_idle):
        if payload.get('engine_addon') is not None:
            from serve.hydra_control import normalize_start
            payload=normalize_start(self.root,payload)
            from serve.hydra_one import requested
            requested(payload)
        from serve.model_engine_requirements import assert_optional_engine
        assert_optional_engine(self.root,payload)
        if not operational_idle:
            raise RuntimeError('Ferma il motore Strata prima di avviare un backend separato')
        # Candidate updates apply only to the device actually validated.
        if not getattr(self,'candidate_validation',False):self.binary=Path.home()/'.unsloth/llama.cpp/build/bin/Release/llama-server.exe'
        if not getattr(self,'candidate_validation',False) and payload.get('mode','gguf')=='gguf' and not payload.get('gpu',False):
            import hashlib
            try:selection=json.loads((self.root/'data/runtime-selection.json').read_text(encoding='utf-8')).get('active')
            except (OSError,ValueError):selection=None
            if selection:
                directory=Path(selection['directory']).resolve()
                if selection.get('scope')!='llama_cpu' or not directory.is_relative_to((self.root/'output/updates/candidates').resolve()):
                    raise ValueError('Invalid active candidate; roll back the runtime selection')
                for row in selection['files']:
                    file=(directory/row['path']).resolve()
                    if not file.is_relative_to(directory) or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=row['sha256']:
                        raise ValueError('Active candidate has changed; roll back the runtime selection')
                self.binary=Path(selection['binary'])
        if not getattr(self,'candidate_validation',False) and payload.get('mode','gguf')=='gguf' and payload.get('gpu',False):
            from serve.llama_gpu_update import selected_binary
            gpu_binary=selected_binary(self.root)
            if gpu_binary:self.binary=gpu_binary
        mode=payload.get('mode','gguf')
        if mode not in ('gguf','safetensors','api'):raise ValueError('Backend non riconosciuto')
        from serve.local_vision import projector
        vision_projector=projector(payload)
        if vision_projector and mode!='gguf':raise ValueError('Local vision projector requires a GGUF backend')
        if mode=='gguf':
            from serve.gguf_runtime_compatibility import unsupported_reason
            reason=unsupported_reason(payload.get('model_path',''),self.root,gpu=bool(payload.get('gpu',False)))
            if reason:raise ValueError(reason)
            from serve.gguf_runtime_compatibility import requires_prism,prism_binary
            if requires_prism(payload.get('model_path','')):
                self.binary=prism_binary(self.root,gpu=bool(payload.get('gpu',False)))
                if self.binary is None:raise ValueError('Prism GPU runtime unavailable or modified')
        if payload.get('fit_mode','manual') not in ('auto','manual'):raise ValueError('ModalitÃ  fit non valida')
        if mode in ('gguf','safetensors') and payload.get('fit_mode')=='auto':
            fitted=self.fit_model(payload)['recommended']
            payload={**payload,**fitted}
        profile=payload.get('profile','balanced')
        context=payload.get('context',4096)
        if payload.get('context_mode','manual') not in ('auto','manual'):raise ValueError('ModalitÃ  del contesto non valida')
        if type(context) is not int or not 1024<=context<=4194304:raise ValueError('Seleziona un contesto da 1K al massimo dichiarato del modello')
        runtime=payload.get('runtime',{})
        inference=payload.get('inference_profile',{})
        if not isinstance(runtime,dict) or not isinstance(inference,dict):raise ValueError('Configurazione non valida')
        if runtime.keys()-{'batch','micro_batch','threads','threads_batch','flash_attention','kv_type','slots','cache_ram_mib','checkpoints','vram_percent','load_mode','spec_type','draft_path','draft_max','draft_min','draft_probability','reasoning_budget','reasoning_message','python_loader','python_quantization','python_attention','python_draft_path','python_cache'}:raise ValueError('Parametro runtime non supportato')
        for key,limit in [('threads',32),('threads_batch',32)]:
            if key in runtime and (type(runtime[key]) is not int or not 1<=runtime[key]<=limit):raise ValueError('Numero thread non valido')
        for key in ('batch','micro_batch'):
            if key in runtime and (type(runtime[key]) is not int or runtime[key] not in (64,128,256,512)):raise ValueError('Batch non supportato')
        if runtime.get('micro_batch',128)>runtime.get('batch',512 if profile=='rocm' else 128):raise ValueError('Micro batch maggiore del batch')
        if runtime.get('flash_attention','auto') not in ('auto','on','off'):raise ValueError('Flash Attention non valida')
        if 'reasoning_message' in runtime and (not isinstance(runtime['reasoning_message'],str) or len(runtime['reasoning_message'])>500):raise ValueError('Messaggio del budget ragionamento non valido')
        if runtime.get('kv_type','f16') not in ('f16','q8_0','q4_0'):raise ValueError('Formato KV non supportato')
        if type(runtime.get('slots',1)) is not int or runtime.get('slots',1) not in (1,2,4):raise ValueError('Slot supportati: 1, 2, 4')
        if runtime.get('load_mode','auto') not in ('auto','none','mmap','mlock','mmap+mlock'):raise ValueError('ModalitÃ  di caricamento non valida')
        if runtime.get('spec_type','none') not in ('none','ngram-simple','draft-mtp','draft-dspark','draft-dflash','draft-mtp,ngram-simple'):raise ValueError('Unsupported speculative decoding mode')
        for key in ('draft_min','draft_max'):
            if key in runtime and (type(runtime[key]) is not int or not (0 if key=='draft_min' else 1)<=runtime[key]<=64):raise ValueError('Draft token count outside supported range')
        if runtime.get('draft_min',0)>runtime.get('draft_max',3):raise ValueError('Minimum draft tokens exceed maximum')
        if 'draft_probability' in runtime and (type(runtime['draft_probability']) not in (int,float) or not math.isfinite(runtime['draft_probability']) or not 0<=runtime['draft_probability']<=1):raise ValueError('Draft probability must be between 0 and 1')
        if runtime.get('spec_type','none').startswith('draft-'):
            draft=Path(runtime.get('draft_path','')).resolve(strict=True)
            if not draft.is_file() or draft.suffix.lower()!='.gguf':raise ValueError('A matching local GGUF draft model is required')
            import psutil
            if draft.stat().st_size*2+4*1024**3>psutil.virtual_memory().available:raise ValueError('Insufficient RAM for additional draft model')
            runtime['draft_path']=str(draft)
        for key,minimum,maximum in [('cache_ram_mib',0,8192),('checkpoints',0,32),('vram_percent',50,95),('reasoning_budget',-1,4096)]:
            if key in runtime and (type(runtime[key]) is not int or not minimum<=runtime[key]<=maximum):raise ValueError('Parametro risorse non valido: '+key)
        if inference.keys()-{'temperature','top_p','max_tokens','thinking','web','tools'}:raise ValueError('Parametro di inferenza non supportato')
        if 'temperature' in inference and (type(inference['temperature']) not in (int,float) or not 0<=inference['temperature']<=2):raise ValueError('Temperatura non valida')
        if 'top_p' in inference and (type(inference['top_p']) not in (int,float) or not 0<inference['top_p']<=1):raise ValueError('Top-p non valido')
        if 'max_tokens' in inference and (type(inference['max_tokens']) is not int or not 1<=inference['max_tokens']<=4096):raise ValueError('Budget token non valido')
        if inference.get('thinking','none') not in ('none','low','medium','high'):raise ValueError('Ragionamento non valido')
        if 'web' in inference and type(inference['web']) is not bool:raise ValueError('Impostazione Internet non valida')
        if 'tools' in inference and (not isinstance(inference['tools'],list) or len(inference['tools'])>100 or any(not isinstance(name,str) or len(name)>200 for name in inference['tools'])):raise ValueError('Selezione strumenti non valida')
        if profile not in ('balanced','rocm'):raise ValueError('Profilo del backend non valido')
        if profile=='rocm' and (mode!='gguf' or payload.get('gpu') is not True):raise ValueError('Il profilo ROCm richiede un GGUF sulla GPU')
        if mode=='gguf':
            path=Path(payload.get('model_path','')).expanduser()
            if not path.is_absolute() or not path.is_file():raise ValueError('Seleziona il percorso assoluto di un GGUF locale')
            lora=payload.get('adapter_path')
            if lora:
                lora_path=Path(lora).expanduser()
                if not lora_path.is_absolute() or not lora_path.is_file() or lora_path.suffix.lower()!='.gguf':raise ValueError('Seleziona un adattatore LoRA GGUF locale')
                payload={**payload,'adapter_path':str(lora_path)}
            from serve.catalogue import read_gguf_header
            try:metadata=read_gguf_header(path.as_uri(),nbytes=16<<20)['meta']
            except Exception as error:
                if context>4096 or payload.get('context_mode')=='auto':raise ValueError('Metadati del contesto non leggibili: usa 4K manuale') from error
                metadata={}
            configuration=None
            if payload.get('context_mode')=='auto':
                configuration=self.context_plan(payload)
                if payload.get('fit_mode')!='auto':context=configuration['recommended_context']
                if not context:raise ValueError('Nessun contesto protetto entra nelle risorse disponibili')
                payload={**payload,'context':context}
            architecture=metadata.get('general.architecture')
            declared=metadata.get(str(architecture)+'.context_length')
            if declared is not None and context//runtime.get('slots',1)>declared:raise ValueError('Il contesto supera il massimo dichiarato dal modello')
            if context>4096 or runtime:
                configuration=configuration or self.context_plan(payload)
                selected=next((row for row in configuration['options'] if row['context']==context),None)
                if not selected:raise ValueError('Impossibile stimare questo contesto per il modello')
                if selected['kv_gib'] is None and context>4096 and payload.get('fit_mode')!='auto':raise ValueError('Stima KV non disponibile: usa fit automatico del runtime')
                if not selected['fits']:raise ValueError('Il contesto scelto supera la memoria disponibile con i margini protetti')
                kv_bytes=int((selected['kv_gib'] or 0)*2**30)
            else:kv_bytes=0
            import re
            from serve.gguf_parts import weight_bytes
            model_bytes=weight_bytes(path)
            with path.open('rb') as stream:
                if stream.read(4)!=b'GGUF':raise ValueError('Il file non Ã¨ un GGUF')
            import psutil
            resource_row=next((row for row in (configuration or {}).get('options',[]) if row['context']==context),None)
            ram_required=resource_row['ram_required_gib']*2**30 if resource_row else model_bytes+kv_bytes+8*1024**3
            if vision_projector and not resource_row:ram_required+=vision_projector.stat().st_size*3
            if psutil.virtual_memory().available<ram_required:
                raise ValueError('Memoria RAM disponibile insufficiente: servono i pesi piÃ¹ 8 GiB di margine')
            if not self.binary.is_file():raise RuntimeError('Runtime Unsloth llama.cpp non installato')
            if type(payload.get('gpu',False)) is not bool:raise ValueError('Impostazione GPU non valida')
        elif mode=='safetensors':
            from serve.safetensors_runtime import inspect_model
            path=Path(payload.get('model_path','')).expanduser()
            native_info=inspect_model(path)
            if 'image' in native_info.get('input_modalities',[]) and (payload.get('gpu') or runtime.get('python_loader','transformers')!='transformers' or payload.get('adapter_path') or runtime.get('python_draft_path') or runtime.get('python_quantization','none')!='none'):
                raise ValueError('LLaVA immagini richiede Transformers CPU senza adapter, draft o quantizzazione')
            declared=native_info['model_max_context'];configuration=None
            if type(payload.get('gpu',False)) is not bool:raise ValueError('Impostazione GPU non valida')
            if payload.get('gpu'):
                try:probe=json.loads((self.root/'output/verification/amd-gpu-bounded-probe.json').read_text(encoding='utf-8'))
                except (OSError,ValueError):probe={}
                if probe.get('passed') is not True or time.time()-probe.get('finished_at',0)>86400:raise ValueError('Verifica GPU locale recente richiesta prima del caricamento Python')
            from serve.python_inference_update import selected_python
            original_python=Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe'
            if runtime.get('python_loader')=='airllm':
                from serve.airllm_runtime import verify_environment as airllm_python,validate_options
                validate_options('cuda' if payload.get('gpu') else 'cpu',payload.get('adapter_path'),runtime.get('python_draft_path'),runtime.get('python_quantization','none'),runtime.get('python_attention','auto'),runtime.get('python_cache','auto'))
                chosen_python=airllm_python(self.root)
            else:chosen_python=selected_python(self.root,original_python,gpu=True) if payload.get('gpu') else selected_python(self.root,original_python)
            self.python_runtime=chosen_python
            if not self.python_runtime.is_file():raise ValueError('Ambiente Python Unsloth non trovato')
            if profile!='balanced':raise ValueError('Il runtime Python CPU usa il profilo bilanciato')
            if runtime.keys()-{'threads','python_loader','python_quantization','python_attention','python_draft_path','python_cache'}:raise ValueError('Il runtime Python accetta thread e loader; i parametri GGUF non vengono applicati')
            if runtime.get('python_quantization','none') not in ('none','nf4'):raise ValueError('Quantizzazione Python non valida')
            if runtime.get('python_quantization')=='nf4' and (not payload.get('gpu') or runtime.get('python_loader')!='unsloth'):raise ValueError('NF4 richiede Unsloth nativo GPU e un modello base')
            from serve.safetensors_runtime import attention_options,cache_options
            cache_options(runtime.get('python_loader','transformers'),runtime.get('python_cache','auto'))
            if runtime.get('python_draft_path') and runtime.get('python_cache')=='off':raise ValueError('Draft Python richiede cache KV attiva')
            attention_options(runtime.get('python_loader','transformers'),runtime.get('python_attention','auto'))
            if runtime.get('python_loader','transformers') not in ('transformers','unsloth','airllm'):raise ValueError('Loader Python non valido')
            if runtime.get('python_loader')=='unsloth' and (not payload.get('gpu') or (payload.get('adapter_path') and runtime.get('python_quantization')!='nf4')):raise ValueError('Adapter Unsloth nativo richiede GPU e NF4')
            if runtime.get('python_draft_path') and (runtime.get('python_loader','transformers')!='transformers' or payload.get('adapter_path')):raise ValueError('Draft Python richiede Transformers senza adapter')
            configuration=self.python_context_plan(payload)
            if payload.get('context_mode')=='auto':
                if payload.get('fit_mode')!='auto':context=configuration['recommended_context']
                if not context:raise ValueError('Nessun contesto entra nella RAM disponibile con i margini protetti')
                payload={**payload,'context':context}
            if context>declared:raise ValueError('Il contesto supera il limite del modello')
            if payload.get('gpu') and not any(row['context']>=context and row['fits'] for row in configuration['options']):raise ValueError('Configurazione oltre il budget GPU disponibile')
            adapter=payload.get('adapter_path')
            if adapter:
                from serve.safetensors_runtime import validate_adapter
                validate_adapter(adapter,path)
            import psutil
            if context>configuration['model_max_context']:raise ValueError('Il contesto supera il limite del modello o del draft')
            combined_kv=configuration.get('kv_bytes_per_token',native_info['kv_bytes_per_token'])
            if combined_kv is None and context>4096:raise ValueError('KV non stimabile per un contesto superiore a 4K nel runtime Python')
            kv_requirement=context*combined_kv if combined_kv else (4 if runtime.get('python_draft_path') else 2)*2**30
            combined_weights=configuration.get('weights_gib',native_info['bytes']*2/2**30)*2**30
            if not payload.get('gpu') and psutil.virtual_memory().available<combined_weights+kv_requirement+10*2**30:
                raise ValueError('RAM disponibile insufficiente per il runtime CPU FP32 e il margine di 8 GiB')
        else:
            self.api_client(payload)
            model=payload.get('model')
            if not isinstance(model,str) or not model:raise ValueError('Inserisci lâ€™ID effettivo del modello esterno')
        hydra_plan=None
        if payload.get('engine_addon')=='hydra-one':
            from serve.hydra_control import model_plan
            hydra_plan=model_plan(self,{**payload,'fit_mode':'manual'})
            if not hydra_plan['available']:raise ValueError(hydra_plan['reason'])
        with self.lock:
            if self.state['status'] in ('loading','ready'):raise RuntimeError('Un backend Ã¨ giÃ  collegato: arrestalo prima di cambiare')
            shared = mode=='api' and bool(getattr(self,'external_api_lease',lambda _:False)(payload))
            self.lease=None if shared else GpuLease(self.root,'optional-backend').acquire()
            # Each load owns its cancellation token; a stopped worker must never
            # update or terminate a subsequently started backend.
            self.cancel_load = threading.Event()
            self.state=dict(status='loading',error=None,backend='Unsloth llama.cpp' if mode=='gguf' else 'AirLLM Â· CPU layer streaming' if mode=='safetensors' and runtime.get('python_loader')=='airllm' else 'Transformers Â· ambiente Unsloth' if mode=='safetensors' else 'API locale',
                              model=path.stem if mode in ('gguf','safetensors') else model,model_path=str(path) if mode in ('gguf','safetensors') else None,
                              adapter_path=str(payload['adapter_path']) if payload.get('adapter_path') else None,
                              mode=mode,profile=profile,started_at=time.time(),requests=0,gpu_requested=bool(payload.get('gpu')),
                              fit_goal=payload.get('fit_goal','context'),fit_mode=payload.get('fit_mode','manual'),runtime=runtime,inference_profile=inference,context=context,context_mode=payload.get('context_mode','manual'),context_plan=configuration if mode in ('gguf','safetensors') else None,model_max_context=declared if mode in ('gguf','safetensors') else None,
                              request_history=[],rate_history=[],totals=dict(since=time.time(),requests=0,prompt_tokens=0,output_tokens=0,reused=0,prompt_ms=0,decode_ms=0))
            self.state['verification_fixture']=mode=='safetensors' and (path/'FIXTURE-NOT-A-TRAINED-MODEL.txt').is_file()
            if mode=='gguf':
                from serve.gguf_runtime_compatibility import requires_prism
                if requires_prism(path):self.state['backend']='Prism llama.cpp · HIP'
            self.state.update(vision_device=payload.get('vision_device','cpu') if vision_projector else None,vision_requested=bool(vision_projector),mmproj_path=str(vision_projector) if vision_projector else None)
            if hydra_plan is not None:self.state['hydra_plan']=hydra_plan
            threading.Thread(target=self._load,args=(mode,payload,path if mode in ('gguf','safetensors') else None,self.cancel_load),daemon=True).start()
        return self.status()

    def _load(self,mode,payload,path,cancel):
        try:
            if mode=='gguf':
                import socket
                with socket.socket() as probe:
                    if probe.connect_ex(('127.0.0.1',8091))==0:raise RuntimeError('La porta dedicata 8091 Ã¨ giÃ  occupata')
                if payload.get('gpu'):
                    result=subprocess.run([str(self.binary),'--list-devices'],cwd=self.binary.parent,
                                          capture_output=True,text=True,timeout=30)
                    import re
                    free=re.search(r'(\d+) MiB free',result.stdout+result.stderr)
                    from serve.catalogue import read_gguf_header
                    ctx=payload.get('context',4096)
                    meta=read_gguf_header(path.as_uri(),nbytes=16<<20)['meta'] if ctx>4096 else {};arch=meta.get('general.architecture')
                    selected=next((row for row in (self.state.get('context_plan') or {}).get('options',[]) if row['context']==ctx),None)
                    kv_extra=(selected.get('kv_gib') or 0)*1024 if selected else 0
                    if ctx>4096 and not selected:
                        from serve.context_profiles import plan
                        per_token=plan(meta,0,10**18)['kv_bytes_per_token']
                        if not per_token:raise ValueError('Memoria KV non stimabile')
                        kv_extra=(next((row['kv_gib'] for row in self.state.get('context_plan',{}).get('options',[]) if row['context']==ctx),None) or per_token*ctx/2**30)*1024
                    protected_min=1536 if self.state.get('context_plan') else 4096
                    if result.returncode or not free or int(free[1])<protected_min:
                        raise RuntimeError('Memoria GPU insufficiente per il profilo protetto; prova prima il caricamento CPU')
                output=self.root/'output/verification/optional-backend-server.log'
                output.parent.mkdir(parents=True,exist_ok=True)
                command=[str(self.binary),'-m',str(path),'--host','127.0.0.1','--port','8091',
                         '--alias','optional-model','-c',str(payload.get('context',4096)),'-np',str((payload.get('runtime') or {}).get('slots',1)),'-b','128','-ub','128','-ngl','auto' if payload.get('gpu') else '0','--fit','on' if payload.get('gpu') else 'off']
                if payload.get('profile')=='rocm':
                    command[command.index('-b')+1]='512'
                    command+=['--threads','8','--threads-batch','16','--flash-attn','auto','--fit-target','4096']
                runtime=payload.get('runtime') or {}
                command += ['--cache-type-k',runtime.get('kv_type','f16'),'--cache-type-v',runtime.get('kv_type','f16'),
                            '--ctx-checkpoints',str(runtime.get('checkpoints',8)),'--cache-ram',str(runtime.get('cache_ram_mib',1024)),
                            '--load-mode',runtime.get('load_mode','auto'),'--spec-type',runtime.get('spec_type','none'),
                            '--reasoning-budget',str(runtime.get('reasoning_budget',-1))]
                if runtime.get('spec_type','none').startswith('draft-'):
                    command+=['--spec-draft-model',runtime['draft_path']]
                    for key,flag in [('draft_min','--spec-draft-n-min'),('draft_max','--spec-draft-n-max'),('draft_probability','--spec-draft-p-min')]:
                        if key in runtime:command += [flag,str(runtime[key])]
                if runtime.get('reasoning_message'):command += ['--reasoning-budget-message',runtime['reasoning_message']]
                if payload.get('vision'):
                    from serve.local_vision import runtime_arguments
                    command+=runtime_arguments(payload,self.binary)
                if payload.get('gpu') and self.state.get('context_plan'):
                    budget=self.state['context_plan'];total_gib=(budget.get('gpu_budget_gib') or 0)*100/runtime.get('vram_percent',85)
                    reserve=max(1536,int(total_gib*1024*(1-runtime.get('vram_percent',85)/100)))
                    if '--fit-target' in command:command[command.index('--fit-target')+1]=str(reserve)
                    else:command += ['--fit-target',str(reserve)]
                for key,flag in [('batch','-b'),('micro_batch','-ub')]:
                    if key in runtime:command[command.index(flag)+1]=str(runtime[key])
                for key,flag in [('threads','--threads'),('threads_batch','--threads-batch'),('flash_attention','--flash-attn')]:
                    if key in runtime:
                        if flag in command:command[command.index(flag)+1]=str(runtime[key])
                        else:command += [flag,str(runtime[key])]
                if payload.get('adapter_path'):command+=['--lora',str(payload['adapter_path'])]
                with output.open('w',encoding='utf-8') as log:
                    with self.lock:
                        if cancel.is_set() or cancel is not self.cancel_load:return
                        self.child=subprocess.Popen(command,cwd=self.binary.parent,stdout=log,stderr=subprocess.STDOUT,
                                                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                        child=self.child
                client=LocalOpenAIBackend('http://127.0.0.1:8091/v1',timeout=2)
                deadline=time.monotonic()+180
                while not cancel.wait(.5):
                    if child.poll() is not None:
                        lines=output.read_text(encoding='utf-8',errors='replace').splitlines()
                        reason=' | '.join(lines[-6:])[-1800:]
                        raise RuntimeError('Avvio del runtime non riuscito: '+reason)
                    try:
                        ids=[m['id'] for m in client.models()]
                        if 'optional-model' in ids:break
                    except (OSError,ValueError,RuntimeError):pass
                    if time.monotonic()>deadline:raise RuntimeError('Tempo di caricamento superato')
                if cancel.is_set():return
                # Prefill can exceed 30 seconds with long conversation history.
                # This is an inactivity timeout, not a generation token budget.
                client.timeout=300
                model='optional-model'
            elif mode=='safetensors':
                import socket
                with socket.socket() as probe:
                    if probe.connect_ex(('127.0.0.1',8091))==0:raise RuntimeError('Porta dedicata 8091 occupata')
                output=self.root/'output/verification/optional-backend-server.log';output.parent.mkdir(parents=True,exist_ok=True)
                command=[str(self.python_runtime),'-X','utf8',str(self.root/'serve/safetensors_runtime.py'),
                         '--model',str(path),'--context',str(payload.get('context',4096)),
                         '--cache',(payload.get('runtime') or {}).get('python_cache','auto'),'--attention',(payload.get('runtime') or {}).get('python_attention','auto'),'--loader',(payload.get('runtime') or {}).get('python_loader','transformers'),'--quantization',(payload.get('runtime') or {}).get('python_quantization','none'),'--threads',str((payload.get('runtime') or {}).get('threads',8)),'--device','cuda' if payload.get('gpu') else 'cpu','--telemetry-file',str(self.root/'output/verification/optional-gpu-memory.json')]
                if (payload.get('runtime') or {}).get('python_draft_path'):command+=['--draft-model',payload['runtime']['python_draft_path']]
                if payload.get('adapter_path'):command+=['--adapter',payload['adapter_path']]
                with output.open('w',encoding='utf-8') as log:
                    with self.lock:
                        if cancel.is_set() or cancel is not self.cancel_load:return
                        self.child=subprocess.Popen(command,cwd=self.root,stdout=log,stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));child=self.child
                client=LocalOpenAIBackend('http://127.0.0.1:8091/v1',timeout=2);deadline=time.monotonic()+(3600 if (payload.get('runtime') or {}).get('python_loader')=='airllm' else 180)
                while not cancel.wait(.5):
                    if child.poll() is not None:raise RuntimeError('Runtime Python terminato: '+output.read_text(encoding='utf-8',errors='replace')[-1800:])
                    try:
                        if any(row['id']=='optional-model' for row in client.models()):break
                    except (OSError,ValueError,RuntimeError):pass
                    if time.monotonic()>deadline:raise RuntimeError('Tempo di caricamento Python superato')
                if cancel.is_set():return
                client.timeout=300;model='optional-model'
            else:
                client=self.api_client(payload)
                model=payload['model']
                model_row=next((row for row in client.models() if row['id']==model),None)
                if model_row is None:raise RuntimeError('Il modello richiesto non Ã¨ elencato dal backend')
                external_metadata=LocalOpenAIBackend.model_metadata(model_row)
                if model_row.get('owned_by')=='colibri':
                    client.max_output_tokens=32768
                    metadata=getattr(self,'external_api_metadata',None)
                    if metadata:external_metadata.update(metadata(payload))
            with self.lock:
                if not cancel.is_set() and cancel is self.cancel_load:
                    if payload.get('engine_addon')=='hydra-one':
                        from serve.hydra_one import wrap
                        client=wrap(self,client,payload)
                    self.client=client
                    self.state.update(status='ready',api_model=model,ready_at=time.time())
                    if payload.get('engine_addon')=='hydra-one':
                        self.state.update(backend='HYDRA ONE',engine_addon='hydra-one',
                            hydra=dict(mode='embedded',backend=self.state['mode'],
                                       disk_streaming='backend_specific_not_universal',adaptive_routing=False))
                    if mode=='safetensors':
                        native_row=next((row for row in client.models() if row['id']==model),{})
                        self.state.update(input_modalities=native_row.get('input_modalities',['text']),modality_source='owned_python_runtime')
                        self.state.update(native_loader=native_row.get('native_loader'),quantization=native_row.get('quantization','none'),loader_quantization=native_row.get('loader_quantization','none'),checkpoint_quantization=native_row.get('checkpoint_quantization'),adapter_loaded=native_row.get('adapter_loaded',False),backend='AirLLM Â· CPU layer streaming' if native_row.get('native_loader')=='airllm' else 'Unsloth native' if native_row.get('native_loader')=='unsloth' else 'Transformers Â· ambiente Unsloth',device=native_row.get('device'),dtype=native_row.get('dtype'),framework=native_row.get('framework'),framework_version=native_row.get('framework_version'),architecture=native_row.get('architecture'),model_type=native_row.get('model_type'),attention_implementation=native_row.get('attention_implementation'),cache_policy=native_row.get('cache_policy'),speculative_decoding=native_row.get('speculative_decoding'),python_executable=str(self.python_runtime),context_source='owned_python_runtime',native_tool_calling=native_row.get('tool_calling') is True,native_tool_protocol=native_row.get('tool_protocol'))
                    if mode=='safetensors' and payload.get('engine_addon')=='hydra-one':
                        from serve.hydra_one import python_storage_identity
                        identity=python_storage_identity(native_row)
                        self.state['backend']=identity['backend']
                        self.state['hydra']['storage']=identity['storage']
                    if mode=='api':
                        if external_metadata['publisher']=='colibri':self.state['backend']='Colibri'
                        self.state.update(model_max_context=external_metadata['model_max_context'],
                            context=external_metadata['active_context'],context_source=external_metadata['context_source'],
                            publisher=external_metadata['publisher'],input_modalities=external_metadata['input_modalities'],
                            runtime_managed_externally=True)
                    if mode=='gguf':
                        import urllib.request
                        with urllib.request.urlopen('http://127.0.0.1:8091/props',timeout=3) as response:props=json.load(response)
                        has_images=(props.get('modalities') or {}).get('vision') is True
                        if payload.get('vision') and not has_images:raise RuntimeError('Runtime did not activate the selected vision projector')
                        self.state.update(input_modalities=['text','image'] if has_images else ['text'],modality_source='owned_runtime_props')
                        import re
                        startup=output.read_text(encoding='utf-8',errors='replace')
                        slot=re.search(r'n_ctx_slot\s*=\s*(\d+)',startup)
                        if slot:
                            actual=int(slot[1])*self.state['runtime'].get('slots',1)
                            self.state.update(requested_context=self.state['context'],context=actual,context_fitted=actual!=self.state['context'],context_source='runtime_startup_log')
        except Exception as error:
            with self.lock:
                if cancel.is_set() or cancel is not self.cancel_load:return
                self.state.update(status='error',error=str(error))
                self._stop_child()
                self._release()

    def _stop_child(self):
        if getattr(self.client,'_hydra_owned',False) is True and not self.client.close():
            raise RuntimeError('HYDRA ONE: drain incerto; ownership conservata')
        from serve.process_lifecycle import stop_owned_tree
        stop_owned_tree(self.child)
        self.child=None

    def stop(self, *, _conversation_owned=False):
        with self.lock:
            if self.request_lock.locked() or (self.conversation_lock.locked() and not _conversation_owned):raise RuntimeError('Arresta prima la risposta in corso')
            self.cancel_load.set()
            self._stop_child()
            self.client=None
            self._release()
            external=self.state.get('mode')=='api'
            self.state.update(status='idle',model=None,api_model=None,error=None,
                              note='Disconnessione eseguita; il modello nellâ€™app esterna resta gestito da quellâ€™app' if external else None)
        return self.status()

    def close(self):
        """Server shutdown: cancel requests and stop only the owned process."""
        with self.lock:
            self.cancel_load.set()
            if self.active_cancel:self.active_cancel.set()
            self._stop_child();self.client=None;self._release()
            self.state.update(status='idle',model=None,api_model=None)

    def chat(self,payload,cancel):
        with self.lock:
            profile=dict(self.state.get('inference_profile',{}))
            defaults={key:value for key,value in profile.items() if key in ('temperature','top_p','max_tokens')}
        payload={**defaults,**payload}
        if profile.get('thinking')=='none' and 'reasoning_effort' not in payload and 'enable_thinking' not in (payload.get('chat_template_kwargs') or {}):
            payload={**payload,'chat_template_kwargs':{**(payload.get('chat_template_kwargs') or {}),'enable_thinking':False}}
        if not self.request_lock.acquire(blocking=False):raise RuntimeError('Una risposta del backend Ã¨ giÃ  in corso')
        completed=False
        try:
            with self.lock:
                if self.state['status']!='ready' or not self.client:raise RuntimeError('Collega prima un backend pronto')
                client,model=self.client,self.state['api_model']
                self.active_cancel=cancel
                self.state['activity']=dict(state='generating',started_at=time.time(),max_tokens=payload.get('max_tokens',128),timings=None,generated=0)
            options={k:payload[k] for k in ('temperature','top_p','seed','stop','tools','tool_choice','parallel_tool_calls','response_format','chat_template_kwargs','reasoning_effort','cache_prompt','cache_slot','enable_thinking') if k in payload}
            if (self.state.get('mode') in ('gguf','safetensors') or self.state.get('publisher')=='colibri') and 'top_k' in payload:
                if type(payload['top_k']) is not int or not 0<=payload['top_k']<=1000:raise ValueError('Top-k must be an integer in 0..1000')
                options['top_k']=payload['top_k']
            if self.state.get('mode')=='gguf' and payload.get('stream',True):options['timings_per_token']=True
            started=time.monotonic();usage=None;timings=None;finish=None
            messages=payload.get('messages')
            def request_events():
                observed=False
                try:
                    for packet in client.chat(messages,model,payload.get('max_tokens',128),stream=payload.get('stream',True),cancel=cancel,**options):
                        observed=True
                        yield packet
                except BackendError as error:
                    # HYDRA must not replay content or tool-call fragments already
                    # exposed to a harness/client, even on a context-limit error.
                    if self.state.get('engine_addon')=='hydra-one' and observed:raise
                    if self.state.get('mode')!='gguf' or not ('context' in str(error).lower() and ('exceed' in str(error).lower() or 'too large' in str(error).lower())):raise
                    # Retain the complete latest turn including its tool calls/results.
                    # Older messages remain untouched in the browser archive.
                    latest=max((i for i,m in enumerate(messages) if m.get('role')=='user'),default=0)
                    compact=([messages[0]] if messages and messages[0].get('role')=='system' and latest>0 else [])+messages[latest:]
                    if compact==messages:raise
                    with self.lock:self.state['context_recovery']=dict(at=time.time(),removed_messages=len(messages)-len(compact),reason='context_limit')
                    yield from client.chat(compact,model,payload.get('max_tokens',128),stream=payload.get('stream',True),cancel=cancel,**options)
            for event in request_events():
                event=dict(event);event['model']='local/'+str(self.state['model'])
                if event.get('usage'):usage=event['usage']
                if self.state.get('publisher')=='colibri':
                    with self.lock:
                        if usage and type(usage.get('completion_tokens')) is int:self.state['activity']['generated']=usage['completion_tokens']
                        elif any(choice.get('delta',{}).get('content') for choice in event.get('choices') or []):self.state['activity']['received_chunks']=self.state['activity'].get('received_chunks',0)+1

                for choice in event.get('choices') or []:
                    if choice.get('finish_reason'):finish=choice['finish_reason']
                if event.get('timings'):
                    timings=event['timings']
                    with self.lock:
                        self.state['activity']['timings']=timings
                        self.state.setdefault('rate_history',[]).append(dict(time=time.time(),decode=timings.get('predicted_per_second'),prefill=timings.get('prompt_per_second')))
                        self.state['rate_history']=self.state['rate_history'][-120:]
                yield event
            if not cancel.is_set():
                with self.lock:
                    self.state.update(requests=self.state['requests']+1,last_request=dict(wall_s=time.monotonic()-started,usage=usage,timings=timings))
                    u=usage or {};t=timings or {};reused=t.get('cache_n',(u.get('prompt_tokens_details') or {}).get('cached_tokens'))
                    row=dict(time=self.state['activity']['started_at'],finish=finish or 'stop',model='local/'+str(self.state['model']),
                             prompt_tokens=u.get('prompt_tokens'),output_tokens=u.get('completion_tokens'),reused=reused,
                             prompt_ms=t.get('prompt_ms'),decode_ms=t.get('predicted_ms'),decode_tok_s=t.get('predicted_per_second'),
                             prefill_tok_s=t.get('prompt_per_second'),generation_ms=t.get('generation_ms'),generation_tokens=t.get('generation_tokens'),timing_scope=t.get('timing_scope'),duration_s=time.monotonic()-started)
                    self.state.setdefault('request_history',[]).append(row);self.state['request_history']=self.state['request_history'][-100:]
                    if self.state.get('publisher')=='colibri' and type(row['output_tokens']) is int and row['duration_s']>0:
                        row['total_tok_s']=row['output_tokens']/row['duration_s']
                    totals=self.state.setdefault('totals',dict(since=time.time(),requests=0,prompt_tokens=0,output_tokens=0,reused=0,prompt_ms=0,decode_ms=0))
                    totals['requests']+=1
                    for key in ('prompt_tokens','output_tokens','reused','prompt_ms','decode_ms'):
                        totals[key]=totals[key]+row[key] if totals.get(key) is not None and row[key] is not None else None
                    completed=True
        finally:
            with self.lock:
                self.active_cancel=None
                if self.state.get('activity'):self.state['activity']['state']='complete' if completed else 'cancelled' if cancel.is_set() else 'error'
            self.request_lock.release()

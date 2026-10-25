"""Optional in-process HYDRA controller. Strata alone owns model processes."""
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
from serve.optional_inference import LocalOpenAIBackend

BUNDLE_SHA256='1b0cfe7cdc90a41370857f8c96dc8df96c9ae71420b39432be0a3db713f8f570'
_IMPORT_LOCK=threading.Lock()


def python_storage_identity(metadata):
    loader=metadata.get('native_loader');device=metadata.get('device')
    streaming=loader=='airllm' and device=='cpu'
    name='AirLLM CPU · streaming da disco' if streaming else 'Unsloth' if loader=='unsloth' else 'Transformers' if loader=='transformers' else 'runtime Python'
    return dict(backend='HYDRA ONE · '+name,storage=dict(
        strategy='backend_layer_streaming' if streaming else 'backend_managed_residency' if loader in ('transformers','unsloth') else 'unknown',
        source='observed_models_api',evidence_level='backend_declared',owner='native_backend',
        architecture=metadata.get('architecture'),nvme_device_verified=False,
        physical_read_bytes=None,universal_model_support=False))


def control_budget(payload):
    """Additional post-load headroom; resident weights/KV remain loader-owned."""
    limits=dict(host_limit_bytes=2*1024**3,host_reserve_bytes=8*1024**3,
        vram_limit_bytes=2*1024**3,vram_reserve_bytes=512*1024**2,
        request_memory_bytes=256*1024**2,vram_required_bytes=1024**3)
    supplied=payload.get('hydra_budget',{})
    if not isinstance(supplied,dict) or set(supplied)-set(limits):
        raise ValueError('Budget HYDRA non riconosciuto')
    for key,value in supplied.items():
        if type(value) is not int or value<0 or value>1024**5:
            raise ValueError('Limite HYDRA non valido: '+key)
    limits.update(supplied)
    if not limits['request_memory_bytes'] or limits['request_memory_bytes']>limits['host_limit_bytes']:
        raise ValueError('Headroom richiesta oltre il budget RAM HYDRA')
    if not limits['vram_required_bytes'] or limits['vram_required_bytes']+limits['vram_reserve_bytes']>limits['vram_limit_bytes']:
        raise ValueError('Headroom GPU oltre il budget VRAM HYDRA')
    return dict(limits,host_required_bytes=0,kv_required_bytes=None,
        scope='post_load_headroom_not_model_capacity',model_budget_owner='strata_model_loader')


def requested(payload):
    value=payload.get('engine_addon')
    if value is None:return False
    if value!='hydra-one' or payload.get('mode','gguf') not in ('gguf','safetensors'):
        raise ValueError('HYDRA ONE: scegli un modello locale GGUF o Safetensors compatibile')
    control_budget(payload)
    return True


def runtime():
    bundle=Path(__file__).with_name('hydra_one_bundle_v2.pyz')
    with _IMPORT_LOCK:
        if hashlib.sha256(bundle.read_bytes()).hexdigest()!=BUNDLE_SHA256:
            raise RuntimeError('Bundle HYDRA ONE non integro; motori esistenti invariati')
        loaded=sys.modules.get('hydra_hybrid')
        if loaded is not None and not str(getattr(loaded,'__file__','')).startswith(str(bundle)):
            raise RuntimeError('Un runtime HYDRA diverso è già caricato: riavvia il server prima di cambiare bundle')
        if str(bundle) not in sys.path:sys.path.insert(0,str(bundle))
        from hydra_hybrid.config import Config,Budget,host_resources
        from hydra_addon.upstream import ServiceAdapter
        from hydra_lab.adapters import Pending
        return Config,Budget,host_resources,ServiceAdapter,Pending


def observer_directory(owner):
    """Use the existing HIP observer without imposing its DLL layout on Prism."""
    directory=owner.binary.parent
    if (directory/'amdhip64_7.dll').is_file():return directory
    from serve.gguf_runtime_compatibility import prism_binary
    registered=prism_binary(owner.root,gpu=True)
    if registered is not None and registered.resolve()==owner.binary.resolve():
        native=owner.root/'engine'
        if (native/'amdhip64_7.dll').is_file():return native
    raise RuntimeError('HYDRA: monitor HIP locale non disponibile; nessun fallback CPU')


class HydraClient(LocalOpenAIBackend):
    _hydra_owned=True
    def __init__(self,owner,client,payload):
        Config,Budget,host_resources,ServiceAdapter,self.Pending=runtime()
        super().__init__('http://'+client.host+':'+str(client.port)+client.path,timeout=client.timeout)
        self.observer=None;self.closed=False;self.closing=False;self.close_in_progress=False;self.local=threading.local();self.diagnostics=[]
        self.guards={};self.guard_lock=threading.RLock()
        self.graph=None;self.graph_hook_error=None
        try:
            graph_config=getattr(owner,'graph_config',lambda:{})()
            if isinstance(graph_config,dict) and graph_config.get('graph_enabled') and graph_config.get('context_compiler_enabled'):
                from serve.hydra_graph_optional import OptionalGraph
                self.graph=OptionalGraph(owner,client,payload)
        except Exception as exc:
            self.graph_hook_error=type(exc).__name__[:64]
        resource_provider=host_resources
        gpu=payload.get('gpu') is True
        limits=control_budget(payload)
        try:
            if gpu:
                from hydra_addon.observer import HIPObserver
                self.observer=HIPObserver(observer_directory(owner))
                resource_provider=lambda:self.observer.sample()[0]
            # These are POST-LOAD control-plane headroom checks. Already resident
            # model weights are owned/budgeted by Strata's original model loader.
            config=Config(enabled=True,live_io_authorized=True,model='optional-model',
                backend_url='http://'+client.host+':'+str(client.port),threads=2,
                context=payload.get('context',4096)//max(1,(payload.get('runtime') or {}).get('slots',1)),
                max_concurrent=1,gpu_layers=1 if gpu else 0,
                host_required_bytes=0,request_memory_bytes=limits['request_memory_bytes'],
                vram_required_bytes=limits['vram_required_bytes'] if gpu else 0,timeout_s=client.timeout,
                budget=Budget(**{key:limits[key] for key in ('host_limit_bytes','host_reserve_bytes','vram_limit_bytes','vram_reserve_bytes')}))
            self.adapter=ServiceAdapter(config,resources=resource_provider)
            self.identity=self.adapter.prepare()
            self.identity['resource_budget']=limits
        except BaseException:
            if self.observer is not None:self.observer.close()
            raise

    def _request(self,method,suffix,body=None,*,cancel=None):
        if self.closed:raise RuntimeError('HYDRA ONE chiuso')
        if method!='POST' or suffix!='/chat/completions':
            return super()._request(method,suffix,body,cancel=cancel)
        graph=getattr(self,'graph',None)
        if graph is not None:
            original=body
            prepared=graph.prepare(body['messages'],{**body,'cancel':cancel},body.get('max_tokens',128))
            if prepared is not body['messages']:
                candidate={**body,'messages':prepared}
                try:
                    # Exercise the SAME existing byte/context admission before
                    # committing enrichment. No dispatch or generation here.
                    self.adapter.engine._request(candidate)
                    body=candidate
                except Exception:
                    graph.bypass='controller_admission';body=original
        pending=self.local.pending
        if cancel is not None and cancel.is_set():pending.cancel()
        opened=time.perf_counter()
        connection,response=self.adapter.open(method,'/v1'+suffix,
            json.dumps(body,allow_nan=False,ensure_ascii=False,separators=(',',':')).encode('utf-8'),pending)
        self.local.dispatch_headers_s=time.perf_counter()-opened
        self.local.transport=(connection,response,pending)
        return connection,response

    def chat(self,*args,**kwargs):
        with self.guard_lock:
            if self.closed or self.closing:raise RuntimeError('HYDRA ONE in chiusura o chiuso')
        pending=self.Pending();self.local.pending=pending;self.local.transport=None;self.local.dispatch_headers_s=None
        finished=threading.Event();cancel=kwargs.get('cancel')
        deadline=time.perf_counter()+self.timeout
        guard_errors=[]
        def observe_cancel():
            try:
                while not finished.is_set():
                    remaining=deadline-time.perf_counter()
                    if remaining<=0 or (cancel is not None and cancel.is_set()):
                        pending.cancel();return
                    if finished.wait(min(.05,remaining)):return
            except Exception as exc:
                with self.guard_lock:
                    guard_errors.append(exc);self.closing=True
        def check_control():
            with self.guard_lock:
                if guard_errors:raise RuntimeError('HYDRA request guard failed') from guard_errors[0]
            if time.perf_counter()>=deadline:raise TimeoutError('HYDRA request deadline expired')
            return cancel is None or not cancel.is_set()
        watcher=threading.Thread(target=observe_cancel,name='hydra-in-app-request-guard',daemon=True)
        with self.guard_lock:
            if self.closed or self.closing:raise RuntimeError('HYDRA ONE in chiusura o chiuso')
            self.guards[id(pending)]=(watcher,)
        started=time.perf_counter();primary=None;first_packet=first_content=None
        streaming=kwargs.get('stream',False);packets=[];usage=None;timings=None
        try:
            if not check_control():return
            watcher.start()
            # The existing HYDRA transport normalizes every request to SSE.
            # Collect at the app boundary when its caller requested one JSON response.
            for packet in super().chat(*args,**{**kwargs,'stream':True}):
                if not check_control():return
                observed=time.perf_counter()-started
                if first_packet is None:first_packet=observed
                if first_content is None and isinstance(packet,dict):
                    choices=packet.get('choices')
                    if isinstance(choices,list) and any(isinstance(choice,dict) and isinstance(choice.get('delta'),dict) and choice['delta'].get('content') for choice in choices):
                        first_content=observed
                if streaming:yield packet
                else:
                    if packet.get('usage'):usage=packet['usage']
                    if packet.get('timings'):timings=packet['timings']
                    if packet.get('choices'):packets.append(packet)
            if not check_control():return
            if not streaming and packets:
                from serve.server import openai_collect
                packets[-1]={**packets[-1],'usage':usage}
                if timings:packets[-1]['timings']=timings
                yield openai_collect(packets)
        except BaseException as exc:
            primary=exc;raise
        finally:
            errors=[]
            try:
                if self.local.transport is not None:self.adapter.release(*self.local.transport,reusable=False)
            except Exception as exc:
                errors.append(str(exc))
                if primary is not None:primary.add_note('HYDRA cleanup: '+str(exc))
                else:raise
            finally:
                finished.set()
                unknown=False
                for guard in (watcher,):
                    try:
                        if guard.ident is not None:guard.join(1)
                        if guard.is_alive():unknown=True
                    except Exception as exc:
                        errors.append(str(exc));unknown=True
                with self.guard_lock:
                    errors.extend(str(exc) for exc in guard_errors)
                    if unknown:
                        errors.append('Guard drain incerto');self.closing=True
                    else:self.guards.pop(id(pending),None)
                self.diagnostics.append(dict(wall_s=time.perf_counter()-started,source='strata_hydra_client_wrapper',
                    timing_contract='strata-hydra-client-v1',first_packet_s=first_packet,first_content_s=first_content,
                    dispatch_to_headers_s=self.local.dispatch_headers_s,backend_execution_s=None,queue_wait_s=None,
                    cleanup_errors=errors,active=self.adapter.engine.ledger.active))
                self.diagnostics[:]=self.diagnostics[-128:]
                self.local.transport=None

    def close(self):
        with self.guard_lock:
            if self.closed:return True
            self.closing=True
            if getattr(self,'close_in_progress',False):return False
            if self.guards:return False
            self.close_in_progress=True
        try:
            if not self.adapter.close():return False
            if self.observer is not None:self.observer.close()
            with self.guard_lock:self.closed=True
            return True
        finally:
            with self.guard_lock:self.close_in_progress=False


def wrap(owner,client,payload):
    return HydraClient(owner,client,payload)

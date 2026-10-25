"""Opt-in HYDRA adapter over the existing native engine, without another scheduler.

Strata retains FIFO admission, process ownership, packing, KV and expert I/O.
This adapter never converts weights or retries a generation.
"""
import time


def _require_native_admission(svc):
    """The ordinary engine's presence is not a HYDRA native-MoE execution grant."""
    spawn = getattr(svc.engine, 'spawn', None)
    args = spawn[1] if isinstance(spawn, (tuple, list)) and len(spawn) > 1 else []
    if '--pack' in args and '--native' in args:
        from pathlib import Path
        from serve.hydra_native_admission import require_native_moe
        require_native_moe(Path(__file__).resolve().parents[1])


def status(svc):
    with svc.status_lock:
        state=dict(getattr(svc,'hydra_native_state',{}))
    if hasattr(svc,'_hydra_graph_state'):
        try:
            from serve.hydra_graph import snapshot
            state['graph_inference']=snapshot(svc)
        except Exception:
            state['graph_inference']={'enabled':False,'reason':'status_unavailable'}
    if getattr(svc,'_hydra_graph_hook_error',None):
        state['graph_inference_hook_error']=svc._hydra_graph_hook_error
    if state.get('enabled'):
        try:
            _require_native_admission(svc)
        except ValueError as exc:
            state.update(effective_state='BLOCKED',blocked_reason=str(exc))
    return {**dict(enabled=False,backend='Strata native',completed=0,failed=0,
                   cancelled=0,scope='native generation adapter; not client latency'),**state}


def set_enabled(svc,enabled):
    if type(enabled) is not bool:raise ValueError('enabled deve essere booleano')
    if enabled:_require_native_admission(svc)
    if not svc.fifo.acquire(False):raise RuntimeError('Una richiesta è attiva o in coda')
    try:
        optional=svc.optional_backends.status()
        if enabled and optional.get('status') in ('ready','loading'):
            raise RuntimeError('Arresta il backend opzionale prima di usare il pack nativo')
        with svc.status_lock:
            if svc.status.get('busy') or svc.status.get('queued'):
                raise RuntimeError('Una richiesta è attiva o in coda')
            old=getattr(svc,'hydra_native_state',{})
            svc.hydra_native_state={**old,'enabled':enabled,'model':svc.model}
    finally:svc.fifo.release()
    return status(svc)


def generate(svc,ids,max_new,sampling,cancel,**kwargs):
    enabled=status(svc)['enabled']
    if not enabled:
        yield from svc.engine.generate(ids,max_new,sampling,cancel,**kwargs)
        return
    _require_native_admission(svc)
    started=time.monotonic();outcome='completed';stream=None;stop_observed=False
    try:
        stream=svc.engine.generate(ids,max_new,sampling,cancel,**kwargs)
        for token in stream:
            if token is not None and token in getattr(svc,'stop_ids',()):stop_observed=True
            yield token
    except GeneratorExit:
        outcome='cancelled' if cancel.is_set() else 'completed' if stop_observed else 'consumer_closed'
        raise
    except BaseException:
        outcome='failed';raise
    finally:
        try:
            if stream is not None and hasattr(stream,'close'):stream.close()
        finally:
            if cancel.is_set() and outcome=='completed':outcome='cancelled'
            with svc.status_lock:
                state=svc.hydra_native_state
                state[outcome]=state.get(outcome,0)+1
                state.update(last_wall_s=time.monotonic()-started,last_outcome=outcome)


def route(handler,svc,path,*,post=False):
    if path!='/hydra/native':return False
    if not handler._authorized():return True
    if not post:
        handler._json(200,status(svc));return True
    if not handler._own_page('Selezione HYDRA nativa dalla pagina Strata'):return True
    import json
    try:
        body=json.loads(handler._read_body() or b'{}')
        if not isinstance(body,dict) or set(body)!={'enabled'}:
            raise ValueError('Invia soltanto enabled')
        handler._json(200,set_enabled(svc,body['enabled']))
    except (ValueError,TypeError) as exc:handler._json(400,{'error':{'message':str(exc)}})
    except RuntimeError as exc:handler._json(409,{'error':{'message':str(exc)}})
    return True

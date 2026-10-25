"""Common local model resolution and static planning; never owns reservations.

Source-declared architectures are candidates, not verified binary capabilities.
Identity fingerprints bind metadata/stat observations, not full model contents.
"""
import hashlib
import json
import re
from pathlib import Path


def source_architectures():
    source=Path.home()/'.unsloth/llama.cpp/src/llama-arch.cpp'
    try:
        text=source.read_text(encoding='utf-8')
        return set(re.findall(r'\{\s*LLM_ARCH_\w+,\s*"([^"]+)"\s*\}',text))
    except OSError:
        return set()


def resolve_model(root,payload,*,architectures=None):
    result=dict(schema='hydra.model-resolution.v1',available=False,route=None,
                reserved=False,requires_admission=True,performance='NOT_MEASURED',
                capability_state='declared_unverified',reason=None)
    try:
        if not isinstance(payload,dict):raise ValueError('Invia un oggetto JSON')
        if not isinstance(payload.get('runtime',{}),dict):raise ValueError('Configurazione runtime non valida')
        value=payload.get('model_path')
        if not value and payload.get('profile'):
            profile=payload['profile']
            if not isinstance(profile,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',profile):raise ValueError('Profilo locale non valido')
            cfgpath=Path(root)/('strata-'+profile+'.json')
            cfg=json.loads(cfgpath.read_text(encoding='utf-8-sig'));args=cfg.get('args',[])
            if '--native' not in args:raise ValueError('Profilo senza pack nativo')
            native=Path(args[args.index('--native')+1]);cwd=Path(cfg.get('cwd') or cfgpath.parent)
            if not cwd.is_absolute():cwd=cfgpath.parent/cwd
            value=str(native if native.is_absolute() else cwd/native)
        if not isinstance(value,str) or not value or len(value)>4096:raise ValueError('Scegli un modello locale')
        path=Path(value).expanduser()
        if not path.is_absolute() or not path.exists():raise ValueError('Percorso locale assoluto non disponibile')
        path=path.resolve();result['model_path']=str(path)
        from serve.model_engine_requirements import requirement
        pack=requirement(root,path)
        if pack['required_engine']=='strata':
            if not pack.get('strata_ready'):raise ValueError('Pack preparato incompleto')
            result.update(route='hydra-strata',mode='native',profile=pack['strata_key'],
                          configuration=pack['strata_configuration'],architecture=None,
                          resource_owner='existing_native_backend',files=[path])
        elif path.is_dir():
            from serve.safetensors_runtime import inspect_model,validate_adapter
            info=inspect_model(path)
            if not any((path/name).is_file() for name in ('tokenizer.json','tokenizer.model')):
                raise ValueError('Tokenizer locale mancante')
            if payload.get('adapter_path'):validate_adapter(payload['adapter_path'],path)
            if (payload.get('runtime') or {}).get('python_loader')=='airllm':
                from serve.airllm_runtime import inspect_checkpoint,validate_options
                runtime=payload.get('runtime') or {}
                validate_options('cuda' if payload.get('gpu') else 'cpu',payload.get('adapter_path'),runtime.get('python_draft_path'),runtime.get('python_quantization','none'),runtime.get('python_attention','auto'),runtime.get('python_cache','auto'))
                inspect_checkpoint(path)
            result.update(route='hydra-safetensors',mode='safetensors',architecture=info['architecture'],
                          resource_owner='existing_backend_manager',files=sorted(p for p in path.iterdir() if p.is_file() and (p.suffix in ('.json','.safetensors','.model','.jinja'))))
        elif path.suffix.lower()=='.gguf':
            from serve.gguf_runtime_compatibility import unsupported_reason
            reason=unsupported_reason(path,root,gpu=payload.get('gpu'))
            if reason:raise ValueError(reason)
            with path.open('rb') as stream:
                if stream.read(4)!=b'GGUF':raise ValueError('Header GGUF non valido')
            from serve.catalogue import read_gguf_header
            metadata=read_gguf_header(path.as_uri(),nbytes=16<<20)['meta']
            architecture=metadata.get('general.architecture')
            known=source_architectures() if architectures is None else architectures
            if not architecture or architecture not in known:raise ValueError('Architettura GGUF non dichiarata dal runtime locale: '+str(architecture))
            if re.search(r'bert|clip|whisper|wavtokenizer|sortformer|tts',architecture,re.I):
                raise ValueError('Questo modello richiede un percorso diverso dalla chat causale')
            if not isinstance(metadata.get('tokenizer.chat_template'),str) or not metadata['tokenizer.chat_template'].strip():
                raise ValueError('Template chat GGUF mancante: selezione automatica non disponibile')
            from serve.gguf_parts import local_parts
            result.update(route='hydra-gguf',mode='gguf',architecture=architecture,
                          architecture_source='local_llama_source_declaration_not_binary_attestation',
                          resource_owner='existing_backend_manager',files=local_parts(path))
        else:raise ValueError('Formato non riconosciuto dal resolver HYDRA')
        supplied=payload.get('mode','auto')
        if result['mode']!='native' and supplied not in ('auto',result['mode']):
            raise ValueError('Formato del modello e destinazione richiesta non corrispondono')
        files=result.pop('files')
        stats=[dict(path=str(p),bytes=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns) for p in files]
        identity=json.dumps(dict(route=result['route'],architecture=result['architecture'],files=stats),sort_keys=True).encode()
        result.update(available=True,identity=dict(fingerprint=hashlib.sha256(identity).hexdigest(),
                      scope='local_stat_and_metadata_not_full_content_hash',model_sha256=None),
                      reason='Risolto; compatibilità effettiva e risorse da verificare al caricamento')
    except (OSError,ValueError,TypeError,KeyError,IndexError,OverflowError) as exc:
        result.update(available=False,reason=str(exc))
    return result


def normalize_start(root,payload,*,architectures=None):
    resolved=resolve_model(root,payload,architectures=architectures)
    if not resolved['available']:raise ValueError(resolved['reason'])
    if resolved['route']=='hydra-strata':raise ValueError('Il pack usa il percorso HYDRA preparato, non il server GGUF/Python')
    return {**payload,'mode':resolved['mode'],'model_path':resolved['model_path']}


def model_plan(manager,payload,*,inspect_only=False):
    resolved=resolve_model(manager.root,payload)
    if not resolved['available'] or inspect_only or resolved['route']=='hydra-strata':return resolved
    proposed={**payload,'mode':resolved['mode'],'model_path':resolved['model_path']}
    try:
        if payload.get('fit_mode','auto')=='auto':resources=manager.fit_model(proposed)
        else:
            resources=manager.context_plan(proposed)
            chosen=next((r for r in resources['options'] if r['context']==payload.get('context')),None)
            if not chosen or not chosen.get('fits'):raise ValueError('Contesto o memoria non ammissibili')
        resolved['resource_plan']=resources
        resolved['resource_owner']='existing_backend_manager'
    except (OSError,ValueError,TypeError,KeyError) as exc:
        resolved.update(available=False,reason=str(exc))
    return resolved


def route(handler,service,path):
    if path!='/hydra/model-plan':return False
    if not handler._own_page('Il piano HYDRA può essere richiesto dalla pagina locale'):return True
    try:
        payload=json.loads(handler._read_body() or b'{}')
        if not isinstance(payload,dict):raise ValueError('Invia un oggetto JSON')
        inspect_only=payload.pop('inspect_only',False)
        if type(inspect_only) is not bool:raise ValueError('inspect_only deve essere booleano')
        handler._json(200,model_plan(service.optional_backends,payload,inspect_only=inspect_only))
    except (OSError,ValueError,TypeError) as exc:handler._json(400,{'error':{'message':str(exc)}})
    return True

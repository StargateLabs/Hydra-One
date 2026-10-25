"""Bind registered native model packs to Strata; never infer an engine from a folder name."""
import json
from pathlib import Path
from serve.model_inventory import inspect_config
def _identity(path):return str(Path(path).resolve()).casefold()
def requirement(root,model_path):
    root=Path(root);requested=_identity(model_path) if model_path else ''
    ordinary={'required_engine':'gguf','engine_label':'llama.cpp','engine_message':'Modello GGUF: usa il motore compatibile con la sua architettura.'}
    if not requested:return ordinary
    pending=None
    for profile in sorted(root.glob('strata-*.json')):
        if profile.name.endswith('.shared-settings.json'):continue
        try:
            cfg=json.loads(profile.read_text(encoding='utf-8-sig'));args=cfg.get('args') or [];cwd=Path(cfg.get('cwd') or profile.parent)
            if not cwd.is_absolute():cwd=profile.parent/cwd
            matches=[]
            for flag in ('--native','--ple-gguf'):
                if flag in args:
                    value=Path(args[args.index(flag)+1]);matches.append(_identity(value if value.is_absolute() else cwd/value))
            if requested not in matches:continue
            inspected=inspect_config(profile)
            candidate={'required_engine':'strata','engine_label':'Strata','strata_configuration':profile.name,'strata_key':inspected['key'],'strata_ready':inspected['ready'],
                    'engine_message':'Questo modello appartiene a un pack nativo Strata: deve essere usato con il motore Strata, non con il backend llama.cpp.'}
            if inspected['ready']:return candidate
            pending=pending or candidate
        except (OSError,ValueError,TypeError,KeyError,IndexError):continue
    return pending or ordinary
def assert_optional_engine(root,payload):
    if payload.get('mode','gguf')=='gguf' and requirement(root,payload.get('model_path'))['required_engine']=='strata':
        raise ValueError('Questo modello richiede il motore Strata. Seleziona la configurazione Strata; il backend llama.cpp non viene avviato.')

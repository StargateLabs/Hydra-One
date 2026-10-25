"""Readiness means usable files and a complete pack, never just an existing folder."""
import json
from pathlib import Path
import re

def inspect_config(path):
    path=Path(path);result=dict(key=path.stem.removeprefix('strata-'),config=path.name,ready=False,error='')
    try:
        cfg=json.loads(path.read_text(encoding='utf-8-sig'));args=cfg['args'];cwd=Path(cfg.get('cwd') or path.parent)
        def resolve(value):
            p=Path(value);return p if p.is_absolute() else cwd/p
        def flag(name):return resolve(args[args.index(name)+1]) if name in args else None
        result['label']=cfg.get('model_name') or cfg.get('model') or result['key']
        result['display_label']=cfg.get('display_name') or result['label']
        result['author']=cfg.get('catalogue',{}).get('author','')
        result['quant']=cfg.get('catalogue',{}).get('quant','')
        pack=flag('--pack');native=flag('--native');ple=flag('--ple-gguf')
        if not resolve(cfg['exe']).is_file():raise ValueError('Motore non disponibile')
        if not pack or not pack.is_dir():raise ValueError('Pack non disponibile')
        if not native or not native.is_file() or native.stat().st_size<24:raise ValueError('Pesi GGUF non disponibili')
        with native.open('rb') as stream:
            if stream.read(4)!=b'GGUF':raise ValueError('Pesi GGUF non validi')
        if ple and (not ple.is_file() or ple.stat().st_size<24):raise ValueError('Shard PLE non disponibile')
        index=pack/'index.txt';dense=pack/'dense.bin';experts=pack/'native_experts.txt'
        if not all(p.is_file() for p in (index,dense,experts)):raise ValueError('Pack incompleto')
        header=index.read_text(encoding='utf-8').splitlines()[:2]
        match=re.search(r'\bpool (\d+)\b',' '.join(header))
        if not match or int(match.group(1))<=0 or dense.stat().st_size<int(match.group(1)) or experts.stat().st_size==0:raise ValueError('Pack troncato o indice non valido')
        tokenizer=resolve(cfg.get('tokenizer') or pack/'tokenizer')
        if not tokenizer.is_dir() or not all((tokenizer/name).is_file() for name in ('vocab.json','merges.txt','chat_template.jinja')):raise ValueError('Tokenizer incompleto')
        result.update(ready=True,pack=str(pack),backend=cfg.get('backend','unknown'))
    except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:result['error']=str(exc)
    return result

def inventory(root):
    return [inspect_config(path) for path in sorted(Path(root).glob('strata-*.json')) if not path.name.endswith('.shared-settings.json')]

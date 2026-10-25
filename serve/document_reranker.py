"""Pinned, bounded local cross-encoder; ranking scores are not probabilities."""
import hashlib,json,math
from pathlib import Path
REPO='cross-encoder/mmarco-mMiniLMv2-L12-H384-v1'
REVISION='1427fd652930e4ba29e8149678df786c240d8825'
FILES={'config.json','model.safetensors','special_tokens_map.json','tokenizer.json','tokenizer_config.json'}
def model(root,verify=False):
    root=Path(root).resolve()
    try:manifest=json.loads((root/'data/open-webui/reranker.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):raise ValueError('Prepara il modello reranker locale prima di attivarlo') from None
    folder=Path(manifest.get('folder','')).resolve()
    if manifest.get('repo')!=REPO or manifest.get('revision')!=REVISION or not folder.is_relative_to(root/'models/rerankers') or folder.is_symlink():raise ValueError('Reranker identity or location invalid')
    rows=manifest.get('files',[])
    if {r.get('name') for r in rows}!=FILES:raise ValueError('Incomplete reranker manifest')
    for row in rows:
        path=folder/row['name']
        if path.is_symlink() or not path.is_file() or path.stat().st_size!=row['bytes']:raise ValueError('Reranker file changed')
        if verify and hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Reranker integrity verification failed')
    return {'folder':str(folder),'name':REPO,'bytes':sum(r['bytes'] for r in rows),'revision':REVISION}
def ranked(rows,scores):
    if len(rows)!=len(scores) or any(type(v) not in (int,float) or not math.isfinite(v) for v in scores):raise ValueError('Invalid reranker scores')
    return sorted([{**row,'rerank_score':score} for row,score in zip(rows,scores)],key=lambda row:row['rerank_score'],reverse=True)

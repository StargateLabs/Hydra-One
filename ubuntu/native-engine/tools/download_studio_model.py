"""Download public weights through the native hub; never execute model code."""
import hashlib,json,os,re,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def emit(value):print('STRATA_DOWNLOAD:'+json.dumps(value,ensure_ascii=True),flush=True)

def main():
    path=Path(sys.argv[1]).resolve()
    if not path.is_relative_to(ROOT/'output/studio-model-downloads') or path.name!='plan.json':raise ValueError('Invalid managed download plan')
    plan=json.loads(path.read_text(encoding='utf-8'));stage=path.parent/'model'
    if not re.fullmatch(r'[a-f0-9]{40}',plan['revision']):raise ValueError('Invalid revision')
    from huggingface_hub import snapshot_download,get_token
    from serve.download_progress import DownloadProgress
    tracker=DownloadProgress(plan['bytes'],lambda progress:emit({'bytes':progress['received_bytes'],'total':progress['total_bytes']}))
    snapshot_download(repo_id=plan['repo'],revision=plan['revision'],token=(get_token() if plan.get('requires_auth') else False),allow_patterns=[row['path'] for row in plan['files'] if not row.get('inline_base64')],local_dir=str(stage),max_workers=2,tqdm_class=tracker.progress_class(),etag_timeout=15)
    import base64
    for row in plan['files']:
        if row.get('inline_base64'):(stage/row['path']).write_bytes(base64.b64decode(row['inline_base64']))
    emit({'state':'verifying'});hashes={}
    for row in plan['files']:
        file=(stage/row['path'])
        if file.is_symlink() or not file.resolve().is_relative_to(stage) or file.stat().st_size!=row['bytes']:raise ValueError('Downloaded file identity changed')
        with file.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
        if row['sha256'] and digest!=row['sha256']:raise ValueError('Downloaded file hash mismatch')
        hashes[row['path']]=digest
    from serve.studio_model_import import validate
    if plan['kind'] in ('effects','magnet','watermark','mbd','style','jasco'):
        (stage/'audiogen.json').write_text(json.dumps({'repository':plan['repo'],'revision':plan['revision'],'sha256':hashes,'license':plan['license']}),encoding='utf-8')
    if plan['kind']=='embedding':
        from serve.open_webui_runtime import embedding_models
        if not embedding_models(ROOT,(stage,)):raise ValueError('Unsupported local embedding format')
    else:validate(stage,plan['kind'])
    relative={'embedding':'models/embeddings','visual':'models/visual','controlnet':'models/controlnet','music':'models/audio/music','effects':'models/audio/effects','magnet':'models/audio/magnet','watermark':'models/audio/watermark','mbd':'models/audio/mbd','codec24':'models/audio/codec24','adapter':'models/image-adapters','style':'models/audio/style','jasco':'models/audio/jasco'}[plan['kind']]
    target=ROOT/relative
    if not target.resolve().is_relative_to(ROOT):raise ValueError('Invalid managed model destination')
    target.mkdir(parents=True,exist_ok=True)
    final=target/(plan['repo'].split('/')[-1]+'-'+uuid.uuid4().hex[:8])
    from serve.configuration import atomic_json
    atomic_json(stage/'provenance.json',{'repository':plan['repo'],'revision':plan['revision'],'license':plan['license'],'sha256':hashes,'source':plan['source']})
    stage.rename(final);tracker.finish();emit({'state':'complete','path':str(final),'revision':plan['revision']})

if __name__=='__main__':main()

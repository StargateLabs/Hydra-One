"""Bounded audit of current local inventory and retained publisher metadata."""
import json,re,time
from pathlib import Path

def audit(root,models):
    root=Path(root).resolve();issues=[];seen={};rows=[]
    for item in models[:2000]:
        row=dict(item);path=Path(row.get('path','')).resolve();key=str(path).casefold()
        if key in seen:
            issues.append({'kind':'duplicate_local_path','path':str(path),'first':seen[key]});continue
        seen[key]=row.get('name');row['exists']=path.exists();row['external']=not path.is_relative_to(root) and not path.is_relative_to((root.parent/'Strata-data').resolve())
        if not row['exists']:issues.append({'kind':'missing_local_path','path':str(path)})
        rows.append({'name':row.get('name'),'path':str(path),'exists':row['exists'],'external':row['external'],'format':row.get('format'),'runtime_supported':row.get('runtime_supported')})
    publications=[];identities=set()
    for path in sorted((root/'output/research/hf-models-20261009').glob('*.json'))[:256]:
        try:
            if path.is_symlink() or path.stat().st_size>4*1024**2:continue
            info=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(info,dict):continue
            repo=info.get('id')
            if not isinstance(repo,str) or not re.fullmatch(r'[\w.-]+/[\w.-]+',repo):continue
            identity=(repo,info.get('sha'));card=info.get('cardData') or {}
            if not isinstance(card,dict):card={}
            if identity in identities:issues.append({'kind':'duplicate_publication','repo':repo});continue
            identities.add(identity);license=card.get('license');bases=card.get('base_model')
            publications.append({'repo':repo,'author':repo.split('/')[0],'revision':info.get('sha'),'license':license,'declared_bases':bases,'source':path.relative_to(root).as_posix(),'live_refreshed':False})
            if not license:issues.append({'kind':'license_not_declared','repo':repo})
        except (OSError,ValueError,TypeError):issues.append({'kind':'invalid_metadata','source':path.name})
    return {'checked_at':time.time(),'local_models':rows,'publications':publications,'issues':issues,
            'complete_within_inventory':len(models)<=2000,'scope':'Current local inventory and retained publisher snapshots; not the entire online catalogue',
            'network_requests':0,'weights_loaded':False,'publisher_snapshots_may_be_stale':True}

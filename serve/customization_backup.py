"""Recoverable, hash-verified snapshots of the editable mod; never replaces live files."""
import hashlib
import json
import os
import time
import uuid
import zipfile
from pathlib import Path

EXTENSIONS={'.py','.js','.css','.html','.svg','.png','.jpg','.jpeg','.webp','.json',
    '.toml','.yaml','.yml','.ini','.cfg','.txt','.md','.ps1','.bat','.sh','.cmake',
    '.cpp','.c','.h','.hpp','.cu','.cuh','.hip','.rs','.lock','.ttf','.woff','.woff2'}
EXCLUDED={'output','build','node_modules','__pycache__','.git','.pytest_cache','models',
          '.rocm-win','third_party','unsloth_compiled_cache','tmp','engine-backup-0.1.38'}


def snapshot(root):
    root=Path(root).resolve();rows=[];total=0
    generated={'data/hermes-home/cache','data/hermes-home/installs','graphify-out','data/native-workspace/dashboard-profile',
               'data/audiocraft-python','data/python-runtimes'}
    for current, directories, names in os.walk(root,followlinks=False):
        directories[:]=sorted(d for d in directories if d not in EXCLUDED and not d.startswith(('.venv','build-'))
                              and not Path(current,d).is_symlink()
                              and Path(current,d).relative_to(root).as_posix() not in generated
                              and not (Path(current,d)/'pyvenv.cfg').is_file())
        for name in sorted(names):
            path=Path(current,name)
            if path.is_symlink() or (path.suffix.lower() not in EXTENSIONS and name!='CMakeLists.txt' and path.relative_to(root).as_posix()!='HYDRA/recovery/assets.zip'):continue
            size=path.stat().st_size
            if size>64*1024**2:raise ValueError('Editable file exceeds backup limit: '+str(path))
            total+=size
            if total>512*1024**2 or len(rows)>=10000:raise ValueError('Customization backup exceeds size or file limit')
            rows.append((path,path.relative_to(root).as_posix()))
    folder=root/'output/updates/backups';folder.mkdir(parents=True,exist_ok=True)
    identity=time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
    target=folder/(identity+'.zip');partial=target.with_suffix('.partial');manifest=[]
    try:
        with zipfile.ZipFile(partial,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
            for path,relative in rows:
                data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
                archive.writestr(relative,data);manifest.append({'path':relative,'bytes':len(data),'sha256':digest})
            archive.writestr('MOD-BACKUP-MANIFEST.json',json.dumps(manifest,indent=2))
        with zipfile.ZipFile(partial) as archive:
            for row in manifest:
                if hashlib.sha256(archive.read(row['path'])).hexdigest()!=row['sha256']:
                    raise ValueError('Customization archive verification failed')
        partial.replace(target)
        result={'archive':str(target),'files':len(manifest),'source_bytes':total,
                'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'verified':True,
                'scope':'editable_project_files','created_at':time.time(),'installed_engines_replaced':False}
        target.with_suffix('.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        pointer=root/'data/customization-backup-last.json';pointer.parent.mkdir(parents=True,exist_ok=True)
        tmp=pointer.with_suffix('.tmp');tmp.write_text(json.dumps(result),encoding='utf-8');tmp.replace(pointer)
        return result
    except Exception:
        partial.unlink(missing_ok=True)
        raise

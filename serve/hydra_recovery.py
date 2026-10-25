"""Recover only absent HYDRA files from the local, hash-verified recovery capsule."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import zipfile


def capsule(root):
    root=Path(root).resolve();folder=root/'hydra-engine/recovery';manifest=folder/'manifest.json'
    if manifest.stat().st_size>1024**2:raise ValueError('HYDRA recovery manifest exceeds budget')
    record=json.loads(manifest.read_text(encoding='utf8'))
    archive=folder/'assets.zip';rows=record.get('files')
    if record.get('schema_version')!=1 or not isinstance(rows,list) or not 1<=len(rows)<=128 or archive.stat().st_size>64*1024**2:
        raise ValueError('Invalid HYDRA recovery capsule')
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=record.get('archive_sha256'):raise ValueError('HYDRA recovery archive identity changed')
    base=root/'hydra-engine'
    if base.is_symlink():raise ValueError('HYDRA recovery root is a link')
    base=base.resolve();seen=set();total=0
    for row in rows:
        name=row['path'];parts=PurePosixPath(name)
        if not isinstance(name,str) or parts.is_absolute() or '\\' in name or ':' in name or '..' in parts.parts or name in seen or not parts.parts:
            raise ValueError('Unsafe HYDRA recovery path')
        target=base.joinpath(*parts.parts).resolve()
        if not target.is_relative_to(base):raise ValueError('HYDRA recovery target escaped root')
        size=row['bytes']
        if type(size) is not int or not 0<=size<=64*1024**2:raise ValueError('HYDRA recovery file exceeds budget')
        total+=size;seen.add(name)
    if total>128*1024**2:raise ValueError('HYDRA recovery total exceeds budget')
    return base,archive,rows


def inspect(root):
    base,archive,rows=capsule(root);missing=[];changed=[]
    for row in rows:
        target=base/row['path']
        if not target.is_file():missing.append(row['path']);continue
        with target.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if target.stat().st_size!=row['bytes'] or actual!=row['sha256']:changed.append(row['path'])
    return dict(missing=missing,changed=changed,files=len(rows),archive=str(archive))


def restore_missing(root):
    base,archive,rows=capsule(root);payloads={}
    with zipfile.ZipFile(archive) as source:
        if len(source.infolist())!=len(rows) or set(source.namelist())!={r['path'] for r in rows}:raise ValueError('HYDRA capsule inventory mismatch')
        # Validate every payload before the first write.
        for row in rows:
            info=source.getinfo(row['path'])
            if info.file_size!=row['bytes']:raise ValueError('HYDRA capsule size mismatch')
            data=source.read(info)
            if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('HYDRA capsule payload identity changed')
            payloads[row['path']]=data
    restored=[]
    for name,data in payloads.items():
        target=base/name
        if target.exists():continue
        if not target.resolve().is_relative_to(base):raise ValueError('HYDRA recovery target changed')
        target.parent.mkdir(parents=True,exist_ok=True)
        descriptor,temporary=tempfile.mkstemp(prefix='.hydra-recovery-',dir=target.parent)
        try:
            with os.fdopen(descriptor,'wb') as stream:stream.write(data)
            try:os.link(temporary,target)
            except FileExistsError:continue
        finally:
            Path(temporary).unlink(missing_ok=True)
        restored.append(name)
    return dict(restored=restored,**inspect(root),existing_files_overwritten=False,models_downloaded=False)

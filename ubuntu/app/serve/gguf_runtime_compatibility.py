"""Known file roles that cannot run as standalone chat on installed llama.cpp."""
import re
import hashlib
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=4)
def _verified_files(directory, rows, signatures):
    for relative,digest in rows:
        path=Path(directory)/relative
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=digest:return False
    return tuple((str((Path(directory)/r).resolve()),(Path(directory)/r).stat().st_size,
                  (Path(directory)/r).stat().st_mtime_ns,(Path(directory)/r).stat().st_ctime_ns) for r,_ in rows)==signatures


def file_role(path):
    name=Path(path).name
    if name.lower()=='qwen3.8-flash-next-experimental-speed-projection.gguf':return 'controlvector'
    if re.search(r'(?:^|[-_.])mmproj(?:[-_.]|$)',name,re.I):return 'projector'
    if re.search(r'(?:^|[-_.])(DSpark|DFLASH|projection)(?:[-_.]|$)',name,re.I):return 'draft'
    if re.search(r'^Qwen3[.]8-Flash-Next-MTP-(?:BF16|F16|Q\d[^.]*)[.]gguf$',name,re.I):return 'draft'
    return 'model'


def requires_prism(path):
    name=Path(path).name
    return file_role(path)=='model' and bool(re.search(r'(?:^|[-_.])(PQ2_0|PTQ1_0)(?:[-_.]|$)',name,re.I)
        or re.search(r'Ternary-Bonsai-2-27B.*[-_]F16[.]gguf$',name,re.I))


def prism_binary(root, *, gpu=None):
    """Only an explicitly registered, locally validated GPU runtime is eligible.

    No auto-download, arbitrary executable path, CPU fallback or runtime swap.
    The manifest is deployment-owned, never supplied through a request.
    """
    if root is None or gpu is False:return None
    root=Path(root).resolve()
    try:
        manifest=json.loads((root/'data/hydra-prism-runtime.json').read_text(encoding='utf-8'))
        allowed=(root.parent/'HYDRA/prism_integration_20261017/runtime').resolve()
        directory=Path(manifest['directory']).resolve()
        if directory!=allowed or manifest.get('schema')!=1 or manifest.get('device')!='ROCm0' or manifest.get('real_inference_verified') is not True:return None
        files=manifest['files']
        if not isinstance(files,list) or not 1<=len(files)<=100:return None
        rows=[];signatures=[]
        for row in files:
            path=(directory/row['path']).resolve()
            if not path.is_relative_to(directory) or not path.is_file():return None
            stat=path.stat();rows.append((row['path'],row['sha256']))
            signatures.append((str(path),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns))
        if not _verified_files(str(directory),tuple(rows),tuple(signatures)):return None
        binary=directory/'llama-server.exe'
        if not any(row['path']=='llama-server.exe' for row in files):return None
        return binary
    except (OSError,ValueError,TypeError,KeyError):return None


def unsupported_reason(path, root=None, *, gpu=None):
    name=Path(path).name
    if file_role(path)=='controlvector':
        return 'Vettore di controllo sperimentale, non un modello chat né un draft; richiede il motore nativo compatibile.'
    if requires_prism(path) and prism_binary(root,gpu=gpu) is None:
        return 'Questa quantizzazione Prism richiede il runtime Prism dedicato; il llama.cpp Unsloth installato non la supporta.'
    if re.search(r'(?:^|[-_.])(DSpark|DFLASH|mmproj|projection)(?:[-_.]|$)',name,re.I):
        return 'Questo file è un componente ausiliario (draft o proiettore), non un modello chat autonomo.'
    if re.search(r'^Qwen3[.]8-Flash-Next-MTP-(?:BF16|F16|Q\d[^.]*)[.]gguf$',name,re.I):
        return 'Questo file MTP contiene il componente di speculazione e richiede il modello principale e un runtime compatibile.'
    return None

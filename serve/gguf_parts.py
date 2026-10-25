"""Standard llama.cpp GGUF shard names; require a complete, local file set."""
import re
from pathlib import Path
PATTERN=re.compile(r'^(.*)-(\d{5})-of-(\d{5})\.gguf$',re.I)
def identity(name):
    match=PATTERN.match(name)
    if not match:return None
    number,count=int(match[2]),int(match[3])
    if not 1<=number<=count<=128:raise ValueError('Invalid GGUF split file count')
    return match[1],number,count
def local_parts(path):
    path=Path(path);split=identity(path.name)
    if not split:return [path]
    prefix,number,count=split
    if number!=1:raise ValueError('Select the first GGUF part, 00001')
    parts=[path.with_name(f'{prefix}-{index:05d}-of-{count:05d}.gguf') for index in range(1,count+1)]
    for part in parts:
        if not part.is_file() or part.is_symlink() or part.resolve().parent!=path.resolve().parent:raise ValueError('Missing or linked GGUF part: '+part.name)
        with part.open('rb') as stream:
            if stream.read(4)!=b'GGUF':raise ValueError('Invalid GGUF part: '+part.name)
    return parts
def weight_bytes(path):return sum(part.stat().st_size for part in local_parts(path))
def remote_parts(file,files):
    split=identity(file['path'])
    if not split:return [file]
    prefix,number,count=split
    if number!=1:return []
    mapping={row['path']:row for row in files}
    names=[f'{prefix}-{index:05d}-of-{count:05d}.gguf' for index in range(1,count+1)]
    return [mapping[name] for name in names] if all(name in mapping for name in names) else []

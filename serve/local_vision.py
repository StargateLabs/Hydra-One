"""Explicit local GGUF projector selection; CPU default and explicit capability-checked GPU offload."""
from pathlib import Path

def projector(payload):
    enabled=payload.get('vision',False)
    if type(enabled) is not bool:raise ValueError('Vision setting must be boolean')
    if not enabled:return None
    device(payload)
    path=Path(payload.get('mmproj_path','')).expanduser()
    if not path.is_absolute() or not path.is_file() or path.suffix.lower()!='.gguf':raise ValueError('Choose an existing local GGUF vision projector')
    if path.stat().st_size>2*1024**3:raise ValueError('This local projector workflow supports files up to 2 GiB')
    from serve.catalogue import read_gguf_header
    metadata=read_gguf_header(path.as_uri(),nbytes=16<<20)['meta']
    flag=metadata.get('clip.has_vision_encoder')
    if metadata.get('general.architecture')!='clip' or type(flag) not in (int,bool) or flag!=1:raise ValueError('The selected file does not declare a vision encoder')
    return path.resolve()

def budget(resources,payload):
    path=projector(payload)
    if not path:return resources
    import psutil
    extra=path.stat().st_size*3/2**30;free=psutil.virtual_memory().available/2**30
    resources['projector_ram_estimated_gib']=extra
    for row in resources['options']:
        row['ram_required_gib']+=extra;row['ram_estimated_upper_gib']+=extra
        row['fits']=row['fits'] and row['ram_required_gib']<=free
    if device(payload)=='gpu':
        resources['projector_gpu_estimated_gib']=extra
        for row in resources['options']:
            row['gpu_required_gib']=(row.get('gpu_required_gib') or 0)+extra
            row['gpu_estimated_alloc_gib']=(row.get('gpu_estimated_alloc_gib') or 0)+extra
            row['fits']=row['fits'] and row['gpu_required_gib']<=(resources.get('gpu_free_gib') or 0) and (resources.get('gpu_budget_gib') is None or row['gpu_estimated_alloc_gib']<=resources['gpu_budget_gib'])
    resources['recommended_context']=max((row['context'] for row in resources['options'] if row['fits']),default=None)
    return resources


def device(payload):
    value=payload.get('vision_device','cpu')
    if value not in ('cpu','gpu'):raise ValueError('Vision device must be cpu or gpu')
    if value=='gpu' and payload.get('gpu') is not True:raise ValueError('GPU vision requires GPU inference')
    return value


def runtime_arguments(payload,binary):
    if not payload.get('vision'):return []
    selected=device(payload)
    flag='--no-mmproj-offload'
    if selected=='gpu':
        import subprocess
        result=subprocess.run([str(binary),'--help'],cwd=binary.parent,capture_output=True,text=True,timeout=15)
        if result.returncode or '--mmproj-offload' not in result.stdout+result.stderr:
            raise ValueError('The selected runtime does not support GPU vision offload')
        flag='--mmproj-offload'
    return ['--mmproj',payload['mmproj_path'],flag]

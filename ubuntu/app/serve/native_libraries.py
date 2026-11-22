"""Read Windows DLL version resources without loading the target libraries."""
import ctypes
import os
import json
from pathlib import Path


def file_version(path):
    if os.name!='nt':return None
    from ctypes import wintypes
    api=ctypes.WinDLL('version',use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype=wintypes.DWORD
    api.GetFileVersionInfoW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p]
    api.VerQueryValueW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(wintypes.UINT)]
    handle=wintypes.DWORD();size=api.GetFileVersionInfoSizeW(str(path),ctypes.byref(handle))
    if not size or size>1024**2:return None
    buffer=ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path),0,size,buffer):return None
    pointer=ctypes.c_void_p();length=wintypes.UINT()
    if not api.VerQueryValueW(buffer,'\\',ctypes.byref(pointer),ctypes.byref(length)) or length.value<52:return None
    values=ctypes.cast(pointer,ctypes.POINTER(wintypes.DWORD))
    if values[0]!=0xFEEF04BD:return None
    return '.'.join(map(str,(values[2]>>16,values[2]&65535,values[3]>>16,values[3]&65535)))


def inventory(root):
    locations=[('Strata',Path(root)/'engine'),('Unsloth llama.cpp',Path.home()/'.unsloth/llama.cpp/build/bin/Release'),
        ('Unsloth Whisper',Path.home()/'.unsloth/whisper.cpp/build/bin/Release'),
        ('Unsloth audio.cpp',Path.home()/'.unsloth/audio.cpp'),
        ('Unsloth PyTorch',Path.home()/'.unsloth/studio/unsloth_studio/Lib/site-packages/torch/lib')]
    root=Path(root)
    for owner,name in [('Strata selected','strata-runtime-selection.json'),('llama.cpp CPU selected','runtime-selection.json'),('llama.cpp GPU selected','runtime-gpu-selection.json'),('Whisper selected','whisper-runtime-selection.json'),('audio.cpp selected','audio-runtime-selection.json')]:
        try:
            active=json.loads((root/'data'/name).read_text(encoding='utf-8')).get('active')
            if not active:continue
            folder=Path(active.get('directory') or active.get('candidate_directory') or '').resolve()
            if not folder.is_relative_to((root/'output/updates/candidates').resolve()):continue
            binary=active.get('binary') or active.get('executable')
            if binary and Path(binary).resolve().is_relative_to(folder):folder=Path(binary).resolve().parent
            locations.append((owner,folder))
        except (OSError,ValueError,TypeError,KeyError):continue
    rows=[]
    for owner,folder in locations:
        for path in sorted(folder.glob('*.dll'))[:300]:
            if path.is_symlink():continue
            try:
                stat=path.stat()
                rows.append({'name':path.name,'owner':owner,'path':str(path.resolve()),
                'installed_version':file_version(path),'bytes':stat.st_size,'available_version':None,
                'file_id':f'{stat.st_dev}:{stat.st_ino}' if stat.st_ino else None,'hard_link_count':stat.st_nlink,
                'update_policy':'update_with_owning_runtime'})
            except (OSError,ValueError):continue
    names={row['name'].lower() for row in rows}
    shared=[{'name':name,'copies':[row for row in rows if row['name'].lower()==name]} for name in sorted(names)
        if sum(row['name'].lower()==name for row in rows)>1]
    identifiers={row['file_id'] for row in rows if row['file_id']}
    linked=[{'file_id':identity,'copies':[row for row in rows if row['file_id']==identity]} for identity in identifiers if sum(row['file_id']==identity for row in rows)>1]
    return {'libraries':rows,'shared':shared,'physically_linked':linked,'scope':'configured_runtime_directories','loaded_in_process':False}

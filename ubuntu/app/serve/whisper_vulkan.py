"""Additive, explicitly selected Vulkan runtime; the CPU registry stays unchanged."""
import hashlib
import json
from pathlib import Path

SERVER_SHA256='fd6ab11e404ebaa18fec9d5fc446ff4398fd9b2358a07d0da780bb13f4df146f'

def configuration(root):
    path=Path(root)/'data/whisper-vulkan-selection.json'
    if not path.exists():return {'enabled':False}
    if path.stat().st_size>4096:raise ValueError('Invalid Vulkan selection')
    value=json.loads(path.read_text(encoding='utf-8'))
    if type(value.get('enabled')) is not bool:raise ValueError('Invalid Vulkan selection')
    return value

def selected(root,device):
    if device not in ('cpu','vulkan'):raise ValueError('Choose CPU or Vulkan')
    if device=='cpu':return None
    value=configuration(root)
    if not value['enabled'] or value.get('gpu_validated') is not True:raise ValueError('Vulkan candidate not validated')
    path=Path(value['binary']).resolve(strict=True)
    if not path.is_relative_to((Path(root)/'output/updates/candidates').resolve()) or path.name!='whisper-server.exe':raise ValueError('Invalid Vulkan runtime path')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=SERVER_SHA256:raise ValueError('Vulkan runtime changed')
    return path

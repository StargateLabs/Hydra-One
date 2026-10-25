"""Format routing hints, never a claim that a backend can load every architecture."""
from pathlib import Path


def identify(path):
    path = Path(path)
    if path.is_file() and path.suffix.lower() == '.gguf':
        with path.open('rb') as source:
            if source.read(4) != b'GGUF':raise ValueError('Invalid GGUF magic')
        return dict(format='GGUF', candidate='llama.cpp', support='requires_backend_load_verification')
    if path.is_dir() and (path/'native_experts.txt').is_file():
        return dict(format='Strata native pack', candidate='existing_Strata_local_API', support='requires_backend_load_verification',
                    disk_expert_reads='backend_owned_model_specific')
    if path.is_dir() and (path/'config.json').is_file() and (any(path.glob('*.safetensors')) or (path/'model.safetensors.index.json').is_file()):
        return dict(format='Safetensors', candidate='existing_compatible_local_API', support='requires_backend_architecture_and_dependency_verification')
    return dict(format='unknown', candidate=None, support='unavailable')

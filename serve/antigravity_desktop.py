"""Discover and open the installed Google Antigravity desktop application.

Desktop OpenAI endpoint configuration is not documented by Google. SDK local
model support must not be reported as desktop inference support.
"""
import json
import os
from pathlib import Path
import subprocess

DOWNLOAD_URL = 'https://antigravity.google/download'
MODELS_URL = 'https://antigravity.google/docs/models'
SDK_LOCAL_MODELS_URL = 'https://antigravity.google/docs/sdk/local-models/'


def _candidates():
    if os.name != 'nt':
        return []
    # USERPROFILE avoids sandbox-remapped LOCALAPPDATA pointing at a different
    # app installation. Search only known installation locations.
    profile = os.environ.get('USERPROFILE')
    local = Path(profile) / 'AppData' / 'Local' if profile else None
    roots = [Path(os.environ[key]) for key in ('LOCALAPPDATA', 'ProgramFiles') if os.environ.get(key)]
    if local is not None:
        roots.insert(0, local)
    candidates = []
    for base in roots:
        for relative in ('Programs/Antigravity/Antigravity.exe', 'Programs/Google Antigravity/Antigravity.exe', 'Antigravity/Antigravity.exe'):
            path = base / relative
            if path not in candidates:
                candidates.append(path)
    return candidates


def executable():
    return next((path for path in _candidates() if path.is_file()), None)


def _product(path):
    if path is None:
        return {}
    try:
        value = json.loads((path.parent / 'resources/app/product.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def status(root=None):
    path = executable()
    product = _product(path)
    return {
        'installed': path is not None,
        'official': True,
        'original_web_renderer_available': bool(path and (path.parent/'resources/bin/language_server.exe').is_file()),
        'embedded_preview_scope': 'original_ui_without_cloud_or_native_electron_features',
        'executable': str(path) if path else None,
        'product_name': product.get('nameLong'),
        'authenticity_verified': False,
        'configured': False,
        'inference_verified': False,
        'desktop_local_endpoint_documented': False,
        'sdk_local_models_supported': True,
        'shared_mcp_configured': False,
        'shared_mcp_verified': False,
        'download_url': DOWNLOAD_URL,
        'models_documentation_url': MODELS_URL,
        'sdk_local_models_documentation_url': SDK_LOCAL_MODELS_URL,
        'message': ('Antigravity Desktop rilevato; endpoint locale Strata non documentato per questa app. '
                    'Il supporto OpenAI locale documentato riguarda il SDK Python.') if path else 'Antigravity Desktop non installato.',
    }


def launch(root=None):
    path = executable()
    if path is None:
        raise RuntimeError('Antigravity Desktop non installato. Scaricare l’app dal sito Google ufficiale.')
    subprocess.Popen([str(path)], cwd=str(path.parent), close_fds=True)
    return {'ok': True, 'launched': True, 'desktop': status(root)}

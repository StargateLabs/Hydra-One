"""Bounded official AirLLM package metadata; no environment mutation."""
import json
import re
import urllib.request


def release_from_metadata(data):
    info = data.get('info') or {}
    version = info.get('version', '')
    if info.get('name', '').lower() != 'airllm' or not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', version):
        raise ValueError('Official stable AirLLM package identity mismatch')
    return {'id': 'airllm', 'name': 'AirLLM', 'repository': 'lyogavin/airllm',
            'version': version, 'url': 'https://github.com/lyogavin/airllm',
            'release_url': 'https://pypi.org/project/airllm/' + version + '/',
            'requires_python': info.get('requires_python'), 'assets': [],
            'state': 'available', 'update_method': 'isolated_airllm_environment',
            'runtime_validated': False,
            'notes': 'Layer streaming lowers resident weight memory. Throughput depends on disk, hardware and model; no speed guarantee. Use a separate compatible environment.'}


def latest():
    request = urllib.request.Request('https://pypi.org/pypi/airllm/json',
                                    headers={'User-Agent': 'StargateLab-AirLLM-Updates'})
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('AirLLM metadata size limit')
    return release_from_metadata(json.loads(raw))

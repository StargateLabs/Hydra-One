"""Archive selected upstream sources without installing or executing Unsloth."""
import hashlib
import json
import argparse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ['README.md', 'LICENSE', 'unsloth/kernels/rms_layernorm.py',
    'unsloth/kernels/swiglu.py', 'unsloth/kernels/utils.py', 'unsloth/kernels/int4_packed.py',
    'unsloth/models/llama.py', 'unsloth/models/loader.py',
    'studio/backend/core/inference/worker.py', 'studio/LICENSE.AGPL-3.0',
    'unsloth/kernels/nf4.py', 'unsloth/kernels/nf4_gemv.py',
    'unsloth/kernels/rope_embedding.py', 'unsloth_cli/_inference.py',
    'studio/backend/core/inference/llama_cpp.py']

def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Strata-source-audit'})
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--commit')
    args = parser.parse_args()
    commit = args.commit or json.loads(fetch('https://api.github.com/repos/unslothai/unsloth/commits/main'))['sha']
    if len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('Expected a full commit SHA')
    target = ROOT / 'output/research' / f'unsloth-{commit[:12]}'
    rows = []
    for name in FILES:
        url = f'https://raw.githubusercontent.com/unslothai/unsloth/{commit}/{name}'
        content = fetch(url)
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        rows.append(dict(path=name, url=url, bytes=len(content), sha256=hashlib.sha256(content).hexdigest()))
    manifest = dict(repository='https://github.com/unslothai/unsloth', commit=commit,
        fetched_at=datetime.now(timezone.utc).isoformat(), files=rows,
        execution='Source inspection only; no packages installed, no GPU work')
    (target / 'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(commit=commit, directory=str(target), files=len(rows))))

if __name__ == '__main__':
    main()

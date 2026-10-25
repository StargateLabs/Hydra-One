"""Archive all official text documentation at the current main commit, without executing it."""
import hashlib
import argparse
import io
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/research/official-docs-main'

def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Strata-local-documentation-audit'})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', help='Archive an exact revision instead of resolving main again')
    args = parser.parse_args()
    commit = args.commit or json.loads(fetch('https://api.github.com/repos/Niko1221/Strata/commits/main'))['sha']
    if len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('Expected a full lowercase commit hash')
    archive = fetch(f'https://codeload.github.com/Niko1221/Strata/zip/{commit}')
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    with zipfile.ZipFile(io.BytesIO(archive)) as files:
        for item in files.infolist():
            relative = Path(*Path(item.filename).parts[1:])
            if item.is_dir() or relative.is_absolute() or '..' in relative.parts:
                continue
            is_text = relative.suffix.lower() in ('.md', '.txt', '.rst')
            is_doc_data = relative.parts[0] == 'docs' and relative.suffix.lower() in ('.json', '.yaml', '.yml')
            if not is_text and not is_doc_data:
                continue
            if relative.parts[0] not in ('docs', 'serve', 'bench') and len(relative.parts) != 1:
                continue
            content = files.read(item)
            target = OUT / commit / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            records.append({'path':relative.as_posix(),'bytes':len(content),
                            'sha256':hashlib.sha256(content).hexdigest()})
    old_manifest = OUT/'manifest.json'
    old = json.loads(old_manifest.read_text()) if old_manifest.is_file() else {}
    manifest = {'commit':commit,'archive_sha256':hashlib.sha256(archive).hexdigest(),
                'source':'https://github.com/Niko1221/Strata','documents':records}
    if old.get('commit') == commit and 'paper' in old:
        manifest['paper'] = old['paper']
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'commit':commit,'documents':len(records),'directory':str(OUT/commit)}))

if __name__ == '__main__':
    main()

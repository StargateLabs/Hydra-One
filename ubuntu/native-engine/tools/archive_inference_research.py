"""Archive primary repository trees and chosen text files, never execute upstream."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Strata-research'}),timeout=45) as response:
        return response.read()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('repo');parser.add_argument('--files',nargs='*',default=[])
    parser.add_argument('--commit')
    args = parser.parse_args()
    metadata = json.loads(fetch(f'https://api.github.com/repos/{args.repo}'))
    revision = args.commit or json.loads(fetch(f'https://api.github.com/repos/{args.repo}/commits/{metadata["default_branch"]}'))['sha']
    if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):raise ValueError('Invalid revision')
    target = ROOT/'output/research'/f'{args.repo.split("/")[-1]}-{revision[:12]}'
    target.mkdir(parents=True,exist_ok=True)
    tree = json.loads(fetch(f'https://api.github.com/repos/{args.repo}/git/trees/{revision}?recursive=1'))
    (target/'tree.json').write_text(json.dumps(tree,indent=2)+'\n',encoding='utf-8')
    manifest_path = target/'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else dict(repo=metadata['full_name'],commit=revision,files=[])
    known = {row['path']:row for row in manifest['files']}
    for name in args.files:
        if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('Invalid source path')
        url = f'https://raw.githubusercontent.com/{args.repo}/{revision}/{name}'
        content = fetch(url)
        path = target/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
        known[name] = dict(path=name,url=url,bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
    manifest['files'] = list(known.values());manifest['execution']='none'
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(repo=manifest['repo'],commit=revision,directory=str(target),files=len(known),tree_truncated=tree.get('truncated'))))
    if not args.files:
        print('\n'.join(row['path'] for row in tree['tree'] if row['type']=='blob' and ('cache' in row['path'].lower() or 'qwen38' in row['path'].lower() or row['path'].startswith('docs/'))))

if __name__ == '__main__':main()

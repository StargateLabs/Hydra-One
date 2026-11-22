"""Fetch unchanged logos exclusively from their publishers, recording source and digest."""
import hashlib,json,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ASSETS={
 'node':('https://nodejs.org/static/logos/nodejsHex.svg','https://nodejs.org/en/about/branding'),
 'git':('https://git-scm.com/images/logos/downloads/Git-Icon-1788C.svg','https://git-scm.com/community/logos'),
 'python':('https://s3.dualstack.us-east-2.amazonaws.com/pythondotorg-assets/media/files/python-logo-only.svg','https://www.python.org/community/logos/'),
 'uv':('https://raw.githubusercontent.com/astral-sh/uv/main/docs/assets/logo-letter.svg','https://github.com/astral-sh/uv/blob/main/mkdocs.yml'),
 'npm':('https://raw.githubusercontent.com/npm/logos/master/npm%20logo/npm-logo-red.svg','https://github.com/npm/logos'),
}
def main():
 records={}
 for name,(url,source) in ASSETS.items():
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'StargateLab-brand-assets'}),timeout=20) as response:raw=response.read(1024**2)
  if b'<svg' not in raw or b'<script' in raw or b'<html' in raw:raise ValueError('Unexpected logo content: '+name)
  target=ROOT/'serve/web'/('brand-'+name+'.svg');target.write_bytes(raw)
  records[name]={'file':target.name,'source':source,'download':url,'sha256':hashlib.sha256(raw).hexdigest(),'original_bytes':True}
  print(name+': verified official SVG',flush=True)
 path=ROOT/'serve/web/brands/OFFICIAL-ASSETS.json'
 try:saved=json.loads(path.read_text(encoding='utf-8'))
 except (OSError,ValueError):saved={}
 saved.update(records);path.write_text(json.dumps(saved,indent=2),encoding='utf-8')
if __name__=='__main__':main()

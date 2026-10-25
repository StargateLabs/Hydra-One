import hashlib,json,urllib.request,uuid
from pathlib import Path
root=Path.cwd();repo='ggml-org/SmolVLM-256M-Instruct-GGUF';info=json.load(urllib.request.urlopen('https://huggingface.co/api/models/'+repo));revision=info['sha'];files=json.load(urllib.request.urlopen('https://huggingface.co/api/models/'+repo+'/tree/'+revision));dest=root.parent/'Strata-data/models/optional/ggml-org--SmolVLM-256M-Instruct-GGUF'/revision;dest.mkdir(parents=True,exist_ok=True);manifest={'repo':repo,'revision':revision,'license':'apache-2.0','files':[]}
for name in ['SmolVLM-256M-Instruct-Q8_0.gguf','mmproj-SmolVLM-256M-Instruct-f16.gguf']:
 entry=next(f for f in files if f['path']==name);target=dest/name;sha=entry['lfs']['oid'];partial=dest/(uuid.uuid4().hex+'.partial')
 if not target.exists():
  try:
   with urllib.request.urlopen('https://huggingface.co/'+repo+'/resolve/'+revision+'/'+name,timeout=60) as response,partial.open('xb') as output:
    while block:=response.read(1024**2):output.write(block)
   assert partial.stat().st_size==entry['size'];assert hashlib.file_digest(partial.open('rb'),'sha256').hexdigest()==sha;partial.rename(target)
  finally:partial.unlink(missing_ok=True)
 with target.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==sha
 manifest['files'].append({'path':str(target),'sha256':sha,'bytes':entry['size']});print(name+' verified',flush=True)
(dest/'provenance.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8');(root/'output/verification/vision-model-provenance.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')

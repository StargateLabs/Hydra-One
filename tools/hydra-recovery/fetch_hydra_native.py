import hashlib,io,json,urllib.request,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[2]/'hydra-engine/engine_completion_v22'
commit='e3de715222b2667c54a267441159a5729f11155e'
dest=root/'prism-source'
if dest.exists():
 print('Source already present')
 raise SystemExit(0)
url='https://codeload.github.com/PrismML-Eng/llama.cpp/zip/'+commit
with urllib.request.urlopen(url,timeout=90) as response:raw=response.read(160*1024**2+1)
if len(raw)>160*1024**2:raise ValueError('Source archive exceeds budget')
if hashlib.sha256(raw).hexdigest()!='5d9530011900e573b41df334afc4c3784f17857e13689e8b4fdc6b2c99cf0fcd':
 raise ValueError('Official source archive identity differs from recovered build receipt')
with zipfile.ZipFile(io.BytesIO(raw)) as archive:
 for name in archive.namelist():
  relative=Path(*Path(name).parts[1:])
  if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe archive member')
 for item in archive.infolist():
  relative=Path(*Path(item.filename).parts[1:]);target=dest/relative
  if item.is_dir():target.mkdir(parents=True,exist_ok=True)
  else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(item))
record=dict(url=url,source_commit=commit,archive_sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
(root/'source-download.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record))

"""Import an image dataset into one owned folder, preserving source files."""
import base64,hashlib,json,uuid
from pathlib import Path

def upload(root,payload):
 from tools.train_vlm_lora import rows
 kind=payload.get('kind');content=payload.get('content');images=payload.get('images')
 if kind not in ('train','validation') or not isinstance(content,str) or len(content.encode('utf-8'))>1024**2:raise ValueError('Vision dataset: choose training/validation and JSONL or JSON up to 1 MiB')
 if not isinstance(images,list) or not 1<=len(images)<=32:raise ValueError('Select 1 to 32 local images')
 try:
  records=json.loads(content) if str(payload.get('name','')).lower().endswith('.json') else [json.loads(line) for line in content.splitlines() if line.strip()]
 except (ValueError,TypeError) as error:raise ValueError('Invalid vision JSON or JSONL') from error
 if isinstance(records,dict):records=[records]
 if not isinstance(records,list) or not 1<=len(records)<=1000:raise ValueError('Vision dataset requires 1 to 1000 samples')
 decoded={};total=0
 for image in images:
  if not isinstance(image,dict):raise ValueError('Invalid image upload')
  name=image.get('name');data=image.get('content')
  if not isinstance(name,str) or not name or len(name)>160 or any(c in name for c in '/\\:') or name in ('.','..') or Path(name).suffix.lower() not in ('.png','.jpg','.jpeg','.webp'):raise ValueError('Use an image filename without a path')
  key=name.casefold()
  if key in decoded:raise ValueError('Duplicate image filename')
  if not isinstance(data,str) or len(data)>2*1024**2*4//3+4:raise ValueError('Image exceeds 2 MiB')
  try:raw=base64.b64decode(data,validate=True)
  except ValueError as error:raise ValueError('Invalid image base64') from error
  total+=len(raw)
  if not raw or len(raw)>2*1024**2 or total>5*1024**2:raise ValueError('Images exceed 2 MiB each or 5 MiB combined')
  decoded[key]=(name,raw)
 # Validate references before creating files; users need not type absolute paths.
 for row in records:
  if not isinstance(row,dict) or set(row)!={'prompt','response','image'} or not isinstance(row.get('image'),str) or row['image'].casefold() not in decoded:raise ValueError('Each sample needs prompt, response and a matching selected image filename')
 folder=Path(root).resolve()/'output/training-datasets'/('vision-'+uuid.uuid4().hex);folder.mkdir(parents=True)
 try:
  paths={}
  for key,(name,raw) in decoded.items():
   target=folder/(uuid.uuid4().hex+Path(name).suffix.lower());target.write_bytes(raw);paths[key]=str(target)
  target=folder/'dataset.jsonl';target.write_text(''.join(json.dumps({**row,'image':paths[row['image'].casefold()]},ensure_ascii=False)+'\n' for row in records),encoding='utf-8')
  checked=rows(target)
  return {'path':str(target),'kind':kind,'rows':len(checked),'images':len(decoded),'bytes':target.stat().st_size+total,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
 except Exception:
  # Only this call's flat, randomly named folder is removed on validation failure.
  for child in folder.iterdir():child.unlink()
  folder.rmdir()
  raise

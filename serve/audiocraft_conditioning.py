"""Read bounded checkpoint metadata without executing pickle instructions."""
import json,pickletools,zipfile,re
from pathlib import Path

def checkpoint_encoder(path):
 try:return _checkpoint_encoder(path)
 except (zipfile.BadZipFile,KeyError,EOFError) as error:raise ValueError("Invalid AudioCraft checkpoint metadata") from error

def _checkpoint_encoder(path):
 with zipfile.ZipFile(path) as archive:
  matches=[entry for entry in archive.infolist() if entry.filename.endswith('/data.pkl') or entry.filename=='data.pkl']
  if len(matches)!=1 or matches[0].file_size>16*1024**2:raise ValueError('Unsupported AudioCraft checkpoint metadata')
  names=set()
  for opcode,value,_ in pickletools.genops(archive.read(matches[0])):
   if opcode.name not in ('UNICODE','BINUNICODE','SHORT_BINUNICODE','BINUNICODE8'):continue
   if value in ('t5-base','t5-large'):names.add(value)
   names.update(re.findall(r'(?m)^\s*name:\s*[\'"]?(t5-(?:base|large))\b',value))
 if len(names)!=1:raise ValueError('Original conditioning encoder cannot be determined safely')
 return names.pop()

def selected_cache(root,encoder):
 if encoder not in ('t5-base','t5-large'):raise ValueError('Unsupported conditioning encoder')
 root=Path(root).resolve();registry=root/('data/audiocraft-conditioning.json' if encoder=='t5-large' else 'data/audiocraft-conditioning-t5-base.json')
 if not registry.is_file():raise ValueError('Prepare the original '+encoder+' conditioning encoder in AudioCraft settings')
 row=json.loads(registry.read_text(encoding='utf-8'));cache=Path(row['cache']).resolve();revision=row.get('revision','')
 ref=cache/('models--'+encoder)/'refs/main'
 if row.get('validated') is not True or row.get('repository')!='google-t5/'+encoder or not cache.is_relative_to(root/'output/updates/audiocraft-candidates') or not ref.is_file() or ref.read_text(encoding='utf-8').strip()!=revision:raise ValueError('Conditioning encoder has no validated local selection')
 return cache

def style_dependency(root,verify=False):
 root=Path(root).resolve();path=root/'data/audiocraft-style-dependency.json'
 if not path.is_file():raise ValueError('Prepara MERT locale per MusicGen Style nelle impostazioni AudioCraft')
 row=json.loads(path.read_text(encoding='utf-8'));folder=Path(row['folder']).resolve();cache=selected_cache(root,'t5-base')
 if row.get('repository')!='m-a-p/MERT-v1-95M' or row.get('revision')!='12af15fef9d0ac838c3f475bfbbf26d2060dd4f5' or not folder.is_relative_to(cache):raise ValueError('Dipendenza Style non verificata')
 expected={'config.json','configuration_MERT.py','modeling_MERT.py','preprocessor_config.json','pytorch_model.bin'}
 if set(row.get('files',{}))!=expected:raise ValueError('File MERT incompleti')
 import hashlib
 for name,digest in row['files'].items():
  file=folder/name
  if not file.is_file() or file.is_symlink():raise ValueError('File MERT mancante')
  if verify:
   with file.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
   if actual!=digest:raise ValueError('File MERT modificato: prepara nuovamente il componente')
 return row

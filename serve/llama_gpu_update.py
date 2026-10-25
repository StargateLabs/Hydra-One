"""A GPU selection is separate from the existing CPU registry."""
import hashlib,json,time
from pathlib import Path
from serve.configuration import atomic_json

def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  while block:=stream.read(1024*1024):h.update(block)
 return h.hexdigest()

def proof(root,candidate,verify=False,report=None):
 root=Path(root);base=(root/'output/updates/candidates').resolve()
 directory=Path(candidate['candidate_directory']).resolve()
 if not directory.is_relative_to(base):raise ValueError('GPU candidate is outside the isolated folder')
 if report is None:
  report_path=directory/'GPU-validation.json'
  if not report_path.is_file():report_path=root/'output/verification/llama-b11541-gpu-real.json'
  report=json.loads(report_path.read_text(encoding='utf-8'))
 url=candidate.get('source','')
 if not url.startswith('https://github.com/unslothai/llama.cpp/releases/download/') or not url.endswith('windows-x64-rocm-gfx110X.zip'):
  raise ValueError('The GPU proof applies only to the verified gfx110X package')
 if report.get('passed') is not True or report.get('gpu_offload_confirmed') is not True or report.get('owned_process_stopped') is not True or report.get('original_preserved') is not True or report.get('state',{}).get('gpu_requested') is not True:
  raise ValueError('Completed real GPU validation is required')
 if Path(report['candidate']).resolve()!=directory or report.get('archive_sha256')!=candidate.get('sha256'):
  raise ValueError('GPU proof belongs to another candidate')
 version=url.split('/releases/download/',1)[1].split('/',1)[0]
 if report.get('version')!=version:raise ValueError('GPU proof version differs')
 files=candidate.get('files',[])
 if not files or len(files)>20000:raise ValueError('GPU file manifest is missing or oversized')
 if verify:
  for row in files:
   raw=directory/row['path'];path=raw.resolve()
   if raw.is_symlink() or not path.is_relative_to(directory) or not path.is_file() or path.stat().st_size!=row['bytes'] or digest(path)!=row['sha256']:
    raise ValueError('GPU candidate files changed')
 binary=directory/'llama-server.exe'
 if not binary.is_file() or not any(row['path']=='llama-server.exe' for row in files):raise ValueError('GPU server is missing')
 return dict(binary=str(binary),directory=str(directory),files=files,scope='llama_gpu',version=version,validation=report,archive_sha256=candidate['sha256'],source=url)

def activate(root,candidate):
 from serve.customization_backup import snapshot
 root=Path(root);selected=proof(root,candidate,verify=True);registry=root/'data/runtime-gpu-selection.json'
 try:previous=json.loads(registry.read_text(encoding='utf-8')).get('active')
 except (OSError,ValueError):previous=None
 selected['activated_at']=time.time();backup=snapshot(root)
 atomic_json(registry,dict(active=selected,previous=previous,backup=backup))
 return selected

def rollback(root):
 path=Path(root)/'data/runtime-gpu-selection.json';data=json.loads(path.read_text(encoding='utf-8'))
 atomic_json(path,dict(active=data.get('previous'),previous=data.get('active'),backup=data.get('backup'),rolled_back_at=time.time()))

def selected_binary(root):
 root=Path(root);path=root/'data/runtime-gpu-selection.json'
 if not path.exists():return None
 active=json.loads(path.read_text(encoding='utf-8')).get('active')
 if not active:return None
 if active.get('scope')!='llama_gpu':raise ValueError('Invalid GPU selection scope')
 selected=proof(root,dict(candidate_directory=active['directory'],files=active['files'],sha256=active['archive_sha256'],source=active['source']),verify=True,report=active.get('validation'))
 if Path(active['binary']).resolve()!=Path(selected['binary']).resolve():raise ValueError('GPU server selection differs')
 return Path(selected['binary'])

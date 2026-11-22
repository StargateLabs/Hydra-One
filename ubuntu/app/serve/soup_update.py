"""Pinned, isolated Soup update with real CPU, GPU and streaming checks."""
import hashlib,json,os,stat,subprocess,time,uuid,zipfile
from pathlib import Path
from urllib.request import urlopen,Request
from urllib.parse import urlparse

VERSION='0.76.0'

def prepare(root,version,progress):
 from serve.configuration import atomic_json
 from serve.gpu_lease import GpuLease
 root=Path(root).resolve()
 if version!=VERSION:raise ValueError('This Soup version needs a reviewed compatibility bridge')
 base=json.loads((root/'output/verification/soup-0752-cpu-real.json').read_text(encoding='utf-8'))['workflow']['base']
 cpu=root/'.venv-soup/Scripts/python.exe';gpu=Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe'
 if not cpu.is_file() or not gpu.is_file() or not Path(base).is_dir():raise ValueError('Soup update requires the installed CPU/GPU runtimes and local verification model')
 folder=root/'output/updates/soup-candidates'/version;folder.mkdir(parents=True,exist_ok=True)
 def get(url):
  response=urlopen(Request(url,headers={'User-Agent':'StargateLab-SoupUpdater'}),timeout=30)
  if urlparse(response.url).scheme!='https' or urlparse(response.url).hostname not in ('pypi.org','files.pythonhosted.org'):response.close();raise ValueError('Unexpected official package redirect')
  return response
 progress(state='downloading',bytes=0,total=0)
 with get(f'https://pypi.org/pypi/soup-cli/{version}/json') as response:metadata=json.loads(response.read(2*1024*1024))
 if metadata['info']['name']!='soup-cli' or metadata['info']['version']!=version:raise ValueError('Unexpected Soup package metadata')
 wheels=[row for row in metadata['urls'] if row['filename']==f'soup_cli-{version}-py3-none-any.whl' and not row.get('yanked')]
 if len(wheels)!=1:raise ValueError('No unique official Soup wheel')
 row=wheels[0];size=row['size'];digest=row['digests']['sha256'];url=row['url']
 if size>16*1024*1024 or urlparse(url).hostname!='files.pythonhosted.org':raise ValueError('Invalid official wheel')
 wheel=folder/row['filename'];temporary=wheel.with_suffix('.part');received=0;started=time.monotonic()
 if not wheel.is_file() or hashlib.sha256(wheel.read_bytes()).hexdigest()!=digest:
  with get(url) as source,temporary.open('wb') as sink:
   while block:=source.read(256*1024):
    received+=len(block)
    if received>size:raise ValueError('Soup wheel exceeds declared size')
    sink.write(block);progress(state='downloading',bytes=received,total=size,bytes_per_second=received/max(.001,time.monotonic()-started))
  if received!=size or hashlib.sha256(temporary.read_bytes()).hexdigest()!=digest:raise ValueError('Soup wheel checksum mismatch')
  temporary.replace(wheel)
 package=folder/'packages';package.mkdir(exist_ok=True);progress(state='preparing',bytes=size,total=size)
 with zipfile.ZipFile(wheel) as archive:
  members=archive.infolist()
  if len(members)>5000 or sum(m.file_size for m in members)>64*1024*1024:raise ValueError('Soup archive exceeds limits')
  for member in members:
   name=member.filename.replace('\\','/');target=(package/name).resolve()
   if not target.is_relative_to(package.resolve()) or ':' in name or stat.S_ISLNK(member.external_attr>>16) or member.flag_bits&1:raise ValueError('Unsafe Soup archive member')
   if member.is_dir():target.mkdir(parents=True,exist_ok=True);continue
   target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(member))
 atomic_json(folder/'manifest.json',{'version':version,'wheel':str(wheel),'sha256':digest,'package_root':str(package),'source':url})
 # Reserve both dashboards for all three short checks. Never change their installed dependencies.
 with GpuLease(root,'soup-update-'+version):
  for label,device,python,script in [('cpu','cpu',cpu,'train_soup_candidate_0760.py'),('gpu','cuda',gpu,'train_soup_candidate_0760.py'),('streaming','cuda',gpu,'train_soup_streaming_candidate_0760.py')]:
   progress(state='validating',validation_step=label)
   output=root/'output/verification'/('soup-'+version.replace('.','')+'-'+label+'-'+uuid.uuid4().hex[:8]);output.mkdir()
   command=[str(python),'-X','utf8',str(root/'tools'/script),'--device',device,'--package-root',str(package),'--model',base,'--train',str(root/'output/verification/training-smoke-train.jsonl'),'--validation',str(root/'output/verification/training-smoke-validation.jsonl'),'--output',str(output/'training'),'--steps','1','--length','64']
   with (output/'worker.log').open('wb') as log:result=subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   path=output/'training/workflow.json';workflow=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
   passed=result.returncode==0 and workflow.get('status')=='complete' and workflow.get('soup_version')==version and workflow.get('export_logits_verified') is True and workflow.get('export_greedy_tokens_equal') is True
   if label=='streaming':passed=passed and workflow.get('streaming_active') is True
   proof={'passed':passed,'exit_code':result.returncode,'version':version,'device':device,'workflow':workflow,'folder':str(output),'scope':'One trained local 135M step and export parity; no large-model performance claim'}
   atomic_json(root/f'output/verification/soup-{version.replace(".","")}-{label}-real.json',proof)
   if not passed:raise ValueError('Soup '+label+' validation failed; previous version preserved. Details: '+str(output/'worker.log'))
 return {'version':version,'package_root':str(package),'runtime_validated':True,'gpu_validated':True}

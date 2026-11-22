"""Update Transformers in a copied ROCm dependency closure, never in the vendor env."""
import hashlib,json,os,subprocess
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlparse

def prepare(root,source_python,version,progress,reuse_folder=None):
 import re
 from tools.prepare_training_candidate import prepare as clone
 from serve.configuration import atomic_json
 from serve.update_center import check_dependencies
 if not isinstance(version,str) or not re.fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('Invalid Transformers version')
 original_source=str(Path(source_python).resolve())
 # Reuse the already proven native dependency baseline when the original
 # desktop environment still carries an older incompatible dependency.
 from serve.training_runtime_candidates import candidate
 plans=Path(root)/'output/updates/python-plans'
 for path in sorted(plans.glob('*/environment-manifest.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:64]:
  try:
   saved=json.loads(path.read_text(encoding='utf-8'))
   if saved.get('source_python')!=original_source or saved.get('runner')!='unsloth_qlora':continue
   source_python,_=candidate(root,path.parent,'unsloth_qlora','cuda')
   break
  except (OSError,ValueError,KeyError):continue
 progress(state='installing_candidate',phase='preserving_vendor_runtime')
 if reuse_folder:
  folder=Path(reuse_folder).resolve()
  if not folder.is_relative_to(plans.resolve()):raise ValueError('Invalid reusable vendor candidate')
  manifest=json.loads((folder/'environment-manifest.json').read_text(encoding='utf-8'))
  if manifest.get('source_python')!=str(source_python) or manifest.get('activated') or manifest.get('training_validation') or manifest.get('inference_validation'):raise ValueError('Only this unfinished copied dependency baseline can be resumed')
 else:manifest=clone(root,source_python,'unsloth_qlora');folder=Path(manifest['plan_directory'])
 python=Path(manifest['python'])
 if manifest['dependency_health']['state']!='healthy':raise ValueError('Copied vendor dependencies are incompatible; source preserved')
 original=dict(manifest['source_packages']);torch=original.get('torch','')
 if 'rocm' not in torch:raise ValueError('Expected the installed ROCm dependency closure')
 # The resolver can see installed vendor distributions. Other versions stay constrained.
 allowed={'transformers','tokenizers'}
 constraints=folder/'preserved-versions.txt';constraints.write_text(''.join(name+'=='+value+'\n' for name,value in original.items() if name not in allowed),encoding='utf-8')
 env={**os.environ,'PIP_CONFIG_FILE':os.devnull,'PIP_INDEX_URL':'https://pypi.org/simple','PIP_EXTRA_INDEX_URL':'','PIP_FIND_LINKS':''}
 flags=getattr(subprocess,'CREATE_NO_WINDOW',0);report=folder/'pip-report.json'
 result=subprocess.run([str(python),'-I','-m','pip','install','--dry-run','--only-binary=:all:','--disable-pip-version-check','--timeout','10','--retries','0','--report',str(report),'-c',str(constraints),'transformers=='+version],env=env,capture_output=True,text=True,timeout=90,creationflags=flags)
 (folder/'resolver.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
 if result.returncode:raise ValueError('Transformers conflicts with the preserved vendor versions; inspect '+str(folder/'resolver.log'))
 packages=json.loads(report.read_text(encoding='utf-8')).get('install',[])
 names={package['metadata']['name'].lower() for package in packages}
 if not names or not names.issubset(allowed) or 'transformers' not in names or len(names)!=len(packages) or next(p for p in packages if p['metadata']['name'].lower()=='transformers')['metadata']['version']!=version:raise ValueError('The update would change an unrelated dependency')
 wheels=[];official=[]
 for package in packages:
  download=package['download_info'];url=download['url'];digest=download.get('archive_info',{}).get('hashes',{}).get('sha256','');parsed=urlparse(url)
  if parsed.scheme!='https' or parsed.hostname!='files.pythonhosted.org' or parsed.username or parsed.password or not parsed.path.endswith('.whl') or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('Official package wheel integrity is missing')
  with urlopen(Request(url,headers={'User-Agent':'StargateLab-Updater'}),timeout=30) as response:
   if urlparse(response.url).hostname!='files.pythonhosted.org':raise ValueError('Unexpected wheel redirect')
   raw=response.read(32*1024**2+1)
  if len(raw)>32*1024**2 or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Package wheel checksum mismatch')
  wheel=folder/Path(parsed.path).name;wheel.write_bytes(raw);wheels.append(str(wheel));official.append({'name':package['metadata']['name'],'version':package['metadata']['version'],'url':url,'sha256':digest})
 progress(state='installing_candidate',phase='installing_verified_transformers')
 result=subprocess.run([str(python),'-I','-m','pip','install','--no-index','--no-deps',*wheels],env=env,capture_output=True,text=True,timeout=90,creationflags=flags)
 (folder/'installation.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
 if result.returncode:raise ValueError('Isolated Transformers installation failed')
 health=check_dependencies(python)
 if health['state']!='healthy':raise ValueError('Updated vendor candidate has incompatible dependencies: '+health.get('details',''))
 # Re-read all actual candidate versions; tolerate no silent native substitution.
 code="import importlib.metadata as m,json;print(json.dumps({d.metadata['Name'].lower().replace('_','-'):d.version for d in m.distributions() if d.metadata['Name']}))"
 result=subprocess.run([str(python),'-I','-c',code],capture_output=True,text=True,timeout=15,creationflags=flags)
 if result.returncode:raise ValueError('Candidate package inventory failed')
 current=json.loads(result.stdout)
 if any(current.get(name)!=value for name,value in original.items() if name not in allowed) or current.get('transformers')!=version:raise ValueError('A preserved dependency changed')
 manifest.update(source_packages=current,original_packages=original,original_source_python=original_source,vendor_copy=True,dependency_health=health,official_wheels=official,updated_dependencies={name:{'from':original.get(name),'to':current.get(name)} for name in allowed if original.get(name)!=current.get(name)},installed=True,activated=False,runtime_validated=False)
 atomic_json(folder/'environment-manifest.json',manifest)
 return manifest


def canonical(name):return str(name).lower().replace('_','-')


def reconciled_health(source_text,candidate_text,healthy):
 if healthy:return 'healthy'
 return 'preserved_conflicts' if source_text.strip() and candidate_text.strip()==source_text.strip() else 'conflicts'


def constraints_text(original,allowed):
 allowed={canonical(name) for name in allowed}
 return ''.join(name+'=='+version+'\n' for name,version in original.items() if canonical(name) not in allowed)


def validate_report(packages,allowed,requested,original):
 allowed={canonical(name) for name in allowed};requested={canonical(name):version for name,version in requested.items()}
 names=[canonical(package['metadata']['name']) for package in packages]
 if any(name not in allowed for name in names):raise ValueError('The update would change a non-allowlisted dependency')
 for name,version in requested.items():
  row=next((package for package in packages if canonical(package['metadata']['name'])==name),None)
  if row is None:
   if version is None or canonical(original.get(name,''))==canonical(version):continue
   raise ValueError('Requested package missing from the resolution: '+name)
  if version is not None and canonical(row['metadata']['version'])!=canonical(version):raise ValueError('Resolved version differs for '+name)
 return names


def _official_wheels(packages,folder):
 import re
 wheels=[];official=[]
 for package in packages:
  download=package['download_info'];url=download['url'];digest=download.get('archive_info',{}).get('hashes',{}).get('sha256','');parsed=urlparse(url)
  if parsed.scheme!='https' or parsed.hostname!='files.pythonhosted.org' or parsed.username or parsed.password or not parsed.path.endswith('.whl') or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('Official package wheel integrity is missing')
  with urlopen(Request(url,headers={'User-Agent':'StargateLab-Updater'}),timeout=30) as response:
   if urlparse(response.url).hostname!='files.pythonhosted.org':raise ValueError('Unexpected wheel redirect')
   raw=response.read(32*1024**2+1)
  if len(raw)>32*1024**2 or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Package wheel checksum mismatch')
  wheel=folder/Path(parsed.path).name;wheel.write_bytes(raw);wheels.append(str(wheel));official.append({'name':package['metadata']['name'],'version':package['metadata']['version'],'url':url,'sha256':digest})
 return wheels,official


def prepare_packages(root,source_python,packages,progress,reuse_folder=None,runner='full'):
 from tools.prepare_training_candidate import prepare as clone
 from serve.configuration import atomic_json
 from serve.update_center import check_dependencies
 requested={canonical(name):version for name,version in packages.items()};allowed=set(requested)
 if not allowed:raise ValueError('Choose at least one package')
 if any(name in ('torch','torchvision','torchaudio','triton','pytorch-triton-rocm') or name.startswith('amd-torch-device-') for name in allowed):raise ValueError('Vendor GPU packages are never updated by allowlist')
 progress(state='installing_candidate',phase='copying_vendor_environment')
 manifest=clone(root,source_python,runner,extra_roots=list(requested));folder=Path(manifest['plan_directory']);python=Path(manifest['python'])
 original={canonical(name):version for name,version in manifest['source_packages'].items()}
 source_check=subprocess.run([str(source_python),'-I','-m','pip','check'],capture_output=True,text=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 source_text=(source_check.stdout+source_check.stderr).strip()
 initial=reconciled_health(source_text,manifest.get('dependency_health',{}).get('details',''),manifest.get('dependency_health',{}).get('state')=='healthy')
 if initial=='conflicts':raise ValueError('Copied vendor dependencies are incompatible; source preserved')
 constraints=folder/'preserved-versions.txt';constraints.write_text(constraints_text(original,allowed),encoding='utf-8')
 specs=[name+('=='+version if version else '') for name,version in requested.items()]
 upgrade=['--upgrade'] if any(version is None for version in requested.values()) else []
 env={**os.environ,'PIP_CONFIG_FILE':os.devnull,'PIP_INDEX_URL':'https://pypi.org/simple','PIP_EXTRA_INDEX_URL':'','PIP_FIND_LINKS':''}
 flags=getattr(subprocess,'CREATE_NO_WINDOW',0);report=folder/'pip-report.json'
 result=subprocess.run([str(python),'-I','-m','pip','install','--dry-run','--only-binary=:all:','--disable-pip-version-check','--timeout','10','--retries','0','--report',str(report),'-c',str(constraints),*upgrade,*specs],env=env,capture_output=True,text=True,timeout=180,creationflags=flags)
 (folder/'resolver.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
 if result.returncode:raise ValueError('Allowlist conflicts with the preserved vendor versions; inspect resolver.log')
 resolved=json.loads(report.read_text(encoding='utf-8')).get('install',[]);validate_report(resolved,allowed,requested,original)
 wheels,official=_official_wheels(resolved,folder)
 if wheels:
  progress(state='installing_candidate',phase='installing_verified_allowlist')
  result=subprocess.run([str(python),'-I','-m','pip','install','--no-index','--no-deps',*wheels],env=env,capture_output=True,text=True,timeout=120,creationflags=flags)
  (folder/'installation.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
  if result.returncode:raise ValueError('Isolated allowlist installation failed')
 health=check_dependencies(python)
 state=reconciled_health(source_text,health.get('details',''),health['state']=='healthy')
 health={**health,'state':state,'source_conflicts':source_text}
 if state=='conflicts':raise ValueError('Updated vendor candidate has new dependency conflicts: '+health.get('details',''))
 code="import importlib.metadata as m,json;print(json.dumps({d.metadata['Name'].lower().replace('_','-'):d.version for d in m.distributions() if d.metadata['Name']}))"
 result=subprocess.run([str(python),'-I','-c',code],capture_output=True,text=True,timeout=15,creationflags=flags)
 if result.returncode:raise ValueError('Candidate package inventory failed')
 current=json.loads(result.stdout)
 if any(current.get(name)!=version for name,version in original.items() if name not in allowed):raise ValueError('A preserved dependency changed')
 manifest.update(source_packages=current,original_packages=original,original_source_python=str(Path(source_python).resolve()),vendor_copy=True,dependency_health=health,official_wheels=official,allowed_dependencies=sorted(allowed),updated_dependencies={name:{'from':original.get(name),'to':current.get(name)} for name in allowed if original.get(name)!=current.get(name)},installed=True,activated=False,runtime_validated=False)
 atomic_json(folder/'environment-manifest.json',manifest)
 return manifest

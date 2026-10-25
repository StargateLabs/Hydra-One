"""Official installed Hermes runtime, dedicated home and local MCP/model wiring."""
import json,os,re,subprocess
from functools import lru_cache
from pathlib import Path
@lru_cache(maxsize=1)
def runtime(root=None):
 if root is not None:
  from serve.harness_updates import selected
  active=selected(root,'hermes',verify=False)
  if active and active.get('source'):return {'python':Path(active['binary']),**{key:Path(active[key]) for key in ('source','site','venv')}}
 folder=Path(os.environ.get('LOCALAPPDATA',''))/'hermes';source=folder/'hermes-agent'
 if not (source/'hermes_cli/web_server.py').is_file():return None
 candidates=list((folder/'installs').glob('*/environments/*/venv/Scripts/python.exe'))
 for python in candidates:
  try:
   probe=subprocess.run([str(python),'-c','import fastapi;print(fastapi.__version__)'],capture_output=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   if probe.returncode==0:
    configuration=(python.parent.parent/'pyvenv.cfg').read_text(encoding='utf-8')
    home=next(line.split('=',1)[1].strip() for line in configuration.splitlines() if line.startswith('home ='))
    base=Path(home)/'python.exe'
    if base.is_file():return {'python':base,'venv':python.parent.parent,'site':python.parent.parent/'Lib/site-packages','source':source}
  except (OSError,subprocess.SubprocessError):continue
 return None
@lru_cache(maxsize=1)
def installed_version():
 found=runtime()
 if not found:return None
 try:
  describe=subprocess.run(['git','describe','--tags','--always'],cwd=found['source'],capture_output=True,text=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).stdout.strip();match=re.search(r'(\d+\.\d+\.\d+)',describe)
  return {'installed_version':match.group(1) if match else None,'installed_revision':describe,'installed_source':'official_existing_hermes_runtime'}
 except (OSError,subprocess.SubprocessError):return None

def write_config(harness):
 import yaml
 from serve.trueforge_setup import bridge_token
 home=harness.home();home.mkdir(parents=True,exist_ok=True);path=home/'config.yaml'
 try:data=yaml.safe_load(path.read_text(encoding='utf-8')) or {}
 except FileNotFoundError:data={}
 # Hermes' official OpenAI-compatible local adapter accepts an explicit
 # short window; keep the real served context rather than advertising 64K.
 adapter='lmstudio' if 0<harness.model_context<64000 else 'custom'
 data.setdefault('model',{}).update(default=harness.model_id,provider=adapter,base_url=harness.base_url)
 data['model']['context_length']=harness.model_context
 data.setdefault('mcp_servers',{})['stargatelab']={'url':harness.base_url.removesuffix('/v1')+'/harness/mcp','headers':{'Authorization':'Bearer '+bridge_token(harness.root)}}
 path.write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False),encoding='utf-8')
 return path

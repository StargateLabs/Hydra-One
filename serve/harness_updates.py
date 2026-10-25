"""Official npm harness candidates; user session homes are never installation targets."""
import hashlib,json,os,re,shutil,socket,subprocess,threading,time,urllib.request,uuid
from pathlib import Path
PACKAGES={'opencode':'@opencode/cli','dsh':'@deepseek-ai/dsh','trueforge':'@truefoundry/trueforge','browser':'@playwright/mcp','memory':'@modelcontextprotocol/server-memory'}
REPOSITORIES={'opencode':'anomalyco/opencode','dsh':'deepseek-ai/deepseek-harness','trueforge':'truefoundry/trueforge','browser':'microsoft/playwright-mcp','memory':'modelcontextprotocol/servers','hermes':'NousResearch/hermes-agent','claude':'anthropics/claude-code'}

def _native_path(path):
 path=os.path.abspath(path)
 if os.name!='nt' or path.startswith('\\\\?\\'):return Path(path)
 return Path('\\\\?\\UNC\\'+path[2:] if path.startswith('\\\\') else '\\\\?\\'+path)

def staging_candidate(root,kind,version):
 candidate=Path(root)/'output/updates/harness-candidates'/kind/version
 manifest=candidate/'VALIDATED.json'
 if manifest.is_file():
  try:
   row=json.loads(manifest.read_text());binary=Path(row['binary'])
   if not binary.resolve().is_relative_to(candidate.resolve()) or row.get('version')!=version or hashlib.sha256(binary.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Candidate changed')
  except (OSError,ValueError,KeyError,TypeError):
   # Keep the old candidate available for rollback and recovery inspection.
   return candidate.with_name(version+'-repair-'+uuid.uuid4().hex)
 return candidate
def latest(kind):
 if kind=='claude':
  with urllib.request.urlopen('https://downloads.claude.ai/claude-code-releases/latest',timeout=15) as response:version=response.read(256).decode().strip()
  if not re.fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('Invalid official Claude release')
  return {'id':kind,'version':version,'repository':REPOSITORIES[kind],'url':'https://code.claude.com','release_url':'https://downloads.claude.ai/claude-code-releases/'+version+'/manifest.json','state':'available','assets':[],'update_method':'isolated_native_claude','notes':'Official native CLI; isolated home preserved. CLI validation does not verify local model inference.'}
 if kind=='hermes':
  request=urllib.request.Request('https://api.github.com/repos/NousResearch/hermes-agent/releases/latest',headers={'User-Agent':'StargateLab-Update-Center'})
  with urllib.request.urlopen(request,timeout=15) as response:data=json.load(response)
  version=data['tag_name'].removeprefix('v')
  if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?',version):raise ValueError('Invalid official Hermes release')
  return {'id':kind,'version':version,'repository':REPOSITORIES[kind],'url':'https://github.com/'+REPOSITORIES[kind],'release_url':data['html_url'],'state':'available','assets':[],'update_method':'isolated_hermes_source','notes':data.get('body','')[:16000]}
 if kind not in PACKAGES:raise ValueError('Unknown harness')
 url='https://registry.npmjs.org/'+PACKAGES[kind].replace('/','%2f')+'/latest'
 with urllib.request.urlopen(url,timeout=15) as response:raw=response.read(1024*1024+1)
 if len(raw)>1024*1024:raise ValueError('Package metadata limit')
 data=json.loads(raw);version=data.get('version');repo=data.get('repository',{});repo=repo.get('url','') if isinstance(repo,dict) else repo
 if data.get('name')!=PACKAGES[kind] or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?',version or '') or REPOSITORIES[kind] not in repo:raise ValueError('Official package provenance mismatch')
 return {'id':kind,'version':version,'repository':REPOSITORIES[kind],'url':'https://github.com/'+REPOSITORIES[kind],'release_url':'https://www.npmjs.com/package/'+PACKAGES[kind]+'/v/'+version,'state':'available','assets':[],'update_method':'isolated_npm','notes':'Official npm package. Session homes and project files are preserved.'}
def installed(root,kind):
 if kind=='claude':
  from serve.claude_harness import default_runtime
  return (default_runtime(root) or {}).get('version')
 if kind=='hermes':
  from serve.hermes_integration import installed_version
  return (installed_version() or {}).get('installed_version')
 from serve.agent_harness import _default_binary
 if kind in ('browser','memory'):
  manifest=Path(root)/'output/tools'/('agent-browser' if kind=='browser' else 'agent-memory')/'node_modules'/PACKAGES[kind]/'package.json'
 else:
  binary=_default_binary(kind)
  if not binary:return None
  p=Path(binary);manifest=p.parent.parent/'package.json'
 try:return json.loads(manifest.read_text(encoding='utf-8'))['version']
 except (OSError,ValueError,KeyError):return None
def selected(root,kind,verify=True):
 try:
  row=json.loads((Path(root)/'data/harness-runtime-selection.json').read_text())['active'][kind];p=Path(row['binary']);allowed=(Path(root)/'output/updates/harness-candidates').resolve()
  if not p.resolve().is_relative_to(allowed) or not p.is_file() or verify and hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Candidate integrity mismatch')
  return row
 except (OSError,ValueError,KeyError):return None
class HarnessUpdates:
 def __init__(self,root):
  self.root=Path(root);self.lock=threading.Lock();self.job={'state':'idle'};self.child=None
  self.journal=self.root/'data/harness-update-job.json'
  try:
   stored=json.loads(self.journal.read_text());self.job=stored
   if stored.get('state')=='installing':self.job={**stored,'state':'error','error':'Previous harness update was interrupted; the active runtime was preserved'}
  except (OSError,ValueError):pass
 def persist(self):
  from serve.configuration import atomic_json
  atomic_json(self.journal,{**self.job,'owner_pid':os.getpid()})
 def run_owned(self,command,timeout,check=True,**options):
  from serve.winjob import contain
  from serve.process_lifecycle import stop_owned_tree
  process=subprocess.Popen(command,**options);self.child=process;contain(process)
  try:
   code=process.wait(timeout=timeout)
   if check and code:raise subprocess.CalledProcessError(code,command)
  finally:
   if process.poll() is None:stop_owned_tree(process)
   self.child=None
 def close(self):
  from serve.process_lifecycle import stop_owned_tree
  stop_owned_tree(self.child)

 def status(self):
  if not self.lock.locked():
   try:
    saved=json.loads(self.journal.read_text(encoding='utf-8'))
    if isinstance(saved,dict) and saved.get('state'):self.job=saved
   except (OSError,ValueError):pass
  return dict(self.job)
 def start(self,kind,version):
  if self.status().get('state')=='installing':raise ValueError('Harness update already running')
  if not self.lock.acquire(False):raise ValueError('Harness update already running')
  try:
   release=latest(kind)
   if version!=release['version']:raise ValueError('Check the current official version before updating')
   self.job={'state':'installing','kind':kind,'version':version};self.persist()
   threading.Thread(target=self._install_claude if kind=='claude' else self._install_hermes if kind=='hermes' else self._install,args=(kind,version),daemon=True).start()
  except Exception:self.lock.release();raise
  return self.status()
 def _install(self,kind,version):
  candidate=staging_candidate(self.root,kind,version)
  try:
   manifest=candidate/'VALIDATED.json'
   if manifest.is_file():
    row=json.loads(manifest.read_text());binary=Path(row['binary'])
    if not binary.resolve().is_relative_to(candidate.resolve()) or row.get('version')!=version or hashlib.sha256(binary.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Existing candidate integrity mismatch')
    self.job={'state':'validated','kind':kind,**row,'reused_verified_copy':True};return
   node=shutil.which('node');npm=Path(node).parent/'node_modules/npm/bin/npm-cli.js' if node else None
   if not node or not npm.is_file():raise ValueError('Node/npm runtime not found')
   candidate.mkdir(parents=True,exist_ok=True)
   if shutil.disk_usage(candidate).free<2*1024**3:raise ValueError('Keep 2 GiB free for candidate installation')
   log=candidate/'install.log'
   with log.open('wb') as out:
    self.run_owned([node,str(npm),'install','--prefix',str(candidate),'--registry=https://registry.npmjs.org','--ignore-scripts','--no-audit','--no-fund','--save-exact',PACKAGES[kind]+'@'+version],stdout=out,stderr=subprocess.STDOUT,timeout=240,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    package=candidate/'node_modules'/PACKAGES[kind]
    if kind=='trueforge':self.run_owned([node,str(npm),'rebuild','better-sqlite3','--prefix',str(candidate),'--registry=https://registry.npmjs.org'],stdout=out,stderr=subprocess.STDOUT,timeout=120,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if kind=='opencode':self.run_owned([node,str(package/'postinstall.mjs')],cwd=package,stdout=out,stderr=subprocess.STDOUT,timeout=120,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   binary=package/('bin/opencode.exe' if kind=='opencode' else 'dist/cli.js' if kind=='trueforge' else 'cli.js' if kind=='browser' else 'dist/index.js' if kind=='memory' else 'lib/bin.js')
   if json.loads((package/'package.json').read_text())['version']!=version or not binary.is_file():raise ValueError('Installed package identity mismatch')
   if kind in ('browser','memory'):
    from serve.mcp import StdioTransport
    args=[str(binary)]
    environment={}
    if kind=='browser':
     config=json.loads((self.root/'data/agent-browser/config.json').read_text())
     config['browser']['userDataDir']=str(candidate/'validation-profile');config['outputDir']=str(candidate/'validation-output')
     configuration=candidate/'validation-config.json';configuration.write_text(json.dumps(config));args+=['--config',str(configuration)]
    else:environment={'MEMORY_FILE_PATH':str(candidate/'validation-memory.jsonl')}
    probe=StdioTransport(kind,{'command':node,'args':args,'env':environment,'cwd':str(candidate)})
    try:
     probe.start();probe.request('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'StargateLab update validator','version':'1'}},30);probe.notify('notifications/initialized')
     tools=probe.request('tools/list',{},30)['tools']
     if not tools:raise ValueError('MCP candidate exposes no tools')
     result=probe.request('tools/call',{'name':'browser_navigate' if kind=='browser' else 'read_graph','arguments':{'url':'http://127.0.0.1:8088/health'} if kind=='browser' else {}},30)
     if result.get('isError'):raise ValueError('MCP candidate functional validation failed')
    finally:probe.close()
   else:
    from serve.agent_harness import AgentHarness
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    probe=AgentHarness(candidate/'validation-home',kind=kind,port=port,binary=str(binary),mcp_servers={})
    try:
     probe.start();entry=probe.connect()
     with urllib.request.urlopen(urllib.request.Request(entry['url'],headers={'Accept':'text/html'}),timeout=15) as response:html=response.read(1024*1024)
     if b'<html' not in html.lower():raise ValueError('Official UI startup validation failed')
    finally:probe.stop()
   row={'version':version,'binary':str(binary),'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'ui_verified':True,'validated_at':time.time()}
   from serve.configuration import atomic_json
   atomic_json(candidate/'VALIDATED.json',row);self.job={'state':'validated','kind':kind,**row}
  except Exception as error:self.job={'state':'error','kind':kind,'version':version,'error':str(error)}
  finally:
   try:self.persist()
   finally:self.lock.release()
 def _install_claude(self,kind,version):
  candidate=staging_candidate(self.root,kind,version)
  try:
   if not re.fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('Invalid Claude version')
   base='https://downloads.claude.ai/claude-code-releases/'+version
   with urllib.request.urlopen(base+'/manifest.json',timeout=20) as response:raw=response.read(1024*1024+1)
   if len(raw)>1024*1024:raise ValueError('Manifest limit')
   manifest=json.loads(raw);platform=manifest['platforms']['win32-x64']
   if manifest['version']!=version or platform['binary']!='claude.exe' or not re.fullmatch(r'[a-f0-9]{64}',platform['checksum']):raise ValueError('Official Claude manifest mismatch')
   size=platform['size']
   if type(size) is not int or not 0<size<1024**3:raise ValueError('Claude binary size limit')
   candidate.mkdir(parents=True,exist_ok=True)
   if shutil.disk_usage(candidate).free<size+1024**3:raise ValueError('Insufficient disk space')
   binary=candidate/'claude.exe';temporary=candidate/'claude.download'
   if not binary.is_file() or hashlib.sha256(binary.read_bytes()).hexdigest()!=platform['checksum']:
    digest=hashlib.sha256();total=0
    with urllib.request.urlopen(base+'/win32-x64/claude.exe',timeout=60) as response,temporary.open('wb') as output:
     while True:
      chunk=response.read(1024*1024)
      if not chunk:break
      total+=len(chunk)
      if total>size:raise ValueError('Claude download exceeds manifest size')
      output.write(chunk);digest.update(chunk)
    if total!=size or digest.hexdigest()!=platform['checksum']:raise ValueError('Claude SHA256 mismatch')
    temporary.replace(binary)
   if os.name!='nt':raise ValueError('This native candidate requires Windows')
   signature=candidate/'signature.json'
   # Literal paths are supplied through environment, never interpreted as script.
   env={**os.environ,'STRATA_CLAUDE_CANDIDATE':str(binary),'STRATA_CLAUDE_SIGNATURE':str(signature)}
   self.run_owned(['powershell','-NoProfile','-NonInteractive','-Command',"$s=Get-AuthenticodeSignature -LiteralPath $env:STRATA_CLAUDE_CANDIDATE; @{status=$s.Status.ToString();subject=$s.SignerCertificate.Subject}|ConvertTo-Json|Set-Content -LiteralPath $env:STRATA_CLAUDE_SIGNATURE; if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch '(?:^|,\\s*)O=\"?Anthropic,? PBC\"?(?:,|$)'){exit 1}"],timeout=30,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   validation=candidate/'version.txt'
   with validation.open('wb') as output:self.run_owned([str(binary),'--version'],timeout=30,stdout=output,stderr=subprocess.STDOUT,env={**env,'CLAUDE_CONFIG_DIR':str(candidate/'validation-home'),'DISABLE_AUTOUPDATER':'1','CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1'},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   if validation.read_text().strip()!=version+' (Claude Code)':raise ValueError('CLI version mismatch')
   row={'version':version,'binary':str(binary),'sha256':platform['checksum'],'ui_verified':False,'cli_verified':True,'validated_at':time.time()}
   from serve.configuration import atomic_json
   atomic_json(candidate/'VALIDATED.json',row);self.job={'state':'validated','kind':kind,**row}
  except Exception as error:self.job={'state':'error','kind':kind,'version':version,'error':str(error)}
  finally:
   try:self.persist()
   finally:self.lock.release()

 def _install_hermes(self,kind,version):
  candidate=staging_candidate(self.root,kind,version)
  if (candidate/'VALIDATED.json').exists():
   import uuid
   candidate=candidate.with_name(version+'-'+uuid.uuid4().hex)
  try:
   from serve.hermes_integration import runtime
   found=runtime(self.root);uv=self.root/'.venv/Scripts/uv.exe'
   if not uv.is_file():uv=Path(os.environ.get('LOCALAPPDATA',''))/'hermes/bin/uv.exe'
   if not found or not uv.is_file():raise ValueError('Official Hermes Python/uv runtime unavailable')
   candidate.mkdir(parents=True,exist_ok=True)
   if shutil.disk_usage(candidate).free<2*1024**3:raise ValueError('Keep 2 GiB for an isolated Hermes candidate')
   source=candidate/'source';environment=candidate/'venv';log=candidate/'install.log'
   with log.open('wb') as output:
    if not source.exists():self.run_owned(['git','clone','--depth','1','--branch','v'+version,'https://github.com/NousResearch/hermes-agent.git',str(source)],stdout=output,stderr=subprocess.STDOUT,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    python=environment/'Scripts/python.exe'
    if not python.is_file():self.run_owned([str(uv),'venv',str(environment),'--python',str(found['python'])],stdout=output,stderr=subprocess.STDOUT,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    elif environment.is_symlink() or not (environment/'pyvenv.cfg').is_file():raise ValueError('Existing Hermes candidate environment is invalid')
    self.run_owned([str(uv),'pip','install','--python',str(python),'--index-url','https://pypi.org/simple','-e',str(source)+'[web,mcp]'],stdout=output,stderr=subprocess.STDOUT,timeout=240,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    self.run_owned([str(python),'-c','import mcp.client.streamable_http;import httpx2;import fastapi'],stdout=output,stderr=subprocess.STDOUT,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    node=shutil.which('node');npm=Path(node).parent/'node_modules/npm/bin/npm-cli.js'
    self.run_owned([node,str(npm),'install','--registry=https://registry.npmjs.org','--ignore-scripts','--no-audit','--no-fund'],cwd=source/'web',stdout=output,stderr=subprocess.STDOUT,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    self.run_owned([node,str(npm),'run','build'],cwd=source/'web',stdout=output,stderr=subprocess.STDOUT,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
   from serve.agent_harness import AgentHarness
   probe=AgentHarness(candidate/'validation-home',kind='hermes',port=port,binary=str(python),mcp_servers={})
   code="import sys;sys.path.insert(0,sys.argv[1]);from hermes_cli.web_server import start_server;start_server(host='127.0.0.1',port=int(sys.argv[2]),open_browser=False,isolated=True)"
   probe._command=[str(python),'-X','utf8','-c',code,str(source),str(port)]
   original_environment=probe.environment
   probe.environment=lambda:original_environment(hermes_runtime={'source':source,'venv':environment})
   try:
    probe.start()
    with urllib.request.urlopen(probe.connect()['url'],timeout=15) as response:html=response.read(1024*1024)
    if b'<html' not in html.lower():raise ValueError('Hermes candidate UI did not start')
   finally:probe.stop()
   row={'version':version,'binary':str(python),'sha256':hashlib.sha256(python.read_bytes()).hexdigest(),'source':str(source),'site':str(environment/'Lib/site-packages'),'venv':str(environment),'ui_verified':True,'mcp_http_verified':True,'validated_at':time.time()}
   from serve.configuration import atomic_json
   atomic_json(candidate/'VALIDATED.json',row);self.job={'state':'validated','kind':kind,**row}
  except Exception as error:self.job={'state':'error','kind':kind,'version':version,'error':str(error)}
  finally:
   try:self.persist()
   finally:self.lock.release()

 def backup_home(self,kind):
  if kind in ('browser','memory'):return None
  home=self.root/'data'/f'{kind}-home'
  if not home.exists():return None
  files=[p for p in _native_path(home).rglob('*') if p.is_file() and not p.is_symlink()]
  total=sum(p.stat().st_size for p in files)
  if len(files)>100000 or total>2*1024**3:raise ValueError('Harness archive exceeds automatic backup limit')
  self.root.joinpath('output/updates').mkdir(parents=True,exist_ok=True)
  if shutil.disk_usage(self.root/'output/updates').free<total+1024**3:raise ValueError('Insufficient space for harness session backup')
  import uuid
  destination=self.root/'output/updates/harness-home-backups'/kind/uuid.uuid4().hex
  destination.parent.mkdir(parents=True,exist_ok=True)
  shutil.copytree(_native_path(home),_native_path(destination),symlinks=True)
  return str(destination)

 def activate(self,kind,rollback=False):
  if self.lock.locked():raise ValueError('Wait for validation')
  path=self.root/'data/harness-runtime-selection.json'
  try:data=json.loads(path.read_text())
  except (OSError,ValueError):data={'active':{},'previous':{}}
  if rollback:
   old=data.get('previous',{}).get(kind);current=data['active'].get(kind)
   if old:data['active'][kind]=old
   else:data['active'].pop(kind,None)
   data.setdefault('previous',{})[kind]=current
  else:
   if self.job.get('state')!='validated' or self.job.get('kind')!=kind:raise ValueError('Validate a candidate first')
   row={key:self.job[key] for key in ('version','binary','sha256','ui_verified','validated_at')}
   for key in ('source','site','venv','cli_verified'):
    if key in self.job:row[key]=self.job[key]
   if hashlib.sha256(Path(row['binary']).read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Candidate changed since validation')
   data.setdefault('previous',{})[kind]=data['active'].get(kind);data['active'][kind]=row
  backup=self.backup_home(kind)
  from serve.configuration import atomic_json
  atomic_json(path,data);self.job={'state':'selected','kind':kind,'session_backup':backup};self.persist();return self.status()

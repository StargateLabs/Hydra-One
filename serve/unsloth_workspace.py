"""Own the installed Unsloth web service; retain upstream auth and frame policy."""
import os,socket,subprocess,threading,time,urllib.request
from pathlib import Path
URL='http://127.0.0.1:18888'
class UnslothWorkspace:
 def __init__(self,root,idle):
  self.root=Path(root);self.idle=idle;self.lock=threading.RLock();self.process=None;self.error='';self.lease=None
  self.environment=Path(os.environ.get('USERPROFILE',str(Path.home())))/'.unsloth/studio/unsloth_studio'
  self.python=self.environment/'Scripts/python.exe';self.studio=self.environment/'Lib/site-packages/studio'
 def status(self):
  with self.lock:
   if self.process and self.process.poll() is not None:
    self.error='' if self.process.returncode==0 else 'Unsloth terminato: consulta output/unsloth-original/workspace.log';self.process=None
    if self.lease:self.lease.release();self.lease=None
   ready=False
   if self.process:
    try:
     with urllib.request.urlopen(URL+'/api/health',timeout=1) as response:ready=response.status==200
    except OSError:pass
   return dict(installed=self.python.is_file() and (self.studio/'frontend/dist/index.html').is_file(),status='ready' if ready else 'starting' if self.process else 'idle',busy=self.process is not None,owned=self.process is not None,url=URL if ready else None,error=self.error,embedding='top_level_only',scope='Original Unsloth web interface; original authentication, data, model gates and CSP retained')
 def start(self):
  with self.lock:
   state=self.status()
   if self.process:return state
   if not state['installed']:raise ValueError('Frontend/runtime originale Unsloth non disponibile')
   if not self.idle():raise ValueError('Termina le attività e scarica i modelli prima di aprire Unsloth originale')
   with socket.socket() as probe:
    if probe.connect_ex(('127.0.0.1',18888))==0:raise ValueError('Porta Unsloth occupata da un servizio non posseduto; nessun processo modificato')
   from serve.gpu_lease import GpuLease
   self.lease=GpuLease(self.root,'unsloth-original-workspace').acquire()
   try:
    folder=self.root/'output/unsloth-original';folder.mkdir(parents=True,exist_ok=True)
    command=[str(self.python),'-X','utf8',str(self.studio/'backend/run.py'),'--host','127.0.0.1','--port','18888','--frontend',str(self.studio/'frontend/dist'),'--no-cloudflare','--no-secure','--silent']
    with (folder/'workspace.log').open('ab') as log:self.process=subprocess.Popen(command,cwd=self.studio/'backend',stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    from serve.winjob import contain
    contain(self.process);self.error=''
   except BaseException:
    self.lease.release();self.lease=None;raise
   return self.status()
 def stop(self):
  with self.lock:
   if self.process:raise ValueError('Chiudi Unsloth dal comando Esci originale dopo aver terminato i lavori; Strata non interrompe training o download non ispezionabili')
   return self.status()
 def close(self):
  # A running upstream workspace can contain user work. Never terminate it implicitly.
  return self.status()

"""Own the LocalAI native workspace; never launch detached application UIs."""
import json,os,subprocess,sys,threading,time,uuid
from pathlib import Path
from urllib.parse import urlsplit
from serve.configuration import atomic_json

KINDS=('dashboard','claude','antigravity')

def validated_base_url(value):
    parts=urlsplit(value)
    if parts.scheme!='http' or parts.hostname!='127.0.0.1' or not parts.port or parts.username or parts.password or parts.path or parts.query or parts.fragment:
        raise ValueError('Native workspace requires the original loopback dashboard URL')
    return value.rstrip('/')

def browser_executable():
    paths=sorted((Path(os.environ.get('LOCALAPPDATA',''))/'ms-playwright').glob('chromium-*/chrome-win*/chrome.exe'),reverse=True)
    for base in (os.environ.get('ProgramFiles'),os.environ.get('ProgramFiles(x86)'),os.environ.get('LOCALAPPDATA')):
        if base:
            paths.extend(Path(base)/relative for relative in ('Microsoft/Edge/Application/msedge.exe','Google/Chrome/Application/chrome.exe'))
    return next((path for path in paths if path.is_file()),None)

class NativeWorkspace:
    def __init__(self,root,base_url='http://127.0.0.1:8090'):
        self.root=Path(root).resolve();self.base_url=validated_base_url(base_url)
        self.folder=self.root/'data/native-workspace';self.command_file=self.folder/'command.json'
        self.state_file=self.folder/'state.json';self.process=None;self.lock=threading.RLock()

    def _alive(self,row):
        try:
            import psutil
            process=psutil.Process(row['pid'])
            command=process.cmdline()
            return str(self.root/'tools/native_workspace.py') in command and self.base_url in command and abs(process.create_time()-row['process_created_at'])<1
        except (KeyError,OSError,ValueError,psutil.Error):return False

    def status(self):
        row={}
        try:
            if self.state_file.stat().st_size<65536:row=json.loads(self.state_file.read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
        alive=self._alive(row) if row else False
        return {'available':os.name=='nt' and browser_executable() is not None,'running':alive,'ready':alive and row.get('ready',False),
                'starting':self.process is not None and self.process.poll() is None and not alive,
                'base_url':self.base_url,'windows':row.get('windows',{}) if alive else {},
                'selected':row.get('selected') if alive else None,'error':row.get('error') if alive else None,
                'closing':alive and bool(row.get('closing')),
                'pid':row.get('pid') if alive else None,'container':'LocalAI native workspace','native_ui':True}

    def start(self):
        with self.lock:
            status=self.status();deadline=time.monotonic()+50
            while status.get('running') and status.get('closing'):
                if time.monotonic()>=deadline:raise RuntimeError('Completa il salvataggio richiesto dall’app prima di riaprire LocalAI.')
                time.sleep(.2);status=self.status()
            if self.process is not None and self.process.poll() is None:return self.status()
            if status['running']:return self.status()
            if os.name!='nt' or browser_executable() is None:raise RuntimeError('Native Windows workspace browser unavailable')
            self.folder.mkdir(parents=True,exist_ok=True)
            log=self.root/'output/verification/native-workspace.log';log.parent.mkdir(parents=True,exist_ok=True)
            with log.open('ab') as output:
                self.process=subprocess.Popen([sys.executable,str(self.root/'tools/native_workspace.py'),'--root',str(self.root),'--base-url',self.base_url],cwd=self.root,
                    stdout=output,stderr=output,stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),close_fds=True)
            return self.status()

    def _command(self,kind,action):
        if kind not in KINDS:raise ValueError('Unknown native application')
        self.folder.mkdir(parents=True,exist_ok=True)
        atomic_json(self.command_file,{'id':uuid.uuid4().hex,'kind':kind,'action':action,'created_at':time.time()})

    def open(self,kind):
        if kind not in KINDS:raise ValueError('Unknown native application')
        with self.lock:
            self.start();self._command(kind,'open');status=self.status()
            integrated=bool(status.get('windows',{}).get(kind,{}).get('embedded'))
            return {'ok':True,**status,'integrated':integrated,'starting':not integrated}

    def stop_app(self,kind):
        with self.lock:
            self._command(kind,'close');return {'ok':True,'graceful':True,**self.status()}

    def close(self):
        with self.lock:
            status=self.status()
            if status['running'] or status['starting']:
                self._command('dashboard','close_workspace')
                return {'ok':True,'graceful':True}
            return {'ok':True,'stopped':True}

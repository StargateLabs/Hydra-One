import json,psutil,socket,subprocess,time,urllib.request,sys
from pathlib import Path
root=Path.cwd().resolve();base='http://127.0.0.1:8080';metrics=json.load(urllib.request.urlopen(base+'/metrics'));assert metrics['live']['state'] in ('idle','unloaded'),'Generation active'
config=json.load(urllib.request.urlopen(base+'/config'))['config'];target=(root/config).resolve();assert target.is_relative_to(root) and target.is_file()
listeners=[c for c in psutil.net_connections(kind='tcp') if c.status=='LISTEN' and c.laddr.port==8080];assert len(listeners)==1
owner=psutil.Process(listeners[0].pid);assert Path(owner.cwd()).resolve()==root and 'serve/server.py' in owner.cmdline()
lock=root/'data/.gpu-campaign.lock'
if lock.exists():
 raw=lock.read_bytes();entry=json.loads(raw);assert entry['owner']=='agent-harness' and not psutil.pid_exists(entry['pid']),'Live GPU reservation'
 assert not any(p.info['ppid']==entry['pid'] for p in psutil.process_iter(['ppid']))
 for port in (4096,3080,8091,8092):
  with socket.socket() as sock:sock.settimeout(.2);assert sock.connect_ex(('127.0.0.1',port))!=0,'Existing harness or backend'
 assert lock.read_bytes()==raw;archive=root/'data/stale-reservations';archive.mkdir(exist_ok=True);lock.rename(archive/(entry['token']+'.json'))
children=owner.children(recursive=True)
for child in reversed(children):
 try:child.terminate()
 except psutil.NoSuchProcess:pass
owner.terminate();owner.wait(timeout=10);psutil.wait_procs(children,timeout=5)
log=(root/'output/verification/dashboard-harness-native.log').open('w');errors=(root/'output/verification/dashboard-harness-native-errors.log').open('w')
process=subprocess.Popen([str(root/'.venv/Scripts/python.exe'),'-X','utf8','serve/server.py','--engine','strata','--config',str(target),'--port','8080','--lazy','--api-monitor','--idle-unload','900'],cwd=root,stdout=log,stderr=errors,creationflags=subprocess.CREATE_NO_WINDOW)
for unused in range(40):
 if process.poll() is not None:raise RuntimeError('Dashboard exited; see log')
 try:
  status=json.load(urllib.request.urlopen(base+'/harness/opencode/status',timeout=1));assert status['status']=='idle';print('Dashboard restarted hidden; official harness routes active');break
 except OSError:time.sleep(.25)
else:raise TimeoutError('Dashboard startup')

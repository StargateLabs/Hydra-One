"""Background metadata discovery; no weight reads, downloads or filesystem changes."""
import os,time,json,threading
from pathlib import Path
EXCLUDED={'windows','program files','program files (x86)','$recycle.bin','system volume information','node_modules','.git','venv','.venv','site-packages','temp','tmp','output','graphify-out','__pycache__'}
class LocalModelDiscovery:
 def __init__(self,manager):
  self.manager=manager;self.state={'status':'scanning','found_directories':0,'started_at':time.time(),'inaccessible_directories':0}
  self.scan_lock=threading.Lock();self.worker=None
  self.cache=manager.root/'data/local-model-discovery.json'
  try:
   saved=json.loads(self.cache.read_text(encoding='utf-8'))
   if 0<=time.time()-saved['finished_at']<86400:
    for value in saved['directories']:
     folder=Path(value)
     if folder.is_absolute() and folder.is_dir() and folder not in manager.models_roots:manager.models_roots.append(folder)
    self.state=dict(saved['state'],status='complete',cached=True);return
  except (OSError,ValueError,KeyError,TypeError):pass
  self.rescan()
 def rescan(self):
  with self.scan_lock:
   if self.worker and self.worker.is_alive():return dict(self.state)
   self.state={'status':'scanning','found_directories':0,'started_at':time.time(),'inaccessible_directories':0,'cached':False}
   with self.manager.lock:self.manager.model_cache_at=0
   self.worker=threading.Thread(target=self._scan_worker,daemon=True);self.worker.start()
   return dict(self.state)
 def _scan_worker(self):
  try:self.run()
  except Exception as error:self.state.update(status='error',error=str(error),finished_at=time.time())
 def run(self):
  import psutil
  roots=[Path.home()]+[Path(p.mountpoint) for p in psutil.disk_partitions() if 'removable' not in p.opts and p.fstype]
  directories=set();visited=set()
  self.state['visited_directories']=0
  def denied(error):self.state['inaccessible_directories']+=1
  for root in roots:
   for base,children,files in os.walk(root,onerror=denied,followlinks=False):
    try:resolved=str(Path(base).resolve()).lower()
    except OSError:children[:]=[];self.state['inaccessible_directories']+=1;continue
    if resolved in visited:children[:]=[];continue
    visited.add(resolved);self.state['visited_directories']=len(visited)
    children[:]=[d for d in children if d.lower() not in EXCLUDED and not Path(base,d).is_symlink()]
    if any(name.lower().endswith('.gguf') for name in files) or ('config.json' in files and any(name.endswith('.safetensors') for name in files)):
     folder=Path(base)
     if folder not in directories:
      directories.add(folder)
      with self.manager.lock:
       if folder not in self.manager.models_roots:self.manager.models_roots.append(folder)
       self.manager.model_cache_at=0
      self.state['found_directories']=len(directories)
    time.sleep(.001)
  self.state.update(status='complete',finished_at=time.time(),scope='Accessible local volumes; operating-system, application dependency and temporary directories excluded')

  try:
   from serve.configuration import atomic_json
   self.cache.parent.mkdir(parents=True,exist_ok=True)
   atomic_json(self.cache,dict(finished_at=time.time(),directories=sorted(str(p) for p in directories),state=self.state))
  except OSError as error:self.state['cache_error']=str(error)

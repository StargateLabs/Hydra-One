"""Lightweight release-only checks; no runtime inventory, installation or restart."""
import copy,json,threading,time,urllib.request
from pathlib import Path
from serve.configuration import atomic_json
from serve.update_center import SOURCES
from packaging.version import Version,InvalidVersion
def newer(installed,available):
 if not installed or not available:return False
 old=str(installed).removeprefix('v');new=str(available).removeprefix('v')
 try:return Version(new)>Version(old)
 except InvalidVersion:
  import re
  a=re.fullmatch(r'b(\d+)(?:-mix-(\d+))?',old);b=re.fullmatch(r'b(\d+)(?:-mix-(\d+))?',new)
  return bool(a and b and tuple(int(x or 0) for x in b.groups())>tuple(int(x or 0) for x in a.groups()))
def available_rows(root,components,automatic=False):
 if automatic:return []
 path=Path(root)/'data/component-notifications.json'
 try:preferences=json.loads(path.read_text(encoding='utf-8'))
 except (OSError,ValueError):preferences={}
 # A version this PC already selected must never be announced again.
 from serve.update_restart import applied_versions
 applied=applied_versions(root)
 rows=[]
 for row in components:
  if row.get('automatic_update_supported') is False or row.get('version_comparable') is False or not newer(row.get('installed_version'),row.get('version')):continue
  key=row['id']+'@'+str(row['version']);state=preferences.get(key,{})
  if state.get('dismissed') or state.get('snoozed_until',0)>time.time():continue
  if applied.get(row['id']) and str(applied[row['id']]).lstrip('v')==str(row['version']).lstrip('v'):continue
  rows.append({key:row.get(key) for key in ('id','version','installed_version','release_url','assets','installed_backend')})
 return rows
def preference(root,payload):
 component=payload.get('component');version=payload.get('version');action=payload.get('action')
 if component not in SOURCES or not isinstance(version,str) or not 0<len(version)<100 or action not in ('dismiss','later'):raise ValueError('Invalid notification preference')
 path=Path(root)/'data/component-notifications.json'
 try:data=json.loads(path.read_text(encoding='utf-8'))
 except (OSError,ValueError):data={}
 data[component+'@'+version]={'dismissed':action=='dismiss','snoozed_until':time.time()+86400 if action=='later' else 0};path.parent.mkdir(parents=True,exist_ok=True);atomic_json(path,data);return {'saved':True}
def check_releases(center):
 with center.lock:
  if getattr(center,'notification_check_running',False) or time.time()-getattr(center,'notification_checked_at',0)<3600:return
  center.notification_check_running=True
 def run():
  try:
   for component,repo in SOURCES.items():
    if component=='pytorch':continue
    try:
     if component in ('opencode','dsh','trueforge','browser','memory','hermes','claude'):
      from serve.harness_updates import latest
      release=latest(component)
      with center.lock:
       row=next((row for row in center.result.get('components',[]) if row['id']==component),None)
       if row:row.update(release)
      continue
     if component=='transformers':
      from serve.transformers_compatibility import latest
      release=latest(center.root)
      with center.lock:
       row=next((row for row in center.result.get('components',[]) if row['id']==component),None)
       if row:row.update(release)
      continue
     if component in ('transformers','airllm'):
      req=urllib.request.Request('https://pypi.org/pypi/'+component+'/json',headers={'User-Agent':'Strata-Component-Notifications'})
      with urllib.request.urlopen(req,timeout=8) as response:raw=response.read(2*1024**2+1)
      if len(raw)>2*1024**2:continue
      metadata=json.loads(raw);version=metadata['info']['version']
      with center.lock:
       row=next((row for row in center.result.get('components',[]) if row['id']==component),None)
       if row:row.update(version=version,release_url='https://pypi.org/project/'+component+'/'+version+'/',state='available')
      continue
     req=urllib.request.Request('https://api.github.com/repos/'+repo+'/releases/latest',headers={'Accept':'application/vnd.github+json','User-Agent':'Strata-Component-Notifications'})
     with urllib.request.urlopen(req,timeout=8) as response:raw=response.read(2*1024**2+1)
     if len(raw)>2*1024**2:continue
     release=json.loads(raw)
     with center.lock:
      row=next((row for row in center.result.get('components',[]) if row['id']==component),None)
      if row:row.update(version=release['tag_name'],release_url=release['html_url'],state='available',assets=[{'id':a['id'],'name':a['name'],'bytes':a['size'],'url':a['browser_download_url'],'digest':a.get('digest')} for a in release.get('assets',[])[:100]])
    except (OSError,ValueError,KeyError,TypeError):continue
   with center.lock:center.notification_checked_at=time.time()
  finally:
   with center.lock:center.notification_check_running=False
 threading.Thread(target=run,daemon=True).start()

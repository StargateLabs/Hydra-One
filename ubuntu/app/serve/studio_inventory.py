"""Read-only installed desktop Studio version; separate from Python libraries."""
import os,time
from pathlib import Path
_cache=(0,None)
def installed_studio(force=False):
 global _cache
 if not force and time.monotonic()-_cache[0]<60:return _cache[1]
 found=None
 if os.name=='nt':
  import winreg
  for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
   for base in (r'Software\Microsoft\Windows\CurrentVersion\Uninstall',r'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'):
    try:
     with winreg.OpenKey(hive,base) as parent:
      for index in range(min(winreg.QueryInfoKey(parent)[0],2048)):
       try:
        with winreg.OpenKey(parent,winreg.EnumKey(parent,index)) as key:
         name=winreg.QueryValueEx(key,'DisplayName')[0]
         if not isinstance(name,str) or not name.lower().startswith('unsloth'):continue
         version=winreg.QueryValueEx(key,'DisplayVersion')[0];location=winreg.QueryValueEx(key,'InstallLocation')[0]
         directory=Path(location.strip('"'))
         if isinstance(version,str) and version.strip() and directory.is_dir() and any(directory.glob('*.exe')):
          found={'installed_version':version.strip(),'installed_source':'windows_desktop_inventory','installed_app_path':str(directory),'version_comparable':True}
          break
       except (OSError,ValueError,TypeError):continue
    except OSError:continue
    if found:break
   if found:break
 _cache=(time.monotonic(),found);return found

def launch_studio():
 """Legacy endpoint now returns the integrated workspace, never a desktop process."""
 row=installed_studio()
 return {'opened':False,'integrated':True,'target':'training','version':row.get('installed_version') if row else None,'scope':'Use managed Unsloth inference and training inside StargateLab'}

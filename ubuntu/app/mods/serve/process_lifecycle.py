"""Stop an explicitly owned subprocess and its descendants, never an unrelated PID."""
import subprocess

class RecoveredProcess:
 """Popen-compatible handle recovered only after exact ownership verification."""
 def __init__(self,process):self.process=process;self.pid=process.pid
 def poll(self):
  import psutil
  try:return None if self.process.is_running() and self.process.status()!=psutil.STATUS_ZOMBIE else 0
  except psutil.NoSuchProcess:return 0
 def terminate(self):self.process.terminate()
 def kill(self):self.process.kill()
 def wait(self,timeout=None):
  import psutil
  try:return self.process.wait(timeout)
  except psutil.TimeoutExpired:raise subprocess.TimeoutExpired(str(self.pid),timeout) from None

def recover_owned_process(marker,expected_command):
 import json,psutil
 try:
  row=json.loads(marker.read_text(encoding='utf-8'));process=psutil.Process(row['pid'])
  if abs(process.create_time()-row['created_at'])<1 and str(expected_command) in process.cmdline():return RecoveredProcess(process)
 except (OSError,ValueError,KeyError,TypeError,psutil.Error):pass
 return None

def stop_owned_tree(process,timeout=5):
 if process is None:return
 descendants=[]
 if process.poll() is None:
  import psutil
  try:
   owner=psutil.Process(process.pid);descendants=owner.children(recursive=True)
  except (psutil.NoSuchProcess,psutil.AccessDenied,TypeError,ValueError):pass
  for child in reversed(descendants):
   try:child.terminate()
   except psutil.NoSuchProcess:pass
  if process.poll() is None:process.terminate()
  try:process.wait(timeout=timeout)
  except subprocess.TimeoutExpired:process.kill();process.wait(timeout=timeout)
  if descendants:
   _,alive=psutil.wait_procs(descendants,timeout=timeout)
   for child in alive:
    try:child.kill()
    except psutil.NoSuchProcess:pass
   _,alive=psutil.wait_procs(alive,timeout=timeout)
   if alive:raise RuntimeError('Owned worker did not stop completely')

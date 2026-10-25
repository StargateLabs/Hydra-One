import json,subprocess,sys,tempfile,time,unittest
from pathlib import Path
import psutil
from serve.process_lifecycle import stop_owned_tree,recover_owned_process
class OwnedProcessTests(unittest.TestCase):
 def test_recovery_rejects_other_commands_and_reused_pids(self):
  import os
  with tempfile.TemporaryDirectory() as folder:
   marker=Path(folder)/'owner.json';process=psutil.Process()
   marker.write_text(json.dumps({'pid':os.getpid(),'created_at':process.create_time()}))
   expected=process.cmdline()[0];self.assertIsNotNone(recover_owned_process(marker,expected))
   self.assertIsNone(recover_owned_process(marker,'unrelated-command'))
   marker.write_text(json.dumps({'pid':os.getpid(),'created_at':process.create_time()-100}))
   self.assertIsNone(recover_owned_process(marker,expected))
 def test_descendant_is_stopped_and_unrelated_process_is_preserved(self):
  with tempfile.TemporaryDirectory() as folder:
   target=Path(folder)/'child.json'
   child_code="import os,json,time;from pathlib import Path;Path("+repr(str(target))+").write_text(json.dumps({'pid':os.getpid()}));time.sleep(60)"
   parent_code="import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',"+repr(child_code)+"]);time.sleep(60)"
   owned=subprocess.Popen([sys.executable,'-c',parent_code]);other=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
   try:
    deadline=time.monotonic()+10
    while not target.exists() and time.monotonic()<deadline:time.sleep(.05)
    self.assertTrue(target.exists());pid=json.loads(target.read_text())['pid']
    stop_owned_tree(owned)
    self.assertFalse(psutil.pid_exists(pid));self.assertIsNotNone(owned.poll());self.assertIsNone(other.poll())
   finally:stop_owned_tree(owned);stop_owned_tree(other)

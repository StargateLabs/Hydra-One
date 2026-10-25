"""Serial, harmless v10 interprocess proof. Never imports model code."""
import json, pathlib, subprocess, sys, tempfile, time
from serve.hydra_execution_v10 import Reservation, AdmissionError, guarded_popen

def contender(root):
 try:
  r=Reservation({'run_id':'contender'},root).acquire();r.release(True);return 0
 except AdmissionError as e:print(str(e),flush=True);return 23
if len(sys.argv)>1 and sys.argv[1]=='contender':sys.exit(contender(sys.argv[2]))
if len(sys.argv)>1 and sys.argv[1]=='crash':
 r=Reservation({'run_id':'crashed-owner'},sys.argv[2]).acquire()
 print(json.dumps(r.row['owner']),flush=True)
 __import__('os')._exit(17)
if len(sys.argv)>1 and sys.argv[1]=='endpoint':
 import serve.hydra_execution_v10 as admission
 admission.ROOT=pathlib.Path(sys.argv[2])
 from types import SimpleNamespace
 class Store:
  def put(self,row):self.row=row
 @admission.exclusive_execute
 def endpoint(workspace,body):raise AssertionError('busy endpoint started')
 result=endpoint(SimpleNamespace(store=Store()),{'profile':'dummy-cpu','model_id':'none'})
 print(json.dumps(result),flush=True)
 sys.exit(23 if result['status']=='BLOCKED_BUSY' else 1)


def main():
 results=[]
 with tempfile.TemporaryDirectory(prefix='hydra-v10-cpu-') as tmp:
  root=pathlib.Path(tmp)/'coordinator'
  owner=Reservation({'run_id':'owner','backend':'DUMMY_CPU'},root).acquire()
  command=[sys.executable,'-m','serve.test_hydra_execution_v10','contender',str(root)]
  for name,cwd in [('independent_process',pathlib.Path.cwd()),('different_cwd',pathlib.Path(tmp))]:
   env=__import__('os').environ.copy();env['PYTHONPATH']=str(pathlib.Path(__file__).resolve().parents[1])
   p=subprocess.run(command,cwd=cwd,env=env,capture_output=True,text=True,timeout=5)
   assert p.returncode==23 and 'BLOCKED_BUSY' in p.stdout,(name,p.stdout,p.stderr)
   results.append(dict(scenario=name,status='PASS',exit_code=p.returncode,log=p.stdout.strip()))
  p=subprocess.run([sys.executable,'-m','serve.test_hydra_execution_v10','endpoint',str(root)],capture_output=True,text=True,timeout=5)
  assert p.returncode==23 and 'BLOCKED_BUSY' in p.stdout,(p.stdout,p.stderr)
  results.append(dict(scenario='simulated_endpoint_busy',status='PASS',exit_code=p.returncode))
  try:owner.release(False);raise AssertionError('unpersisted outcome released')
  except AdmissionError:results.append(dict(scenario='cleanup_error_retains_lock',status='PASS'))
  child=guarded_popen([sys.executable,'-c','import time;time.sleep(.5)'])
  try:owner.release(True);raise AssertionError('premature release')
  except AdmissionError:results.append(dict(scenario='live_child_retains_lease',status='PASS',child_pid=child.pid))
  child.wait(timeout=3);owner.release(True)
  p=subprocess.run(command,capture_output=True,text=True,timeout=5);assert p.returncode==0,(p.stdout,p.stderr)
  results.append(dict(scenario='normal_release',status='PASS'))
  try:guarded_popen([sys.executable,'-c','pass']);raise AssertionError('bypass')
  except AdmissionError:results.append(dict(scenario='direct_bypass_denied',status='PASS'))
  crashed=pathlib.Path(tmp)/'crash-recovery'
  p=subprocess.run([sys.executable,'-m','serve.test_hydra_execution_v10','crash',str(crashed)],capture_output=True,text=True,timeout=5)
  assert p.returncode==17,(p.stdout,p.stderr)
  recovery=Reservation({'run_id':'verified-recovery'},crashed).acquire()
  assert list(crashed.glob('recovered-*.json'))
  recovery.release(True);results.append(dict(scenario='crashed_owner_verified_recovery',status='PASS',owner=json.loads(p.stdout)))
  broken=pathlib.Path(tmp)/'uncertain';broken.mkdir();(broken/'lease.json').write_text('{}')
  try:Reservation({},broken).acquire();raise AssertionError('unknown owner accepted')
  except AdmissionError:results.append(dict(scenario='uncertain_owner_closed',status='PASS'))
 print(json.dumps(dict(kind='DUMMY_CPU_INTERPROCESS',results=results),indent=2))
if __name__=='__main__':main()

import unittest
from types import SimpleNamespace
from unittest.mock import patch
import serve.hydra_execution_v10 as module
class PublicationTests(unittest.TestCase):
 def test_metadata_update_cannot_borrow_another_runs_reservation(self):
  lease=SimpleNamespace(row={'run_id':'metadata','owner':{},'state':'RUNNING','children':[]},transition=lambda _:None)
  row={'run_id':'already-finished','status':'PASS','execution_admission':{'run_id':'already-finished','state':'VERIFIED_TERMINAL'}}
  with patch.object(module._local,'reservation',lease,create=True):
   self.assertEqual(module.publication_row(row),row)
   self.assertNotIn('attested_request',lease.row)
 def test_mutex_acl_canonical_auto_inherited_flag(self):
  self.assertTrue(module.valid_mutex_acl('D:P(A;;GA;;;SY)(A;;GA;;;OW)'))
  self.assertTrue(module.valid_mutex_acl('D:PAI(A;;0x1f0001;;;SY)(A;;0x1f0001;;;OW)'))
  for value in ('D:AI(A;;GA;;;SY)(A;;GA;;;OW)', 'D:PAI(A;;GA;;;WD)(A;;GA;;;OW)', 'D:PAI(A;ID;GA;;;SY)(A;;GA;;;OW)', 'D:PAI(A;;GA;;;SY)(A;;GA;;;OW)(A;;GA;;;WD)'):
   self.assertFalse(module.valid_mutex_acl(value),value)
 def test_pass_waits_for_cleanup(self):
  lease=SimpleNamespace(row={'run_id':'x','owner':{},'state':'RUNNING','children':[]},transition=lambda _:None)
  with patch.object(module._local,'reservation',lease,create=True):
   original={'status':'PASS','events':[]};actual=module.publication_row(original)
   self.assertEqual(actual['status'],'RUNNING');self.assertEqual(original['status'],'PASS')
 def test_verified_terminal_allows_publication(self):
  lease=SimpleNamespace(row={'run_id':'x','owner':{},'state':'VERIFIED_TERMINAL','children':[]},transition=lambda _:None)
  with patch.object(module._local,'reservation',lease,create=True):self.assertEqual(module.publication_row({'status':'PASS'})['status'],'PASS')
 def test_no_reservation_blocks_direct_launcher(self):
  with patch.object(module._local,'reservation',None,create=True),patch.object(module.subprocess,'Popen') as popen:
   with self.assertRaises(module.AdmissionError):module.guarded_popen(['forbidden-model'])
   popen.assert_not_called()
 def test_nested_runner_is_denied(self):
  @module.exclusive_execute
  def nested(*args,**kwargs):raise AssertionError('must not enter')
  with patch.object(module._local,'reservation',object(),create=True):
   with self.assertRaises(module.AdmissionError):nested(None,{})
 def test_old_unknown_lease_is_not_a_dead_owner(self):
  with self.assertRaises(module.AdmissionError):module.alive({})

 def test_dense_worker_entrypoint_rejects_unregistered_process(self):
  script=pathlib.Path(__file__).resolve().parents[1]/'hydra-engine/hydra_lab/graph_hybrid.py'
  result=subprocess.run([sys.executable,str(script),'--dense-worker','NOT_A_MODEL'],capture_output=True,text=True,timeout=5)
  self.assertNotEqual(result.returncode,0)
  self.assertIn('NO_VALID_CHILD_RESERVATION',result.stderr)

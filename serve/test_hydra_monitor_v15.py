import copy,json,pathlib,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from serve.hydra_lab_live import LiveMonitor
class MonitorSnapshotTests(unittest.TestCase):
 def test_off_reads_no_history_and_writes_no_snapshot(self):
  features=SimpleNamespace(setting=Mock(return_value={'desired':False}));store=SimpleNamespace(list=Mock())
  workspace=SimpleNamespace(store=store,lab=SimpleNamespace(features=features,profile={'port':8091}))
  with patch('serve.hydra_lab_live.os.replace') as replace:
   monitor=LiveMonitor(workspace,{'run_id':'off'});monitor.close();store.list.assert_not_called();replace.assert_not_called()
 def test_history_read_once_current_samples_and_terminal_state_stay_fresh(self):
  row={'run_id':'current','model':'fixture','origin':'BENCHMARK','profile':'cpu','real_execution_kind':'CPU fixture','status':'RUNNING','timestamp':'2026-10-19T12:00:00+00:00','samples':[]}
  past=dict(row,run_id='past',status='PASS',samples=[{'tokens':3,'e2e_ms':100}])
  store=SimpleNamespace(list=Mock(side_effect=lambda:copy.deepcopy([row,past])))
  workspace=SimpleNamespace(store=store,lab=SimpleNamespace(profile={'port':8091},features=None))
  with tempfile.TemporaryDirectory() as temp,patch('serve.hydra_lab_live.threading.Thread'):
   # Keep the fixture away from the real app's shared Monitor file.
   with patch('serve.hydra_lab_live.Path') as paths:
    paths.return_value.resolve.return_value.parents={1:pathlib.Path(temp)}
    monitor=LiveMonitor(workspace,row)
   row['samples']=[{'tokens':16,'e2e_ms':400}];monitor.write(True)
   row['status']='PASS';monitor.close()
   result=json.loads(monitor.path.read_text())
   self.assertEqual(result['metrics']['totals']['output_tokens'],19)
   self.assertEqual(result['metrics']['live']['completed_samples'],1)
   self.assertEqual(result['metrics']['live']['state'],'idle')
   self.assertFalse(result['active'])
   self.assertEqual(store.list.call_count,1,'unchanged historical rows must not be decoded again on each tick')
if __name__=='__main__':unittest.main()

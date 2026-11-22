import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from serve.local_training import LocalTraining
class TrainingManagerTests(unittest.TestCase):
 def test_inference_loader_changes_do_not_change_training_base(self):
  manager=SimpleNamespace(root=Path.cwd(),python_runtime=Path('inference-candidate'),training_python_runtime=Path('original-training-runtime'))
  training=LocalTraining(manager)
  manager.python_runtime=Path('airllm-cpu-runtime')
  self.assertEqual(training.training_python,Path('original-training-runtime'))
 def test_registered_history_restores_configuration_and_rejects_unknown_path(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);folder=root/'output/training/session';folder.mkdir(parents=True)
   entry={'output':str(folder),'model':'base','runner':'unsloth_qlora','steps':2}
   (folder/'workflow.json').write_text(json.dumps({'base':'base','train_path':'train.jsonl','validation_path':'valid.jsonl','options':{'device':'cuda','steps':2}}),encoding='utf-8')
   training=LocalTraining(SimpleNamespace(root=root));training.status=Mock(return_value={'history':[entry]})
   restored=training.session({'output':str(folder)})
   self.assertEqual(restored['device'],'cuda');self.assertEqual(restored['train_path'],'train.jsonl')
   with self.assertRaisesRegex(ValueError,'not registered'):training.session({'output':str(root)})
 def test_missing_runtime_and_busy_inference_are_rejected(self):
  manager=SimpleNamespace(root=Path.cwd(),python_runtime=Path('missing-python'),status=lambda:{'status':'idle'})
  training=LocalTraining(manager)
  with self.assertRaisesRegex(ValueError,'Unload'):training.start({},False)
  with self.assertRaisesRegex(ValueError,'unavailable'):training.start({},True)
 def test_failed_export_is_not_complete_and_lease_released(self):
  with tempfile.TemporaryDirectory() as directory:
   manager=SimpleNamespace(root=Path(directory));training=LocalTraining(manager)
   training.state={'status':'running','output':directory};training.process=Mock();training.process.poll.return_value=0;training.process.returncode=0;training.lease=Mock();lease=training.lease
   Path(directory,'workflow.json').write_text(json.dumps({'status':'complete','export_logits_verified':False}))
   self.assertEqual(training.status()['status'],'failed');lease.release.assert_called_once()
 def test_completed_result_survives_manager_restart(self):
  with tempfile.TemporaryDirectory() as directory:
   manager=SimpleNamespace(root=Path(directory));training=LocalTraining(manager)
   training.state={'status':'running','output':directory};training.process=Mock();training.process.poll.return_value=0;training.process.returncode=0
   Path(directory,'workflow.json').write_text(json.dumps({'status':'complete','export_logits_verified':True}))
   training.status()
   self.assertEqual(LocalTraining(manager).status()['status'],'complete')
 def test_running_progress_is_read_without_promoting_result(self):
  with tempfile.TemporaryDirectory() as directory:
   training=LocalTraining(SimpleNamespace(root=Path(directory)));training.state={'status':'running','output':directory};training.process=Mock();training.process.poll.return_value=None
   Path(directory,'workflow.json').write_text(json.dumps({'status':'running','completed_steps':3,'total_steps':20}))
   state=training.status();self.assertEqual(state['status'],'running');self.assertEqual(state['workflow']['completed_steps'],3)
 def test_stop_terminates_owned_process_and_marks_cancelled(self):
  with tempfile.TemporaryDirectory() as directory:
   training=LocalTraining(SimpleNamespace(root=Path(directory)));training.state={'status':'running','output':directory}
   process=Mock();process.returncode=None;process.poll.side_effect=lambda:process.returncode;process.terminate.side_effect=lambda:setattr(process,'returncode',-15);training.process=process;training.lease=Mock();lease=training.lease
   self.assertEqual(training.stop()['status'],'cancelled');process.terminate.assert_called_once();lease.release.assert_called_once()
 def test_close_waits_for_owned_child_and_releases_reservation(self):
  with tempfile.TemporaryDirectory() as directory:
   training=LocalTraining(SimpleNamespace(root=Path(directory)));training.state={'status':'running','output':directory}
   process=Mock();process.returncode=None;process.poll.side_effect=lambda:process.returncode;process.terminate.side_effect=lambda:setattr(process,'returncode',-15);training.process=process;training.lease=Mock();lease=training.lease
   training.close();process.terminate.assert_called_once();process.wait.assert_called_once_with(timeout=10);lease.release.assert_called_once();self.assertEqual(training.state['status'],'cancelled')
 def test_verified_export_is_complete(self):
  with tempfile.TemporaryDirectory() as directory:
   training=LocalTraining(SimpleNamespace(root=Path(directory)));training.state={'status':'running','output':directory};training.process=Mock();training.process.poll.return_value=0;training.process.returncode=0
   Path(directory,'workflow.json').write_text(json.dumps({'status':'complete','export_logits_verified':True}))
   self.assertEqual(training.status()['status'],'complete')

 def test_greedy_reload_completes_only_native_qlora(self):
  for runner,expected in [('unsloth_qlora','complete'),('trl_cpu','failed')]:
   with tempfile.TemporaryDirectory() as directory:
    training=LocalTraining(SimpleNamespace(root=Path(directory)))
    training.state={'status':'running','runner':runner,'output':directory};training.process=Mock();training.process.poll.return_value=0;training.process.returncode=0
    Path(directory,'workflow.json').write_text(json.dumps({'status':'complete','export_greedy_tokens_equal':True}),encoding='utf-8')
    self.assertEqual(training.status()['status'],expected)

 def test_dataset_upload_validates_content_and_cleans_invalid_file(self):
  with tempfile.TemporaryDirectory() as directory:
   training=LocalTraining(SimpleNamespace(root=Path(directory)))
   result=training.upload_dataset({'kind':'train','content':'{"text":"A training example"}\n'})
   self.assertEqual(result['rows'],1);self.assertTrue(Path(result['path']).is_file())
   with self.assertRaises(ValueError):training.upload_dataset({'kind':'validation','content':'{"bad":true}'})
   self.assertEqual(len(list((Path(directory)/'output/training-datasets').glob('*.jsonl'))),1)

 def test_dataset_upload_normalizes_supported_formats(self):
  with tempfile.TemporaryDirectory() as directory:
   training=LocalTraining(SimpleNamespace(root=Path(directory)))
   for name,content,count in [('data.json','[{"text":"first"},{"text":"second"}]',2),('data.csv','text,tag\nfirst,x\nsecond,y\n',2),('data.txt','A plain text example',1)]:
    result=training.upload_dataset({'kind':'train','name':name,'content':content})
    self.assertEqual(result['rows'],count)
   with self.assertRaisesRegex(ValueError,'text column'):
    training.upload_dataset({'kind':'train','name':'bad.csv','content':'other\nvalue'})

 def test_split_is_repeatable_and_duplicate_groups_do_not_leak(self):
  with tempfile.TemporaryDirectory() as directory:
   training=LocalTraining(SimpleNamespace(root=Path(directory)))
   source=training.upload_dataset({'kind':'train','content':'\n'.join(json.dumps({'text':text}) for text in ['one','two','three','four','one'])})
   first=training.split_dataset({'path':source['path'],'seed':9});second=training.split_dataset({'path':source['path'],'seed':9})
   self.assertEqual(first['datasets']['train']['sha256'],second['datasets']['train']['sha256'])
   datasets={kind:[json.loads(line)['text'] for line in Path(row['path']).read_text().splitlines()] for kind,row in first['datasets'].items()}
   self.assertFalse(set(datasets['train'])&set(datasets['validation']))
   self.assertEqual(len(datasets['train'])+len(datasets['validation']),5)

 def test_split_rejects_external_single_example_and_bad_parameters(self):
  with tempfile.TemporaryDirectory() as directory:
   training=LocalTraining(SimpleNamespace(root=Path(directory)))
   source=training.upload_dataset({'kind':'train','content':'{"text":"one"}'})
   for value in ({'path':source['path']},{'path':source['path'],'seed':True},{'path':source['path'],'validation_percent':50}):
    with self.assertRaises(ValueError):training.split_dataset(value)
   external=Path(directory)/'external.jsonl';external.write_text('{"text":"other"}')
   with self.assertRaisesRegex(ValueError,'uploaded'):training.split_dataset({'path':str(external)})

if __name__=='__main__':unittest.main()

class SoupMetadataTests(unittest.TestCase):
 def test_selected_version_and_gpu_proof_are_not_planner_version(self):
  with tempfile.TemporaryDirectory() as folder:
   training=LocalTraining(SimpleNamespace(root=Path(folder)))
   training.native_soup=Mock(return_value={'version':'0.75.2','validation':{'gpu_verified':True}})
   training.soup_available=Mock(return_value=False)
   info=training.soup_metadata()
   self.assertEqual(info['version'],'0.75.2');self.assertEqual(info['planner_version'],'0.75.0')
   self.assertTrue(info['cpu_training_enabled']);self.assertTrue(info['gpu_training_enabled'])
   self.assertFalse(info['layer_streaming_enabled'])

class StreamingProofTests(unittest.TestCase):
 def test_streaming_proof_is_bound_to_bridge_and_selected_package(self):
  import hashlib
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'tools').mkdir();bridge=root/'tools/train_soup_streaming_candidate.py';bridge.write_text('fixture')
   proof_folder=root/'output/verification';proof_folder.mkdir(parents=True)
   training=LocalTraining(SimpleNamespace(root=root));training.native_soup=Mock(return_value={'version':'0.75.2'})
   self.assertFalse(training.native_streaming_available())
   proof={'passed':True,'exit_code':0,'workflow':{'status':'complete','streaming_active':True,'device':'cuda','updated_adapter_tensors':1,'export_greedy_tokens_equal':True,'export_logits_verified':True,'bridge_sha256':hashlib.sha256(bridge.read_bytes()).hexdigest(),'soup_version':'0.75.2'}}
   (proof_folder/'soup-streaming-candidate-real.json').write_text(json.dumps(proof))
   self.assertTrue(training.native_streaming_available())
   bridge.write_text('changed');self.assertFalse(training.native_streaming_available())

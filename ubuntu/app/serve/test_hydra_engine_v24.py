import hashlib,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch

class V24(unittest.TestCase):
 def test_invalid_native_token_ids_cannot_be_counted_as_success(self):
  from serve.hydra_native_text_server import compile_native_context
  for bad in ([True],[-1],'tokens'):
   with patch('serve.hydra_native_text_server.native_json',side_effect=[{'prompt':'fixture'},{'tokens':bad}]):
    with self.assertRaisesRegex(ValueError,'TOKENIZER_IDS'):compile_native_context(1234,'key',[],{'thinking':'off','max_tokens':1},128)
 def test_idle_transport_expires_without_reconnect(self):
  from serve.hydra_http_pool import SerialConnectionPool
  from types import SimpleNamespace
  first=Mock();second=Mock();first.getresponse.return_value=SimpleNamespace(length=0,isclosed=lambda:True,will_close=False)
  pool=SerialConnectionPool(Mock(side_effect=[first,second]))
  with patch('serve.hydra_http_pool.time.monotonic',return_value=1):
   lease=pool.connection('localhost',1234,1);lease.getresponse();lease.close()
  with patch('serve.hydra_http_pool.time.monotonic',return_value=32):other=pool.connection('127.0.0.1',1234,1)
  first.close.assert_called_once();self.assertIs(other.raw,second);self.assertEqual(pool.stats['reused'],0);pool.close()
 def test_context_compiler_forwards_pool_and_cancel(self):
  from serve.hydra_native_text_server import compile_native_context
  pool=Mock();cancel=threading.Event()
  with patch('serve.hydra_native_text_server.native_json',side_effect=[{'prompt':'fixture'},{'tokens':[1,2]}]) as api:
   self.assertEqual(compile_native_context(1234,'key',[],{'thinking':'off','max_tokens':1},128,pool=pool,cancel=cancel)['compiled_prompt_tokens'],2)
   for call in api.call_args_list:self.assertIs(call.kwargs['pool'],pool);self.assertIs(call.kwargs['cancel'],cancel)
 def test_off_refused_before_reservation(self):
  from serve.hydra_execution_v10 import exclusive_execute
  workspace=Mock();workspace.lab.features.resolve.side_effect=ValueError('FEATURE_OFF')
  with patch('serve.hydra_execution_v10.Reservation') as reservation:
   with self.assertRaisesRegex(ValueError,'FEATURE_OFF'):exclusive_execute(Mock())(workspace,{'model_id':'local/Qwen3-0.6B-Q8_0'})
   reservation.assert_not_called()
 def test_cleanup_failure_still_terminates_owned_child(self):
  from serve.hydra_lab_app import Lab
  lab=Lab.__new__(Lab);lab.client=Mock();lab.client.close.side_effect=OSError('fixture');lab.http_pool=Mock();lab.http_pool.stats={};lab.child=Mock();child=lab.child;lab.log=Mock();lab.calls=[]
  child.poll.return_value=None
  with self.assertRaisesRegex(RuntimeError,'CLEANUP_UNVERIFIED'):lab.stop_backend()
  child.terminate.assert_called_once();child.wait.assert_called_once();self.assertIsNone(lab.child);self.assertIsNone(lab.http_pool)
 def test_pool_rejects_nonlocal_and_nonfinite_before_factory(self):
  from serve.hydra_http_pool import SerialConnectionPool
  factory=Mock();pool=SerialConnectionPool(factory)
  for host,timeout in [('example.invalid',1),('127.0.0.1',None),('127.0.0.1',float('nan')),('127.0.0.1',0)]:
   with self.assertRaises(ValueError):pool.connection(host,1234,timeout)
  factory.assert_not_called();pool.close()
 def test_local_backend_preserves_finite_header_timeout(self):
  from serve.optional_inference import LocalOpenAIBackend
  raw=Mock();raw.getresponse.return_value.status=200
  backend=LocalOpenAIBackend('http://127.0.0.1:1234/v1',timeout=8);backend.connection_factory=Mock(return_value=raw)
  connection,response=backend._request('POST','/chat/completions',{})
  raw.sock.settimeout.assert_called_with(8);connection.close()
 def test_graph_ingest_uses_selected_digest(self):
  from serve.hydra_graph_memory import GraphMemory
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source=root/'source.md';source.write_bytes(b'# Selected\n\noriginal')
   graph=GraphMemory.create(root/'index.sqlite',roots=[root])
   digest=hashlib.sha256(source.read_bytes()).hexdigest()
   with patch.object(graph,'_read_source',return_value=b'# Other\n\nchanged'):
    with self.assertRaisesRegex(ValueError,'SELECTED_SOURCE'):graph.ingest_sections('lab',source,expected_sha256=digest)
   self.assertTrue(graph.ingest_sections('lab',source,expected_sha256=digest))
 def test_native_metadata_requests_use_owned_pool(self):
  from serve.hydra_native_text_server import native_json
  raw=Mock();raw.getresponse.return_value.status=200;raw.getresponse.return_value.read.return_value=b'{"tokens":[1]}'
  pool=Mock();pool.connection.return_value=raw
  self.assertEqual(native_json(1234,'fixture','/tokenize',{},pool=pool)['tokens'],[1])
  pool.connection.assert_called_once_with('127.0.0.1',1234,10);raw.close.assert_called_once()
  cancel=threading.Event();cancel.set()
  with self.assertRaisesRegex(ValueError,'CANCELLED'):native_json(1234,'fixture','/tokenize',{},pool=pool,cancel=cancel)
  pool.connection.assert_called_once()

if __name__=='__main__':unittest.main(failfast=True)

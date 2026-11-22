import json,tempfile,unittest
from pathlib import Path
from serve import hydra_acceptance_v18 as C

class CampaignTests(unittest.TestCase):
 def test_http_forward_requires_one_already_counted_permit(self):
  calls=[]
  with __import__('unittest.mock',fromlist=['patch']).patch.object(C,'before_request',side_effect=lambda *args:calls.append(('count',args[2]))):
   gate=C.RequestGate(dict(samples=1),'run',dict(warmup=False),lambda payload:calls.append(('native',payload)))
   with self.assertRaisesRegex(ValueError,'PERMIT'):gate({'prompt':'same'})
   gate.authorize(1);gate({'prompt':'same'})
   with self.assertRaisesRegex(ValueError,'PERMIT'):gate({'prompt':'same'})
   with self.assertRaisesRegex(ValueError,'ORDER'):gate.authorize(1)
  self.assertEqual(calls,[('count',1),('native',{'prompt':'same'})])
 def test_comparison_uses_effective_sampler_and_rejects_unknown_alias(self):
  row=dict(model_hash='model',runtime_hash='runtime',prompt_hash='prompt',quantization='Q8_0',template_hash='template',parameters=dict(samplers=['greedy']),measurement_scope='app HTTP')
  C.bind_comparison(row);self.assertTrue(row['comparison_key'].startswith('INCOMPLETE:'))
  bad=row['comparison_key'];row['parameters']['samplers']=['temperature'];C.bind_comparison(row)
  self.assertFalse(row['comparison_key'].startswith('INCOMPLETE:'));self.assertNotEqual(row['comparison_key'],bad)
 def test_actual_prism_sampler_is_temperature_not_unknown_greedy(self):
  self.assertEqual(C.sampling_payload(),dict(samplers=['temperature'],temperature=0,return_tokens=True))
 def test_native_limit_is_not_a_completed_quality_answer(self):
  self.assertTrue(C.is_truncated(dict(stop_type='limit',truncated=False)))
  self.assertFalse(C.is_truncated(dict(stop_type='eos',truncated=False)))
 def test_quality_template_preserves_exact_user_prompt(self):
  self.assertEqual(C.template_request('Quanto fa 3 + 5?')['messages'],[dict(role='user',content='Quanto fa 3 + 5?')])
  self.assertFalse(C.template_request('x')['chat_template_kwargs']['enable_thinking'])
 def test_native_admission_uses_coordinator_compact_identity(self):
  plan=dict(runs={'known':dict(profile='v8-v18-cpu-qwen',model_id=C.MODEL)})
  self.assertEqual(C.launch_item(dict(workload='known',profile='v8-v18-cpu-qwen',model=C.MODEL),plan),plan['runs']['known'])
  with self.assertRaisesRegex(ValueError,'IDENTITY'):C.launch_item(dict(workload='known',profile='v8-v18-gpu-qwen',model=C.MODEL),plan)
 def test_quality_keeps_extra_content_and_length_failure(self):
  self.assertTrue(C.quality('Q1',' 8\n',False)['pass'])
  self.assertFalse(C.quality('Q1','8. oppure 9',False)['pass'])
  self.assertFalse(C.quality('Q2','4, 5, 6',False)['pass'])
  self.assertFalse(C.quality('Q1','8',True)['pass'])
  self.assertTrue(C.quality('Q3','sferica',False)['pass'])
 def test_budget_consumes_before_request_even_when_failed(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'ticket.json';p.write_text(json.dumps(dict(state='ARMED',measured_used=79,warmup_used=0,max_measured=80)))
   C.consume(p,'run1',1,False)
   self.assertEqual(json.loads(p.read_text())['measured_used'],80)
   with self.assertRaisesRegex(ValueError,'BUDGET'):C.consume(p,'run2',1,False)
   with self.assertRaises(FileExistsError):C.consume(p,'run1',1,False)
 def test_halted_campaign_cannot_consume_warmup(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'ticket.json';p.write_text(json.dumps(dict(state='HALTED',measured_used=0,warmup_used=0,max_measured=80)))
   with self.assertRaisesRegex(ValueError,'HALTED'):C.consume(p,'run1',0,True)
 def test_unsupported_workload_cannot_change_prompt(self):
  plan=dict(runs={'known':dict(profile='v8-v18-gpu-qwen',model_id=C.MODEL,prompt='frozen',samples=1,max_tokens=16)})
  with self.assertRaisesRegex(ValueError,'FROZEN'):C.validate(dict(prompt_id='known',profile='v8-v18-gpu-qwen',model_id=C.MODEL,prompt='altered',samples=1,max_tokens=16),plan)

class HybridContextTests(unittest.TestCase):
 def test_ranked_ids_keep_provider_order_and_revalidate_sources(self):
  from serve.hydra_graph_memory import GraphMemory
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);graph=GraphMemory.create(root/'graph.sqlite',roots=[root]);a=root/'a.txt';b=root/'b.txt'
   a.write_text('Alpha source');b.write_text('Beta source')
   aid=graph.ingest('lab',a);bid=graph.ingest('lab',b)
   rows=graph.retrieve('lab','question without lexical match',allowed_sources=[str(a),str(b)],ranked_node_ids=[bid,aid],max_nodes=2,depth=0)
   self.assertEqual([r['id'] for r in rows],[bid,aid])
   self.assertEqual(graph.retrieve('other','question',allowed_sources=[str(a),str(b)],ranked_node_ids=[bid],depth=0),[])
   self.assertEqual(graph.retrieve('lab','question',allowed_sources=[str(a)],ranked_node_ids=[bid],depth=0),[])
   b.write_text('Changed source')
   self.assertEqual(graph.retrieve('lab','question',allowed_sources=[str(b)],ranked_node_ids=[bid],depth=0),[])
 def test_hybrid_chat_requires_graph_and_explicit_variant(self):
  from serve.hydra_lab_app import validate_chat,LabError
  body=dict(messages=[dict(role='user',content='question')],max_tokens=16,graph=True,variant='H1v2')
  self.assertEqual(validate_chat(body),16)
  with self.assertRaises(LabError):validate_chat(dict(body,graph=False))

if __name__=='__main__':unittest.main()

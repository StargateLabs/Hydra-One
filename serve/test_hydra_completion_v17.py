import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from serve.hydra_gpu_recovery_v16 import persist_module_evidence,validate_body,PROMPT,PROFILE,MODEL

class V17RecoveryTests(unittest.TestCase):
 def test_module_map_is_separate_event(self):
  with tempfile.TemporaryDirectory() as tmp:
   identity={'pid':12,'loaded_DLL_map':'NOT_AVAILABLE'}
   row={'process_identity':identity,'events':[{'kind':'identity','detail':identity}]}
   persist_module_evidence(row,[],Path(tmp))
   self.assertEqual(row['events'][0]['detail']['loaded_DLL_map'],'NOT_AVAILABLE')
   self.assertEqual(row['events'][1]['kind'],'native_module_map')
   self.assertEqual(json.loads((Path(tmp)/'loaded-modules.json').read_text())['loaded_DLL_map'],[])
 def test_persistence_failure_is_explicit(self):
  with patch.object(Path,'write_text',side_effect=OSError('disk unavailable')):
   with self.assertRaisesRegex(RuntimeError,'DIAGNOSTIC_PERSISTENCE_FAILED'):
    persist_module_evidence({'process_identity':{},'events':[]},[],Path('fixture'))
 def test_new_explicit_reasoned_v17_execution(self):
  body=dict(profile=PROFILE,model_id=MODEL,prompt=PROMPT,prompt_id='v17-gpu-first',samples=1,max_tokens=8)
  validate_body(body,dict(samples=1,prompt_prefix='v17-'))
  with self.assertRaises(ValueError):validate_body(dict(body,prompt_id='v16-previous'),dict(samples=1,prompt_prefix='v17-'))
 def test_prompt_id_alias_cannot_add_extra_recovery_generations(self):
  from serve import hydra_fastpath
  body=dict(profile=PROFILE,model_id=MODEL,prompt=PROMPT,prompt_id='v17-alias-paths',samples=1,max_tokens=8)
  chosen=dict(recovery=True,expected_model=MODEL,app_paths=False)
  with patch.object(hydra_fastpath,'resolve_profile',return_value=chosen),patch('serve.hydra_v7_experiments.execute',return_value={}) as native:
   hydra_fastpath.execute(object(),body)
   self.assertFalse(native.call_args.kwargs['_experiment']['app_paths'])

class RepositoryContextTests(unittest.TestCase):
 def test_exact_symbol_and_filename_beat_generic_words(self):
  from serve.hydra_graphify_runtime import select_sources
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'serve').mkdir()
   (root/'serve/target.py').write_text('def persist_module_evidence(): pass')
   (root/'serve/generic.py').write_text('def JSON(): pass')
   graph=root/'graph.json';graph.write_text(json.dumps(dict(nodes=[dict(id='a',label='JSON()',source_file='serve/generic.py'),dict(id='b',label='persist_module_evidence()',source_file='serve/target.py')])))
   rows,_=select_sources(root,graph,'In target.py which JSON file does persist_module_evidence use?',limit=1)
   self.assertEqual(rows[0]['node_id'],'b')
 def test_repository_files_feed_bounded_exact_source_sections(self):
  from types import SimpleNamespace
  from serve.hydra_graph_memory import GraphMemory
  from serve.hydra_graphify_runtime import repository_context
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'module.py'
   text='\n\n'.join('def other_%d():\n    return %r'%(i,'x'*400) for i in range(35))+'\n\ndef target_fn():\n    return "loaded-modules.json"\n'
   source.write_text(text,encoding='utf8')
   graph=GraphMemory.create(root/'graph.sqlite',roots=[root])
   features=SimpleNamespace(setting=lambda n:dict(desired=n==26,parameters={}))
   lab=SimpleNamespace(g=graph,sources=[],features=features,graph_options={},configure_graph=lambda:None)
   selected=[dict(path=str(source),node_id='target',label='target_fn',bytes=len(source.read_bytes()),source_sha256=__import__('hashlib').sha256(source.read_bytes()).hexdigest())]
   with patch('serve.hydra_graphify_runtime.select_sources',return_value=(selected,dict(graph_sha256='fixture'))):
    with repository_context(lab,dict(path='/lab/retrieve',request=dict(query='target_fn'))):
     rows=graph.retrieve('lab','target_fn',allowed_sources=lab.sources,max_nodes=1,depth=0)
     self.assertEqual(len(rows),1)
     self.assertLess(len(rows[0]['content']),2000)
     self.assertIn('loaded-modules.json',rows[0]['content'])
     span=rows[0]['source_span'];actual=source.read_bytes().decode('utf-8-sig')
     self.assertEqual(rows[0]['content'],actual[span['start_char']:span['end_char']])
     source.write_text(text+'# changed\n',encoding='utf8')
     self.assertEqual(graph.retrieve('lab','target_fn',allowed_sources=lab.sources,max_nodes=1,depth=0),[])

if __name__=='__main__':unittest.main()

import json,tempfile,unittest
from pathlib import Path
from serve.hydra_graphify_runtime import select_sources
from serve import hydra_graphify_runtime as runtime
class GraphifyRuntimeTests(unittest.TestCase):
 def test_actual_index_residency_and_invalidation(self):
  tiers=runtime.GraphIndexTiers();raw=b'{"nodes":[{"id":"one"}],"links":[]}'
  self.assertEqual(tiers.resolve(raw,2)[0]['id'],'one')
  tiers.resolve(raw,2);self.assertEqual(tiers.stats['hot_hits'],1)
  tiers.resolve(raw,1);self.assertIsNone(tiers.hot);self.assertIsInstance(tiers.warm,bytes)
  tiers.resolve(raw,1);self.assertGreater(tiers.stats['warm_hits'],0)
  tiers.resolve(b'{"nodes":[{"id":"two"}]}',2)
  self.assertEqual(tiers.hot[0]['id'],'two');self.assertEqual(tiers.stats['invalidations'],1)
  tiers.resolve(raw,0);self.assertIsNone(tiers.hot);self.assertIsNone(tiers.warm)
  tiers.clear();self.assertIsNone(tiers.identity)
 def test_only_current_local_source_matches_selected_graph_node(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'serve').mkdir();(root/'serve/guard.py').write_text('class RequestGuard:\n    pass\n')
   graph=root/'graph.json';graph.write_text(json.dumps(dict(nodes=[dict(id='guard',label='RequestGuard',source_file='serve/guard.py'),dict(id='escape',label='RequestGuard',source_file='../secret.py')],links=[])))
   rows,meta=select_sources(root,graph,'Come funziona RequestGuard?',limit=2)
   self.assertEqual([row['path'] for row in rows],[str((root/'serve/guard.py').resolve())])
   self.assertEqual(meta['kind'],'REPOSITORY_SOURCE_SELECTION; not GPU or weight acceleration')
   (root/'serve/guard.py').write_text('class Renamed:\n    pass\n')
   self.assertEqual(select_sources(root,graph,'RequestGuard',limit=2)[0],[])
 def test_no_match_does_not_broaden_sources(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);graph=root/'graph.json';graph.write_text('{"nodes":[],"links":[]}')
   self.assertEqual(select_sources(root,graph,'Nebbia',limit=2)[0],[])

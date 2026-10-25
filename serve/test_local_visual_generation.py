import tempfile,unittest,json
from pathlib import Path
from types import SimpleNamespace
from serve.local_visual_generation import LocalVisualGeneration
class VisualTests(unittest.TestCase):
 def test_limits_and_family(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);model=root/'models/tiny';model.mkdir(parents=True);(model/'model_index.json').write_text(json.dumps({'_class_name':'StableDiffusionPipeline'}))
   for component in ('unet','vae','text_encoder'):
    (model/component).mkdir();(model/component/'model.safetensors').write_bytes(b'fixture')
   engine=LocalVisualGeneration(SimpleNamespace(root=root,python_runtime=Path('missing'),status=lambda:{'status':'idle'}))
   for options in ({'width':4096},{'frames':500},{'steps':500},{'prompt':'x'*3000},{'device':'auto'}):
    with self.assertRaises(ValueError):engine.validate(dict({'model':str(model),'prompt':'hello'},**options))
   self.assertEqual(engine.validate({'model':str(model),'prompt':'hello'})['kind'],'image')
   with self.assertRaises(ValueError):engine.validate({'model':str(model),'prompt':'hello','kind':'video'})
   (model/'unet/model.safetensors').unlink()
   self.assertEqual(engine.models(),[])
 def test_unknown_artifact_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   engine=LocalVisualGeneration(SimpleNamespace(root=Path(d)))
   with self.assertRaises(ValueError):engine.artifact('../secret')

 def test_completed_report_requires_actual_hash(self):
  from unittest.mock import Mock
  import hashlib
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);engine=LocalVisualGeneration(SimpleNamespace(root=root));folder=root/'output/visual-generations'/('a'*32);folder.mkdir(parents=True)
   media=folder/'image.png';media.write_bytes(b'fixture');report={'status':'complete','file':'image.png','bytes':7,'sha256':hashlib.sha256(b'fixture').hexdigest()};(folder/'result.json').write_text(json.dumps(report))
   engine.state={'status':'running','folder':str(folder)};engine.process=Mock();engine.process.poll.return_value=0;engine.process.returncode=0;engine.lease=Mock()
   self.assertEqual(engine.status()['status'],'complete');self.assertEqual(engine.artifact('a'*32),media)
   media.write_bytes(b'corrupt')
   with self.assertRaises(ValueError):engine.artifact('a'*32)

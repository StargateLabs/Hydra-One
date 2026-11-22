import json,tempfile,unittest
from pathlib import Path
from PIL import Image
from tools.train_local_lora import dataset_rows
from serve.training_options import training_options
class VisionDatasetTests(unittest.TestCase):
 def test_image_pairs_are_normalized_and_invalid_images_rejected(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder);image=path/'picture.png';Image.new('RGB',(16,16),'red').save(image)
   dataset=path/'dataset.jsonl';dataset.write_text(json.dumps({'prompt':'Describe','response':'Red','image':str(image)}),encoding='utf-8')
   normalized=dataset_rows(dataset,'vlm')[0]
   self.assertEqual(normalized['response'],'Red');self.assertEqual(len(normalized['image_sha256']),64)
   self.assertEqual(dataset_rows(dataset,'auto')[0]['text'],normalized['text'])
   image.write_bytes(b'not an image')
   with self.assertRaises(Exception):dataset_rows(dataset,'vlm')
 def test_vision_limits_are_explicit_without_changing_sft(self):
  self.assertEqual(training_options({'method':'vlm','length':1024})['length'],1024)
  for request in ({'method':'vlm','device':'cuda'},{'method':'sft','length':1024}):
   with self.assertRaises(ValueError):training_options(request)
 def test_vision_checkpoint_save_and_resume_are_accepted(self):
  for request in ({'method':'vlm','checkpointing':True},{'method':'vlm','save_steps':1},
                  {'method':'vlm','resume_checkpoint':'output/training/run/trainer/checkpoint-1'}):
   with self.subTest(request=request):
    self.assertTrue(training_options(request))

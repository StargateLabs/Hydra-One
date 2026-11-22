import base64,io,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from serve.vision_dataset_upload import upload

class VisionImportTests(unittest.TestCase):
 def payload(self):
  stream=io.BytesIO();Image.new('RGB',(16,16),'green').save(stream,format='PNG')
  return {'kind':'train','name':'samples.jsonl','content':json.dumps({'prompt':'Describe the image','response':'Green square','image':'photo.png'}),'images':[{'name':'photo.png','content':base64.b64encode(stream.getvalue()).decode()}]}
 def test_import_links_images_and_records_inside_one_owned_folder(self):
  with tempfile.TemporaryDirectory() as folder:
   result=upload(folder,self.payload());path=Path(result['path']);row=json.loads(path.read_text(encoding='utf-8'))
   self.assertEqual(result['rows'],1);self.assertEqual(result['images'],1)
   self.assertEqual(Path(row['image']).parent,path.parent);self.assertTrue(Path(row['image']).is_file())
 def test_missing_reference_or_duplicate_name_creates_no_candidate(self):
  with tempfile.TemporaryDirectory() as folder:
   payload=self.payload();payload['images'][0]['name']='different.png'
   with self.assertRaisesRegex(ValueError,'matching'):upload(folder,payload)
   self.assertFalse((Path(folder)/'output').exists())
   payload=self.payload();payload['images']*=2
   with self.assertRaisesRegex(ValueError,'Duplicate'):upload(folder,payload)
 def test_invalid_image_is_rejected_and_owned_partial_files_are_removed(self):
  with tempfile.TemporaryDirectory() as folder:
   sentinel=Path(folder)/'original.txt';sentinel.write_text('preserve')
   payload=self.payload();payload['images'][0]['content']=base64.b64encode(b'invalid image').decode()
   with self.assertRaises(Exception):upload(folder,payload)
   self.assertEqual(list((Path(folder)/'output/training-datasets').iterdir()),[])
   self.assertEqual(sentinel.read_text(),'preserve')
 def test_paths_and_oversized_data_are_rejected(self):
  with tempfile.TemporaryDirectory() as folder:
   payload=self.payload();payload['images'][0]['name']='../photo.png'
   with self.assertRaisesRegex(ValueError,'filename'):upload(folder,payload)
   payload=self.payload();payload['images'][0]['content']='a'*(3*1024**2)
   with self.assertRaisesRegex(ValueError,'exceeds'):upload(folder,payload)

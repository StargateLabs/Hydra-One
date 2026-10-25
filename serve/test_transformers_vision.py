import base64,io,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from serve.transformers_vision import image_inputs, inspect_vision

class VisionContracts(unittest.TestCase):
 def data(self,size=(8,8)):
  out=io.BytesIO();Image.new('RGB',size,'red').save(out,format='PNG');return 'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()
 def test_images_and_instructions_preserved(self):
  messages,images=image_inputs([{'role':'user','content':[{'type':'text','text':'Describe'},{'type':'image_url','image_url':{'url':self.data()}}]},{'role':'system','content':'Be precise'}])
  self.assertEqual(messages[0]['role'],'system');self.assertEqual(len(images),1);self.assertEqual(messages[1]['content'][1],{'type':'image'})
 def test_remote_and_file_images_rejected(self):
  for url in ['https://example.com/photo.png','file:///C:/secret.png']:
   with self.assertRaises(ValueError):image_inputs([{'role':'user','content':[{'type':'image_url','image_url':{'url':url}}]}])
 def test_image_count_and_pixels_bounded(self):
  part={'type':'image_url','image_url':{'url':self.data()}}
  with self.assertRaises(ValueError):image_inputs([{'role':'user','content':[part]*3}])
  with self.assertRaises(ValueError):image_inputs([{'role':'user','content':[{'type':'image_url','image_url':{'url':self.data((1025,1025))}}]}])
 def test_explicit_family_and_nested_text_budget(self):
  with tempfile.TemporaryDirectory(dir='output/verification/test-temp') as temp:
   folder=Path(temp).resolve();(folder/'config.json').write_text(json.dumps({'model_type':'llava','architectures':['LlavaForConditionalGeneration'],'text_config':{'max_position_embeddings':2048,'hidden_size':16,'num_attention_heads':2,'num_hidden_layers':1},'vision_config':{'image_size':16,'patch_size':4}}));(folder/'model.safetensors').write_bytes(b'fixture');(folder/'preprocessor_config.json').write_text('{}')
   row=inspect_vision(folder);self.assertEqual(row['model_max_context'],2048);self.assertEqual(row['input_modalities'],['text','image'])
   (folder/'preprocessor_config.json').unlink();(folder/'processor_config.json').write_text(json.dumps({'image_processor':{}}));self.assertEqual(inspect_vision(folder)['model_type'],'llava')
   config=json.loads((folder/'config.json').read_text());config['model_type']='unknown_vl';(folder/'config.json').write_text(json.dumps(config))
   with self.assertRaises(ValueError):inspect_vision(folder)

if __name__=='__main__':unittest.main()

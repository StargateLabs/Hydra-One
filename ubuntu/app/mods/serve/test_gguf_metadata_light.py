import struct,tempfile,unittest
from pathlib import Path
from serve.gguf_metadata_light import metadata_string
class Metadata(unittest.TestCase):
 def test_large_token_array_is_skipped_before_template(self):
  def text(value):
   raw=value.encode();return struct.pack('<Q',len(raw))+raw
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'model.gguf'
   path.write_bytes(b'GGUF'+struct.pack('<IQQ',3,0,2)+text('tokenizer.ggml.tokens')+struct.pack('<IIQ',9,8,100001)+text('a')*100001+text('tokenizer.chat_template')+struct.pack('<I',8)+text('tools template'))
   self.assertEqual(metadata_string(path,'tokenizer.chat_template'),'tools template')

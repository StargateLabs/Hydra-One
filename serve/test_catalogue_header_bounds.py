import struct,unittest
from unittest.mock import patch
from serve.catalogue import read_gguf_header

class HeaderBounds(unittest.TestCase):
    def read(self,payload):
        with patch('serve.catalogue._range_bytes',return_value=payload):return read_gguf_header('fixture')
    def test_absurd_key_length_is_bounded(self):
        row=self.read(b'GGUF'+struct.pack('<IQQQ',3,0,1,2**60)+b'xxx')
        self.assertFalse(row['metadata_complete']);self.assertEqual(row['meta'],{})
    def test_complete_header_identified(self):
        row=self.read(b'GGUF'+struct.pack('<IQQ',3,0,0));self.assertTrue(row['metadata_complete'])
    def test_array_extent_is_bounded(self):
        key=b'array';payload=b'GGUF'+struct.pack('<IQQQ',3,0,1,len(key))+key+struct.pack('<IIQ',9,4,2**60)
        self.assertFalse(self.read(payload)['metadata_complete'])

if __name__=='__main__':unittest.main()

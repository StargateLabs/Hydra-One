from pathlib import Path
import tempfile
import unittest
from tools.export_local_gguf import convert,ROOT
class ExportValidation(unittest.TestCase):
 def test_destination_and_type_rejected_before_conversion(self):
  with tempfile.TemporaryDirectory() as directory:
   with self.assertRaisesRegex(ValueError,'inside project'):convert(directory,Path(directory)/'out.gguf')
   with self.assertRaisesRegex(ValueError,'Unsupported'):convert(directory,ROOT/'output/new.gguf','invalid')
 def test_existing_output_not_overwritten(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'output') as directory:
   destination=Path(directory)/'exists.gguf';destination.write_bytes(b'keep')
   with self.assertRaises(ValueError):convert(directory,destination)
   self.assertEqual(destination.read_bytes(),b'keep')
if __name__=='__main__':unittest.main()

import json,tempfile,unittest
from pathlib import Path
from serve.update_center import whisper_cpu_dependencies,file_sha256

class WhisperPairingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.whisper=self.root/'whisper';self.whisper.mkdir()
  (self.whisper/'whisper-server.exe').write_bytes(b'whisper fixture')
  self.asset='whisper-new-windows-x64-slim.zip';self.tag='b11541-mix-2500203'
  (self.whisper/'UNSLOTH_WHISPER_PREBUILT_INFO.json').write_text(json.dumps(dict(source_repo='unslothai/whisper.cpp',asset_name=self.asset,os='windows',arch='x64',requires_llama_tag=self.tag,requires_ggml_sonames=['ggml.dll','ggml-base.dll','libomp140.x86_64.dll'])),encoding='utf-8')
  self.paired=self.root/'paired';self.paired.mkdir();rows=[]
  for name in ['llama-server.exe','ggml.dll','ggml-base.dll','ggml-cpu-x64.dll','libomp140.x86_64.dll','amdhip64_7.dll']:
   p=self.paired/name;p.write_bytes(name.encode());rows.append(dict(path=name,bytes=p.stat().st_size,sha256=file_sha256(p)))
  (self.paired/'CANDIDATE-MANIFEST.json').write_text(json.dumps(dict(source='https://github.com/unslothai/llama.cpp/releases/download/'+self.tag+'/app-'+self.tag+'-windows-x64-cpu.zip',files=rows)),encoding='utf-8')
 def test_new_bundle_selects_exact_isolated_pair_and_omits_gpu_dlls(self):
  result=whisper_cpu_dependencies(self.whisper,self.asset)
  self.assertEqual(result['paired_llama_tag'],self.tag)
  self.assertTrue((self.whisper/'ggml.dll').is_file())
  self.assertTrue((self.whisper/'libomp140.x86_64.dll').is_file())
  self.assertFalse((self.whisper/'amdhip64_7.dll').exists())
 def test_tampered_pair_is_rejected_before_copy(self):
  (self.paired/'ggml.dll').write_bytes(b'changed')
  with self.assertRaisesRegex(ValueError,'changed'):whisper_cpu_dependencies(self.whisper,self.asset)
  self.assertFalse((self.whisper/'ggml-base.dll').exists())
 def test_conflicting_destination_dll_is_never_overwritten(self):
  (self.whisper/'ggml-base.dll').write_bytes(b'custom')
  with self.assertRaisesRegex(ValueError,'conflicting'):whisper_cpu_dependencies(self.whisper,self.asset)
  self.assertEqual((self.whisper/'ggml-base.dll').read_bytes(),b'custom')
 def test_asset_mismatch_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'metadata'):whisper_cpu_dependencies(self.whisper,'different.zip')

"""Small source/build identity fixtures; never launches a runtime or GPU API."""
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from serve import hydra_native_admission as native

class SourceBinding(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.parent=Path(self.temp.name);self.root=self.parent/'app';self.root.mkdir()
  self.relative='HYDRA/engine_link_fixture';self.delivery=self.parent/self.relative
  self.binary=self.delivery/'candidate-source-bound/strata.exe'
  self.binary.parent.mkdir(parents=True);self.binary.write_bytes(b'not executable; identity fixture only')
  self.source=self.root/'owned.cpp';self.source.write_text('owned source')
  self.write('build/compile_commands.json',[]);self.write('build/CMakeCache.txt',{'fixture':True})
  manifest=dict(kind='FULL_NATIVE_HIP_BUILD_AND_LINK_ONLY',backend='HIP gfx1100',runtime_sha256=self.sha(self.binary),compile_commands_sha256=self.sha(self.delivery/'build/compile_commands.json'),cmake_cache_sha256=self.sha(self.delivery/'build/CMakeCache.txt'))
  self.write('candidate-manifest.json',manifest)
  self.write('source-inputs.json',{str(self.source):self.sha(self.source)})
  self.write('build-bd3c84dd0e/result.json',dict(exit_code=0,cleanup=True,sources_unchanged=True))
  self.identity=dict(directory=self.relative,binary_sha256=self.sha(self.binary),receipts={name:self.sha(self.delivery/name) for name in native.SOURCE_BOUND_V32['receipts']})
  self.replace=patch.object(native,'SOURCE_BOUND_V32',self.identity);self.replace.start();self.addCleanup(self.replace.stop)
  self.config=self.root/'strata-hf_85a248b2_q2_0.json';self.config.write_text(json.dumps({'exe':str(self.binary)}))
 def sha(self,path):return hashlib.sha256(path.read_bytes()).hexdigest()
 def write(self,name,value):
  path=self.delivery/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
 def test_real_resolver_consumes_exact_linked_identity_without_old_candidate(self):
  before=self.config.read_bytes();row=native.runtime_provenance(self.root)
  self.assertEqual(row['status'],'SOURCE_BOUND_PENDING_RUNTIME_ATTESTATION')
  self.assertEqual(row['sources_verified'],1);self.assertFalse(row['execution_enabled']);self.assertFalse(row['automatic_fallback'])
  self.assertEqual(self.config.read_bytes(),before)
 def test_changed_source_invalidates_build_binding(self):
  self.source.write_text('changed source');row=native.runtime_provenance(self.root)
  self.assertEqual(row['status'],'BLOCKED');self.assertIn('SOURCE_BUILD_SOURCE_CHANGED',row['detail'])
 def test_changed_binary_cannot_inherit_filename_identity(self):
  self.binary.write_bytes(b'changed executable');row=native.runtime_provenance(self.root)
  self.assertEqual(row['status'],'BLOCKED');self.assertIn('SOURCE_BUILD_RUNTIME_CHANGED',row['detail'])
 def test_modified_receipt_is_not_trusted(self):
  self.write('candidate-manifest.json',{'execution_enabled':True});row=native.runtime_provenance(self.root)
  self.assertEqual(row['status'],'BLOCKED');self.assertIn('PROVENANCE_CHANGED',row['detail'])
 def test_configuration_hash_is_part_of_source_binding(self):
  self.write('build/compile_commands.json',['changed options']);row=native.runtime_provenance(self.root)
  self.assertEqual(row['status'],'BLOCKED');self.assertIn('CONFIGURATION_CHANGED',row['detail'])
 def test_other_executable_has_no_silent_mapping(self):
  other=self.root/'another.exe';other.write_bytes(self.binary.read_bytes())
  row=native.inspect_source_bound_runtime(self.root,other)
  self.assertEqual(row['status'],'BLOCKED');self.assertIn('PATH_MISMATCH',row['detail'])
 def test_preflight_keeps_execution_attestation_and_budget_block(self):
  with patch.object(native,'runtime_provenance',return_value=dict(status='SOURCE_BOUND_PENDING_RUNTIME_ATTESTATION',reason='NATIVE_MOE_RUNTIME_EXECUTION_ATTESTATION_REQUIRED')):
   row=native.native_preflight(self.root)
  self.assertFalse(row['execution_enabled']);self.assertIn('NATIVE_MOE_RUNTIME_EXECUTION_ATTESTATION_REQUIRED',row['blockers'])
  self.assertIn('NATIVE_MOE_COMPLETE_RAM_VRAM_UPPER_BOUND_REQUIRED',row['blockers'])
  self.assertNotIn('NATIVE_MOE_RUNTIME_SOURCE_BINDING_REQUIRED',row['blockers'])

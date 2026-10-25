import hashlib,json,pathlib,unittest
from unittest.mock import patch
from serve import test_hydra_feature_control as fixtures
from serve.hydra_feature_control import FeatureError,runtime_options
class FastPresetTests(unittest.TestCase):
 setUp=fixtures.FeatureControlTests.setUp
 tearDown=fixtures.FeatureControlTests.tearDown
 change=fixtures.FeatureControlTests.change
 def test_missing_gate_refuses_preset_without_any_runtime(self):
  with patch('serve.hydra_performance_v15.PROMOTION',self.root/'missing.json',create=True):
   with self.assertRaisesRegex(FeatureError,'FASTPATH_NOT_PROMOTED'):self.control.preset('hydra-cpu-fastpath-v2')
 def test_verified_gate_applies_cpu_cache_and_off_restores_reference_policy(self):
  model='9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031'
  options=dict(runtime_reuse=True,cache_prompt=True,mmap=True,model_io='standard',checkpoint=False,http_pool=False,threads=2,affinity_cpus=2,context=2048,max_tokens=128,seed=42)
  frozen={'state':'UNPROMOTED_CANDIDATE','preset_id':'hydra-cpu-fastpath-v2','model_sha256':model,'model_path':'fixture','runtime_hash':'fixture','runtime_path':'fixture','runtime_manifest':{'files':{}},'protocol_sha256':__import__('serve.hydra_performance_v15',fromlist=['EXPECTED']).EXPECTED,'options':options}
  raw=json.dumps(frozen).encode();(self.root/'candidate-profile-frozen.json').write_bytes(raw);fingerprint=hashlib.sha256(raw).hexdigest();verdict={'GO':True,'gain_percent':25,'compatible_workloads':['short','medium','prefix-pair']}
  promotion=dict(frozen,state='PROMOTED',promoted=True,frozen_candidate_sha256=fingerprint,gate_record_id='fixture-gate',profile_gate=verdict);path=self.root/'promotion.json';path.write_text(json.dumps(promotion))
  gate={'status':'PASS','cleanup':True,'model_hash':model,'runtime_hash':'fixture','original_result':{'frozen_candidate_sha256':fingerprint,'profile_gate':verdict}}
  with self.control.db() as db:
   db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,payload TEXT)');db.execute('INSERT INTO runs VALUES(?,?)',('fixture-gate',json.dumps(gate)))
  with patch('serve.hydra_performance_v15.PROMOTION',path,create=True),patch('serve.hydra_performance_v15.verify_certified_assets',create=True) as assets:
   plan=self.control.preset('hydra-cpu-fastpath-v2');assets.assert_called_once();self.assertEqual(plan['preset_id'],'hydra-cpu-fastpath-v2')
   self.change(plan['changes']);options=runtime_options(self.control);self.assertTrue(options['cache_prompt']);self.assertTrue(options['mmap']);self.assertEqual(options['model_io'],'standard')
   self.assertTrue(all(not v['desired'] for k,v in self.control.export()['features'].items() if k.startswith('runtime.')))
   promotion['options']['model_io']='iocp';path.write_text(json.dumps(promotion))
   with self.assertRaisesRegex(FeatureError,'FASTPATH_CERTIFICATION_MISMATCH'):self.control.preset('hydra-cpu-fastpath-v2')
   self.assertEqual(assets.call_count,1,'tampered configuration refused before asset admission')
   self.change(self.control.preset('hydra-local-complete-v1')['changes']);self.assertFalse(runtime_options(self.control)['cache_prompt'])
if __name__=='__main__':unittest.main()

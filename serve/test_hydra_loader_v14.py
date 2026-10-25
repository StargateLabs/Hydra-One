import unittest
from serve import test_hydra_feature_control as fixtures
from serve.hydra_feature_control import runtime_options,FeatureError
class LoaderTests(unittest.TestCase):
 setUp=fixtures.FeatureControlTests.setUp
 tearDown=fixtures.FeatureControlTests.tearDown
 change=fixtures.FeatureControlTests.change
 def test_loader_off_uses_reference(self):
  self.assertEqual(runtime_options(self.control)['model_io'],'standard')
 def test_iocp_mmap_conflict_is_explicit(self):
  with self.assertRaisesRegex(FeatureError,'IOCP_REQUIRES_MMAP_OFF'):
   self.change({'V7-E-029':{'desired':True}},allow_blocked=True)
 def test_iocp_only_cpu_qwen(self):
  self.change({'V7-E-028':{'desired':False},'V7-E-029':{'desired':True}},allow_blocked=True)
  self.assertEqual(runtime_options(self.control)['model_io'],'iocp')
  # No native process is started by this contract test.
  with self.assertRaisesRegex(FeatureError,'IOCP_SCOPE'):
   self.control.resolve(dict(profile='cpu',model_id='other/model'))
if __name__=='__main__':unittest.main()

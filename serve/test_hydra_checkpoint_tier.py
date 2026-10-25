import unittest
from serve import test_hydra_feature_control as fixtures
from serve.hydra_feature_control import FeatureError
class TierPolicyTests(unittest.TestCase):
 setUp=fixtures.FeatureControlTests.setUp
 tearDown=fixtures.FeatureControlTests.tearDown
 change=fixtures.FeatureControlTests.change
 def test_explicit_disk_tier_and_off(self):
  plan=self.control.preview({'V7-C-013':{'desired':True,'parameters':{'checkpoint_tier':1}}},include_dependencies=True)
  self.change(plan['changes']);self.assertEqual(self.control.setting(13)['parameters']['checkpoint_tier'],1)
  self.change({'V7-C-013':{'desired':False}});self.assertFalse(self.control.setting(13)['desired'])
 def test_unsupported_tier_refused(self):
  with self.assertRaises(FeatureError):self.change({'V7-C-013':{'parameters':{'checkpoint_tier':2}}})
 def test_v14_helper_alias_requires_central_admission(self):
  from serve.hydra_feature_control import check_native_policy
  with self.assertRaisesRegex(FeatureError,'FEATURE_CONTROL_REQUIRED'):check_native_policy(['native-score-v14.exe','runtime','model'],{})

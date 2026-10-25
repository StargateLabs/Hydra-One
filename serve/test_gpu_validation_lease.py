import json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from serve.gpu_lease import owns_inherited_validation_lease

class ValidationLease(unittest.TestCase):
 def test_only_actual_descendant_with_matching_token_may_use_reservation(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'data').mkdir()
   (root/'data/.gpu-campaign.lock').write_text(json.dumps({'owner':'strata-bounded-check','token':'owned-token','pid':123}),encoding='utf-8')
   with patch.dict(os.environ,{'STRATA_VALIDATION_LEASE_TOKEN':'owned-token'}),patch('psutil.Process') as process:
    process.return_value.parents.return_value=[SimpleNamespace(pid=123)]
    self.assertTrue(owns_inherited_validation_lease(root))
    process.return_value.parents.return_value=[SimpleNamespace(pid=456)]
    self.assertFalse(owns_inherited_validation_lease(root))
   with patch.dict(os.environ,{'STRATA_VALIDATION_LEASE_TOKEN':'wrong-token'}):self.assertFalse(owns_inherited_validation_lease(root))
   with patch.dict(os.environ,{},clear=True):self.assertFalse(owns_inherited_validation_lease(root))

import tempfile,unittest,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from serve.optional_catalogue import OptionalCatalogue
class LocalIdentityTests(unittest.TestCase):
 def make(self,folder,rows):return OptionalCatalogue(SimpleNamespace(root=Path(folder),binary=Path(folder)/'server.exe',status=lambda:{'local_models':[dict(r) for r in rows]}))
 def test_status_bounds_workers_and_prunes_removed(self):
  with tempfile.TemporaryDirectory() as folder:
   rows=[{'path':str(i),'repo':'author/model'} for i in range(20)];catalogue=self.make(folder,rows);catalogue.local_identities['removed']={};catalogue.local_identity_checked['removed']=500
   with patch('serve.optional_catalogue.threading.Thread') as thread,patch('serve.optional_catalogue.time.monotonic',return_value=1):
    catalogue.status();catalogue.status();self.assertEqual(thread.call_count,2);self.assertEqual(len(catalogue.local_pending),2);self.assertNotIn('removed',catalogue.local_identities)
 def test_offline_preserves_facts_then_retries(self):
  with tempfile.TemporaryDirectory() as folder:
   row={'path':'existing','repo':'author/model'};catalogue=self.make(folder,[row]);catalogue.local_identities['existing']={'repo':'author/model','license':'mit'};catalogue.local_pending.add('existing')
   with patch('serve.optional_catalogue.get_json',side_effect=OSError('offline')),patch('serve.optional_catalogue.time.monotonic',return_value=10):catalogue._local_identity(row)
   self.assertEqual(catalogue.local_identities['existing']['license'],'mit');self.assertEqual(catalogue.local_identity_checked['existing'],70);self.assertFalse(catalogue.local_pending)
   with patch('serve.optional_catalogue.threading.Thread') as thread,patch('serve.optional_catalogue.time.monotonic',return_value=69):catalogue.status();thread.assert_not_called()
   with patch('serve.optional_catalogue.threading.Thread') as thread,patch('serve.optional_catalogue.time.monotonic',return_value=70):catalogue.status();thread.assert_called_once()
if __name__=='__main__':unittest.main()

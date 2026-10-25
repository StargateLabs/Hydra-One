import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from serve.gpu_lease import recover_stale_optional_reservation,recover_stale_colibri_reservation
class ReservationRecoveryTests(unittest.TestCase):
 def test_colibri_requires_dead_parent_dead_engine_and_closed_port(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);home=root/'data/colibri';home.mkdir(parents=True)
   (home/'setup.json').write_text(json.dumps({'host':'127.0.0.1','port':18889}))
   (home/'strata-runtime.json').write_text(json.dumps({'pid':456}))
   path=root/'data/.gpu-campaign.lock';path.write_text(json.dumps({'owner':'colibri-original-workspace','pid':123,'token':'b'*32}))
   with patch('psutil.pid_exists',side_effect=lambda pid:pid==456):self.assertFalse(recover_stale_colibri_reservation(root))
   with patch('psutil.pid_exists',return_value=False),patch('psutil.process_iter',return_value=[]),patch('socket.socket') as socket:
    socket.return_value.__enter__.return_value.connect_ex.return_value=0
    self.assertFalse(recover_stale_colibri_reservation(root));self.assertTrue(path.exists())
    socket.return_value.__enter__.return_value.connect_ex.return_value=1
    self.assertTrue(recover_stale_colibri_reservation(root))
   self.assertTrue((root/'data/stale-reservations'/('b'*32+'.json')).exists())
 def test_live_owner_never_removed(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);(root/'data').mkdir();path=root/'data/.gpu-campaign.lock';path.write_text(json.dumps({'owner':'optional-backend','pid':123,'token':'a'*32}))
   with patch('psutil.pid_exists',return_value=True):self.assertFalse(recover_stale_optional_reservation(root))
   self.assertTrue(path.exists())
 def test_dead_owner_without_children_or_ports_archived(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);(root/'data').mkdir();path=root/'data/.gpu-campaign.lock';path.write_text(json.dumps({'owner':'optional-backend','pid':123,'token':'a'*32}))
   with patch('psutil.pid_exists',return_value=False),patch('psutil.process_iter',return_value=[]),patch('socket.socket') as socket:
    socket.return_value.__enter__.return_value.connect_ex.return_value=1
    self.assertTrue(recover_stale_optional_reservation(root))
   self.assertFalse(path.exists());self.assertTrue((root/'data/stale-reservations'/('a'*32+'.json')).exists())
if __name__=='__main__':unittest.main()

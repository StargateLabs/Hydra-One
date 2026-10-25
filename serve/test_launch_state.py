import json
from pathlib import Path
import tempfile
import unittest
from serve.launch_state import selected_profile,remember_launch

class LaunchStateTests(unittest.TestCase):
    def test_isolated_launch_cannot_replace_operational_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); cfg=root/'strata-iq3_xxs.json';cfg.write_text('{}')
            state=root/'ultimo-avvio.json'
            self.assertTrue(remember_launch(root,root,cfg,8088))
            previous=state.read_bytes()
            self.assertFalse(remember_launch(root,root,cfg,8089))
            test=root/'output'/'verification'/'test.json';test.parent.mkdir(parents=True);test.write_text('{}')
            self.assertFalse(remember_launch(root,root,test,8088))
            self.assertEqual(state.read_bytes(),previous)
            state.write_text(json.dumps(dict(config=str(test),port=8089)))
            self.assertEqual(selected_profile(root,state),cfg)

if __name__=='__main__':unittest.main()

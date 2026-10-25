import json
import tempfile
import sqlite3
import time
from contextlib import closing
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from serve.harness_activity import activity


class ActivityTests(unittest.TestCase):
    def test_dsh_open_turn_is_busy_and_closed_turn_is_idle(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            directory = root / 'data/dsh-home/storages/session_projcache/sessions'
            directory.mkdir(parents=True)
            agent = SimpleNamespace(root=root, kind='dsh', child=Mock())
            agent.child.poll.return_value = None
            for start, expected in [(12, True), (None, False)]:
                (directory / 'session.json').write_text(json.dumps({'record': {'rows': {'turnBoundary': {'val': {'openTurnStartSeq': start}}}}}))
                self.assertEqual(activity(agent)['busy'], expected)

    def test_missing_signal_prevents_stopping(self):
        agent = SimpleNamespace(root=Path('nonexistent'), kind='hermes', child=Mock())
        agent.child.poll.return_value = None
        self.assertEqual(activity(agent), {'busy': True, 'activity_known': False})

    def test_dead_process_is_not_busy(self):
        self.assertFalse(activity(SimpleNamespace(child=None))['busy'])

    def test_trueforge_native_json_running_and_done(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);home=root/'data/trueforge-home';home.mkdir(parents=True)
            child=Mock();child.poll.return_value=None
            agent=SimpleNamespace(root=root,kind='trueforge',child=child)
            with closing(sqlite3.connect(home/'db.sqlite')) as db:
                db.execute('CREATE TABLE turn(state TEXT)')
                db.execute('INSERT INTO turn VALUES (?)',(json.dumps({'status':'running'}),));db.commit()
                self.assertTrue(activity(agent)['busy'])
                db.execute('UPDATE turn SET state=?',(json.dumps({'status':'done'}),));db.commit()
                self.assertFalse(activity(agent)['busy'])

    def test_hermes_only_unexpired_lease_protects(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);home=root/'data/hermes-home';home.mkdir(parents=True)
            child=Mock();child.poll.return_value=None
            agent=SimpleNamespace(root=root,kind='hermes',child=child)
            with closing(sqlite3.connect(home/'state.db')) as db:
                db.execute('CREATE TABLE session_turn_leases(expires_at REAL)')
                db.execute('INSERT INTO session_turn_leases VALUES (?)',(time.time()+60,));db.commit()
                self.assertTrue(activity(agent)['busy'])
                db.execute('UPDATE session_turn_leases SET expires_at=?',(time.time()-1,));db.commit()
                self.assertFalse(activity(agent)['busy'])

    def test_busy_stop_retains_owned_process(self):
        from serve.agent_harness import AgentHarness
        with tempfile.TemporaryDirectory() as folder:
            agent=AgentHarness(Path(folder),command=['probe'])
            with patch('serve.harness_activity.activity',return_value={'busy':True,'activity_known':True}),patch.object(agent,'_stop_child') as stop:
                with self.assertRaises(RuntimeError):agent.stop()
                self.assertFalse(agent.close())
                stop.assert_not_called()

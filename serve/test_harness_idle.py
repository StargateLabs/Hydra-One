"""An unused harness releases its RAM instead of running forever."""
import json
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FakeChild:
    """A running child: poll() is None until it is stopped."""
    def __init__(self):
        self.running = True
    def poll(self):
        return None if self.running else 0


class HarnessIdleTests(unittest.TestCase):
    def manager(self, **overrides):
        from serve.agent_harness import AgentHarness
        fields = dict(root=ROOT, kind='opencode', port=4196, config={})
        fields.update(overrides)
        harness = AgentHarness.__new__(AgentHarness)
        for key, value in fields.items():
            setattr(harness, key, value)
        harness.lock = threading.RLock()
        harness.child = FakeChild()
        harness.stopped = 0
        harness.state = {'status': 'ready', 'error': None}
        harness.started_at = time.monotonic() - 10_000
        harness.last_activity = time.monotonic() - 10_000
        harness.idle_stop_s = overrides.get('idle_stop_s', 0)

        def fake_stop():
            harness.stopped += 1
            harness.child.running = False
            harness.state.update(status='idle')
            return harness.state

        harness.stop = fake_stop
        return harness

    def test_idle_harness_is_stopped_after_the_quiet_period(self):
        harness = self.manager(idle_stop_s=60)
        # 30 s of silence against a 60 s budget: nothing must happen yet.
        self.assertFalse(harness.idle_should_stop(now=harness.last_activity + 30, busy=False))
        self.assertEqual(harness.stopped, 0)
        # past the budget with no activity: the harness must release.
        self.assertTrue(harness.idle_should_stop(now=harness.last_activity + 61, busy=False))
        harness.stop()
        self.assertEqual(harness.state['status'], 'idle')
        self.assertEqual(harness.stopped, 1)

    def test_a_harness_with_recent_activity_is_kept(self):
        harness = self.manager(idle_stop_s=60)
        harness.last_activity = time.monotonic() - 5
        self.assertFalse(harness.idle_should_stop(now=time.monotonic(), busy=False))

    def test_a_busy_harness_is_never_stopped(self):
        harness = self.manager(idle_stop_s=60)
        harness.last_activity = time.monotonic() - 10_000
        self.assertFalse(harness.idle_should_stop(now=time.monotonic(), busy=True),
                         'a harness with an open session must never be released')

    def test_unreadable_activity_never_stops_the_harness(self):
        harness = self.manager(idle_stop_s=60)
        harness.last_activity = time.monotonic() - 10_000
        # activity() would need a live harness; with no reachable one it must refuse.
        self.assertFalse(harness.idle_should_stop(now=time.monotonic() + 10_000))

    def test_a_harness_that_is_not_running_is_never_stopped(self):
        from serve.agent_harness import AgentHarness
        for status in ('idle', 'starting', 'error'):
            with self.subTest(status=status):
                harness = self.manager()
                harness.child.running = False
                harness.state['status'] = status
                self.assertFalse(harness.idle_should_stop(now=time.monotonic() + 10_000, busy=False))

    def test_idle_stop_is_disabled_by_default(self):
        harness = self.manager()
        self.assertEqual(harness.idle_stop_s, 0)
        self.assertFalse(harness.idle_should_stop(now=time.monotonic() + 10_000, busy=False))


if __name__ == '__main__':
    unittest.main()

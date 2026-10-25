"""A safe update ladder: reclaim, verify, validate, and never activate silently."""
import unittest
from pathlib import Path

from serve.safe_update import (
    plan_update,
    UpdatePlan,
    BLOCKED,
    READY,
    PREFLIGHT_FAILED,
)

ROOT = Path(__file__).resolve().parents[1]


class Service:
    def __init__(self, **state):
        self.state = state

    def status(self):
        return self.state


class FakeDashboard:
    def __init__(self, engine='unloaded', backend='idle', busy=False, ram_gib=40.0):
        self.engine = engine
        self.backend = backend
        self.busy = busy
        self.ram_gib = ram_gib
        self.harnesses = {}

    def harness(self, kind, status='ready', busy=False):
        self.harnesses[kind] = Service(status=status, busy=busy, installed=True)
        return self

    def idle(self):
        return (self.engine == 'unloaded' and self.backend == 'idle'
                and not any(h.status().get('busy') for h in self.harnesses.values()))


class SafeUpdateTests(unittest.TestCase):
    def dashboard(self, **kwargs):
        return FakeDashboard(**kwargs)

    def test_a_busy_engine_blocks_every_update(self):
        plan = plan_update(self.dashboard(engine='loading'), headroom_gib=40.0)
        self.assertEqual(plan.state, PREFLIGHT_FAILED)
        self.assertIn('motore', plan.reason.lower())

    def test_a_busy_harness_blocks_every_update(self):
        dashboard = self.dashboard()
        dashboard.harness('opencode', status='ready', busy=True)
        plan = plan_update(dashboard, headroom_gib=40.0)
        self.assertEqual(plan.state, PREFLIGHT_FAILED)
        self.assertIn('opencode', plan.reason)

    def test_insufficient_headroom_blocks_the_update(self):
        plan = plan_update(self.dashboard(), headroom_gib=6.0)
        self.assertEqual(plan.state, PREFLIGHT_FAILED)
        self.assertIn('RAM', plan.reason)

    def test_an_idle_dashboard_with_headroom_is_ready(self):
        plan = plan_update(self.dashboard(), headroom_gib=40.0)
        self.assertEqual(plan.state, READY)
        self.assertEqual(plan.reason, '')

    def test_idle_harnesses_are_reclaimed_before_updating(self):
        dashboard = self.dashboard()
        dashboard.harness('opencode')
        dashboard.harness('dsh')
        plan = plan_update(dashboard, headroom_gib=40.0)
        self.assertEqual(plan.state, READY)
        self.assertEqual(plan.reclaim, ['opencode', 'dsh'])

    def test_a_harness_already_stopped_is_not_reclaimed_again(self):
        dashboard = self.dashboard()
        dashboard.harness('opencode', status='idle')
        plan = plan_update(dashboard, headroom_gib=40.0)
        self.assertEqual(plan.reclaim, [])

    def test_an_unknown_state_is_never_treated_as_ready(self):
        dashboard = self.dashboard(engine='unknown')
        plan = plan_update(dashboard, headroom_gib=40.0)
        self.assertEqual(plan.state, PREFLIGHT_FAILED)

    def test_the_plan_never_proposes_activation_on_its_own(self):
        plan = plan_update(self.dashboard(), headroom_gib=40.0)
        self.assertFalse(plan.activate,
                         'activation must stay an explicit, separate user action')

    def test_a_protected_component_is_never_planned(self):
        plan = plan_update(self.dashboard(), headroom_gib=40.0,
                           components=[{'id': 'pytorch', 'version': '2.14.1',
                                        'automatic_update_supported': False}])
        self.assertEqual(plan.components, [])
        self.assertIn('pytorch: aggiornamento automatico non supportato', plan.skipped)

    def test_a_component_already_current_is_skipped(self):
        plan = plan_update(self.dashboard(), headroom_gib=40.0,
                           components=[{'id': 'soup', 'version': '0.76.0',
                                        'installed_version': '0.76.0'}])
        self.assertEqual(plan.components, [])
        self.assertIn('soup: già alla versione disponibile', plan.skipped)


if __name__ == '__main__':
    unittest.main()

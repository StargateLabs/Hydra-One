"""Integrated programs stay reachable from Strata's own interface.

Every integrated agent opens from a Strata tab, and the address it loads must be one of
Strata's own loopback harness ports. The page never navigates to an arbitrary external
origin: that would break the integration and leak the session.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'serve' / 'web'

HTML = (WEB / 'index.html').read_text(encoding='utf-8')
SHIPPED = re.findall(r'<script[^>]+src="web/([^"?]+)', HTML)

# The harness ports Strata owns; a panel may only ever load one of these.
HARNESS_PORTS = {8090, 8091, 18196}


class IntegratedFromOurInterfaceTests(unittest.TestCase):
    def scripts(self):
        return [name for name in SHIPPED if (WEB / name).is_file()]

    def test_harness_panels_are_part_of_the_interface(self):
        """Every integrated agent is reachable from a Strata tab, never a separate app."""
        source = (WEB / 'agent-harness.js').read_text(encoding='utf-8')
        for kind in ('opencode', 'hermes', 'trueforge', 'dsh'):
            with self.subTest(kind=kind):
                self.assertIn("'" + kind + "'", source, f'{kind} has no Strata tab')
        self.assertIn('harness-frame', source, 'the harness panel is missing its frame')

    def test_loaded_interface_addresses_stay_on_strata_loopback(self):
        """A panel may only load a Strata harness port, never an arbitrary origin."""
        for name in self.scripts():
            source = (WEB / name).read_text(encoding='utf-8')
            for match in re.finditer(r"url\.port!==?'?(\d+)'?", source):
                with self.subTest(script=name, port=match.group(1)):
                    self.assertIn(int(match.group(1)), HARNESS_PORTS,
                                  f'{name} validates against a port Strata does not own')
            for match in re.finditer(r"url\.hostname!==?'([^']+)'", source):
                with self.subTest(script=name, host=match.group(1)):
                    self.assertEqual(match.group(1), '127.0.0.1',
                                     f'{name} accepts a non-loopback host')

    def test_no_shipped_script_navigates_to_an_external_origin(self):
        """Nothing in the page jumps the browser to a foreign site on its own."""
        offenders = []
        for name in self.scripts():
            source = (WEB / name).read_text(encoding='utf-8')
            if re.search(r"location\s*\.\s*href\s*=\s*['\"]https?:", source):
                offenders.append(f'{name}: location.href navigation')
            if re.search(r"window\s*\.\s*open\s*\(\s*['\"]https?:", source):
                offenders.append(f'{name}: window.open to an external origin')
        self.assertEqual(offenders, [], 'A shipped script navigates outside Strata: ' + '; '.join(offenders))

    def test_harness_connect_endpoint_is_available(self):
        server = (ROOT / 'serve' / 'server.py').read_text(encoding='utf-8')
        self.assertIn('"connect"', server, 'the harness connect endpoint is missing')

    def test_harness_launch_endpoint_is_available(self):
        """The antigravity route must still be able to open the app it names.

        The route delegates to the native workspace, which resolves the executable
        through antigravity_desktop; both halves must exist.
        """
        server = (ROOT / 'serve' / 'server.py').read_text(encoding='utf-8')
        self.assertIn("'/harness/antigravity/desktop'", server)
        self.assertIn('native_workspace_routes', server,
                      'the antigravity route lost its launcher')
        from serve.antigravity_desktop import launch, executable
        self.assertTrue(callable(launch), 'the Antigravity launcher is gone')

    def test_native_workspace_knows_every_integrated_app(self):
        from serve.native_workspace import KINDS
        for kind in ('dashboard', 'claude', 'antigravity'):
            with self.subTest(kind=kind):
                self.assertIn(kind, KINDS)


if __name__ == '__main__':
    unittest.main()

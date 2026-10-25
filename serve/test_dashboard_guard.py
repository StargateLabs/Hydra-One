"""Only one Strata dashboard may run per PC; a second start must point at the first."""
import json
import tempfile
import unittest
from pathlib import Path

from serve.dashboard_guard import (
    claimed_port,
    existing_dashboard,
    release_dashboard_claim,
    claim_dashboard,
    DashboardBusy,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeDashboard:
    """A loopback listener that answers /health like a Strata dashboard."""

    def __init__(self, port):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path != '/health':
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps({'status': 'ok', 'service': 'strata',
                                   'model': 'fixture', 'max_context': 1024}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.port = self.server.server_address[1]

    def __enter__(self):
        import threading
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class DashboardGuardTests(unittest.TestCase):
    def test_a_running_dashboard_is_found_on_its_own_port(self):
        with FakeDashboard(0) as dashboard:
            found = existing_dashboard(ports=(dashboard.port,))
            self.assertEqual(found, dashboard.port)

    def test_a_silent_port_reports_nothing(self):
        import socket
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            free = probe.getsockname()[1]
        self.assertIsNone(existing_dashboard(ports=(free,)))

    def test_a_non_strata_service_is_not_mistaken_for_a_dashboard(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = json.dumps({'service': 'something-else'}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        import threading
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertIsNone(existing_dashboard(ports=(server.server_address[1],)))
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_the_first_dashboard_claims_the_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertIsNone(claimed_port(root))
            claim_dashboard(root, 9001)
            self.assertEqual(claimed_port(root), 9001)

    def test_a_second_dashboard_is_refused_and_told_where_to_look(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            claim_dashboard(root, 9001)
            with self.assertRaises(DashboardBusy) as caught:
                claim_dashboard(root, 9002)
            message = str(caught.exception)
            self.assertIn('9001', message)
            self.assertIn('http://127.0.0.1:9001/', message)

    def test_an_internal_sidecar_is_not_blocked_by_the_guard(self):
        """The bounded candidate check runs its own server while the dashboard stays up."""
        import os
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            claim_dashboard(root, 9001)
            os.environ['STRATA_VALIDATION_LEASE_TOKEN'] = 'fixture-token'
            try:
                self.assertIsNone(claim_dashboard(root, 9002))
            finally:
                os.environ.pop('STRATA_VALIDATION_LEASE_TOKEN', None)

    def test_the_server_claims_the_lock_at_startup(self):
        """The entry point must wire the guard, not just define it."""
        server = (ROOT / 'serve' / 'server.py').read_text(encoding='utf-8')
        self.assertIn('claim_dashboard', server,
                      'the server must claim the single-dashboard lock at startup')
        self.assertIn('release_dashboard_claim', server,
                      'the server must release the claim on a clean shutdown')

    def test_a_stale_claim_from_a_dead_process_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'data').mkdir()
            (root / 'data' / 'dashboard.lock').write_text(
                json.dumps({'port': 9001, 'pid': 999999}), encoding='utf-8')
            self.assertIsNone(claimed_port(root))

    def test_releasing_the_claim_clears_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            claim_dashboard(root, 9001)
            release_dashboard_claim(root)
            self.assertIsNone(claimed_port(root))



if __name__ == '__main__':
    unittest.main()

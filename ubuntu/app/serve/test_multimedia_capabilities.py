"""Capabilities must describe wired workflows, not installed-package guesses."""
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class MultimediaCapabilitiesTests(unittest.TestCase):
    def service(self):
        def worker(**state):
            return SimpleNamespace(status=lambda: state)
        return SimpleNamespace(
            local_audio=worker(installed=True, status='idle', models=[{'name': 'tiny'}],
                               formats=['wav'], input_limit_bytes=200, duration_limit_s=300),
            local_speech=worker(installed=False, status='idle', models=[{'name': 'kokoro'}]),
            local_separation=worker(status='idle', models=[]))

    def test_installed_runtime_requires_model_and_never_certifies_quality(self):
        from serve.multimedia_capabilities import capabilities
        result = capabilities(self.service())
        rows = {row['id']: row for row in result['tasks']}
        self.assertTrue(rows['asr']['available'])
        self.assertFalse(rows['tts']['available'])
        self.assertEqual(rows['asr']['limits']['duration_seconds'], 300)
        self.assertEqual(rows['asr']['endpoints'], ['/v1/audio/transcriptions', '/v1/audio/translations'])
        self.assertIsNone(rows['asr']['quality_verified'])
        self.assertFalse(rows['video_generation']['implemented'])
        self.assertFalse(rows['video_generation']['available'])
        self.assertEqual(rows['video_generation']['endpoints'], [])

    def test_one_failed_status_does_not_hide_other_workflows(self):
        from serve.multimedia_capabilities import capabilities
        service = self.service()
        service.local_audio.status = lambda: (_ for _ in ()).throw(ValueError('broken runtime'))
        result = capabilities(service)
        rows = {row['id']: row for row in result['tasks']}
        self.assertFalse(rows['asr']['available'])
        self.assertEqual(rows['asr']['error'], 'broken runtime')
        self.assertIn('tts', rows)


class MultimediaHTTPTests(unittest.TestCase):
    def setUp(self):
        from serve.server import make_handler
        self.service = MultimediaCapabilitiesTests().service()
        self.service.api_key = 'fixture-key'
        self.service.cors_origins = []
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.service))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, path, key):
        return urlopen(Request(f'http://127.0.0.1:{self.server.server_port}{path}',
                               headers={'Authorization': 'Bearer ' + key}), timeout=5)

    def test_registry_requires_authentication_and_returns_live_status(self):
        with self.assertRaises(HTTPError) as caught:
            self.request('/multimedia-capabilities', 'wrong')
        self.assertEqual(caught.exception.code, 401)
        with self.request('/multimedia-capabilities', 'fixture-key') as response:
            self.assertTrue(json.load(response)['tasks'])

    def test_separation_status_requires_authentication(self):
        with self.assertRaises(HTTPError) as caught:
            self.request('/local-separation', 'wrong')
        self.assertEqual(caught.exception.code, 401)
        with self.request('/local-separation', 'fixture-key') as response:
            self.assertEqual(json.load(response)['status'], 'idle')


if __name__ == '__main__':
    unittest.main()

"""Finished original jobs select the downloadable file; callers cannot choose paths."""
import base64
import json
import unittest
from unittest.mock import Mock
from serve.voicestudio_jobs import action


class LongformDownloadTests(unittest.TestCase):
    def test_finished_job_download_uses_original_output(self):
        client = Mock()
        audio = b'\0\0\0\x18ftypM4B ' + b'\0' * 12
        client._request.side_effect = [
            (json.dumps({'jobs': [{'job_id': 'book-1', 'output': 'original.m4b'}]}).encode(), None, None),
            (audio, None, 'audio/mp4'),
        ]
        result = action(client, {'kind': 'longform', 'action': 'download', 'id': 'book-1'})
        self.assertEqual(result['filename'], 'original.m4b')
        self.assertEqual(base64.b64decode(result['file_base64']), audio)
        self.assertEqual(client._request.call_args.args[0], '/audio/original.m4b')

    def test_unknown_job_or_unsafe_native_filename_never_reads_audio(self):
        for rows in ([], [{'job_id': 'book-1', 'output': '../private.m4b'}],
                     [{'job_id': 'book-1', 'output': 'secret.json'}],
                     [{'job_id': 'book-1', 'output': 'folder\\private.mp3'}]):
            with self.subTest(rows=rows):
                client = Mock()
                client._request.return_value = (json.dumps({'jobs': rows}).encode(), None, None)
                with self.assertRaises((ValueError, RuntimeError)):
                    action(client, {'kind': 'longform', 'action': 'download', 'id': 'book-1'})
                self.assertEqual(client._request.call_count, 1)

    def test_invalid_identifier_never_contacts_runtime(self):
        client = Mock()
        with self.assertRaises(ValueError):
            action(client, {'kind': 'longform', 'action': 'download', 'id': '../book'})
        client._request.assert_not_called()

    def test_html_error_is_not_exported_as_audio(self):
        client = Mock()
        client._request.side_effect = [
            (b'{"jobs":[{"job_id":"book-1","output":"original.mp3"}]}', None, None),
            (b'<html>Error</html>', None, 'text/html'),
        ]
        with self.assertRaises(RuntimeError):
            action(client, {'kind': 'longform', 'action': 'download', 'id': 'book-1'})


if __name__ == '__main__':
    unittest.main()

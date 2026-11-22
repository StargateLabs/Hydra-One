import hashlib
import io
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from serve.mod_baseline import fetch_official_source, read_baseline_version


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=-1):
        return self.data if limit < 0 else self.data[:limit]


def zip_bytes(entries, symlink=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, 'target')
    return buffer.getvalue()


class OfficialBaseline(unittest.TestCase):
    def test_zipball_strips_the_single_top_directory_and_records_the_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            data = zip_bytes({'owner-repo-abc/serve/ok.py': 'ok', 'owner-repo-abc/BUILD.json': '{}'})
            destination = Path(folder) / 'baseline'
            record = fetch_official_source('owner/repo', 'v1.2.3', destination,
                                           opener=lambda request, **kwargs: FakeResponse(data))
            self.assertTrue((destination / 'serve/ok.py').is_file())
            self.assertEqual(record['archive_sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(record['tag'], 'v1.2.3')
            self.assertEqual(record['files'], 2)
            manifest = json.loads((destination / 'BASELINE.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['repository'], 'owner/repo')
            self.assertEqual(read_baseline_version(destination), 'v1.2.3')

    def test_zipball_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            data = zip_bytes({'owner-repo-abc/serve/ok.py': 'ok', 'owner-repo-abc/../evil.py': 'evil'})
            destination = Path(folder) / 'baseline'
            with self.assertRaises(ValueError):
                fetch_official_source('owner/repo', 'v1', destination,
                                      opener=lambda request, **kwargs: FakeResponse(data))
            self.assertFalse(destination.exists())

    def test_zipball_rejects_symlink_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            data = zip_bytes({'owner-repo-abc/serve/ok.py': 'ok'}, symlink='owner-repo-abc/link.py')
            with self.assertRaises(ValueError):
                fetch_official_source('owner/repo', 'v1', Path(folder) / 'baseline',
                                      opener=lambda request, **kwargs: FakeResponse(data))

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / 'baseline'
            destination.mkdir()
            (destination / 'KEEP').write_text('keep')
            with self.assertRaises(ValueError):
                fetch_official_source('owner/repo', 'v1', destination,
                                      opener=lambda request, **kwargs: FakeResponse(zip_bytes({})))
            self.assertEqual((destination / 'KEEP').read_text(), 'keep')

    def test_expected_sha256_is_verified_before_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            data = zip_bytes({'owner-repo-abc/serve/ok.py': 'ok'})
            destination = Path(folder) / 'baseline'
            with self.assertRaises(ValueError):
                fetch_official_source('owner/repo', 'v1', destination, expected_sha256='0' * 64,
                                      opener=lambda request, **kwargs: FakeResponse(data))
            self.assertFalse(destination.exists())

    def test_zipball_must_have_a_single_top_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            data = zip_bytes({'owner-repo-abc/serve/ok.py': 'ok', 'stray.py': 'stray'})
            with self.assertRaises(ValueError):
                fetch_official_source('owner/repo', 'v1', Path(folder) / 'baseline',
                                      opener=lambda request, **kwargs: FakeResponse(data))

    def test_archive_size_limit_is_enforced_before_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            data = zip_bytes({'owner-repo-abc/serve/ok.py': 'ok'})
            with self.assertRaises(ValueError):
                fetch_official_source('owner/repo', 'v1', Path(folder) / 'baseline',
                                      opener=lambda request, **kwargs: FakeResponse(data), max_bytes=10)


if __name__ == '__main__':
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from serve.mod_manifest import build_manifest, compare_trees, write_manifest


def fixture(folder):
    live = Path(folder) / 'live'
    base = Path(folder) / 'base'
    for root in (live, base):
        (root / 'serve').mkdir(parents=True)
    (base / 'serve/same.py').write_text('same')
    (live / 'serve/same.py').write_text('same')
    (base / 'serve/changed.py').write_text('old\n')
    (live / 'serve/changed.py').write_text('new\n')
    (live / 'serve/added.py').write_text('added')
    (base / 'serve/gone.py').write_text('gone')
    return live, base


class CompareTrees(unittest.TestCase):
    def test_compare_reports_modified_added_deleted_and_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            live, base = fixture(folder)
            rows = {row['path']: row for row in compare_trees(live, base)}
            self.assertEqual(rows['serve/same.py']['status'], 'unchanged')
            self.assertEqual(rows['serve/changed.py']['status'], 'modified')
            self.assertIn('-old', rows['serve/changed.py']['diff'])
            self.assertIn('+new', rows['serve/changed.py']['diff'])
            self.assertEqual(rows['serve/added.py']['status'], 'added')
            self.assertEqual(rows['serve/gone.py']['status'], 'deleted')
            self.assertEqual(rows['serve/gone.py']['live'], None)
            self.assertEqual(rows['serve/added.py']['baseline'], None)

    def test_binary_files_get_no_diff(self):
        with tempfile.TemporaryDirectory() as folder:
            live, base = fixture(folder)
            (base / 'serve/blob.png').write_bytes(b'\x89PNG\x00old')
            (live / 'serve/blob.png').write_bytes(b'\x89PNG\x00new')
            row = next(r for r in compare_trees(live, base) if r['path'] == 'serve/blob.png')
            self.assertEqual(row['status'], 'modified')
            self.assertTrue(row['binary'])
            self.assertIsNone(row['diff'])

    def test_excluded_directories_never_enter_the_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            live, base = fixture(folder)
            (live / 'node_modules').mkdir()
            (live / 'node_modules/skip.js').write_text('x')
            (base / 'node_modules').mkdir()
            (base / 'node_modules/skip.js').write_text('y')
            paths = {row['path'] for row in compare_trees(live, base)}
            self.assertNotIn('node_modules/skip.js', paths)

    def test_baseline_marker_is_never_compared(self):
        with tempfile.TemporaryDirectory() as folder:
            live, base = fixture(folder)
            (base / 'BASELINE.json').write_text('{"tag":"v1"}')
            paths = {row['path'] for row in compare_trees(live, base)}
            self.assertNotIn('BASELINE.json', paths)

    def test_binary_sniff_checks_both_sides(self):
        with tempfile.TemporaryDirectory() as folder:
            live, base = fixture(folder)
            (base / 'serve/blob.json').write_bytes(b'\x00old')
            (live / 'serve/blob.json').write_bytes(b'new')
            row = next(r for r in compare_trees(live, base) if r['path'] == 'serve/blob.json')
            self.assertTrue(row['binary'])
            self.assertIsNone(row['diff'])

    def test_large_inputs_skip_the_diff_without_reading_it(self):
        with tempfile.TemporaryDirectory() as folder:
            live, base = fixture(folder)
            (base / 'serve/huge.py').write_text('a' * (5 * 1024 * 1024))
            (live / 'serve/huge.py').write_text('b' * (5 * 1024 * 1024))
            row = next(r for r in compare_trees(live, base) if r['path'] == 'serve/huge.py')
            self.assertIsNone(row['diff'])
            self.assertTrue(row['diff_truncated'])

    def test_truncated_diff_is_flagged(self):
        with tempfile.TemporaryDirectory() as folder:
            live, base = fixture(folder)
            (base / 'serve/large.py').write_text('a' * 200000)
            (live / 'serve/large.py').write_text('b' * 200000)
            row = next(r for r in compare_trees(live, base) if r['path'] == 'serve/large.py')
            self.assertTrue(row['diff_truncated'])
            self.assertLessEqual(len(row['diff']), 64 * 1024)


class BuildManifest(unittest.TestCase):
    def test_manifest_summary_and_atomic_write(self):
        with tempfile.TemporaryDirectory() as folder:
            live, base = fixture(folder)
            manifest = build_manifest(live, base, baseline_version='v0.1.42', baseline_archive_sha256='a' * 64)
            self.assertEqual(manifest['schema_version'], 1)
            self.assertEqual(manifest['baseline_version'], 'v0.1.42')
            self.assertEqual(manifest['baseline_archive_sha256'], 'a' * 64)
            self.assertEqual(manifest['summary']['total'], 4)
            self.assertEqual(manifest['summary']['modified'], 1)
            self.assertEqual(manifest['summary']['added'], 1)
            self.assertEqual(manifest['summary']['deleted'], 1)
            self.assertEqual(manifest['summary']['unchanged'], 1)
            self.assertEqual([row['path'] for row in manifest['files']], sorted(row['path'] for row in manifest['files']))
            out = write_manifest(manifest, Path(folder) / 'm.json')
            self.assertEqual(json.loads(out.read_text(encoding='utf-8')), manifest)
            self.assertFalse(out.with_suffix('.tmp').exists())

    def test_total_diff_budget_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            live, base = fixture(folder)
            for index in range(3):
                (base / f'serve/f{index}.py').write_text('a' * 100)
                (live / f'serve/f{index}.py').write_text('b' * 100)
            manifest = build_manifest(live, base, diff_budget=500)
            self.assertLessEqual(manifest['summary']['diff_bytes'], 500)
            self.assertGreater(manifest['summary']['diff_bytes'], 0)
            dropped = [row for row in manifest['files'] if row['diff_truncated'] and row['diff'] is None]
            self.assertTrue(dropped)

    def test_no_diffs_option_never_reads_text_content(self):
        with tempfile.TemporaryDirectory() as folder:
            live, base = fixture(folder)
            with patch('serve.mod_manifest.bounded_diff', side_effect=AssertionError('read text')):
                manifest = build_manifest(live, base, include_diffs=False)
            self.assertTrue(all(row['diff'] is None for row in manifest['files']))


class CommandLine(unittest.TestCase):
    def test_cli_writes_manifest_and_returns_zero(self):
        from tools.mod_manifest import main
        with tempfile.TemporaryDirectory() as folder:
            live, base = fixture(folder)
            out = Path(folder) / 'm.json'
            code = main(['--live', str(live), '--baseline', str(base), '--out', str(out), '--version', 'v0.1.42'])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['summary']['added'], 1)

    def test_cli_refuses_missing_directory(self):
        from tools.mod_manifest import main
        with tempfile.TemporaryDirectory() as folder:
            code = main(['--live', str(Path(folder) / 'missing'), '--baseline', folder, '--out', str(Path(folder) / 'm.json')])
            self.assertEqual(code, 2)

    def test_cli_refuses_an_output_inside_the_live_tree(self):
        from tools.mod_manifest import main
        with tempfile.TemporaryDirectory() as folder:
            live, base = fixture(folder)
            code = main(['--live', str(live), '--baseline', str(base), '--out', str(live / 'm.json')])
            self.assertEqual(code, 2)
            self.assertFalse((live / 'm.json').exists())

    def test_cli_uses_the_recorded_baseline_and_rejects_a_mismatch(self):
        from tools.mod_manifest import main
        with tempfile.TemporaryDirectory() as folder:
            live, base = fixture(folder)
            (base / 'BASELINE.json').write_text(json.dumps({'tag': 'v9', 'archive_sha256': 'b' * 64}))
            out = Path(folder) / 'm.json'
            self.assertEqual(main(['--live', str(live), '--baseline', str(base), '--out', str(out)]), 0)
            manifest = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(manifest['baseline_version'], 'v9')
            self.assertEqual(manifest['baseline_archive_sha256'], 'b' * 64)
            self.assertEqual(main(['--live', str(live), '--baseline', str(base), '--out', str(out), '--version', 'v8']), 2)


if __name__ == '__main__':
    unittest.main()

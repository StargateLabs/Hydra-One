import json
import tempfile
import unittest
from pathlib import Path
from serve.mod_apply import materialize, plan_apply
from serve.mod_manifest import build_manifest
from serve.mod_report import build_report, render_markdown


def write(root, relative, body):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def fixture(folder):
    live = Path(folder) / 'live'
    old = Path(folder) / 'old'
    new = Path(folder) / 'new'
    for root in (live, old, new):
        (root / 'serve').mkdir(parents=True)
    write(old, 'serve/same.py', 'same'); write(live, 'serve/same.py', 'same'); write(new, 'serve/same.py', 'same')
    write(old, 'serve/user.py', 'old'); write(live, 'serve/user.py', 'user'); write(new, 'serve/user.py', 'old')
    write(old, 'serve/both.py', 'old'); write(live, 'serve/both.py', 'user'); write(new, 'serve/both.py', 'upstream')
    write(new, 'serve/newonly.py', 'new')
    write(live, 'serve/useronly.py', 'user')
    write(live, 'serve/bothadded.py', 'user'); write(new, 'serve/bothadded.py', 'upstream')
    write(old, 'serve/gone.py', 'old')
    write(old, 'serve/gone_changed.py', 'old'); write(new, 'serve/gone_changed.py', 'upstream')
    write(old, 'serve/upstream_removed.py', 'old'); write(live, 'serve/upstream_removed.py', 'user')
    write(old, 'serve/upstream_removed_kept.py', 'old'); write(live, 'serve/upstream_removed_kept.py', 'old')
    return live, old, new


def actions(plan):
    return {row['path']: row['action'] for row in plan['actions']}


class Planner(unittest.TestCase):
    def test_three_way_decisions_are_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            live, old, new = fixture(folder)
            manifest = build_manifest(live, old, include_diffs=False)
            plan = plan_apply(manifest, live, old, new, prefixes=None)
            got = actions(plan)
            self.assertEqual(got['serve/same.py'], 'take_new')
            self.assertEqual(got['serve/user.py'], 'take_live')
            self.assertEqual(got['serve/both.py'], 'conflict')
            self.assertEqual(got['serve/newonly.py'], 'take_new')
            self.assertEqual(got['serve/useronly.py'], 'take_live')
            self.assertEqual(got['serve/bothadded.py'], 'conflict')
            self.assertEqual(got['serve/gone.py'], 'keep_absent')
            self.assertEqual(got['serve/gone_changed.py'], 'conflict')
            self.assertEqual(got['serve/upstream_removed.py'], 'conflict')
            self.assertEqual(got['serve/upstream_removed_kept.py'], 'keep_absent')
            self.assertFalse(plan['ready'])
            self.assertEqual(len(plan['conflicts']), 4)

    def test_stale_live_or_baseline_blocks_the_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            live, old, new = fixture(folder)
            manifest = build_manifest(live, old, include_diffs=False)
            write(live, 'serve/same.py', 'changed after manifest')
            write(old, 'serve/user.py', 'changed baseline')
            plan = plan_apply(manifest, live, old, new, prefixes=None)
            self.assertFalse(plan['ready'])
            reasons = {(row['path'], row['reason']) for row in plan['stale']}
            self.assertIn(('serve/same.py', 'live_changed'), reasons)
            self.assertIn(('serve/user.py', 'old_baseline_changed'), reasons)

    def test_non_code_conflicts_resolve_with_warnings_but_code_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            live = Path(folder) / 'live'; old = Path(folder) / 'old'; new = Path(folder) / 'new'
            for root in (live, old, new):
                (root / 'serve').mkdir(parents=True)
            write(old, 'docs/changed.md', 'old'); write(live, 'docs/changed.md', 'user'); write(new, 'docs/changed.md', 'upstream')
            write(old, 'docs/deleted.md', 'old'); write(new, 'docs/deleted.md', 'upstream')
            write(old, 'README.md', 'old'); write(live, 'README.md', 'user'); write(new, 'README.md', 'upstream')
            write(old, 'CMakeLists.txt', 'old'); write(live, 'CMakeLists.txt', 'user'); write(new, 'CMakeLists.txt', 'upstream')
            manifest = build_manifest(live, old, include_diffs=False)
            plan = plan_apply(manifest, live, old, new, prefixes=None)
            got = actions(plan)
            self.assertEqual(got['docs/changed.md'], 'take_live')
            self.assertEqual(got['docs/deleted.md'], 'keep_absent')
            self.assertEqual(got['README.md'], 'take_live')
            self.assertEqual(got['CMakeLists.txt'], 'conflict')
            self.assertEqual(sorted(row['path'] for row in plan['warnings']), ['README.md', 'docs/changed.md', 'docs/deleted.md'])
            self.assertEqual(len(plan['conflicts']), 1)
            self.assertFalse(plan['ready'])

    def test_explicit_resolutions_can_clear_code_conflicts(self):
        with tempfile.TemporaryDirectory() as folder:
            live, old, new = fixture(folder)
            manifest = build_manifest(live, old, include_diffs=False)
            plan = plan_apply(manifest, live, old, new, prefixes=None)
            self.assertFalse(plan['ready'])
            resolutions = {row['path']: 'keep_live' for row in plan['conflicts']}
            resolved = plan_apply(manifest, live, old, new, prefixes=None, resolutions=resolutions)
            self.assertTrue(resolved['ready'])
            got = actions(resolved)
            self.assertEqual(got['serve/both.py'], 'take_live')
            self.assertEqual(got['serve/bothadded.py'], 'take_live')
            with self.assertRaises(ValueError):
                plan_apply(manifest, live, old, new, prefixes=None, resolutions={'serve/both.py': 'guess'})

    def test_take_new_resolution_uses_the_upstream_file(self):
        with tempfile.TemporaryDirectory() as folder:
            live, old, new = fixture(folder)
            manifest = build_manifest(live, old, include_diffs=False)
            plan = plan_apply(manifest, live, old, new, prefixes=None)
            resolutions = {row['path']: 'take_new' for row in plan['conflicts']}
            resolved = plan_apply(manifest, live, old, new, prefixes=None, resolutions=resolutions)
            self.assertTrue(resolved['ready'])
            self.assertEqual(actions(resolved)['serve/both.py'], 'take_new')

    def test_scope_filter_excludes_runtime_data(self):
        with tempfile.TemporaryDirectory() as folder:
            live, old, new = fixture(folder)
            write(live, 'data/config.json', 'live'); write(old, 'data/config.json', 'old')
            manifest = build_manifest(live, old, include_diffs=False)
            plan = plan_apply(manifest, live, old, new)
            self.assertNotIn('data/config.json', actions(plan))
            plan = plan_apply(manifest, live, old, new, prefixes=None)
            self.assertIn('data/config.json', actions(plan))


class Materializer(unittest.TestCase):
    def test_candidate_gets_new_baseline_plus_user_files_and_live_is_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            live, old, new = fixture(folder)
            manifest = build_manifest(live, old, include_diffs=False)
            plan = plan_apply(manifest, live, old, new, prefixes=None)
            plan['ready'] = True
            plan['conflicts'] = []
            (Path(folder) / 'candidate').mkdir()
            result = materialize(plan, live, new, Path(folder) / 'candidate2')
            candidate = Path(result['destination'])
            self.assertEqual((candidate / 'serve/user.py').read_text(), 'user')
            self.assertEqual((candidate / 'serve/both.py').read_text(), 'upstream')
            self.assertEqual((candidate / 'serve/same.py').read_text(), 'same')
            self.assertTrue((candidate / 'APPLY-REPORT.json').is_file())
            self.assertEqual((live / 'serve/user.py').read_text(), 'user')
            self.assertEqual(json.loads((candidate / 'APPLY-REPORT.json').read_text())['schema_version'], 1)

    def test_materialize_refuses_a_plan_with_conflicts(self):
        with tempfile.TemporaryDirectory() as folder:
            live, old, new = fixture(folder)
            manifest = build_manifest(live, old, include_diffs=False)
            plan = plan_apply(manifest, live, old, new, prefixes=None)
            with self.assertRaises(ValueError):
                materialize(plan, live, new, Path(folder) / 'candidate')


class Report(unittest.TestCase):
    def test_report_lists_conflicts_with_both_diffs(self):
        with tempfile.TemporaryDirectory() as folder:
            live, old, new = fixture(folder)
            manifest = build_manifest(live, old, include_diffs=False)
            plan = plan_apply(manifest, live, old, new, prefixes=None)
            report = build_report(plan, live, old, new)
            self.assertEqual(report['summary']['conflicts'], len(plan['conflicts']))
            row = next(r for r in report['conflicts'] if r['path'] == 'serve/both.py')
            self.assertIn('-old', row['upstream_diff'])
            self.assertIn('+upstream', row['upstream_diff'])
            self.assertIn('+user', row['user_diff'])
            markdown = render_markdown(report)
            self.assertIn('serve/both.py', markdown)
            self.assertIn('both_changed', markdown)

    def test_report_cli_writes_json_and_markdown(self):
        from tools.mod_report import main
        with tempfile.TemporaryDirectory() as folder:
            live, old, new = fixture(folder)
            manifest = build_manifest(live, old, include_diffs=False)
            manifest_path = Path(folder) / 'manifest.json'; manifest_path.write_text(json.dumps(manifest))
            out = Path(folder) / 'reports'
            code = main(['--manifest', str(manifest_path), '--live', str(live), '--old-baseline', str(old),
                         '--new-baseline', str(new), '--out-dir', str(out), '--scope', 'all'])
            self.assertEqual(code, 0)
            self.assertTrue((out / 'conflicts.json').is_file())
            self.assertTrue((out / 'conflicts.md').is_file())
            self.assertTrue((out / 'resolutions-template.json').is_file())
            template = json.loads((out / 'resolutions-template.json').read_text(encoding='utf-8'))
            self.assertIn('serve/both.py', template)
            self.assertIsNone(template['serve/both.py'])
            self.assertIn('serve/both.py', (out / 'conflicts.md').read_text(encoding='utf-8'))


class CommandLine(unittest.TestCase):
    def build(self, folder):
        live, old, new = fixture(folder)
        manifest = build_manifest(live, old, include_diffs=False)
        manifest_path = Path(folder) / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest))
        return live, old, new, manifest_path

    def test_dry_run_never_writes_and_reports_conflicts(self):
        from tools.mod_apply import main
        with tempfile.TemporaryDirectory() as folder:
            live, old, new, manifest = self.build(folder)
            out = Path(folder) / 'candidate'
            code = main(['--manifest', str(manifest), '--live', str(live), '--old-baseline', str(old),
                         '--new-baseline', str(new), '--out', str(out), '--scope', 'all'])
            self.assertEqual(code, 3)
            self.assertFalse(out.exists())

    def test_resolutions_file_clears_every_conflict_before_materializing(self):
        from tools.mod_apply import main
        with tempfile.TemporaryDirectory() as folder:
            live, old, new = fixture(folder)
            manifest = build_manifest(live, old, include_diffs=False)
            manifest_path = Path(folder) / 'manifest.json'; manifest_path.write_text(json.dumps(manifest))
            plan = plan_apply(manifest, live, old, new, prefixes=None)
            resolutions = Path(folder) / 'resolutions.json'
            resolutions.write_text(json.dumps({row['path']: 'keep_live' for row in plan['conflicts']}))
            out = Path(folder) / 'candidate'
            args = ['--manifest', str(manifest_path), '--live', str(live), '--old-baseline', str(old),
                    '--new-baseline', str(new), '--out', str(out), '--scope', 'all',
                    '--resolutions', str(resolutions)]
            self.assertEqual(main(args), 0)
            self.assertFalse(out.exists())
            self.assertEqual(main(args + ['--materialize']), 0)
            self.assertTrue((out / 'serve/both.py').is_file())

    def test_ready_plan_materializes_only_with_the_flag(self):
        from tools.mod_apply import main
        with tempfile.TemporaryDirectory() as folder:
            live, old, new = fixture(folder)
            # remove the conflict cases by making new match old for the conflicted paths
            for relative in ('serve/both.py', 'serve/bothadded.py', 'serve/gone_changed.py', 'serve/upstream_removed.py'):
                target = new / relative
                if (old / relative).exists():
                    target.write_text((old / relative).read_text())
                else:
                    target.unlink(missing_ok=True)
            (new / 'serve/bothadded.py').unlink(missing_ok=True)
            (new / 'serve/gone_changed.py').unlink(missing_ok=True)
            manifest = build_manifest(live, old, include_diffs=False)
            manifest_path = Path(folder) / 'manifest.json'; manifest_path.write_text(json.dumps(manifest))
            out = Path(folder) / 'candidate'
            args = ['--manifest', str(manifest_path), '--live', str(live), '--old-baseline', str(old),
                    '--new-baseline', str(new), '--out', str(out), '--scope', 'all']
            self.assertEqual(main(args), 0)
            self.assertFalse(out.exists())
            self.assertEqual(main(args + ['--materialize']), 0)
            self.assertTrue((out / 'serve/user.py').is_file())


if __name__ == '__main__':
    unittest.main()

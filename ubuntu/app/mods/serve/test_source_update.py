"""Tests for source_update: activation is reversible and refuses to half-apply."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from serve.source_update import (SourceUpdateError, activate, app_files, plan, restore, rollback,
                                 sha256, snapshot)


def make_tree(root: Path, tag: str) -> None:
    files = {
        "serve/server.py": f"# server {tag}\n",
        "serve/other.py": f"# other {tag}\n",
        "serve/web/index.html": f"<!-- page {tag} -->\n",
        "mods/hooks.py": f"# hooks {tag}\n",
        "tools/tool.py": f"# tool {tag}\n",
        "setup.py": f"# setup {tag}\n",
        "data/keep.txt": "data is never app files\n",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class ActivationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "live"
        self.staging = Path(self.tmp.name) / "staging"
        make_tree(self.root, "old")
        make_tree(self.staging, "new")

    def test_activation_copies_and_keeps_a_snapshot(self):
        report = activate(self.root, self.staging, health=lambda: True)
        self.assertTrue(report["activated"])
        self.assertEqual((self.root / "serve/server.py").read_text(encoding="utf-8"), "# server new\n")
        self.assertTrue(Path(report["snapshot"], "snapshot.json").is_file())
        # data/ is not app files and is untouched
        self.assertEqual((self.root / "data/keep.txt").read_text(encoding="utf-8"), "data is never app files\n")

    def test_a_failed_health_check_restores_the_exact_bytes(self):
        before = {rel: sha256(path) for rel, path in app_files(self.root).items()}
        with self.assertRaises(SourceUpdateError) as caught:
            activate(self.root, self.staging, health=lambda: False)
        self.assertIn("restored the previous tree", str(caught.exception))
        after = {rel: sha256(path) for rel, path in app_files(self.root).items()}
        self.assertEqual(after, before)

    def test_a_health_exception_also_restores(self):
        before = {rel: sha256(path) for rel, path in app_files(self.root).items()}

        def boom():
            raise RuntimeError("dashboard did not answer")

        with self.assertRaises(SourceUpdateError):
            activate(self.root, self.staging, health=boom)
        self.assertEqual({rel: sha256(path) for rel, path in app_files(self.root).items()}, before)

    def test_rollback_restores_and_removes_added_files(self):
        old_hashes = {rel: sha256(path) for rel, path in app_files(self.root).items()}
        with (self.staging / "serve/added.py").open("w", encoding="utf-8") as f:
            f.write("# added by the candidate\n")
        info = activate(self.root, self.staging, health=lambda: True)
        self.assertTrue((self.root / "serve/added.py").is_file())
        rollback(self.root)
        self.assertFalse((self.root / "serve/added.py").exists())
        self.assertEqual({rel: sha256(path) for rel, path in app_files(self.root).items()}, old_hashes)

    def test_changed_staging_files_abort_before_writing(self):
        manifest = {rel: sha256(path) for rel, path in app_files(self.staging).items()}
        (self.staging / "serve/server.py").write_text("# changed after the manifest\n", encoding="utf-8")
        before = {rel: sha256(path) for rel, path in app_files(self.root).items()}
        with self.assertRaises(SourceUpdateError) as caught:
            plan(self.root, self.staging, manifest)
        self.assertIn("changed after the manifest", str(caught.exception))
        self.assertEqual({rel: sha256(path) for rel, path in app_files(self.root).items()}, before)

    def test_an_incomplete_candidate_is_refused(self):
        (self.staging / "mods/hooks.py").unlink()
        with self.assertRaises(SourceUpdateError) as caught:
            plan(self.root, self.staging)
        self.assertIn("mods/hooks.py", str(caught.exception))

    def test_plan_leaves_live_only_files_alone(self):
        (self.root / "serve/live_extra.py").write_text("# a mod the candidate does not carry\n", encoding="utf-8")
        steps = plan(self.root, self.staging)
        self.assertIn("serve/live_extra.py", steps["keep"])
        self.assertFalse((self.staging / "serve/live_extra.py").exists())

    def test_rollback_removes_a_new_package_and_its_cache(self):
        old_hashes = {rel: sha256(path) for rel, path in app_files(self.root).items()}
        added = self.staging / "strata_cli/client.py"
        added.parent.mkdir(parents=True, exist_ok=True)
        added.write_text("# a new package\n", encoding="utf-8")
        activate(self.root, self.staging, health=lambda: True)
        cache = self.root / "strata_cli/__pycache__"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "client.cpython-312.pyc").write_bytes(b"\0")
        rollback(self.root)
        self.assertFalse((self.root / "strata_cli").exists())
        self.assertEqual({rel: sha256(path) for rel, path in app_files(self.root).items()}, old_hashes)

    def test_manifest_superset_aborts(self):
        manifest = {rel: sha256(path) for rel, path in app_files(self.staging).items()}
        (self.staging / "serve/extra.py").write_text("# not in the manifest\n", encoding="utf-8")
        with self.assertRaises(SourceUpdateError) as caught:
            plan(self.root, self.staging, manifest)
        self.assertIn("does not cover", str(caught.exception))

    def test_rollback_skips_a_snapshot_without_manifest(self):
        old_hashes = {rel: sha256(path) for rel, path in app_files(self.root).items()}
        activate(self.root, self.staging, health=lambda: True)
        base = self.root / "data/source-snapshots"
        broken = base / "99999999-000000"
        broken.mkdir(parents=True)
        (broken / "files").mkdir()
        rollback(self.root)                      # must use the newest *usable* snapshot
        self.assertEqual({rel: sha256(path) for rel, path in app_files(self.root).items()}, old_hashes)

    def test_the_overlay_source_is_the_running_copy(self):
        here = Path(__file__).resolve().parent
        # repo layout: mods/serve/*.py is the overlay, serve/*.py the running copy. The
        # same test file is copied to serve/ at build time, so accept either side.
        if here.parent.name == "mods":
            overlay, running = here, here.parent.parent / "serve"
        elif (here.parent / "mods" / "serve").is_dir():
            overlay, running = here.parent / "mods" / "serve", here
        else:
            self.skipTest("not the repository tree")
        if not running.is_dir():
            self.skipTest("no running tree beside the overlay")
        drifted = sorted(p.name for p in overlay.glob("*.py")
                         if not (running / p.name).is_file()
                         or (running / p.name).read_bytes() != p.read_bytes())
        self.assertEqual(drifted, [], "mods/serve must be the running copy: sync these files")

    def test_restore_refuses_a_snapshot_from_another_root(self):
        snap = snapshot(self.root, ["serve/server.py"], [])
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        with self.assertRaises(SourceUpdateError) as caught:
            restore(other, snap)
        self.assertIn("snapshot was taken from", str(caught.exception))

    def test_restore_refuses_a_manifest_key_outside_the_root(self):
        snap = snapshot(self.root, ["serve/server.py"], [])
        (snap / "outside.txt").write_text("# inside the snapshot, outside the root\n", encoding="utf-8")
        manifest = json.loads((snap / "snapshot.json").read_text(encoding="utf-8"))
        manifest["files"]["../outside.txt"] = {"sha256": "0" * 64, "size": 0}
        (snap / "snapshot.json").write_text(json.dumps(manifest), encoding="utf-8")
        outside = self.root.parent / "outside.txt"
        outside.write_text("untouched\n", encoding="utf-8")
        self.addCleanup(outside.unlink)
        with self.assertRaises(SourceUpdateError) as caught:
            restore(self.root, snap)
        self.assertIn("escapes the root", str(caught.exception))
        self.assertEqual(outside.read_text(encoding="utf-8"), "untouched\n")

    def test_snapshot_is_unique_per_activation(self):
        first = snapshot(self.root, ["serve/server.py"], [])
        second = snapshot(self.root, ["serve/server.py"], [])
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_dir() and second.is_dir())


if __name__ == "__main__":
    unittest.main()

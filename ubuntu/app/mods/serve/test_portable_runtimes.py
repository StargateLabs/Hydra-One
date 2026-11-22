"""Portable runtime candidate: isolated extraction, validation, pointer selection and rollback."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from serve.portable_runtimes import (
    environment,
    rollback,
    select,
    selected,
    stage,
    validate,
)


def node_archive(path: Path, version: str = "26.0.0") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        root = f"node-v{version}-win-x64"
        archive.writestr(root + "/node.exe", b"fixture node")
        archive.writestr(root + "/node_modules/npm/bin/npm-cli.js", b"fixture npm")
    return path


class PortableRuntimeTests(unittest.TestCase):
    def test_stage_validate_select_and_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = node_archive(root / "node.zip")
            candidate = stage(root, "node", "26.0.0", archive)
            self.assertEqual(candidate.binary.name, "node.exe")
            self.assertTrue((candidate.root / "CANDIDATE-MANIFEST.json").is_file())
            with patch("serve.portable_runtimes.subprocess.run",
                       return_value=SimpleNamespace(returncode=0, stdout="v26.0.0\n", stderr="")):
                report = validate(root, candidate)
            self.assertTrue(report["validated"])
            entry = select(root, "node", "26.0.0")
            self.assertEqual(entry["version"], "26.0.0")
            self.assertEqual(selected(root, "node")["version"], "26.0.0")
            self.assertTrue(environment(root, "node")["PATH"].startswith(str(candidate.binary.parent)))
            rollback(root, "node")
            self.assertIsNone(selected(root, "node"))

    def test_zip_slip_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "evil.zip"
            with zipfile.ZipFile(archive, "w") as source:
                source.writestr("../evil.txt", b"no")
            with self.assertRaises(ValueError):
                stage(root, "node", "26.0.0", archive)
            self.assertFalse((root / "output/updates/runtimes/node/26.0.0").exists())

    def test_checksum_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = node_archive(root / "node.zip")
            with self.assertRaises(ValueError):
                stage(root, "node", "26.0.0", archive, checksum="0" * 64)

    def test_tampered_candidate_is_not_selected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = node_archive(root / "node.zip")
            candidate = stage(root, "node", "26.0.0", archive)
            with patch("serve.portable_runtimes.subprocess.run",
                       return_value=SimpleNamespace(returncode=0, stdout="v26.0.0\n", stderr="")):
                validate(root, candidate)
            select(root, "node", "26.0.0")
            candidate.binary.write_bytes(b"changed")
            self.assertIsNone(selected(root, "node"))

    def test_validate_requires_the_candidate_to_be_intact(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = node_archive(root / "node.zip")
            candidate = stage(root, "node", "26.0.0", archive)
            candidate.binary.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                validate(root, candidate)

    def test_selection_requires_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = node_archive(root / "node.zip")
            stage(root, "node", "26.0.0", archive)
            with self.assertRaises(ValueError):
                select(root, "node", "26.0.0")


if __name__ == "__main__":
    unittest.main()

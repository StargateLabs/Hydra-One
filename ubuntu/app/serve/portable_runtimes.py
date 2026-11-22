"""Side-by-side runtimes for apps that need a newer Node/npm than the system provides.

A portable runtime is extracted under ``output/updates/runtimes/<name>/<version>``,
validated, and selected through ``data/portable-runtimes.json``.  The system
runtime is never replaced; ``environment()`` returns a PATH prefix for one child
process only, and rollback switches the pointer back to the previous candidate.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from serve.configuration import atomic_json

MAX_FILES = 20000
MAX_BYTES = 2 * 1024 ** 3
MAX_DOWNLOAD = 512 * 1024 ** 2
REGISTRY = Path("data") / "portable-runtimes.json"


class RuntimeError_(RuntimeError):
    """A portable runtime candidate is missing, unsafe or changed."""


@dataclass(frozen=True)
class RuntimeCandidate:
    name: str
    version: str
    root: Path
    binary: Path
    npm: Path | None
    files: tuple[tuple[str, str, int], ...]
    archive_sha256: str


def _safe_name(value: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", text):
        raise ValueError(f"invalid runtime name or version: {value!r}")
    return text


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member(name: str) -> tuple[str, ...]:
    text = str(name or "").replace("\\", "/")
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise ValueError(f"archive member is absolute: {name!r}")
    parts = tuple(part for part in PurePosixPath(text).parts if part not in ("", "."))
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"archive member escapes its root: {name!r}")
    return parts


def _extract_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        if len(members) > MAX_FILES:
            raise ValueError("archive has too many files")
        total = 0
        for info in members:
            parts = _safe_member(info.filename)
            target = destination.joinpath(*parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"archive contains a symlink: {info.filename!r}")
            total += info.file_size
            if total > MAX_BYTES:
                raise ValueError("archive expands beyond the runtime limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as stream, target.open("wb") as output:
                shutil.copyfileobj(stream, output, 1 << 20)
            if (info.external_attr >> 16) & 0o111:
                target.chmod(0o755)


def _extract_tar(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:*") as source:
        members = source.getmembers()
        if len(members) > MAX_FILES:
            raise ValueError("archive has too many files")
        total = 0
        for info in members:
            parts = _safe_member(info.name)
            target = destination.joinpath(*parts)
            if info.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not info.isfile():
                raise ValueError(f"archive contains a non-regular entry: {info.name!r}")
            total += info.size
            if total > MAX_BYTES:
                raise ValueError("archive expands beyond the runtime limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = source.extractfile(info)
            if stream is None:
                raise ValueError(f"archive entry is unreadable: {info.name!r}")
            with stream, target.open("wb") as output:
                shutil.copyfileobj(stream, output, 1 << 20)
            if info.mode & 0o111:
                target.chmod(0o755)


def _manifest(root: Path) -> tuple[tuple[str, str, int], ...]:
    rows = []
    total = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if path.name == "CANDIDATE-MANIFEST.json":
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        total += size
        if len(rows) >= MAX_FILES or total > MAX_BYTES:
            raise ValueError("runtime candidate exceeds the size limit")
        rows.append((relative, _sha256(path), size))
    return tuple(rows)


def _find_binary(root: Path, name: str) -> tuple[Path, Path | None]:
    binary_name = "node.exe" if name == "node" and os.name == "nt" else name
    matches = [path for path in root.rglob(binary_name) if path.is_file()]
    if len(matches) != 1:
        raise RuntimeError_("candidate must contain exactly one " + binary_name)
    binary = matches[0]
    npm = None
    if name == "node":
        npm_matches = [path for path in root.rglob("npm-cli.js") if path.is_file()]
        if len(npm_matches) != 1:
            raise RuntimeError_("candidate must contain exactly one npm-cli.js")
        npm = npm_matches[0]
    return binary, npm


def stage(root, name: str, version: str, archive, checksum: str | None = None) -> RuntimeCandidate:
    """Extract a downloaded archive into an isolated, hash-recorded candidate."""
    root = Path(root).resolve()
    name, version = _safe_name(name), _safe_name(version)
    archive = Path(archive).resolve()
    if not archive.is_file():
        raise ValueError("runtime archive is missing")
    if archive.stat().st_size > MAX_DOWNLOAD:
        raise ValueError("runtime archive exceeds the download limit")
    digest = _sha256(archive)
    if checksum and digest != str(checksum).lower():
        raise ValueError("runtime archive SHA-256 mismatch")
    destination = (root / "output/updates/runtimes" / name / version).resolve()
    if not _inside(root / "output/updates/runtimes", destination):
        raise ValueError("runtime destination is outside the update folder")
    if shutil.disk_usage(destination.parent if destination.parent.exists() else root).free < 256 * 1024 ** 2:
        raise ValueError("keep 256 MiB free for a portable runtime")
    if destination.exists():
        manifest_path = destination / "CANDIDATE-MANIFEST.json"
        if not manifest_path.is_file():
            raise ValueError("runtime candidate exists without a manifest")
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        if saved.get("archive_sha256") != digest or saved.get("version") != version:
            raise ValueError("existing runtime candidate is from another archive")
        for relative, sha, size in saved.get("files", []):
            path = (destination / relative).resolve()
            if not _inside(destination, path) or not path.is_file() or path.stat().st_size != size or _sha256(path) != sha:
                raise ValueError("existing runtime candidate has changed")
        binary, npm = _find_binary(destination, name)
        return RuntimeCandidate(name, version, destination, binary, npm,
                                tuple((r["path"], r["sha256"], r["bytes"]) for r in saved["files"]), digest)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        if zipfile.is_zipfile(archive):
            _extract_zip(archive, destination)
        elif tarfile.is_tarfile(archive):
            _extract_tar(archive, destination)
        else:
            raise ValueError("runtime archive must be ZIP or tar.gz")
        binary, npm = _find_binary(destination, name)
        files = _manifest(destination)
        manifest = {"name": name, "version": version, "archive_sha256": digest,
                    "binary": binary.relative_to(destination).as_posix(),
                    "npm": npm.relative_to(destination).as_posix() if npm else None,
                    "files": [{"path": r, "sha256": s, "bytes": b} for r, s, b in files],
                    "staged_at": time.time()}
        atomic_json(destination / "CANDIDATE-MANIFEST.json", manifest)
        return RuntimeCandidate(name, version, destination, binary, npm, files, digest)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _candidate_from_root(root: Path, name: str, version: str) -> RuntimeCandidate:
    destination = (Path(root).resolve() / "output/updates/runtimes" / _safe_name(name) / _safe_name(version)).resolve()
    manifest_path = destination / "CANDIDATE-MANIFEST.json"
    if not manifest_path.is_file():
        raise RuntimeError_("runtime candidate has no manifest")
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = tuple((row["path"], row["sha256"], row["bytes"]) for row in saved.get("files", []))
    binary = destination / saved["binary"]
    npm = destination / saved["npm"] if saved.get("npm") else None
    return RuntimeCandidate(_safe_name(name), _safe_name(version), destination, binary, npm, files,
                            saved["archive_sha256"])


def validate(root, candidate: RuntimeCandidate) -> dict:
    """Run the candidate's own ``--version`` checks; never touches the system runtime."""
    root = Path(root).resolve()
    if not _inside(root / "output/updates/runtimes", candidate.root):
        raise ValueError("runtime candidate is outside the update folder")
    for relative, sha, size in candidate.files:
        path = (candidate.root / relative).resolve()
        if not _inside(candidate.root, path) or not path.is_file() or path.stat().st_size != size or _sha256(path) != sha:
            raise ValueError("runtime candidate files have changed")
    if not candidate.binary.is_file():
        raise ValueError("runtime binary is missing")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    node = subprocess.run([str(candidate.binary), "--version"], capture_output=True, text=True,
                          timeout=20, creationflags=flags)
    if node.returncode or not (node.stdout or "").strip():
        raise ValueError("runtime version check failed: " + (node.stderr or node.stdout or "")[:400])
    result = {"validated": True, "name": candidate.name, "version": candidate.version,
              "node": (node.stdout or "").strip(), "validated_at": time.time()}
    if candidate.npm is not None:
        npm = subprocess.run([str(candidate.binary), str(candidate.npm), "--version"], capture_output=True,
                             text=True, timeout=20, creationflags=flags)
        if npm.returncode or not (npm.stdout or "").strip():
            raise ValueError("npm version check failed: " + (npm.stderr or npm.stdout or "")[:400])
        result["npm"] = (npm.stdout or "").strip()
    atomic_json(candidate.root / "VALIDATED.json", result)
    return result


def node_archive_name(version: str, platform: str | None = None) -> str:
    platform = platform or ("win32" if os.name == "nt" else "linux" if sys.platform.startswith("linux") else "darwin")
    version = _safe_name(version)
    if platform == "win32":
        return f"node-v{version}-win-x64.zip"
    if platform == "linux":
        return f"node-v{version}-linux-x64.tar.xz"
    if platform == "darwin":
        return f"node-v{version}-darwin-x64.tar.gz"
    raise ValueError(f"unsupported portable Node platform: {platform}")


def fetch_node(root, version: str, platform: str | None = None, opener=None) -> RuntimeCandidate:
    """Download an official Node archive and extract it as an isolated candidate."""
    version = _safe_name(version)
    name = node_archive_name(version, platform)
    opener = opener or urllib.request.urlopen
    base = f"https://nodejs.org/dist/v{version}"
    with opener(base + "/SHASUMS256.txt", timeout=30) as response:
        raw = response.read(2 * 1024 * 1024).decode("utf-8", "replace")
    checksum = next((match.group(1) for line in raw.splitlines()
                     if (match := re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+)$", line.strip()))
                     and match.group(2).strip() == name), None)
    if not checksum:
        raise ValueError(f"official SHASUMS256.txt does not list {name}")
    folder = Path(root).resolve() / "output/updates/downloads"
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / name
    digest = hashlib.sha256()
    total = 0
    with opener(base + "/" + name, timeout=60) as response, archive.open("wb") as output:
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            total += len(block)
            if total > MAX_DOWNLOAD:
                archive.unlink(missing_ok=True)
                raise ValueError("Node archive exceeds the download limit")
            digest.update(block)
            output.write(block)
    if digest.hexdigest().lower() != checksum.lower():
        archive.unlink(missing_ok=True)
        raise ValueError("Node archive SHA-256 mismatch")
    return stage(root, "node", version, archive, checksum=checksum)


def install_node(root, version: str, platform: str | None = None) -> dict:
    """Fetch, validate and select Node side by side; the system Node is untouched."""
    candidate = fetch_node(root, version, platform=platform)
    report = validate(root, candidate)
    entry = select(root, "node", version)
    return {"candidate": str(candidate.root), "validation": report, "selection": entry}


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Manage side-by-side portable runtimes")
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install")
    install.add_argument("name", choices=("node",))
    install.add_argument("version")
    install.add_argument("--platform")
    rollback_parser = sub.add_parser("rollback")
    rollback_parser.add_argument("name", choices=("node",))
    sub.add_parser("list")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    if args.command == "install":
        installed = install_node(root, args.version, platform=args.platform)
        selection = installed.get("selection") or {}
        result = {"candidate": installed.get("candidate"),
                  "validation": installed.get("validation"),
                  "selection": {key: selection.get(key) for key in ("name", "version", "binary", "npm", "activated_at")}}
    elif args.command == "rollback":
        result = rollback(root, args.name)
    else:
        result = {"selected": {name: selected(root, name) for name in ("node",)},
                  "registry": _registry(root)}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _registry(root: Path) -> dict:
    path = Path(root) / REGISTRY
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def selected(root, name: str) -> dict | None:
    """The validated active selection for ``name``, or None when absent/changed."""
    root = Path(root).resolve()
    name = _safe_name(name)
    active = (_registry(root).get("active") or {}).get(name)
    if not isinstance(active, dict):
        return None
    try:
        candidate = _candidate_from_root(root, name, active["version"])
        if not _inside(root / "output/updates/runtimes", candidate.root):
            return None
        if Path(active["binary"]).resolve() != candidate.binary.resolve():
            return None
        for relative, sha, size in candidate.files:
            path = (candidate.root / relative).resolve()
            if not _inside(candidate.root, path) or not path.is_file() or path.stat().st_size != size or _sha256(path) != sha:
                return None
        if not (candidate.root / "VALIDATED.json").is_file():
            return None
        return dict(active)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError_):
        return None


def select(root, name: str, version: str) -> dict:
    """Point one app at a validated candidate; keep the previous selection for rollback."""
    root = Path(root).resolve()
    name, version = _safe_name(name), _safe_name(version)
    candidate = _candidate_from_root(root, name, version)
    if not _inside(root / "output/updates/runtimes", candidate.root):
        raise ValueError("runtime candidate is outside the update folder")
    if not (candidate.root / "VALIDATED.json").is_file():
        raise ValueError("validate the portable runtime before selecting it")
    for relative, sha, size in candidate.files:
        path = (candidate.root / relative).resolve()
        if not _inside(candidate.root, path) or not path.is_file() or path.stat().st_size != size or _sha256(path) != sha:
            raise ValueError("validated runtime candidate has changed")
    registry = _registry(root)
    previous = dict(registry.get("active") or {})
    entry = {"name": name, "version": version, "candidate": str(candidate.root),
             "binary": str(candidate.binary), "npm": str(candidate.npm) if candidate.npm else None,
             "files": [{"path": r, "sha256": s, "bytes": b} for r, s, b in candidate.files],
             "archive_sha256": candidate.archive_sha256, "activated_at": time.time()}
    registry["active"] = {**previous, name: entry}
    registry["previous"] = {**(registry.get("previous") or {}), name: previous.get(name)}
    (root / "data").mkdir(parents=True, exist_ok=True)
    atomic_json(root / REGISTRY, registry)
    return entry


def rollback(root, name: str) -> dict:
    """Switch the pointer back to the previous portable runtime."""
    root = Path(root).resolve()
    name = _safe_name(name)
    registry = _registry(root)
    active = dict(registry.get("active") or {})
    previous = dict(registry.get("previous") or {})
    if name not in previous:
        raise ValueError("no previous portable runtime to restore")
    active[name], previous[name] = previous[name], active.get(name)
    registry["active"] = active
    registry["previous"] = previous
    registry["rolled_back_at"] = time.time()
    (root / "data").mkdir(parents=True, exist_ok=True)
    atomic_json(root / REGISTRY, registry)
    return (registry.get("active") or {}).get(name) or {}


def environment(root, name: str) -> dict:
    """Environment overrides for one child process; empty when no candidate is selected."""
    active = selected(root, name)
    if not active:
        return {}
    binary = Path(active["binary"])
    path = str(binary.parent)
    return {"PATH": path + os.pathsep + os.environ.get("PATH", ""),
            "NODE_HOME": str(binary.parent),
            "NODE_PATH": str(binary.parent / "node_modules"),
            "PORTABLE_RUNTIME": str(binary.parent)}


if __name__ == "__main__":
    raise SystemExit(main())

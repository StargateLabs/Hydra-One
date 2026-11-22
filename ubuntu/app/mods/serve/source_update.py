"""Activate a staged app tree on the live root: snapshot, copy, verify, roll back.

The app is the files under `serve/`, `tools/`, `tests/`, `mods/` plus the root
scripts. The engine (`engine/`), models, `data/` and `output/` are never touched:
the engine stays the validated 0.1.44.1.

Every activation writes `data/source-snapshots/<stamp>/` first: the previous bytes
of every file it overwrites, and the list of files it adds. A failed health check
restores that snapshot byte for byte and removes the added files, so a refused
activation leaves the previous tree. `rollback()` does the same on demand.

    python -m serve.source_update activate --root . --staging <tree> --config strata-iq3_s.json
    python -m serve.source_update rollback --root . [--snapshot <dir>]
    python -m serve.source_update status --root .

No file outside `root` is written, and staging is only read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

APP_DIRS = ("serve", "tools", "tests", "mods", "strata_control", "strata_cli")
APP_FILES = ("setup.py", "setup.sh", "START-HERE.bat", "UPDATE.bat", "update.sh", "requirements.txt")
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache"}
SNAPSHOT_DIR = Path("data") / "source-snapshots"
SNAPSHOT_KEEP = 8                 # newest activations kept; older ones are pruned
# the files a candidate may not omit: without them the tree is not this app
REQUIRED = ("serve/server.py", "mods/hooks.py", "serve/web/index.html")


class SourceUpdateError(RuntimeError):
    """The activation was refused or undone; the message says why."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def app_files(root: Path) -> dict[str, Path]:
    """Every app file under root, keyed by its relative POSIX path."""
    root = Path(root)
    out: dict[str, Path] = {}
    for name in APP_DIRS:
        base = root / name
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for filename in filenames:
                if filename.endswith(".pyc"):
                    continue
                path = Path(dirpath) / filename
                out[path.relative_to(root).as_posix()] = path
    for name in APP_FILES:
        path = root / name
        if path.is_file():
            out[name] = path
    return out


def plan(root: Path, staging: Path, expect: dict | None = None) -> dict:
    """What activation would do: the staging files, their hashes, and what they replace."""
    root, staging = Path(root), Path(staging)
    if not staging.is_dir():
        raise SourceUpdateError(f"staging tree not found: {staging}")
    candidate = app_files(staging)
    missing = [name for name in REQUIRED if name not in candidate]
    if missing:
        raise SourceUpdateError(f"staging is not a complete app tree: missing {', '.join(missing)}")
    hashes = {rel: sha256(path) for rel, path in candidate.items()}
    if expect is not None:
        # `tools/port_mods.py` writes the flat map; `staging-overlay.json` carries it
        # under "manifest": accept the artifact the build itself produced
        if isinstance(expect, dict) and isinstance(expect.get("manifest"), dict):
            expect = expect["manifest"]
        changed = [rel for rel, digest in expect.items() if hashes.get(rel) != digest]
        if changed:
            raise SourceUpdateError("the staged files changed after the manifest: " + ", ".join(sorted(changed)[:10]))
        extra = sorted(set(hashes) - set(expect))
        if extra:
            raise SourceUpdateError("the staging tree has files the manifest does not cover: "
                                    + ", ".join(extra[:10]))
    current = app_files(root)
    return {
        "staging": str(staging),
        "root": str(root),
        "files": len(hashes),
        "hashes": hashes,
        "overwrite": sorted(set(hashes) & set(current)),
        "add": sorted(set(hashes) - set(current)),
        "keep": sorted(set(current) - set(hashes)),      # live files the candidate does not have
    }


def snapshot(root: Path, files: list[str], added: list[str]) -> Path:
    """Store the previous bytes of `files` and record the `added` names."""
    root = Path(root)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = root / SNAPSHOT_DIR / stamp
    n = 1
    while dest.exists():
        n += 1
        dest = root / SNAPSHOT_DIR / f"{stamp}-{n}"
    dest.mkdir(parents=True)
    manifest = {"created": time.time(), "root": str(root), "files": {}, "added": added}
    for rel in files:
        source = root / rel
        target = dest / "files" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest["files"][rel] = {"sha256": sha256(source), "size": source.stat().st_size}
    (dest / "snapshot.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _prune_snapshots(root)
    return dest


def _prune_snapshots(root: Path) -> None:
    """Keep the newest `SNAPSHOT_KEEP` activations: the snapshots are the whole overwritten
    tree, so a long update history would quietly cost hundreds of MB."""
    try:
        dirs = sorted((p for p in (root / SNAPSHOT_DIR).iterdir()
                       if p.is_dir() and (p / "snapshot.json").is_file()),
                      key=lambda p: (p / "snapshot.json").stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in dirs[SNAPSHOT_KEEP:]:
        shutil.rmtree(old, ignore_errors=True)


def _target_inside(root: Path, rel: str) -> Path:
    """The file a manifest key names, guaranteed inside `root`.

    A snapshot is data: a corrupted or hand-edited `snapshot.json` must not be able to
    overwrite (or unlink) a file outside the root, so absolute paths, `..` segments and
    symlinks that redirect the write elsewhere are all refused before anything is joined.
    """
    text = str(rel)
    pure = Path(text)
    if not text or pure.is_absolute() or pure.drive or pure.anchor:
        raise SourceUpdateError(f"snapshot key is not a relative path: {rel!r}")
    if any(part in ("", ".", "..") for part in text.replace("\\", "/").split("/")):
        raise SourceUpdateError(f"snapshot key escapes the root: {rel!r}")
    target = root / text
    if target.is_symlink():
        raise SourceUpdateError(f"snapshot key names a symlink: {rel!r}")
    resolved = target.resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise SourceUpdateError(f"snapshot key escapes the root: {rel!r}")
    return target


def restore(root: Path, snap: Path) -> dict:
    """Put the snapshot back byte for byte, and remove the files it says were added."""
    root, snap = Path(root).resolve(), Path(snap).resolve()
    manifest = json.loads((snap / "snapshot.json").read_text(encoding="utf-8"))
    recorded = manifest.get("root")
    if recorded and Path(recorded).resolve() != root:
        raise SourceUpdateError(f"the snapshot was taken from {recorded}, not {root}; "
                                "a rollback must restore the tree it came from")
    restored, removed, wrong = 0, 0, []
    for rel, info in manifest["files"].items():
        source = snap / "files" / rel
        if not source.is_file():
            raise SourceUpdateError(f"snapshot is incomplete: {rel}")
        target = _target_inside(root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if sha256(target) != info["sha256"]:
            wrong.append(rel)
        restored += 1
    for rel in manifest.get("added", []):
        target = _target_inside(root, rel)
        if target.is_file():
            target.unlink()
            removed += 1
        parent = target.parent
        while parent != root and parent.is_dir():
            # generated caches of the removed files go too; a directory with real files stays
            for cache in list(parent.rglob("__pycache__")):
                shutil.rmtree(cache, ignore_errors=True)
            if any(parent.iterdir()):
                break
            parent.rmdir()
            parent = parent.parent
    if wrong:
        raise SourceUpdateError("the rollback did not reproduce the snapshot: " + ", ".join(wrong[:10]))
    return {"snapshot": str(snap), "restored": restored, "removed": removed}


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # write beside the target, then replace: a half-written server.py never exists.
    # A unique suffix keeps two activations from colliding, and the finally removes
    # an interrupted copy so it can never be taken for an app file later.
    tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.source-update-tmp")
    try:
        shutil.copy2(source, tmp)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def activate(root: Path, staging: Path, *, health, expect: dict | None = None,
             keep_snapshot: bool = True) -> dict:
    """Copy the staged app onto root; call `health()`; undo everything if it fails."""
    root, staging = Path(root), Path(staging)
    if root.resolve() == staging.resolve():
        raise SourceUpdateError("root and staging are the same tree")
    if not callable(health):
        raise SourceUpdateError("activate() needs a health check: activation is not declared without one")
    steps = plan(root, staging, expect)
    snap = snapshot(root, steps["overwrite"], steps["add"])
    copied = 0
    try:
        for rel in steps["hashes"]:
            _copy_file(staging / rel, root / rel)
            copied += 1
        wrong = [rel for rel, digest in steps["hashes"].items() if sha256(root / rel) != digest]
        if wrong:
            raise SourceUpdateError("copied files do not match staging: " + ", ".join(wrong[:10]))
        result = health()
        if not result:
            raise SourceUpdateError(f"the health check failed: {result!r}")
    except BaseException as error:
        report = restore(root, snap)
        if not keep_snapshot:
            shutil.rmtree(snap, ignore_errors=True)
        raise SourceUpdateError(f"{error}; restored the previous tree "
                                f"({report['restored']} files, {report['removed']} removed)") from error
    return {
        "activated": True,
        "files": copied,
        "added": len(steps["add"]),
        "kept": len(steps["keep"]),
        "snapshot": str(snap),
        "health": True,
    }


def rollback(root: Path, snap: Path | None = None) -> dict:
    """Undo the newest usable activation (or the one named by `snap`)."""
    root = Path(root)
    if snap is None:
        base = root / SNAPSHOT_DIR
        candidates = sorted((p for p in base.iterdir() if p.is_dir() and (p / "snapshot.json").is_file()),
                            key=lambda p: p.stat().st_mtime) if base.is_dir() else []
        if not candidates:
            raise SourceUpdateError("no snapshot to roll back to")
        snap = candidates[-1]
    snap = Path(snap)
    if not (snap / "snapshot.json").is_file():
        raise SourceUpdateError(f"not a snapshot: {snap}")
    return restore(root, snap)


def health_over_http(url: str, timeout: float = 60.0, proc=None) -> bool:
    """Poll `url` until it answers 200 with status ok (the activated server starts in a moment).

    `proc` (the child we spawned) is checked on every poll: a dead child cannot be
    rescued by whatever else happens to listen on the port.
    """
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            print(f"[source-update] the health-check server exited with {proc.returncode}", file=sys.stderr)
            return False
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                body = json.loads(response.read() or b"{}")
                if response.status == 200 and body.get("status") == "ok":
                    return True
                last = body
        except (OSError, ValueError) as error:
            last = error
        time.sleep(1)
    print(f"[source-update] health check gave up: {last!r}", file=sys.stderr)
    return False


def port_is_free(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def start_and_check(root: Path, config: str, port: int, timeout: float = 90.0) -> bool:
    """Start the activated app lazily and check /health, then stop it again."""
    root = Path(root)
    if not port_is_free(port):
        print(f"[source-update] port {port} is already in use; refusing to treat a foreign answer as health",
              file=sys.stderr)
        return False
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    # the dashboard guard is root-scoped: a second server for the same root would be
    # refused as "another dashboard"; this flag skips only that claim
    env["STRATA_SOURCE_UPDATE_CHECK"] = "1"
    cmd = [sys.executable, "-m", "serve.server", "--engine", "strata", "--config", config,
           "--port", str(port), "--lazy"]
    log = tempfile.NamedTemporaryFile(prefix="source-update-", suffix=".log", delete=False)
    log_path = Path(log.name)
    proc = subprocess.Popen(cmd, cwd=str(root), env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        ok = health_over_http(f"http://127.0.0.1:{port}/health", timeout, proc)
        if not ok:
            log.close()
            tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
            print("[source-update] server log:\n" + "\n".join(tail), file=sys.stderr)
        return ok
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        log.close()
        try:
            log_path.unlink(missing_ok=True)
        except OSError:
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Activate a staged Strata app tree, or roll it back")
    sub = parser.add_subparsers(dest="command", required=True)
    act = sub.add_parser("activate")
    act.add_argument("--root", default=".")
    act.add_argument("--staging", required=True)
    act.add_argument("--config", required=True, help="the run config the health check starts the app with")
    act.add_argument("--port", type=int, default=8099)
    act.add_argument("--manifest", help="JSON {relative path: sha256} the staging tree must match")
    act.add_argument("--dry-run", action="store_true")
    rb = sub.add_parser("rollback")
    rb.add_argument("--root", default=".")
    rb.add_argument("--snapshot")
    st = sub.add_parser("status")
    st.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    try:
        if args.command == "activate":
            expect = json.loads(Path(args.manifest).read_text(encoding="utf-8")) if args.manifest else None
            steps = plan(root, Path(args.staging).resolve(), expect)
            if args.dry_run:
                print(json.dumps({k: v for k, v in steps.items() if k != "hashes"}, indent=2))
                return 0
            report = activate(root, Path(args.staging).resolve(),
                              health=lambda: start_and_check(root, args.config, args.port), expect=expect)
            print(json.dumps(report, indent=2))
            return 0
        if args.command == "rollback":
            print(json.dumps(rollback(root, Path(args.snapshot) if args.snapshot else None), indent=2))
            return 0
        base = root / SNAPSHOT_DIR
        snaps = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime) if base.is_dir() else []
        print(json.dumps({"root": str(root), "snapshots": [str(p) for p in snaps]}, indent=2))
        return 0
    except SourceUpdateError as error:
        print(f"[source-update] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

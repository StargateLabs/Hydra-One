"""Build a Strata app tree from an upstream release plus the mods overlay.

    python tools/port_mods.py --upstream output/updates/baselines/Niko1221-Strata-v0.2.9 \
        --live . --staging output/updates/port-0.2.9/staging [--test]

The tool owns the mechanical part of a port (ADR-0001):
1. check the overlay contract: every custom route block of the live `serve/server.py`
   is still in `mods/hooks.py`, and every module in `mods/serve/` is present;
2. copy the upstream app files and the upstream-only modules the target imports;
3. apply the documented patches to upstream files (server footer + CLI, frontend
   message preparation, MCP result status, telemetry) and add our new modules;
4. optionally run the upstream baseline suite, the staged server suite and the overlay
   suite, then write a candidate manifest.

A missing overlay file, a hook whose body no longer matches, or a suite failure
aborts with the file and the reason. The live tree is only read.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from serve.source_update import app_files

ROOT = Path(__file__).resolve().parents[1]
MODS = ROOT / "mods"
# The port starts from the live app tree (it keeps the live line's tools, tests and
# resources) and overwrites the upstream-owned files below. These paths are not part of
# the app to carry: the overlay source (copied to serve/ separately) and vendored tools.
EXCLUDE_PREFIXES = ("mods/serve/", "mods/tests/", "tools/graphify/", "tools/local-generative-audio/")
EXCLUDE_FILES = {"tools/port_mods.py", "tools/test_port_mods.py"}

SHARED = [
    "serve/server.py", "serve/frontend.py", "serve/mcp.py", "serve/structured.py",
    "serve/telemetry.py", "serve/winjob.py",
    "serve/test_detok.py", "serve/test_frontend.py", "serve/test_lifecycle.py", "serve/test_mcp.py",
    "serve/test_monitor.py",
    "serve/test_security.py", "serve/test_server.py", "serve/test_structured.py", "serve/test_winjob.py",
    "tools/strata_tokenizer.py", "tools/make_profile.py",
]

# the upstream-only modules `serve/server.py` and the release's tests import: the live
# overlay replaces the rest of serve/ (405 modules), so this is the whole 0.2.9 surface
# the port keeps from upstream
CLOSURE = """
serve/cache_drop.py serve/cpu_affinity.py serve/ds_pictures.py serve/dsml.py serve/images.py
serve/keepawake.py serve/launch_identity.py serve/lifeline.py serve/loader_diag.py serve/logit_bias.py
serve/mcp_fake_server.py
serve/owner_guard.py serve/prometheus.py serve/ready.py serve/replicas.py serve/responses.py
serve/runconfig.py serve/session_save_retry.py serve/split.py serve/webfiles.py
strata_control/__init__.py strata_control/acquisition.py strata_control/atomic.py
strata_control/draft_layer.py strata_control/drafting.py strata_control/engine_component.py
strata_control/gpu_fit.py strata_control/gpu_roles.py strata_control/hipblaslt_tuning.py
strata_control/longpath.py strata_control/offline.py strata_control/paths.py strata_control/presets.py
strata_control/private_files.py strata_control/procs.py strata_control/profiles.py
strata_control/replica_profile.py strata_control/signing.py strata_control/targets.py
strata_control/tls.py strata_control/tune_history.py strata_control/tune_knobs.py
strata_control/tune_machine.py strata_control/user_args.py strata_control/vision_reader.py
strata_control/winproc.py
strata_cli/__init__.py strata_cli/client.py
tools/web_i18n.py tools/test_strata_tokenizer.py
""".split()
# the live-line test suite creates its temp trees under these (present in a live checkout)
SCRATCH_DIRS = ("output", "output/verification", "tmp")

MC_NATIVE = '''

def native_result_status(server_name: str, result: dict, tool: str) -> dict:
    """Recognize the exact native error envelopes lacking an MCP error flag."""
    if server_name not in ('voicestudio', 'graphify') or not isinstance(result, dict) or result.get('isError'):
        return result
    for block in result.get('content', []):
        text = block.get('text') if isinstance(block, dict) and block.get('type') == 'text' else None
        if not isinstance(text, str) or len(text) > 65536:
            continue
        if server_name == 'graphify':
            if text.startswith('Error executing ' + tool + ':'):
                return {**result, 'isError': True}
            continue
        if not text.lstrip().startswith('{'):
            continue
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get('error'), str) and payload['error']:
            return {**result, 'isError': True}
    return result

'''


class PortError(RuntimeError):
    """The port was refused; the message names the file and the reason."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def norm_code(text: str) -> str:
    """Comparison form: no quotes, no whitespace, no grouping parentheses (ast.unparse adds some)."""
    return "".join(ch for ch in text.replace("'", '"') if not ch.isspace() and ch not in "()")


def _nodes_in(tree: ast.Module, functions: tuple[str, ...],
              rename: dict[str, str] | None = None) -> dict[str, ast.If]:
    """The `if` node each comparison key names, so a route's body can be hashed too."""
    class Rename(ast.NodeTransformer):
        def visit_Name(self, node):
            if rename and node.id in rename:
                node.id = rename[node.id]
            return node

    nodes: dict[str, ast.If] = {}
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name in functions):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.If):
                test = Rename().visit(ast.parse(ast.unparse(node.test), mode="eval").body)
                nodes[norm_code(ast.unparse(ast.fix_missing_locations(test)))] = node
    return nodes


def _conditions_in(tree: ast.Module, functions: tuple[str, ...], rename: dict[str, str] | None = None) -> set[str]:
    """Comparison keys of the `if` tests inside the named functions (never comments/coverage)."""
    return set(_nodes_in(tree, functions, rename))


def check_hooks(mods: Path = MODS) -> dict:
    """The overlay contract on its own: every route block of ROUTES.json is still in hooks.py."""
    hooks = mods / "hooks.py"
    routes = mods / "ROUTES.json"
    for path in (hooks, routes):
        if not path.is_file():
            raise PortError(f"overlay file missing: {path}")
    contract = json.loads(routes.read_text(encoding="utf-8"))
    tree = ast.parse(hooks.read_text(encoding="utf-8"))
    # per method: the same condition (`path == "/power"`) exists in both handlers
    nodes = {label: _nodes_in(tree, (fn,), {"handler": "self"})
             for label, fn in (("GET", "handle_get"), ("POST", "handle_post"))}
    stale = []
    for method, blocks in contract["blocks"].items():
        for block in blocks:
            node = nodes.get(method, {}).get(norm_code(block["condition"]))
            if node is None:
                stale.append(f"{method} {block['condition'][:80]} (live line {block['line']})")
            elif block.get("sha256"):
                digest = sha(ast.dump(node, annotate_fields=False, include_attributes=False).encode())
                if digest != block["sha256"]:
                    stale.append(f"{method} {block['condition'][:80]}: the body changed "
                                 f"(live line {block['line']})")
    if stale:
        raise PortError("the hooks no longer match the route contract:\n  " + "\n  ".join(stale[:15]))
    overlay = json.loads((mods / "OVERLAY.json").read_text(encoding="utf-8")) if (mods / "OVERLAY.json").is_file() else None
    if overlay:
        entries = overlay.get("files", [])
        rels = [e["path"] if isinstance(e, dict) else e for e in entries]
        # repo: mods/serve/x.py; staging: the same module is copied to serve/x.py
        missing = [rel for rel in rels
                   if not (mods / Path(rel)).is_file() and not (mods.parent / Path(rel)).is_file()]
        if missing:
            raise PortError("overlay modules missing: " + ", ".join(sorted(missing)[:10]))
    return {"blocks": sum(len(v) for v in contract["blocks"].values())}


def check_overlay(live: Path, mods: Path = MODS, *, check_live: bool = True) -> dict:
    """Hooks vs contract, and (while porting) the custom routes still in the live server.

    After activation the live `serve/server.py` is the ported upstream one: there is
    no custom route block left to compare, and `check_live=False` (or `check_hooks`)
    is the meaningful check. A live tree with none of the blocks gets a clear error
    instead of one line per block.
    """
    report = check_hooks(mods)
    if not check_live:
        return report
    server = Path(live) / "serve/server.py"
    if not server.is_file():
        raise PortError(f"live server missing: {server}")
    contract = json.loads((mods / "ROUTES.json").read_text(encoding="utf-8"))
    tree = ast.parse(server.read_text(encoding="utf-8"))
    conditions = _conditions_in(tree, ("do_GET", "do_POST", "_post", "_get"))
    present = 0
    total = 0
    stale = []
    for method, blocks in contract["blocks"].items():
        for block in blocks:
            total += 1
            if norm_code(block["condition"]) in conditions:
                present += 1
            else:
                stale.append(f"{method} block at live line {block['line']} is no longer in serve/server.py")
    if present < max(1, total // 2):
        raise PortError(f"only {present} of {total} custom route blocks are in serve/server.py: this live tree "
                        "looks like the already-ported upstream one; pass the pre-activation custom tree as --live")
    if stale:
        raise PortError("the hooks no longer match the live routes:\n  " + "\n  ".join(stale[:15]))
    return report


def contract_for(live: Path, mods: Path = MODS) -> dict:
    """The overlay contract for this live tree.

    Before the first activation the live `serve/server.py` still has the custom route
    blocks and is compared with them. After activation those blocks are gone (the live
    tree is the ported upstream one): the hooks are the contract, and building the next
    candidate from the activated tree is the normal case.
    """
    try:
        return check_overlay(Path(live), mods)
    except PortError as error:
        if "already-ported" not in str(error):
            raise
        return check_hooks(mods)


def _copy(upstream: Path, staging: Path, rel: str, manifest: dict) -> None:
    src = upstream / rel
    if not src.is_file():
        raise PortError(f"upstream file missing: {rel}")
    dst = staging / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    dst.write_bytes(data)
    manifest[rel] = sha(data)


def _copy_live_app(live: Path, staging: Path, manifest: dict) -> None:
    """Start from the live app tree, minus the overlay source and the vendored tools.

    The port keeps the live line's tools, tests and resources; `SHARED + CLOSURE` then
    overwrite every file the upstream release owns. This is the same app surface
    `source_update` activates, so the suite sees the tree it was written for.
    """
    for rel, src in sorted(app_files(live).items()):
        if rel in EXCLUDE_FILES or any(rel.startswith(prefix) for prefix in EXCLUDE_PREFIXES):
            continue
        dst = staging / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        manifest[rel] = sha(src.read_bytes())


def _patch_server(staging: Path, manifest: dict) -> None:
    path = staging / "serve/server.py"
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n").rstrip("\n")
    footer = ('\n\n# --- mods overlay: custom managers and routes (docs/adr/0001-mods-overlay-on-upstream.md) ---\n'
              'from mods import hooks as _mods_hooks  # noqa: E402\n'
              '_mods_hooks.install(sys.modules[__name__])\n')
    guard = 'if __name__ == "__main__":'
    if text.count(guard) != 1:
        raise PortError("serve/server.py: the __main__ guard is not exactly once; the overlay footer has no place")
    text = text.replace(guard, footer + guard, 1)
    lazy = ('    ap.add_argument("--lazy", action="store_true", help="start the API unloaded (the engine and the vision '
            'encoder start with the first request)")\n')
    if lazy not in text:
        raise PortError("serve/server.py: the --lazy argument changed; the live CLI default cannot be carried")
    text = text.replace(lazy,
                        '    ap.add_argument("--lazy", action="store_true", default=True, help="start unloaded (default); '
                        'load only on an explicit start or the first inference request")\n'
                        '    ap.add_argument("--preload", dest="lazy", action="store_false", help="load the model at '
                        'dashboard startup")\n', 1)
    data = text.replace("\n", "\r\n" if crlf else "\n").encode("utf-8")
    path.write_bytes(data)
    manifest["serve/server.py"] = sha(data)


def _patch_mcp(staging: Path, manifest: dict) -> None:
    path = staging / "serve/mcp.py"
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    marker = "\nclass McpError(RuntimeError):"
    if text.count(marker) != 1:
        raise PortError("serve/mcp.py: the McpError class changed")
    text = text.replace(marker, MC_NATIVE + marker, 1)
    old = "    def call(self, tool: str, arguments: dict, timeout: float, cancel=None) -> dict:"
    if text.count(old) != 1:
        raise PortError("serve/mcp.py: McpServer.call changed")
    text = text.replace(old, '''    def call(self, tool: str, arguments: dict, timeout: float, cancel=None) -> dict:
        return native_result_status(self.name, self._call_locked(tool, arguments, timeout, cancel), tool)

    def _call_locked(self, tool: str, arguments: dict, timeout: float, cancel=None) -> dict:''', 1)
    data = text.replace("\n", "\r\n" if crlf else "\n").encode("utf-8")
    path.write_bytes(data)
    manifest["serve/mcp.py"] = sha(data)


def _patch_frontend(staging: Path, manifest: dict) -> None:
    path = staging / "serve/frontend.py"
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    old_helper = ('    return [dict(m, role="user") if m.get("role") == "system" and i > 0 else m '
                  'for i, m in enumerate(messages)]')
    if old_helper not in text:
        raise PortError("serve/frontend.py: _late_system_to_user changed")
    text = text.replace(old_helper,
                        '    return [dict(m, role="system" if i == 0 else "user")\n'
                        '            if m.get("role") in ("system", "developer") else m for i, m in enumerate(messages)]', 1)
    render = ("    def render(self, messages: list[dict], tools: list[dict] | None = None, "
              "add_generation_prompt: bool = True,\n               **kwargs) -> str:\n")
    if render not in text:
        raise PortError("serve/frontend.py: ChatTemplate.render changed")
    prep = ("        messages = [dict(message) for message in _late_system_to_user([dict(m) for m in messages])]\n"
            "        for message in messages:\n"
            "            if message.get('tool_calls'):\n"
            "                # copy only the calls we rewrite: deepcopy(messages) also walked every\n"
            "                # image payload for nothing (str/bytes are shared either way)\n"
            "                message['tool_calls'] = copy.deepcopy(message['tool_calls'])\n"
            "        for message in messages:\n"
            "            for call in message.get('tool_calls') or []:\n"
            "                function = call.get('function') or {}\n"
            "                arguments = function.get('arguments', {})\n"
            "                # OpenAI uses JSON strings on the wire; HF templates require objects.\n"
            "                for _ in range(2):\n"
            "                    if isinstance(arguments, str):\n"
            "                        try:\n"
            "                            arguments = json.loads(arguments)\n"
            "                        except ValueError as error:\n"
            "                            raise TemplateRequestError('Argomenti dello strumento: JSON non valido') from error\n"
            "                if not isinstance(arguments, dict):\n"
            "                    raise TemplateRequestError('Gli argomenti dello strumento devono essere un oggetto')\n"
            "                function['arguments'] = arguments\n")
    text = text.replace(render, render + prep, 1)
    if "\nimport copy\n" not in text:
        text = text.replace("\nimport json\n", "\nimport copy\nimport json\n", 1)
    data = text.replace("\n", "\r\n" if crlf else "\n").encode("utf-8")
    path.write_bytes(data)
    manifest["serve/frontend.py"] = sha(data)


def _patch_telemetry(staging: Path, live: Path, manifest: dict) -> None:
    """Upstream telemetry + the live pieces: _AmdWindows (#301), gpu_archs, the sampler."""
    live_src = (live / "serve/telemetry.py").read_text(encoding="utf-8")
    live_tree = ast.parse(live_src)
    live_lines = live_src.splitlines()
    path = staging / "serve/telemetry.py"
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    cls = next(n for n in live_tree.body if isinstance(n, ast.ClassDef) and n.name == "_AmdWindows")
    block = "\n".join(live_lines[cls.lineno - 1:cls.end_lineno])
    # inherits _Amd's link()/_hops(): a caller that names a sysfs device reads it
    block = block.replace("class _AmdWindows:", "class _AmdWindows(_Amd):", 1)
    block = block.replace("    def __init__(self, index=0):\n",
                          "    def __init__(self, index=0):\n        self.dev = None\n", 1)
    if "class _AmdWindows" in text or "\ndef gpu_reader(" not in text:
        raise PortError("serve/telemetry.py: the shape changed; _AmdWindows has no place")
    text = text.replace("\ndef gpu_reader(", "\n" + block + "\n\ndef gpu_reader(", 1)
    old = ("    if amd:\n        return _Amd(index)\n"
           "    return _Metal(index) if sys.platform == \"darwin\" else _Nvml(index)\n")
    if old not in text:
        raise PortError("serve/telemetry.py: gpu_reader changed")
    text = text.replace(old, (
        "    if amd:\n"
        "        # Windows has no amdgpu sysfs for a real card: use the OS GPU counters instead (#301).\n"
        "        # A readable sysfs tree (Linux, or a test's fake SYSFS) is read as before.\n"
        "        if os.name == \"nt\" and amd_device_dir(index) is None:\n"
        "            return _AmdWindows(index)\n"
        "        return _Amd(index)\n"
        "    return _Metal(index) if sys.platform == \"darwin\" else _Nvml(index)\n"), 1)
    # close() joins; _loop survives an uninitialised object; static carries the arch
    if "        self._stop.set()\n" not in text:
        raise PortError("serve/telemetry.py: Telemetry.close changed")
    text = text.replace("        self._stop.set()\n",
                        "        self._stop.set()\n        if self._thread is not threading.current_thread():\n"
                        "            self._thread.join(timeout=2)\n", 1)
    # the live sampler body: the efficiency series (serve/efficiency.py) and its snapshot
    def class_method(lines: list[str], tree: ast.Module, name: str) -> str:
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Telemetry")
        node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
        return "\n".join(lines[node.lineno - 1:node.end_lineno])

    up_tree = ast.parse(text)
    up_lines = text.splitlines()
    for name in ("_loop", "snapshot", "_disk", "sample"):
        old_method = class_method(up_lines, up_tree, name)
        new_method = class_method(live_lines, live_tree, name)
        if old_method not in text:
            raise PortError(f"serve/telemetry.py: Telemetry.{name} changed")
        text = text.replace(old_method, new_method, 1)
    if "        self._disk_prev = None\n" not in text:
        raise PortError("serve/telemetry.py: Telemetry._disk_prev initialisation changed")
    text = text.replace("        self._disk_prev = None\n",
                        "        self.last_efficiency = None\n        self._disk_prev = None\n", 1)
    if 'while not getattr(self, "_stop", threading.Event()).is_set():' not in text:
        # live's _loop normally already carries this; only the raw upstream form needs it
        if "while not self._stop.is_set():" not in text:
            raise PortError("serve/telemetry.py: the sampler loop changed")
        text = text.replace("while not self._stop.is_set():",
                            'while not getattr(self, "_stop", threading.Event()).is_set():', 1)
    static_end = '            "psutil": self.ps is not None,\n        }\n'
    if static_end not in text:
        raise PortError("serve/telemetry.py: Telemetry.static changed")
    # the arch probe block is taken from the live __init__, so its shape (a background
    # thread) can never drift from the live line
    tel_cls = next(n for n in live_tree.body if isinstance(n, ast.ClassDef) and n.name == "Telemetry")
    tel_init = next(n for n in tel_cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    arch_node = next(n for n in tel_init.body if isinstance(n, ast.If) and "gpu_archs" in ast.unparse(n))
    arch = "\n".join(live_lines[arch_node.lineno - 1:arch_node.end_lineno]) + "\n"
    text = text.replace(static_end, static_end + arch, 1)
    for needed in ("subprocess", "re", "struct"):
        if f"\nimport {needed}\n" not in text:
            anchor = "from __future__ import annotations\n"
            if anchor in text:
                text = text.replace(anchor, anchor + f"import {needed}\n", 1)
            else:
                text = f"import {needed}\n" + text
    data = text.replace("\n", "\r\n" if crlf else "\n").encode("utf-8")
    path.write_bytes(data)
    manifest["serve/telemetry.py"] = sha(data)


def build(upstream: Path, live: Path, staging: Path, *, test: bool = False, timeout: int = 1800) -> dict:
    """Produce staging = the live app with upstream's own files overwritten, plus the overlay."""
    upstream, live, staging = Path(upstream).resolve(), Path(live).resolve(), Path(staging).resolve()
    if staging in (upstream, live):
        raise PortError("staging must be a tree of its own")
    contract = contract_for(live)
    if staging.exists():
        if not staging.is_dir():
            raise PortError(f"staging is not a directory: {staging}")
        # a rebuild must not keep a module that was deleted from the overlay
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    manifest: dict[str, str] = {}
    _copy_live_app(live, staging, manifest)
    for rel in SHARED + CLOSURE:
        _copy(upstream, staging, rel, manifest)
    _patch_server(staging, manifest)
    _patch_mcp(staging, manifest)
    _patch_frontend(staging, manifest)
    _patch_telemetry(staging, live, manifest)

    # the overlay source: hooks, service, their tests, and the new modules
    for name in ("__init__.py", "hooks.py", "service.py", "ROUTES.json", "test_hooks.py", "README.md", "OVERLAY.json"):
        src = MODS / name
        if not src.is_file():
            raise PortError(f"overlay file missing: {src}")
        (staging / "mods").mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, staging / "mods" / name)
        manifest[f"mods/{name}"] = sha(src.read_bytes())
    for src in sorted((MODS / "serve").glob("*.py")):
        if src.name in ("__init__.py",):
            continue
        (staging / "serve").mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, staging / "serve" / src.name)
        manifest[f"serve/{src.name}"] = sha(src.read_bytes())
    for src in sorted((MODS / "tests").glob("*.py")) if (MODS / "tests").is_dir() else []:
        shutil.copy2(src, staging / "serve" / src.name)
        manifest[f"serve/{src.name}"] = sha(src.read_bytes())
    for rel in SCRATCH_DIRS:
        # the live-line tests write their temp trees here; a fresh staging has no output/
        (staging / rel).mkdir(parents=True, exist_ok=True)

    report = {"upstream": str(upstream), "staging": str(staging), "files": len(manifest),
              "blocks": contract["blocks"], "manifest": manifest, "tested": False}
    (staging / "staging-overlay.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (staging / "staging-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if test:
        # The overlay suite replaces upstream's own copy of the tests it changed, so the
        # upstream release is also run, untouched, before the port: a red baseline stops
        # the build instead of being hidden by a green overlay suite.
        base_env = dict(os.environ, HIP_VISIBLE_DEVICES="-1", CUDA_VISIBLE_DEVICES="-1",
                        PYTHONDONTWRITEBYTECODE="1")
        scratch = tempfile.mkdtemp(prefix="strata-port-")
        created_hydra: Path | None = None
        # the HYDRA tests read `staging.parent/HYDRA` (the app resolves it two levels above
        # serve/); a production staging is a sibling of the live tree, a temp one is not.
        # Provisioned only for the staging runs, never for the upstream baseline.
        hydra = staging.parent / "HYDRA"
        source_hydra = next((base for base in (live.parent / "HYDRA", live / "HYDRA",
                                               ROOT.parent / "HYDRA", ROOT / "HYDRA")
                             if base.is_dir()), None)
        try:
            runs = [
                ("upstream", [sys.executable, "-m", "unittest", "discover",
                              "-s", str(upstream / "serve"), "-t", str(upstream), "-p", "test_*.py"],
                 Path(scratch), str(upstream)),
                ("server", [sys.executable, "-m", "unittest", "discover", "-s", "serve", "-p", "test_*.py"],
                 staging, str(staging)),
                ("overlay", [sys.executable, "-m", "unittest", "mods.test_hooks"], staging, str(staging)),
            ]
            logs, failed, failed_tail = [], None, ""
            for label, command, cwd, path in runs:
                if label == "server" and not hydra.exists() and source_hydra is not None:
                    shutil.copytree(source_hydra, hydra)
                    created_hydra = hydra
                run = subprocess.run(command, cwd=str(cwd), env=dict(base_env, PYTHONPATH=path),
                                     capture_output=True, text=True, timeout=timeout)
                logs.append(f"== {label} ==\n{run.stdout}{run.stderr}")
                if run.returncode != 0:
                    logs.append(f"== {label}: exit {run.returncode} ==\n")
                    if failed is None:
                        failed = label
                        failed_tail = "\n".join((run.stdout + run.stderr).splitlines()[-12:])
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
            if created_hydra is not None:
                shutil.rmtree(created_hydra, ignore_errors=True)
        log = "\n".join(logs)
        report["tested"] = failed is None
        report["test_tail"] = failed_tail or "\n".join(log.splitlines()[-8:])
        (staging / "port-tests.log").write_text(log, encoding="utf-8")
        if failed:
            raise PortError(f"the {failed} tests failed:\n{failed_tail}")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Port the mods overlay onto an upstream Strata release")
    parser.add_argument("--upstream", help="the upstream tree (e.g. output/updates/baselines/...v0.2.9)")
    parser.add_argument("--live", default=".", help="the live/custom tree (read-only)")
    parser.add_argument("--staging", help="the candidate tree to write")
    parser.add_argument("--test", action="store_true", help="run the full server suite in staging")
    parser.add_argument("--check", action="store_true", help="only check the overlay contract")
    args = parser.parse_args(argv)
    try:
        if args.check:
            print(json.dumps(check_overlay(Path(args.live), check_live=False), indent=2))
            return 0
        if not args.upstream or not args.staging:
            parser.error("--upstream and --staging are required unless --check is used")
        report = build(Path(args.upstream), Path(args.live), Path(args.staging), test=args.test)
        print(json.dumps({k: v for k, v in report.items() if k != "manifest"}, indent=2))
        return 0
    except PortError as error:
        print(f"[port-mods] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Contract tests for mods/hooks.py: the custom route surface of the live line.

Run from the repository root:
    python -m unittest mods.test_hooks -v

The tests never start the engine, open a socket or touch the live tree: handlers
are fakes and the server module is imported read-only.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mods import hooks  # noqa: E402

ROUTES = Path(__file__).with_name("ROUTES.json")


class FakeHandler:
    """The handler methods the custom routes use, with the responses recorded."""

    def __init__(self, body=b"{}", content_length=None, authorized=True, own_page=True):
        self.body = body
        self.headers = {"Content-Length": str(len(body) if content_length is None else content_length)}
        self.authorized = authorized
        self.own_page = own_page
        self.path = "/"
        self.command = "POST"
        self.sent = []

    # -- handler API the routes call ------------------------------------
    def _json(self, code, obj):
        self.sent.append((code, obj))

    def _authorized(self):
        if not self.authorized:
            self._json(401, {"error": {"message": "missing or wrong API key"}})
        return self.authorized

    def _own_page(self, why):
        if not self.own_page:
            self._json(403, {"error": {"message": why}})
        return self.own_page

    def _foreign_page(self, allow_multipart=False):
        return False

    def _read_body(self):
        return self.body


class FakeService:
    """Only the attributes the exercised routes read."""

    def __init__(self, **attrs):
        for name, value in attrs.items():
            setattr(self, name, value)


def attr(*names):
    """A service whose attributes are MagicMocks, chained as needed."""
    svc = FakeService()
    for name in names:
        setattr(svc, name, mock.MagicMock(name=name))
    return svc


class DispatchTest(unittest.TestCase):
    def test_chat_archive_post_saves_the_rows(self):
        handler, svc = FakeHandler(body=b'[{"id": "x"}]'), FakeService()
        with mock.patch("serve.chat_archive.save_archive", return_value=1) as save:
            self.assertTrue(hooks.handle_post(handler, svc, "/chat/archive"))
        save.assert_called_once()
        self.assertEqual(handler.sent, [(200, {"saved": 1})])

    def test_nested_web_asset_is_left_to_upstream(self):
        handler, svc = FakeHandler(), FakeService()
        self.assertFalse(hooks.handle_get(handler, svc, "/web/vendor/katex/katex.min.css"))
        self.assertEqual(handler.sent, [])

    def test_unknown_get_path_is_not_handled(self):
        handler, svc = FakeHandler(), attr()
        self.assertFalse(hooks.handle_get(handler, svc, "/v1/does-not-exist"))
        self.assertEqual(handler.sent, [])

    def test_unknown_post_path_is_not_handled(self):
        handler, svc = FakeHandler(), attr()
        self.assertTrue(hooks.handle_post(handler, svc, "/v1/chat/completions") is False)
        self.assertEqual(handler.sent, [])

    def test_updates_get_calls_the_update_center(self):
        handler, svc = FakeHandler(), attr("update_center")
        svc.update_center.status.return_value = {"state": "idle"}
        self.assertTrue(hooks.handle_get(handler, svc, "/updates"))
        svc.update_center.status.assert_called_once_with()
        self.assertEqual(handler.sent, [(200, {"state": "idle"})])

    def test_updates_get_still_requires_the_api_key(self):
        handler, svc = FakeHandler(authorized=False), attr("update_center")
        self.assertTrue(hooks.handle_get(handler, svc, "/updates"))
        svc.update_center.status.assert_not_called()
        self.assertEqual(handler.sent[0][0], 401)

    def test_benchmark_lab_mock_shell_is_not_reported_busy(self):
        class MockEngine:
            pass
        svc = FakeService(engine=MockEngine(), benchmark_lab=mock.MagicMock(),
                          optional_backends=mock.MagicMock(), optional_benchmark=mock.MagicMock())
        svc.benchmark_lab.status.return_value = {"job": {"status": "idle"},
                                                 "models": [{"id": "native", "ready": False}]}
        svc.optional_backends.status.return_value = {
            "status": "idle",
            "local_models": [
                {"path": "/models/native.gguf", "name": "native", "format": "GGUF",
                 "runtime_supported": True, "required_engine": "strata"},
                {"path": "/models/chat.gguf", "name": "chat", "format": "GGUF",
                 "runtime_supported": True, "required_engine": "gguf"},
            ],
        }
        svc.optional_benchmark.status.return_value = ({"status": "idle"}, [])
        handler = FakeHandler()
        self.assertTrue(hooks.handle_get(handler, svc, "/benchmark-lab"))
        body = handler.sent[0][1]
        self.assertFalse(body["operational_loaded"])
        ids = [model["id"] for model in body["models"]]
        self.assertIn("optional_local:/models/chat.gguf", ids)
        self.assertNotIn("optional_local:/models/native.gguf", ids)

    def test_benchmarks_keep_optional_record_when_backend_is_idle(self):
        native_report = {"reports": [{"id": "native", "status": "complete"}], "best_groups": []}
        optional_row = {"model": "local/Qwen3-4B", "status": "complete", "protocol": {}, "summary": {}}
        optional_group = {"id": "g", "model": "local/Qwen3-4B", "protocol": {}, "tested_profiles": 1,
                          "winner": {"label": "x", "summary": {}, "finished_at": 0}}
        with mock.patch("serve.diagnostics.benchmark_reports", return_value=native_report), \
             mock.patch("serve.benchmark_records.best_groups", return_value=[]), \
             mock.patch("serve.optional_reports.reports", return_value=[optional_row]), \
             mock.patch("serve.optional_reports.best_groups", return_value=[optional_group]) as optional_best:
            svc = FakeService(model="native-model", optional_backends=mock.MagicMock())
            svc.optional_backends.status.return_value = {"status": "idle"}
            handler = FakeHandler()
            self.assertTrue(hooks.handle_get(handler, svc, "/benchmarks"))
        body = handler.sent[0][1]
        self.assertEqual(body["best_groups"], [optional_group])
        self.assertEqual(len(body["reports"]), 2)
        self.assertEqual(body["reports"][0]["id"], "native")
        self.assertEqual(body["reports"][1], optional_row)
        optional_best.assert_called_once_with([optional_row], "local/Qwen3-4B")

    def test_local_export_preflight_posts_the_payload(self):
        handler, svc = FakeHandler(body=b'{"a": 1}'), attr("local_export")
        svc.local_export.preflight.return_value = {"ready": True}
        self.assertTrue(hooks.handle_post(handler, svc, "/local-export/preflight"))
        svc.local_export.preflight.assert_called_once_with({"a": 1})
        self.assertEqual(handler.sent, [(200, {"ready": True})])

    def test_local_export_rejects_a_foreign_page(self):
        handler, svc = FakeHandler(body=b"{}"), attr("local_export")
        handler._own_page = lambda why: False
        self.assertTrue(hooks.handle_post(handler, svc, "/local-export/preflight"))
        svc.local_export.preflight.assert_not_called()

    def test_trailing_slash_and_query_are_normalised_by_the_caller(self):
        # The hook contract takes an already-normalised path (the wrapper does it);
        # the same route string the live handler computes must match.
        path = "/updates/?x=1".split("?")[0].rstrip("/")
        self.assertEqual(path, "/updates")
        handler, svc = FakeHandler(), attr("update_center")
        self.assertTrue(hooks.handle_get(handler, svc, path))

    def test_config_post_accepts_the_dashboard_flat_body(self):
        handler = FakeHandler(body=b'{"vram_reserve_mib": 2048, "kv_resident": true, "max_context": 32768}')
        svc = attr("set_resources", "set_vision", "resource_state")
        svc.set_resources.side_effect = [False, True]
        svc.set_vision.return_value = {"vision": False}
        svc.resource_state.return_value = {"vram_reserve_mib": 2048}
        self.assertTrue(hooks.handle_post(handler, svc, "/config"))
        svc.set_resources.assert_any_call(vram_reserve_mib=2048, kv_resident=True, max_context=32768,
                                          validate_only=True)
        svc.set_vision.assert_called_once_with(None)
        self.assertEqual(handler.sent[0][0], 200)
        self.assertEqual(handler.sent[0][1]["changed"], True)

    def test_config_post_answers_409_when_the_model_is_busy(self):
        handler = FakeHandler(body=b'{"vision": true}')
        svc = attr("set_resources", "set_vision", "resource_state")
        busy = type("GpuBusy", (RuntimeError,), {})
        svc.set_resources.side_effect = busy("the engine is loading")
        with mock.patch.object(hooks, "GpuBusy", busy, create=True):
            self.assertTrue(hooks.handle_post(handler, svc, "/config"))
        self.assertEqual(handler.sent[0][0], 409)

    def test_local_model_is_refused_for_a_foreign_page(self):
        handler, svc = FakeHandler(body=b'{"model": "local/x"}'), attr("optional_backends")
        handler._foreign_page = lambda allow_multipart=False: True
        self.assertTrue(hooks.handle_post(handler, svc, "/v1/chat/completions"))
        svc.optional_backends.status.assert_not_called()


class HandlerSignatureTest(unittest.TestCase):
    """Every handler method a hook body calls must exist where the wrapper calls it.

    The multipart audio bug (`_foreign_page(allow_multipart=True)` against upstream's
    no-argument method) passed the suite because the fake mirrored the live signature:
    this test reads the real Handler instead.
    """

    @classmethod
    def setUpClass(cls):
        cls.server = ast.parse((ROOT / "serve/server.py").read_text(encoding="utf-8"))
        cls.hook_tree = ast.parse(Path(hooks.__file__).read_text(encoding="utf-8"))

    @staticmethod
    def _methods(tree, class_names):
        found = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in class_names:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        found[item.name] = item
        return found

    def test_called_handler_methods_exist_and_accept_the_keywords(self):
        upstream = self._methods(self.server, {"Handler"})
        ours = self._methods(self.hook_tree, {"HandlerMixin", "HookedHandler"})
        called = {}
        for node in ast.walk(self.hook_tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "handler"):
                called.setdefault(node.func.attr, set()).update(
                    k.arg for k in node.keywords if k.arg is not None)
        self.assertTrue(called, "the hook bodies call no handler method")
        import http.server
        base_api = set(dir(http.server.BaseHTTPRequestHandler))
        # `_read_body` is added to HookedHandler by install(), not declared in the class
        unknown = sorted(name for name in called
                         if name not in upstream and name not in ours
                         and name not in base_api and name != "_read_body")
        self.assertEqual(unknown, [], "the hooks call handler methods the runtime does not define")
        for name, keywords in called.items():
            if not keywords:
                continue
            fn = ours.get(name) or upstream.get(name)
            if fn is None or fn.args.kwarg is not None:
                continue
            accepted = ({a.arg for a in fn.args.posonlyargs + fn.args.args}
                        | {a.arg for a in fn.args.kwonlyargs})
            self.assertTrue(keywords <= accepted,
                            f"handler.{name} does not accept {sorted(keywords - accepted)}")


class BridgeTest(unittest.TestCase):
    """The MCP bridge token: never empty, never a prefix, and the happy path intact."""

    def test_a_truncated_token_is_replaced(self):
        from serve import trueforge_setup
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data/agent-harness/trueforge-mcp-token"
            path.parent.mkdir(parents=True)
            path.write_text("short", encoding="utf-8")
            token = trueforge_setup.bridge_token(tmp)
            self.assertGreaterEqual(len(token), 32)
            self.assertEqual(path.read_text(encoding="utf-8"), token)
            self.assertEqual(trueforge_setup.bridge_token(tmp), token)

    def test_the_mcp_bridge_needs_the_exact_bearer_token(self):
        from serve import trueforge_setup
        handler = FakeHandler(body=b'{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}')
        svc = attr("mcp")
        with mock.patch.object(trueforge_setup, "bridge_token", return_value="t" * 43):
            handler.headers["Authorization"] = "Bearer "       # an empty token used to pass
            self.assertTrue(hooks.handle_post(handler, svc, "/harness/mcp"))
        self.assertEqual(handler.sent[0][0], 401)
        with mock.patch.object(trueforge_setup, "bridge_token", return_value="t" * 43), \
                mock.patch.object(trueforge_setup, "bridge_response", return_value={"ok": True}) as respond:
            handler.sent.clear()
            handler.headers["Authorization"] = "Bearer " + "t" * 43
            self.assertTrue(hooks.handle_post(handler, svc, "/harness/mcp"))
        respond.assert_called_once()
        self.assertEqual(handler.sent[-1][0], 200)


class RouteCoverageTest(unittest.TestCase):
    """Every custom block of the live line must be reachable through the hooks."""

    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(ROUTES.read_text(encoding="utf-8"))

    def test_every_contract_path_is_covered(self):
        source = re.sub(r"\s+", "", Path(hooks.__file__).read_text(encoding="utf-8"))
        for method, blocks in self.contract["blocks"].items():
            covered = set(hooks.COVERAGE[method])
            for block in blocks:
                if not block["paths"]:
                    # a lazy router or a guard with no literal path: the condition
                    # itself must be in the module, `self` -> `handler`.
                    expected = re.sub(r"\s+", "", re.sub(r"\bself\b", "handler", block["condition"]))
                    self.assertTrue(expected in source,
                                    f"{method} block at live line {block['line']} is not in the hooks")
                for path in block["paths"]:
                    self.assertIn(path, covered, f"{method} {path} from live line {block['line']} is not hooked")

    def test_contract_has_no_duplicate_paths(self):
        # A guard block may name a path an earlier/later route block also owns
        # (e.g. the /own_page guard for /config, /setup-download, /switch-model);
        # only duplicate *route* blocks would be dead code.
        for method, blocks in self.contract["blocks"].items():
            seen = set()
            for block in blocks:
                condition = block["condition"]
                if "path ==" not in condition and "path in" not in condition:
                    continue
                for path in block["paths"]:
                    if " and " in condition:
                        continue
                    self.assertNotIn(path, seen, f"{method} {path} appears twice")
                    seen.add(path)

    def test_coverage_counts_match_the_live_blocks(self):
        self.assertEqual(len(hooks.COVERAGE["GET"]), len({
            p for b in self.contract["blocks"]["GET"] for p in b["paths"]}))
        self.assertEqual(len(hooks.COVERAGE["POST"]), len({
            p for b in self.contract["blocks"]["POST"] for p in b["paths"]}))


class InstallTest(unittest.TestCase):
    """install() must wire the hook into any server module without editing it."""

    def fake_server(self):
        module = types.ModuleType("fake_server_for_hooks")

        class Service:
            def __init__(self, engine="engine"):
                self.engine = engine
                self.built = True
                self.api_key = None
                self.host_names = {"127.0.0.1"}
                self.trusted_origins = []
                self.cors_origins = []

            def ensure_loaded(self):
                return "loaded"

            def prepare(self, messages, tools, kwargs, max_new=None, **extra):
                return ([], False, max_new)

            def metrics(self, *args, **kwargs):
                return {"engine": {"version": "test"}}

        def make_handler(svc):
            class Handler:
                protocol_version = "HTTP/1.0"

                def _authorized(self):
                    return True

                def _own_page(self, what):
                    self.own_page_calls = getattr(self, "own_page_calls", 0) + 1
                    self._json(415, {"error": {"message": "send application/json"}})
                    return False          # upstream's stricter check: no JSON content type

                def _foreign_origin(self):
                    return False

                def _json(self, code, obj):
                    self.last_json = (code, obj)

                def _body(self):
                    return b"{}"

                def do_GET(self):
                    self.fallback = "GET"

                def do_POST(self):
                    self.fallback = "POST"

            return Handler

        module.Service = Service
        module.make_handler = make_handler
        module.ROOT = ROOT

        class BadBody(Exception):
            def __init__(self, status, message):
                super().__init__(message)
                self.status = status

        module.BadBody = BadBody
        module.Vision = object
        module.vision_env = lambda cfg, env: {}
        module.engine_args = lambda cfg: list(cfg.get("args") or [])
        module.GpuBusy = RuntimeError
        module.ModelBusy = RuntimeError
        module.openai_collect = lambda chunks: {"choices": []}
        module.origin_allowed = lambda origin, host, names, origins: True

        def serve(svc, host="127.0.0.1", port=0):
            class Httpd:
                server_address = (host, port)
            return Httpd()

        module.serve = serve

        class Server:
            def server_close(self):
                self.closed = True

        module.Server = Server
        module.main = lambda *a, **k: 0
        return module

    def test_wraps_service_init_and_make_handler_once(self):
        module = self.fake_server()
        with mock.patch.object(hooks, "install_managers") as managers:
            hooks.install(module)
            hooks.install(module)
            svc = module.Service()
            managers.assert_called_once_with(svc)
            self.assertTrue(svc.built)
            handler = module.make_handler(svc)()
            self.assertEqual(handler.protocol_version, "HTTP/1.0")
            self.assertTrue(callable(handler.do_GET) and callable(handler.do_POST))

    def test_hooked_handler_uses_a_hook_when_it_matches(self):
        module = self.fake_server()
        with mock.patch.object(hooks, "install_managers"):
            hooks.install(module)
            svc = module.Service()
            handler = module.make_handler(svc)()
            handler.path = "/updates"
            handler._json = lambda code, obj: setattr(handler, "sent", (code, obj))
            handler._authorized = lambda: True
            with mock.patch.object(svc, "update_center", create=True) as center:
                center.status.return_value = {"ok": True}
                handler.do_GET()
        self.assertEqual(handler.sent, (200, {"ok": True}))
        self.assertFalse(hasattr(handler, "fallback"))

    def test_hooked_handler_falls_back_to_upstream(self):
        module = self.fake_server()
        with mock.patch.object(hooks, "install_managers"):
            hooks.install(module)
            svc = module.Service()
            handler = module.make_handler(svc)()
            handler.path = "/health"
            handler.do_GET()
            self.assertEqual(handler.fallback, "GET")
            handler.path = "/v1/chat/completions"
            handler.headers = {}
            handler.do_POST()
            self.assertEqual(handler.fallback, "POST")

    def test_own_page_get_needs_no_content_type_but_post_keeps_the_check(self):
        # upstream's _own_page requires application/json on every method; our GET routes
        # (Voicestudio, chat archive) call it and the browser sends none -> 415
        module = self.fake_server()
        with mock.patch.object(hooks, "install_managers"):
            hooks.install(module)
        handler = module.make_handler(module.Service())()
        handler.command = "GET"
        handler.headers = {}
        self.assertTrue(handler._own_page("test"))
        self.assertFalse(hasattr(handler, "last_json"))
        handler.command = "POST"
        self.assertFalse(handler._own_page("test"))
        self.assertEqual(handler.last_json[0], 415)

    def test_get_restart_from_a_cross_site_page_is_refused(self):
        module = self.fake_server()
        with mock.patch.object(hooks, "install_managers"):
            hooks.install(module)
        svc = module.Service()
        svc.automatic_restart = mock.Mock()
        handler = module.make_handler(svc)()
        handler.command = "GET"
        handler.path = "/updates/restart"
        handler.headers = {"Sec-Fetch-Site": "cross-site"}
        handler.do_GET()
        self.assertEqual(handler.last_json[0], 403)
        svc.automatic_restart.assert_not_called()

    def test_foreign_page_allows_multipart_from_our_own_page(self):
        # the audio routes pass allow_multipart=True; upstream's method has no such flag,
        # so HookedHandler must provide it (a missing one raised TypeError before 400)
        module = self.fake_server()
        with mock.patch.object(hooks, "install_managers"):
            hooks.install(module)
        handler = module.make_handler(module.Service())()
        handler.headers = {"Origin": "http://127.0.0.1:8090", "Host": "127.0.0.1:8090",
                           "Content-Type": "multipart/form-data; boundary=x"}
        self.assertFalse(handler._foreign_page(allow_multipart=True))
        self.assertTrue(handler._foreign_page())            # JSON is still required without the flag
        self.assertEqual(handler.last_json[0], 415)

    def test_foreign_page_refuses_another_site(self):
        module = self.fake_server()
        with mock.patch.object(hooks, "install_managers"):
            hooks.install(module)
        handler = module.make_handler(module.Service())()
        handler.headers = {"Origin": "https://evil.example", "Host": "127.0.0.1:8090",
                           "Content-Type": "application/json"}
        with mock.patch.object(hooks, "origin_allowed", lambda *a: False):
            self.assertTrue(handler._foreign_page(allow_multipart=True))
        self.assertEqual(handler.last_json[0], 403)

    def test_after_serve_sets_the_run_config_and_port(self):
        import tempfile

        module = self.fake_server()
        svc = module.Service()

        class Httpd:
            server_address = ("127.0.0.1", 8090)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "strata.json"
            path.write_text(json.dumps({"exe": str(Path(tmp) / "strata.exe")}), encoding="utf-8")
            with mock.patch("sys.argv", ["serve/server.py", "--config", str(path), "--port", "8090"]):
                hooks.after_serve(svc, Httpd())
        self.assertEqual(svc.port, 8090)
        self.assertEqual(svc.cfg_path, str(path))
        self.assertEqual(svc.cfg["exe"], str(Path(tmp) / "strata.exe"))

    def test_install_exposes_the_live_only_harness_helper(self):
        # our custom modules do `from serve.server import agent_harness_for`;
        # upstream 0.2.9 has no such function, the overlay owns it.
        module = self.fake_server()
        self.assertFalse(hasattr(module, "agent_harness_for"))
        with mock.patch.object(hooks, "install_managers"):
            hooks.install(module)
        self.assertIs(module.agent_harness_for, hooks.agent_harness_for)

    def test_install_adds_the_model_management_methods(self):
        # the Control tab's routes call these; upstream 0.2.9's Service has none of them
        from mods import service

        module = self.fake_server()
        with mock.patch.object(hooks, "install_managers"):
            hooks.install(module)
        for name in service.METHODS:
            method = getattr(module.Service, name)
            if getattr(method, "_mods_serial", False):
                continue                    # serialized wrapper around the same body
            self.assertIs(method, getattr(service.ServiceMixin, name), name)
        self.assertIs(module.find_mmproj, service._find_mmproj)
        self.assertTrue(getattr(module.Service.ensure_loaded, "_mods_guarded", False))

    def test_metrics_fills_backend_platform_rocm_from_build_json(self):
        import tempfile

        module = self.fake_server()
        with mock.patch.object(hooks, "install_managers"):
            hooks.install(module)
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "BUILD.json").write_text(
                json.dumps({"backend": "hip", "platform": "windows-x64", "rocm": "10.2.0"}),
                encoding="utf-8")
            svc = module.Service()
            svc.cfg = {"exe": str(Path(tmp) / "strata.exe")}
            data = module.Service.metrics(svc)
        self.assertEqual(data["engine"]["backend"], "hip")
        self.assertEqual(data["engine"]["platform"], "windows-x64")
        self.assertEqual(data["engine"]["rocm"], "10.2.0")

    def test_metrics_exposes_the_power_manager_state(self):
        module = self.fake_server()
        with mock.patch.object(hooks, "install_managers"):
            hooks.install(module)
        svc = module.Service()
        svc.telemetry = mock.Mock()
        svc.telemetry.snapshot.return_value = {
            "now": {"gpu_power": 120.0, "gpu_temp": 60.0}, "history": {}, "static": {},
            "efficiency_sample": {"tps_per_w": 0.3}}
        manager = mock.Mock()
        manager.config.mode = "balanced"
        manager.config.temp_limit.return_value = 80.0
        manager.config.power_limit.return_value = 250.0
        manager.get_state.return_value = mock.Mock(
            power_w=120.0, temp_c=60.0, speed_tps=36.0, efficiency=0.3,
            throttling=False, throttle_reason="", cooldown_s=0.0)
        svc.power_manager = manager
        data = module.Service.metrics(svc)
        self.assertEqual(data["power"]["mode"], "balanced")
        self.assertEqual(data["power"]["temp_limit"], 80.0)
        self.assertEqual(data["power"]["power_limit"], 250.0)
        self.assertEqual(data["power"]["power_w"], 120.0)
        self.assertEqual(data["power"]["efficiency"], 0.3)
        self.assertEqual(data["efficiency_sample"], {"tps_per_w": 0.3})
        manager.update.assert_called_once()

    def test_ensure_loaded_guard_refuses_a_competing_benchmark(self):
        module = self.fake_server()
        with mock.patch.object(hooks, "install_managers"):
            hooks.install(module)
        svc = module.Service()
        with mock.patch("serve.gpu_lease.reserved", return_value=False), \
             mock.patch("serve.benchmark_monitor.competing_benchmark", return_value="probe"):
            with self.assertRaises(RuntimeError) as caught:   # the fake's GpuBusy
                module.Service.ensure_loaded(svc)
        self.assertIn("probe", str(caught.exception))

    def test_unauthorized_post_never_reaches_a_hook(self):
        module = self.fake_server()
        with mock.patch.object(hooks, "install_managers"):
            hooks.install(module)
            svc = module.Service()
            handler = module.make_handler(svc)()
            handler._authorized = lambda: False
            handler.path = "/updates/check"
            with mock.patch.object(hooks, "handle_post") as hook:
                handler.do_POST()
        hook.assert_not_called()
        self.assertFalse(hasattr(handler, "fallback"))


class LiveServerInstallTest(unittest.TestCase):
    """The real live server module must accept the hook without a Service."""

    def test_install_wraps_the_live_module_once(self):
        import serve.server as server_module

        hooks.install(server_module)
        wrapped_init = server_module.Service.__init__
        wrapped_make = server_module.make_handler
        hooks.install(server_module)
        self.assertIs(server_module.Service.__init__, wrapped_init)
        self.assertIs(server_module.make_handler, wrapped_make)

    def test_live_handler_dispatches_a_custom_get_before_upstream(self):
        import serve.server as server_module

        hooks.install(server_module)
        svc = FakeService(update_center=mock.MagicMock(), api_key="")
        svc.update_center.status.return_value = {"state": "idle"}
        handler = server_module.make_handler(svc).__new__(server_module.make_handler(svc))
        handler.path = "/updates"
        handler.sent = []
        handler._json = lambda code, obj: handler.sent.append((code, obj))
        handler.do_GET()          # a real socket would fail: the hook answers first
        self.assertEqual(handler.sent, [(200, {"state": "idle"})])


class HookBodyTest(unittest.TestCase):
    """Structural invariants of the generated bodies (they run inside a function)."""

    def functions(self):
        import ast

        tree = ast.parse(Path(hooks.__file__).read_text(encoding="utf-8"))
        return [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("handle_get", "handle_post")]

    def test_no_bare_return_inside_a_route_body(self):
        # A bare `return` would make handle_get/handle_post return None, which the
        # wrapper reads as "not handled" and passes the custom path to upstream.
        def walk(node, found):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    continue
                if isinstance(child, ast.Return) and child.value is None:
                    found.append(child.lineno)
                walk(child, found)

        for fn in self.functions():
            found = []
            walk(fn, found)
            self.assertEqual(found, [], f"{fn.name} has bare returns at {found}")

    def test_every_route_block_terminates(self):
        # A route block that falls through would continue matching later routes for a
        # path it already partly handled. Guards are the exception: the /web/ subtree
        # and unknown /harness/ paths return False and let upstream answer.
        guards = ("/web/", "/harness/")
        for fn in self.functions():
            statements = fn.body
            for index, stmt in enumerate(statements):
                if not isinstance(stmt, ast.If):
                    continue
                condition = ast.unparse(stmt.test)
                if any(guard in condition for guard in guards):
                    continue
                last = stmt.body[-1]
                followed_by_return = (index + 1 < len(statements)
                                      and isinstance(statements[index + 1], ast.Return))
                self.assertTrue(isinstance(last, (ast.Return, ast.Raise)) or followed_by_return,
                                f"{fn.name}:{stmt.lineno} falls through")


class ConfigTest(unittest.TestCase):
    def test_port_from_argv_reads_the_run_script_flag(self):
        self.assertEqual(hooks.port_from_argv(["--model", "x", "--port", "8090"]), 8090)
        self.assertEqual(hooks.port_from_argv(["--port=8091"]), 8091)
        self.assertEqual(hooks.port_from_argv(["--lazy"]), 8095)
        self.assertEqual(hooks.port_from_argv(["--port", "not-a-number"]), 8095)


    def test_config_path_from_argv(self):
        self.assertEqual(hooks.config_path_from_argv(["--config", "a.json"]), "a.json")
        self.assertEqual(hooks.config_path_from_argv(["--config=b.json"]), "b.json")
        self.assertIsNone(hooks.config_path_from_argv(["--port", "8090"]))


class ManagersTest(unittest.TestCase):
    def test_install_managers_leaves_an_already_installed_service_alone(self):
        svc = FakeService(update_center=object())
        before = dict(svc.__dict__)
        hooks.install_managers(svc)
        self.assertEqual(svc.__dict__, before)

    def test_install_managers_adds_the_custom_managers(self):
        import tempfile

        from serve.server import ByteTokenizer, MockEngine

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(hooks, "ROOT", Path(tmp)):
            engine = MockEngine(ByteTokenizer(), "")
            svc = FakeService(engine=engine, fifo=mock.MagicMock(), telemetry=None)
            hooks.install_managers(svc)
            for name in ("benchmark_lab", "optional_backends", "optional_benchmark", "optional_catalogue",
                         "local_training", "local_export", "update_center", "local_audio", "local_speech",
                         "local_separation", "local_visual", "local_generative_audio", "audiocraft_setup",
                         "voicestudio", "unsloth_workspace", "colibri_workspace", "antigravity_web",
                         "airllm_setup", "open_webui_setup", "power_manager"):
                self.assertTrue(hasattr(svc, name), name)
            self.assertIsNone(svc.native_workspace)
            self.assertIsNone(svc.automatic_updates)
            self.assertTrue(callable(svc.update_center.operational_idle))


if __name__ == "__main__":
    unittest.main()

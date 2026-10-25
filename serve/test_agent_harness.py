from unittest.mock import patch
_idle_probe = patch('serve.harness_activity.activity', return_value={'busy': False, 'activity_known': True})
def setUpModule():
    _idle_probe.start()
def tearDownModule():
    _idle_probe.stop()
"""Tests for the agent-harness lifecycle (OpenCode / DeepSeek Harness beside Strata).

No real harness binary is started: the process command is injectable, and the
readiness probe is a URL that a fake server can serve. The module must never kill a
process it did not start, must refuse a second start, and must hold the GPU lease.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from serve.agent_harness import (AgentHarness, build_config, build_dsh_patch, translate_mcp,
                                 OPENCODE_KIND, DSH_KIND)


class TranslateMcp(unittest.TestCase):
    def test_stdio_server_becomes_local_with_command_joined(self):
        out = translate_mcp({"filesystem": {"command": "npx",
                                            "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\root"]}})
        self.assertEqual(out, {"filesystem": {"type": "local",
                                              "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "C:\\root"],
                                              "enabled": True}})

    def test_url_server_becomes_remote(self):
        out = translate_mcp({"context7": {"url": "https://mcp.context7.com/mcp"}})
        self.assertEqual(out, {"context7": {"type": "remote", "url": "https://mcp.context7.com/mcp", "enabled": True}})

    def test_unknown_entry_is_skipped_not_guessed(self):
        out = translate_mcp({"weird": {"nothing": 1}})
        self.assertEqual(out, {})

    def test_all_eight_strata_servers_translate(self):
        # the shape of Strata's own data/mcp-dashboard.json
        servers = {
            "strata_diagnostics": {"command": "py", "args": ["project_mcp.py"], "cwd": "C:\\p"},
            "filesystem": {"command": "npx", "args": ["-y", "fs", "C:\\p"]},
            "memory": {"command": "npx", "args": ["-y", "mem"]},
            "sequential-thinking": {"command": "npx", "args": ["-y", "st"]},
            "context7": {"url": "https://mcp.context7.com/mcp"},
            "deepwiki": {"url": "https://mcp.deepwiki.com/mcp"},
            "graphify": {"command": "graphify-mcp.exe", "args": ["graph.json"]},
            "time": {"command": "py", "args": ["-m", "mcp_server_time"]},
        }
        out = translate_mcp(servers)
        self.assertEqual(len(out), 8)
        self.assertEqual(out["context7"]["type"], "remote")
        self.assertEqual(out["graphify"]["type"], "local")
        self.assertTrue(all(v["enabled"] for v in out.values()))


class BuildConfig(unittest.TestCase):
    def test_single_slot_does_not_run_background_title_inference(self):
        cfg = build_config({}, base_url='http://127.0.0.1:8080/v1', model_id='strata',
                           model_name='Local', context=65536, output=512)
        self.assertEqual(cfg['agent']['title'], {'disable': True})

    def test_config_points_the_local_model_at_strata_and_declares_capabilities(self):
        cfg = build_config({}, base_url="http://127.0.0.1:8080/v1", model_id="strata",
                           model_name="Qwen3.8", context=131072, output=16384)
        model = cfg["provider"]["strata"]["models"]["strata"]
        self.assertEqual(cfg["provider"]["strata"]["options"]["baseURL"], "http://127.0.0.1:8080/v1")
        self.assertEqual(model["limit"], {"context": 131072, "output": 16384})
        self.assertTrue(model["tool_call"], "senza tool_call OpenCode non offre strumenti al modello")
        self.assertTrue(model["reasoning"])

    def test_config_carries_the_translated_mcp_servers(self):
        cfg = build_config({"time": {"command": "py", "args": ["-m", "mcp_server_time"]}},
                           base_url="http://127.0.0.1:8080/v1", model_id="strata",
                           model_name="Qwen3.8", context=131072, output=16384)
        self.assertIn("time", cfg["mcp"])
        self.assertEqual(cfg["mcp"]["time"]["type"], "local")

    def test_output_stays_under_context(self):
        cfg = build_config({}, base_url="u", model_id="strata", model_name="m",
                           context=131072, output=16384)
        limit = cfg["provider"]["strata"]["models"]["strata"]["limit"]
        self.assertLess(limit["output"], limit["context"])

    def test_config_is_json_serializable(self):
        cfg = build_config({"a": {"url": "https://x/y"}}, base_url="u", model_id="s",
                           model_name="n", context=1024, output=256)
        json.dumps(cfg)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class EnvironmentIsolation(unittest.TestCase):
    """The child must be a clean harness: a parent OpenCode session's variables
    (password, client, embedded-UI switch) must not leak into it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        self.saved = {k: os.environ.get(k) for k in
                      ("OPENCODE_SERVER_PASSWORD", "OPENCODE_SERVER_USERNAME",
                       "OPENCODE_CLIENT", "OPENCODE_DISABLE_EMBEDDED_WEB_UI",
                       "OPENCODE_EXPERIMENTAL_FILEWATCHER", "STRATA_TEST_PW",
                       "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME")}

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _harness(self, **kw):
        return AgentHarness(self.root, port=_free_port(),
                            command=[sys.executable, "-c", "import time;time.sleep(1)"], **kw)

    def test_parent_opencode_variables_do_not_leak(self):
        os.environ["OPENCODE_SERVER_PASSWORD"] = "parent-secret"
        os.environ["OPENCODE_SERVER_USERNAME"] = "parent"
        os.environ["OPENCODE_CLIENT"] = "desktop"
        os.environ["OPENCODE_DISABLE_EMBEDDED_WEB_UI"] = "true"
        os.environ["OPENCODE_EXPERIMENTAL_FILEWATCHER"] = "true"
        env = self._harness().environment()
        for leaked in ("OPENCODE_SERVER_USERNAME", "OPENCODE_CLIENT",
                       "OPENCODE_DISABLE_EMBEDDED_WEB_UI", "OPENCODE_EXPERIMENTAL_FILEWATCHER"):
            self.assertNotIn(leaked, env, f"{leaked} è trapelato nel figlio")
        # a password IS present, but it is ours, never the parent session's
        self.assertIn("OPENCODE_SERVER_PASSWORD", env)
        self.assertNotEqual(env["OPENCODE_SERVER_PASSWORD"], "parent-secret")

    def test_config_dir_is_always_set(self):
        h = self._harness()
        self.assertEqual(h.environment()["OPENCODE_CONFIG_DIR"], str(h.config_dir))

    def test_an_explicit_password_is_set_from_its_env_var(self):
        os.environ["STRATA_TEST_PW"] = "chosen-secret"
        env = self._harness(password_env="STRATA_TEST_PW").environment()
        self.assertEqual(env["OPENCODE_SERVER_PASSWORD"], "chosen-secret")

    def test_a_generated_password_is_always_set_and_never_empty(self):
        # OpenCode v2 gates every /api/* call behind basic auth: without a password the
        # harness is unusable, so one is always present.
        h = self._harness()
        self.assertTrue(h.environment()["OPENCODE_SERVER_PASSWORD"])
        self.assertNotIn("password",h.status())

    def test_two_harnesses_do_not_share_a_password(self):
        self.assertNotEqual(self._harness().password, self._harness().password)

    def test_xdg_roots_are_isolated_into_the_sandbox(self):
        # An inherited XDG_STATE_HOME pointing at another OpenCode's (multi-gigabyte)
        # store made the child block and its API die. Every XDG root is redirected.
        os.environ["XDG_STATE_HOME"] = "C:\\somewhere\\else"
        os.environ["XDG_DATA_HOME"] = "C:\\somewhere\\else"
        env = self._harness().environment()
        for key in ("XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
            self.assertNotEqual(env[key], "C:\\somewhere\\else", f"{key} non è stato isolato")
            self.assertTrue(env[key].startswith(str(self.root)), f"{key} non è nella sandbox")


class Lifecycle(unittest.TestCase):
    """A fake 'harness' process stands in for opencode: a python one-liner that
    sleeps until killed, and an optional tiny HTTP responder for readiness."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        self.port = _free_port()

    def tearDown(self):
        if getattr(self, "h", None):
            try:
                self.h.close()
            except Exception:
                pass
        self.tmp.cleanup()

    def _fake_harness(self, *, serve_health=False):
        code = "import time;time.sleep(300)"
        if serve_health:
            code = (
                "import http.server,socketserver,threading\n"
                "class H(http.server.BaseHTTPRequestHandler):\n"
                " def do_GET(self):\n"
                "  self.send_response(200);self.end_headers();self.wfile.write(b'{\"ok\":true}')\n"
                " def log_message(self,*a):pass\n"
                f"socketserver.TCPServer(('127.0.0.1',{self.port}),H).serve_forever()"
            )
        return [sys.executable, "-c", code]

    def _make(self, **kw):
        self.h = AgentHarness(self.root, port=self.port, command=self._fake_harness(**kw),
                              health_url=f"http://127.0.0.1:{self.port}/health" if kw.get("serve_health") else None)
        return self.h

    def test_starts_and_reports_ready(self):
        h = self._make(serve_health=True)
        h.start()
        self.assertEqual(h.status()["status"], "ready")
        self.assertTrue(h.status()["owned_process"])

    def test_second_start_is_refused(self):
        h = self._make()
        h.start()
        with self.assertRaises(RuntimeError):
            h.start()

    def test_stop_releases_the_lease_and_the_child(self):
        h = self._make()
        h.start()
        h.stop()
        self.assertEqual(h.status()["status"], "idle")
        self.assertIsNone(h.status()["pid"])
        self.assertFalse((self.root / "data" / ".gpu-campaign.lock").exists())

    def test_stop_never_touches_a_foreign_process(self):
        outsider = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(300)"])
        try:
            h = self._make()
            h.start()
            h.stop()
            time.sleep(0.3)
            self.assertIsNone(outsider.poll(), "un processo non avviato da noi è stato ucciso")
        finally:
            outsider.kill()
            outsider.wait()

    def test_graphical_service_does_not_reserve_model_gpu(self):
        h=self._make();h.start()
        self.assertFalse((self.root/'data/.gpu-campaign.lock').exists());h.stop()

    def test_both_graphical_services_can_run_without_loading_models(self):
        h=self._make();h.start()
        other=AgentHarness(self.root,kind=DSH_KIND,port=_free_port(),command=self._fake_harness())
        try:
            other.start();self.assertTrue(h.status()['owned_process']);self.assertTrue(other.status()['owned_process'])
        finally:other.stop();h.stop()

    def test_close_is_idempotent(self):
        h = self._make()
        h.start()
        h.close()
        h.close()
        self.assertEqual(h.status()["status"], "idle")

    def test_status_shape_is_stable(self):
        h = self._make()
        st = h.status()
        for key in ("status", "port", "kind", "owned_process", "pid", "error"):
            self.assertIn(key, st)


class BuildDshPatch(unittest.TestCase):
    """The DeepSeek Harness profile patch (cordis.patch.yml)."""

    def test_single_slot_disables_only_background_title_provider(self):
        patch = self._patch()
        self.assertIn({'id': 'session-title-llm', 'disabled': True}, patch)
        self.assertNotIn({'id': 'session-title', 'disabled': True}, patch)

    def _patch(self, servers=None):
        return build_dsh_patch(servers if servers is not None else {},
                               base_url="http://127.0.0.1:8080/v1", model_id="strata",
                               model_name="Qwen3.8", context=131072, output=16384)

    def test_provider_points_at_strata_with_compat_for_a_llamacpp_server(self):
        patch = self._patch()
        provider = patch[0]["config"]["providers"]["strata"]
        self.assertEqual(provider["baseURL"], "http://127.0.0.1:8080/v1")
        self.assertEqual(provider["api"], "openai-completions")
        # a llama.cpp-style server refuses the developer role and max_completion_tokens
        self.assertFalse(provider["compat"]["supportsDeveloperRole"])
        self.assertEqual(provider["compat"]["maxTokensField"], "max_tokens")

    def test_the_local_model_is_declared_with_its_capacities(self):
        model = self._patch()[0]["config"]["providers"]["strata"]["models"][0]
        self.assertEqual(model["id"], "strata")
        self.assertEqual(model["contextWindow"], 131072)
        self.assertEqual(model["maxOutputTokens"], 16384)

    def test_each_mcp_server_is_its_own_additive_entry(self):
        patch = self._patch({"time": {"command": "py", "args": ["-m", "mcp_server_time"]},
                             "context7": {"url": "https://mcp.context7.com/mcp"}})
        ids = [entry["id"] for entry in patch]
        self.assertIn("llm-pi-ai", ids)
        self.assertIn("mcp-time", ids)
        self.assertIn("mcp-context7", ids)
        time_entry = next(e for e in patch if e["id"] == "mcp-time")
        self.assertEqual(time_entry["name"], "@deepseek-ai/dsh-mcp-client")
        self.assertEqual(time_entry["config"]["transport"], "stdio")
        self.assertEqual(time_entry["config"]["command"], "py")
        ctx = next(e for e in patch if e["id"] == "mcp-context7")
        self.assertEqual(ctx["config"]["transport"], "streamable-http")

    def test_patch_is_yaml_serializable(self):
        import yaml
        yaml.safe_dump(self._patch({"time": {"command": "py", "args": []}}), allow_unicode=True)


class DshHarness(unittest.TestCase):
    def test_dsh_runs_through_npx_when_no_binary_is_installed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            with patch('serve.agent_harness._default_binary',return_value=None):h = AgentHarness(root, kind=DSH_KIND)
            cmd = h.command()
            # on Windows npx resolves to npx.CMD: check for npx, not the exact spelling
            self.assertIn("npx", Path(cmd[0]).name.lower())
            self.assertIn("web", cmd)
            self.assertIn("--no-open", cmd)
            self.assertIn("3080", cmd)

    def test_dsh_home_is_isolated_under_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            env = AgentHarness(root, kind=DSH_KIND, command=["x"]).environment()
            self.assertIn("dsh-home", env["DSH_HOME"])
            self.assertTrue(env["DSH_HOME"].startswith(str(root)))

    def test_dsh_writes_a_cordis_patch_in_the_web_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            h = AgentHarness(root, kind=DSH_KIND, command=["x"],
                             mcp_servers={"time": {"command": "py", "args": ["-m", "mcp_server_time"]}})
            path = h.write_config()
            self.assertTrue(path.is_file())
            self.assertEqual(path.name, "cordis.patch.yml")
            self.assertIn("profiles", str(path))
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertIn("llm-pi-ai", [e.get("id") for e in data])
            inserted = [entry for operation in data for entry in operation.get('insert', [])]
            self.assertEqual([entry['id'] for entry in inserted], ['mcp-time'])
            self.assertEqual(inserted[0]['config']['transport'], 'stdio')

    def test_dsh_is_reported_installable_because_npx_can_fetch_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            self.assertTrue(AgentHarness(root, kind=DSH_KIND).status()["installed"])


class WritesConfig(unittest.TestCase):
    def test_start_writes_an_opencode_json_that_opencode_can_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            h = AgentHarness(root, port=_free_port(),
                             command=[sys.executable, "-c", "import time;time.sleep(300)"],
                             mcp_servers={"time": {"command": "py", "args": ["-m", "mcp_server_time"]}},
                             base_url="http://127.0.0.1:8080/v1", model_context=131072, model_output=16384)
            h.start()
            path = root / "data" / "agent-harness" / "opencode.json"
            self.assertTrue(path.is_file(), "la config va scritta dove OPENCODE_CONFIG_DIR la cerca")
            cfg = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("strata", cfg["provider"])
            self.assertIn("time", cfg["mcp"])
            h.close()


if __name__ == "__main__":
    unittest.main()

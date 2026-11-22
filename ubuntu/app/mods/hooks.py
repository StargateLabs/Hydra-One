"""Strata mods overlay: the custom routes and managers, applied to upstream 0.2.9.

The live line (base v0.1.42) added a `/updates` center, local integrations
(speech, audio, separation, training, export, catalogue), VoiceStudio, the agent
harness tabs, HYDRA and AirLLM routes. Upstream 0.2.9 knows none of them. This
module carries those blocks unchanged: `install(server_module)` wraps
`Service.__init__` and `make_handler`, and the wrapper handler tries the hooks
before upstream's own routing, so the rest of the server stays upstream.

The route bodies come from the live `serve/server.py` (generated); see
`ROUTES.json` for the block -> path contract and `mods/README.md` for the rules.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def _native_model_loaded(svc):
    """The mock shell is idle until an optional backend really has a model."""
    if type(svc.engine).__name__ == 'MockEngine':
        return svc.optional_backends.status()['status'] in ('ready', 'loading')
    return svc.loaded()


# Names the route bodies and the handler mixin take from the server module.
SERVER_GLOBALS = ("BadBody", "GpuBusy", "ModelBusy", "openai_collect", "origin_allowed")

# What each hook group owns; the coverage test compares it with ROUTES.json.
COVERAGE: dict[str, tuple[str, ...]] = {
    "GET": (
        "/lab/benchmarks/api/",
        "/lab/benchmarks/",
        "/multimedia-capabilities",
        "/inference-backends",
        "/local-separation",
        "/local-speech",
        "/local-speech/library",
        "/local-speech/artifact/",
        "/local-audio",
        "/voicestudio/engines",
        "/open-webui/documents",
        "/open-webui",
        "/airllm",
        "/voicestudio/workspace",
        "/voicestudio/activities",
        "/voicestudio",
        "/voicestudio/voices",
        "/voicestudio/setup",
        "/harness/antigravity/status",
        "/local-training",
        "/updates/health",
        "/updates",
        "/local-export",
        "/optional-catalogue",
        "/benchmark-lab",
        "/power",
        "/catalogue",
        "/benchmarks",
        "/harness/mcp",
        "/harness/browser-mcp",
        "/harness/memory-mcp",
        "/harness/",
        "/updates/restart-pending",
        "/updates/restart",
        "/updates/restart-dismiss",
        "/chat/archive",
        "/api-monitor",
        "/v1/models",
        "/models",
        "/config",
        "/web/",
    ),
    "POST": (
        "/lab/benchmarks/",
        "/open-webui/prepare",
        "/open-webui/documents/upload",
        "/open-webui/documents/metadata",
        "/open-webui/documents/read",
        "/open-webui/documents/search-library",
        "/open-webui/documents/search",
        "/open-webui/documents/remove",
        "/open-webui/documents/attach",
        "/open-webui/documents/cancel",
        "/open-webui/documents/import-embedding",
        "/open-webui/context",
        "/airllm/prepare",
        "/airllm/rollback",
        "/chat/context/compact",
        "/voicestudio/audiobook/render",
        "/voicestudio/audiobook/cancel",
        "/voicestudio/launch",
        "/voicestudio/speech",
        "/voicestudio/connect-mcp",
        "/voicestudio/install",
        "/voicestudio/engine/select",
        "/voicestudio/web/start",
        "/voicestudio/stop",
        "/voicestudio/pronunciation",
        "/voicestudio/profile",
        "/voicestudio/job",
        "/harness/antigravity/web/start",
        "/harness/antigravity/web/stop",
        "/harness/antigravity/desktop",
        "/local-separation/stop",
        "/local-separation/run",
        "/local-speech/library/import",
        "/local-speech/library/export",
        "/local-speech/library/edit",
        "/local-speech/library/delete",
        "/updates/vendor-allowlist",
        "/updates/harness-install",
        "/updates/harness-activate",
        "/updates/harness-rollback",
        "/updates/health-check",
        "/updates/repair-missing",
        "/updates/validate-visual-python",
        "/updates/select-visual-python",
        "/updates/rollback-visual-python",
        "/updates/validate-document-python",
        "/updates/select-document-python",
        "/updates/rollback-document-python",
        "/updates/validate-inference-python",
        "/updates/validate-audio-python",
        "/updates/select-audio-python",
        "/updates/rollback-audio-python",
        "/updates/select-inference-python",
        "/updates/rollback-inference-python",
        "/updates/llama-gpu-activate",
        "/updates/llama-gpu-rollback",
        "/updates/soup-prepare",
        "/updates/soup-activate",
        "/updates/soup-rollback",
        "/updates/check",
        "/updates/stage",
        "/updates/cancel",
        "/updates/prepare",
        "/updates/validate",
        "/updates/activate",
        "/updates/rollback",
        "/updates/dependencies",
        "/updates/install-dependencies",
        "/updates/select-python",
        "/updates/rollback-python",
        "/updates/validate-python",
        "/updates/validate-inference",
        "/local-export/preflight",
        "/local-export/start",
        "/local-export/stop",
        "/local-speech/start",
        "/local-speech/stop",
        "/local-speech/generate",
        "/v1/audio/speech",
        "/local-audio/process",
        "/local-audio/start",
        "/local-audio/stop",
        "/local-audio/transcribe",
        "/v1/audio/transcriptions",
        "/v1/audio/translations",
        "/local-training/start",
        "/local-training/stop",
        "/local-training/preflight",
        "/local-training/upload",
        "/local-training/split",
        "/local-training/session",
        "/optional-catalogue/search",
        "/optional-catalogue/download",
        "/optional-catalogue/cancel",
        "/optional-catalogue/details",
        "/optional-catalogue/delete",
        "/harness/mcp",
        "/harness/browser-mcp",
        "/harness/memory-mcp",
        "/harness/claude/desktop",
        "/harness/claude/run",
        "/harness/claude/new-session",
        "/harness/",
        "/inference-backends/start",
        "/inference-backends/stop",
        "/inference-backends/chat",
        "/inference-backends/probe",
        "/inference-backends/context-plan",
        "/inference-backends/fit",
        "/inference-backends/rescan",
        "/benchmark-lab/start",
        "/benchmark-lab/stop",
        "/power",
        "/config",
        "/setup-download",
        "/switch-model",
        "/catalogue-inspect",
        "/catalogue-search",
        "/catalogue-fetch",
        "/chat/archive",
    ),
}

# GET routes that read user data or restart the process: they need the API key when the
# server was started with one (the dashboard sends it; a bare curl on a LAN does not).
PRIVATE_GET = (
    "/chat/archive",
    "/open-webui",
    "/open-webui/documents",
    "/voicestudio/engines",
    "/voicestudio/workspace",
    "/voicestudio/activities",
    "/updates/restart",
    "/updates/restart-pending",
    "/updates/restart-dismiss",
)

_SERVER = None            # the server module install() was called with
_INSTALLED = None         # idempotency: the same module is wired once


class HandlerMixin:
    """Handler methods the hooks and the live routes call that upstream 0.2.9 lacks."""
    def _weather_reply(self,req):
        if req.get('strata_web') is not True or req.get('strata_mcp') is not True or not self._mods_svc.mcp:return False
        from serve.weather_intent import intent,run
        args=intent(req.get('messages') or [])
        if not args:return False
        if not self._own_page('MCP tools can be used'):return True
        self._mods_svc.mcp.wait(10)
        selected=req.get('strata_tools')
        available=[t['name'] for t in self._mods_svc.mcp.template_tools() if selected is None or t['name'] in selected]
        weather=next((name for name in available if name.endswith('__weather_forecast')),None)
        if not weather:return False
        cancel=threading.Event();self._mods_cancel=cancel;self._watch_client(cancel)
        chunks=run(self._mods_svc.mcp,weather,args,self._mods_svc.model,cancel,english=str(req.get('strata_locale','')).startswith('en'))
        try:
            if not req.get('stream'):self._json(200,openai_collect(chunks));return True
            self._sse()
            for chunk in chunks:
                self.wfile.write(b'data: '+json.dumps(chunk,ensure_ascii=False).encode()+b'\n\n');self.wfile.flush()
            self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
        except OSError:cancel.set()
        finally:
            chunks.close()
            if self.watch_done:self.watch_done.set();self.watch_done=None
        return True

    def _optional_anthropic(self, req):
        from serve.claude_optional import to_openai, from_openai, stream_events
        if type(req.get('stream', False)) is not bool: raise ValueError('stream deve essere booleano')
        payload = to_openai(req)
        cancel = threading.Event()
        self._mods_cancel = cancel
        self._watch_client(cancel)
        if not self._mods_svc.optional_backends.conversation_lock.acquire(False): raise ModelBusy('Una richiesta del backend è già in corso')
        events = None
        try:
            events = self._mods_svc.optional_backends.chat(payload, cancel)
            response = next(events, None)
            if cancel.is_set():return
            if response is None: raise ValueError('Risposta vuota dal backend')
            for _ in events: pass
            message = from_openai(response, req['model'])
        finally:
            cancel.set()
            if events is not None: events.close()
            self._mods_svc.optional_backends.conversation_lock.release()
            if self.watch_done: self.watch_done.set(); self.watch_done = None
        if not req.get('stream'):
            self._json(200, message); return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'close')
        self._cors(); self.end_headers(); self.close_connection = True
        for name, event in stream_events(message):
            self.wfile.write(('event: '+name+'\ndata: '+json.dumps(event)+'\n\n').encode('utf-8'))
            self.wfile.flush()

    def _optional_chat(self,payload):
        cancel=threading.Event();self._mods_cancel=cancel;events=None;streaming=False
        self._watch_client(cancel)
        reserved=False
        try:
            reserved=self._mods_svc.optional_backends.conversation_lock.acquire(blocking=False)
            if not reserved:raise RuntimeError('Una richiesta del backend è già in corso')
            if type(payload.get('stream',False)) is not bool:raise ValueError('stream deve essere booleano')
            generation_defaults={key:value for key,value in self._mods_svc.optional_backends.state.get('inference_profile',{}).items() if key in ('temperature','top_p','max_tokens')}
            payload={**generation_defaults,**payload,'stream':payload.get('stream',False)}
            configured=self._mods_svc.optional_backends.state.get('inference_profile',{}).get('tools')
            if configured is not None:
                requested=payload.get('strata_tools',configured)
                if not isinstance(requested,list):raise ValueError('Selezione strumenti non valida')
                payload['strata_tools']=[name for name in requested if name in configured]
            use_tools = payload.get('strata_mcp') is True and getattr(self._mods_svc,'mcp',None) is not None
            if use_tools:
                self._mods_svc.mcp.wait(10)
                from serve.optional_tools import chat_with_tools
                events=chat_with_tools(self._mods_svc.optional_backends,self._mods_svc.mcp,payload,cancel)
            else:
                events=self._mods_svc.optional_backends.chat(payload,cancel)
            first=next(events,None)
            if cancel.is_set():return
            if not payload.get('stream',False):
                if first is None:raise RuntimeError('Risposta vuota dal backend')
                if use_tools:
                    collected=openai_collect(iter([first,*events]))
                    self._mods_svc.optional_backends.conversation_lock.release();reserved=False
                    self._json(200,collected);return
                for _ in events:pass
                self._mods_svc.optional_backends.conversation_lock.release();reserved=False
                self._json(200,first);return
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Cache-Control','no-cache')
            self.send_header('Connection','close')
            self._cors();self.end_headers();self.close_connection=True;streaming=True
            def emit(event):
                self.wfile.write(('data: '+json.dumps(event,ensure_ascii=False)+'\n\n').encode('utf-8'));self.wfile.flush()
            if first is not None:emit(first)
            for event in events:emit(event)
            self._mods_svc.optional_backends.conversation_lock.release();reserved=False
            self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError):cancel.set()
        except Exception as exc:
            if streaming:
                try:
                    self.wfile.write(('data: '+json.dumps({'error':{'message':str(exc)}})+'\n\n').encode());self.wfile.flush()
                except OSError:pass
            else:self._json(400 if isinstance(exc,(ValueError,TypeError)) else 409,{'error':{'message':str(exc)}})
        finally:
            cancel.set()
            if events is not None:events.close()
            if reserved:self._mods_svc.optional_backends.conversation_lock.release()
            if self.watch_done:self.watch_done.set();self.watch_done=None


def install(server_module) -> None:
    """Wire the hooks into a server module without editing upstream files.

    Idempotent: a second call for the same module does nothing, so a reload or a
    test that imports the module twice cannot wrap `Service.__init__` twice.
    """
    global _SERVER, _INSTALLED
    if _INSTALLED is server_module:
        return
    _SERVER = server_module
    globals()["ROOT"] = getattr(server_module, "ROOT", ROOT)
    for name in SERVER_GLOBALS:
        if not hasattr(server_module, name):
            raise AttributeError(f"mods.hooks: the server module has no {name!r}; the hook contract changed")
        globals()[name] = getattr(server_module, name)
    # live-only symbol our modules import from serve.server (upstream 0.2.9 has none)
    server_module.agent_harness_for = agent_harness_for
    from mods import service as _mods_service
    _mods_service.install(server_module)          # model management / resources / vision

    original_init = server_module.Service.__init__
    if not getattr(original_init, "_mods_hooked", False):
        def __init__(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            install_managers(self)
            start_harness_idle_stop(self)
        __init__._mods_hooked = True
        server_module.Service.__init__ = __init__

    original_make_handler = server_module.make_handler
    if not getattr(original_make_handler, "_mods_hooked", False):
        def make_handler(svc):
            base = original_make_handler(svc)

            class HookedHandler(HandlerMixin, base):
                """Hooks first, upstream second; the handler API is upstream's."""

                _mods_svc = svc

                def do_GET(self):
                    path = self.path.split("?")[0].rstrip("/")
                    if handle_get(self, svc, path):
                        return
                    super().do_GET()

                def do_POST(self):
                    # live do_POST opened with `if not self._authorized(): return`;
                    # upstream's own check runs only after the hooks, so repeat it here.
                    if not self._authorized():
                        return
                    path = self.path.split("?")[0].rstrip("/")
                    # an Anthropic client given ".../v1" as its base posts /v1/v1/messages
                    path = getattr(_SERVER, "V1_V1_ALIASES", {}).get(path, path)
                    try:
                        if handle_post(self, svc, path):
                            return
                    except BadBody as exc:
                        # hooks run before upstream's try/except: a malformed or oversized
                        # body must still get its status line, not a dropped connection
                        self._json(exc.status, {"error": {"type": "invalid_request_error", "message": str(exc)}})
                        return
                    finally:
                        # upstream drops its own cancel in _post's finally; a hook path
                        # never reaches it, so the set grew one entry per request
                        cancel = getattr(self, "_mods_cancel", None)
                        active = getattr(svc, "active_cancels", None)
                        if cancel is not None and active is not None:
                            active.discard(cancel)
                    super().do_POST()

                def _openai(self, req):
                    # the live line answers a weather question from its own MCP tool
                    if req.get("model", svc.model) in svc.model_names() and self._weather_reply(req):
                        return
                    return super()._openai(req)

                def _own_page(self, what):
                    # A GET cannot change state, so the JSON content type upstream demands
                    # on every method is not required here (a browser sends none). The
                    # origin evidence still is: a page elsewhere (<img>, <a>, fetch) sends
                    # Sec-Fetch-Site cross-site/same-site and must not reach /updates/restart.
                    if self.command in ("GET", "HEAD"):
                        if self._foreign_origin():
                            self._json(403, {"error": {"message": f"{what} only from Strata's own page (or an origin "
                                                                  f"in the config's trusted_origins)"}})
                            return False
                        if self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
                            self._json(403, {"error": {"message": f"{what} only from Strata's own page"}})
                            return False
                        return True
                    return super()._own_page(what)

                def _foreign_page(self, allow_multipart=False):
                    # upstream 0.2.9's _foreign_page takes no multipart flag, but the
                    # live /v1/audio routes pass one; this is the live body unchanged.
                    origin = self.headers.get("Origin")
                    if svc.api_key or not origin:
                        return False
                    if not origin_allowed(origin, self.headers.get("Host"), svc.host_names,
                                          [*svc.trusted_origins, *svc.cors_origins]):
                        print(f"[strata] refused an API request from the web page {origin!r} (no API key; add its host to "
                              "'allowed_hosts' or its origin to 'cors_origins' in the config)", flush=True)
                        self._json(403, {"error": {"type": "forbidden", "message":
                                         f"web pages of {origin} may not use this server without an API key; set 'api_key', "
                                         "or add the page's host to 'allowed_hosts' (or its origin to 'cors_origins') "
                                         "in the config"}})
                        return True
                    content_type = self.headers.get("Content-Type", "")
                    if not content_type.startswith("application/json") and not (
                            allow_multipart and content_type.startswith("multipart/form-data;")):
                        self._json(415, {"error": {"message": "send application/json"}})
                        return True
                    return False

            if not hasattr(base, "_read_body"):
                # live name for upstream's _body(); shared and hook bodies call it. Upstream
                # reads the request body again later, so the bytes are cached for it.
                def _read_body(self):
                    cached = getattr(self, "_mods_body", None)
                    if cached is None:
                        cached = self._body()
                        self._mods_body = cached
                        self._body = lambda: cached
                    return cached
                HookedHandler._read_body = _read_body
            return HookedHandler
        make_handler._mods_hooked = True
        server_module.make_handler = make_handler

    original_serve = server_module.serve
    if not getattr(original_serve, "_mods_hooked", False):
        def serve(svc, *args, **kwargs):
            httpd = original_serve(svc, *args, **kwargs)
            after_serve(svc, httpd)
            return httpd
        serve._mods_hooked = True
        server_module.serve = serve

    original_main = server_module.main
    if not getattr(original_main, "_mods_hooked", False):
        def main(*args, **kwargs):
            root = getattr(_SERVER, "ROOT", ROOT)      # a test can point the server at a temp root
            port = port_from_argv()
            if port <= 0:                              # an ephemeral test port owns no dashboard
                return original_main(*args, **kwargs)
            if os.environ.get("STRATA_SOURCE_UPDATE_CHECK") == "1":
                # source_update starts a second server on the same root for its health
                # check; the dashboard guard is root-scoped and would refuse it
                return original_main(*args, **kwargs)
            claim_dashboard(root, port)
            try:
                return original_main(*args, **kwargs)
            finally:
                from serve.dashboard_guard import release_dashboard_claim
                release_dashboard_claim(root)
        main._mods_hooked = True
        server_module.main = main

    original_close = server_module.Server.server_close
    if not getattr(original_close, "_mods_hooked", False):
        def server_close(self):
            try:
                original_close(self)
            finally:
                service = getattr(self, "owned_service", None)
                # the normal benchmark lab first (install_managers creates it); the hydra
                # lab only exists under HYDRA_LAB_MODE, and it is a different object
                benchmark_lab = getattr(service, "benchmark_lab", None)
                if benchmark_lab is not None:
                    try:
                        benchmark_lab.close()
                    except Exception:
                        pass
                lab = getattr(service, "_hydra_benchmark_lab", None)
                if lab is not None:
                    lab.close()
                automatic = getattr(service, "automatic_updates", None)
                if automatic is not None:
                    automatic.close()
                telemetry = getattr(self, "owned_telemetry", None)
                if telemetry is not None:
                    telemetry.close()
                    self.owned_telemetry = None
                    if service is not None and getattr(service, "telemetry", None) is telemetry:
                        service.telemetry = None
        server_close._mods_hooked = True
        server_module.Server.server_close = server_close
    _INSTALLED = server_module


def claim_dashboard(root, port) -> None:
    """The live line's startup guard: one dashboard per PC, or a clear refusal."""
    from serve.dashboard_guard import claim_dashboard as claim, release_dashboard_claim, DashboardBusy
    try:
        claim(root, port)
    except DashboardBusy as busy:
        raise SystemExit(f"[strata] {busy}")
    import atexit
    atexit.register(lambda: release_dashboard_claim(root))


def config_path_from_argv(argv=None) -> str | None:
    """The --config our run scripts pass (the Control tab edits that file)."""
    args = list(sys.argv[1:] if argv is None else argv)
    for i, value in enumerate(args):
        if value == "--config" and i + 1 < len(args):
            return args[i + 1]
        if value.startswith("--config="):
            return value.split("=", 1)[1]
    return None


def port_from_argv(argv=None) -> int:
    """The --port our run scripts pass; the server's default when the flag is absent."""
    args = list(sys.argv[1:] if argv is None else argv)
    for i, value in enumerate(args):
        if value == "--port" and i + 1 < len(args):
            try:
                return int(args[i + 1])
            except ValueError:
                break
        if value.startswith("--port="):
            try:
                return int(value.split("=", 1)[1])
            except ValueError:
                break
    return 8095


def after_serve(svc, httpd) -> None:
    """The live serve() wiring upstream 0.2.9 does not do: the dashboard port, the
    automatic updater, the restart that /updates/restart asks for, and the run config
    on the Service (upstream keeps it local to main(), our Control tab needs it)."""
    port = getattr(httpd, "server_address", (None, None))[1]
    svc.dashboard_port = port
    svc.port = port
    httpd.owned_service = svc
    path = config_path_from_argv()
    if path and not getattr(svc, "cfg", None):
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
            parser = getattr(_SERVER, "parse_config_text", None)
            svc.cfg = parser(text, path) if parser else json.loads(text)
            svc.cfg_path = path
        except (OSError, ValueError) as error:
            print(f"[strata] the run config {path} could not be read ({error}); "
                  "the Control tab will show no budget until it is fixed", flush=True)
    if getattr(svc, "update_center", None) is not None:
        svc.update_center.port = port
        if getattr(svc.update_center, "harness_updates", None) is not None:
            svc.update_center.harness_updates.port = port
        if getattr(svc, "automatic_updates", None) is None:
            from serve.automatic_updates import AutomaticUpdates
            svc.automatic_updates = AutomaticUpdates(svc)
    if getattr(svc, "optional_backends", None) is not None:
        svc.optional_backends.dashboard_port = port
    svc.automatic_restart = _automatic_restart(port)


def _automatic_restart(port):
    def automatic_restart():
        import subprocess
        from serve.update_restart import restart_command
        command = [sys.executable, *getattr(sys, "orig_argv", [sys.executable, *sys.argv])[1:]]
        restart_command(command, port)
        subprocess.Popen([sys.executable, str(ROOT / "tools/restart_dashboard.py"), "--pid", str(os.getpid()),
                          "--root", str(ROOT), "--", *command], cwd=ROOT, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
        threading.Thread(target=lambda: (time.sleep(1.5), os._exit(0)), daemon=True).start()
    return automatic_restart


def install_managers(svc) -> None:
    """Create the custom managers on a Service built by upstream's __init__."""
    if getattr(svc, "update_center", None) is not None:
        return                      # a server module that still creates them itself
    from serve.benchmark_lab import BenchmarkLab
    svc.benchmark_lab = BenchmarkLab(ROOT)
    from serve.optional_backends import OptionalBackends
    from serve.server import MockEngine
    svc.optional_backends = OptionalBackends(ROOT, discover_models=not isinstance(svc.engine, MockEngine))
    svc.optional_backends.graph_config = lambda: (getattr(svc, 'cfg', {}) or {}).get('hydra_graph_inference', {})
    svc.optional_backends.memory_snapshot = lambda: svc.telemetry.snapshot() if getattr(svc, 'telemetry', None) else {}
    from serve.optional_benchmark import OptionalBenchmark
    svc.optional_benchmark = OptionalBenchmark(svc.optional_backends)
    from serve.optional_catalogue import OptionalCatalogue
    svc.optional_catalogue = OptionalCatalogue(svc.optional_backends)
    from serve.local_training import LocalTraining
    svc.local_training = LocalTraining(svc.optional_backends)
    from serve.local_export import LocalExport
    svc.local_export = LocalExport(svc.optional_backends)
    from serve.update_center import UpdateCenter
    svc.update_center = UpdateCenter(ROOT, port=getattr(svc, 'port', None))
    svc.update_center.operational_idle = lambda: not _native_model_loaded(svc) and svc.optional_backends.status()['status'] == 'idle' and svc.local_audio.status()['status'] == 'idle' and svc.local_speech.status()['status'] == 'idle' and not svc.local_separation.lock.locked() and not (ROOT / 'data/.gpu-campaign.lock').exists()
    svc.update_center.configuration_provider = lambda: getattr(svc, 'cfg_path', None)
    svc.update_center.installed_provider = lambda: {'strata': {'installed_version': svc.engine.info['version'], 'installed_source': 'engine_reported_version'}} if getattr(svc.engine, 'info', {}).get('version') else {}
    from serve.local_audio import LocalAudio
    svc.local_audio = LocalAudio(ROOT)
    from serve.local_speech import LocalSpeech
    svc.local_speech = LocalSpeech(ROOT)
    from serve.local_separation import LocalSeparation
    svc.local_separation = LocalSeparation(ROOT)
    from serve.local_visual_generation import LocalVisualGeneration
    svc.local_visual = LocalVisualGeneration(svc.optional_backends)
    from serve.local_generative_audio import LocalGenerativeAudio
    svc.local_generative_audio = LocalGenerativeAudio(ROOT)
    from serve.audiocraft_setup import AudioCraftSetup
    svc.audiocraft_setup = AudioCraftSetup(ROOT)
    previous_idle = svc.update_center.operational_idle
    svc.update_center.operational_idle = lambda: previous_idle() and not svc.local_visual.status()['busy'] and not svc.local_generative_audio.status()['busy'] and not svc.audiocraft_setup.status()['busy']
    from serve.voicestudio import VoiceStudio
    svc.voicestudio = VoiceStudio(ROOT)
    from serve.unsloth_workspace import UnslothWorkspace
    svc.unsloth_workspace = UnslothWorkspace(ROOT, svc.update_center.operational_idle)
    from serve.colibri_workspace import ColibriWorkspace
    svc.colibri_workspace = ColibriWorkspace(ROOT, svc.update_center.operational_idle)
    svc.optional_backends.external_api_lease = svc.colibri_workspace.api_lease_matches
    svc.optional_backends.external_api_metadata = svc.colibri_workspace.api_metadata
    svc.native_workspace = None
    svc.automatic_updates = None
    from serve.antigravity_web import OriginalWeb
    svc.antigravity_web = OriginalWeb(ROOT, busy=lambda: svc.optional_backends.request_lock.locked())
    import atexit
    atexit.register(svc.antigravity_web.close)
    from serve.local_integration_jobs import AirLLMSetup
    svc.airllm_setup = AirLLMSetup(ROOT, lambda: svc.update_center.operational_idle() and svc.update_center.job.get('state') not in ('downloading', 'preparing', 'validating', 'resolving', 'installing_candidate', 'validating_python') and svc.update_center.harness_updates.status().get('state') != 'installing')
    from serve.local_integration_jobs import OpenWebUISetup
    svc.open_webui_setup = OpenWebUISetup(ROOT, lambda: svc.airllm_setup.idle())
    idle_before_integrations = svc.update_center.operational_idle
    svc.update_center.operational_idle = lambda: idle_before_integrations() and svc.airllm_setup.job['state'] != 'preparing' and not svc.voicestudio._busy.locked()
    from serve.power_manager import PowerManager, PowerConfig
    svc.power_manager = PowerManager(PowerConfig(mode="balanced"))


def start_harness_idle_stop(svc):
    """Release harnesses that nobody used for a while.

    A harness is only stopped when it is ready, its activity is readable and it reports no
    open session. Conversation archives live in data/<kind>-home on disk, so nothing is
    lost: the harness starts again from the same home. Enabled with
    STRATA_HARNESS_IDLE_STOP=<seconds>; disabled by default.
    """
    try:
        budget = float(os.environ.get("STRATA_HARNESS_IDLE_STOP", "0") or 0)
    except ValueError:
        print("[strata] STRATA_HARNESS_IDLE_STOP is not a number of seconds; idle release is off", flush=True)
        return
    if not budget:
        return

    def loop():
        while True:
            time.sleep(max(30.0, min(300.0, budget / 4)))
            for kind in ("opencode", "dsh", "trueforge", "hermes"):
                attr = {"opencode": "agent_harness", "dsh": "agent_harness_dsh",
                        "trueforge": "agent_harness_trueforge", "hermes": "agent_harness_hermes"}[kind]
                if getattr(svc, attr, None) is None:
                    continue            # never built: nothing to release, and do not build it here
                try:
                    harness = agent_harness_for(svc, kind)
                    if not harness.idle_stop_s:
                        harness.idle_stop_s = budget
                    if not harness.idle_should_stop():
                        continue
                    harness.stop()
                    print(f"[strata] {kind} released after {budget:.0f}s without use", flush=True)
                except Exception as error:                     # a failing kind must not stop the loop
                    print(f"[strata] idle release of {kind}: {error}", flush=True)

    threading.Thread(target=loop, daemon=True).start()


def agent_harness_for(svc, kind="opencode", host=None):
    """Lazily build one agent-harness manager (`opencode` or `dsh`) beside Strata.

    Built on first use, not in Service.__init__, so a server that never opens a Harness
    tab pays nothing and never imports serve.agent_harness (which pulls psutil through
    gpu_lease). Each harness is fed by this same server's model and by the same MCP servers
    the chat page uses; its own config is written under data/.
    """
    kinds = {"claude": ("agent_harness_claude", 0), "opencode": ("agent_harness", 4096), "dsh": ("agent_harness_dsh", 3080),"trueforge":("agent_harness_trueforge",8790),"hermes":("agent_harness_hermes",9120)}
    if kind not in kinds:
        kind = "opencode"
    attr, port = kinds[kind]
    # the lookup is quick; building a harness (proxy, imports, file writes) must not
    # hold status_lock: it is the same lock as admission, /metrics and every status read
    with svc.status_lock:
        harness = getattr(svc, attr, None)
    if harness is not None:
        if not harness.status().get('busy'):
            from serve.harness_model import local_selection
            selection = local_selection(svc)
            if kind=='claude':
                harness.model='strata'
                harness.context_budget=selection['context']
                harness.output_budget=selection['output']
            else:harness.model_id = 'strata'
            harness.model_context = selection['context']
            harness.model_output = selection['output']
            harness.api_key = svc.api_key
        return harness
    from serve.agent_harness import AgentHarness
    # the origin a harness must trust is this server's own bound address, never the
    # request's Host header: with an API key upstream skips its Host check, so a client
    # could otherwise point the harness at another host and persist that under data/
    bound = getattr(svc, "port", None) or 8080
    name = (urlsplit(f"http://{host}").hostname if host else None) or "127.0.0.1"
    known = {str(n).lower() for n in (getattr(svc, "host_names", None) or ())}
    if known and name.lower() not in known:
        name = "127.0.0.1"
    page = f"http://[{name}]:{bound}" if ":" in name else f"http://{name}:{bound}"
    if bound == 8090:
        port += 100
    from serve.headroom_integration import ensure_proxy
    inference_base = ensure_proxy(ROOT, page)
    if kind == 'claude':
        from serve.claude_harness import ClaudeHarness
        harness = ClaudeHarness(ROOT, base_url=inference_base, model_id='strata', api_key=svc.api_key)
        from serve.harness_model import local_selection
        selection=local_selection(svc)
        harness.model='strata'
        harness.context_budget=selection['context']
        harness.output_budget=selection['output']
        with svc.status_lock:
            existing = getattr(svc, attr, None)
        if existing is not None:
            return existing
        setattr(svc, attr, harness)
        return harness
    from serve.harness_model import local_selection
    selection = local_selection(svc)
    harness = AgentHarness(
        ROOT, kind=kind, port=port, api_key=svc.api_key, model_id="strata",
        cors_origin=page if kind == "opencode" else None,
        base_url=inference_base+"/v1",
        model_context=selection["context"],
        model_output=selection["output"],
    )
    with svc.status_lock:
        existing = getattr(svc, attr, None)
    if existing is not None:
        return existing
    setattr(svc, attr, harness)
    return harness


def handle_get(handler, svc, path) -> bool:
    """True when a custom route answered; False means upstream's do_GET runs."""
    # these read user data (archive, documents, voices) or restart the process; with an
    # API key the dashboard's fetch sends it, a LAN or tunnel client without it gets 401
    if path in PRIVATE_GET and not handler._authorized():
        return True
    # nested /web/ files (vendor, locales) are upstream's whitelisted subtrees; our
    # flat-file block below rejects a "/" and would shadow them with a 404
    if path.startswith("/web/") and ("/" in path[len("/web/"):] or "\\" in path[len("/web/"):]):
        return False
    # the live /harness/ catch-all returns True even when it wrote nothing, which
    # closes the connection with no answer; unknown harness paths fall to upstream
    if path.startswith("/harness/"):
        parts = path.split("/")
        known = ((len(parts) == 4 and parts[2] in ("opencode", "dsh", "trueforge", "hermes", "claude", "superara")
                  and parts[3] == "status")
                 or path in ("/harness/codex/status", "/harness/codex/terminal", "/harness/claude/terminal")
                 or path == "/harness/antigravity/status"
                 or path in ("/harness/mcp", "/harness/browser-mcp", "/harness/memory-mcp"))
        if not known:
            return False
    if os.environ.get('HYDRA_LAB_MODE')!='1' and path.startswith('/lab/benchmarks/api/'):
        if not handler._authorized():return True
        from serve.hydra_lab_integration import readonly_route
        try:readonly_route(handler,ROOT,path)
        except (ValueError,OSError) as exc:handler._json(404,{'error':str(exc)})
        return True

    if os.environ.get('HYDRA_LAB_MODE')=='1' and path.startswith('/lab/benchmarks/'):
        from serve.hydra_lab_integration import route,service_lab
        try:route(handler,service_lab(svc),'GET',path)
        except (OSError,ValueError) as exc:handler._json(503,{'error':str(exc)})
        return True

    from serve.hydra_native import route as hydra_native_route
    if hydra_native_route(handler,svc,path):return True

    from serve.codex_original import route as codex_original_route
    if codex_original_route(handler,svc,path):return True

    from serve.groq_voice import route as groq_voice_route
    if groq_voice_route(handler,svc,path):return True

    from serve.cloud_providers import route as cloud_provider_route
    if cloud_provider_route(handler,svc,path):return True

    from serve.original_harness_routes import get as original_get
    if original_get(handler,svc,path):return True

    from serve.generation_routes import get as generation_get
    if generation_get(handler,svc,path):return True

    from serve.native_workspace_routes import get as native_get
    if native_get(handler,svc,path):return True

    from serve.automatic_update_routes import get as automatic_get
    if automatic_get(handler,svc,path):return True

    from serve.model_engine_routes import get as model_engine_get
    if model_engine_get(handler,svc,path):return True

    if path == '/multimedia-capabilities':
        if handler._authorized():
            from serve.multimedia_capabilities import capabilities
            handler._json(200,capabilities(svc))
        return True

    if path == '/inference-backends':
        if handler._authorized():handler._json(200,svc.optional_backends.status())
        return True

    if path == '/local-separation':
        if handler._authorized():handler._json(200,svc.local_separation.status())
        return True

    if path == '/local-speech':
        if handler._authorized():handler._json(200,svc.local_speech.status())
        return True

    if path == '/local-speech/library' or path.startswith('/local-speech/artifact/'):
        if not handler._authorized():return True
        from serve.audio_library import AudioLibrary
        library=AudioLibrary(ROOT)
        try:
            if path.endswith('/library'):handler._json(200,{'items':library.list(),'limit_items':100,'limit_bytes':1024**3})
            else:
                data=library.read(path.removeprefix('/local-speech/artifact/'))
                handler.send_response(200);handler.send_header('Content-Type','audio/wav');handler.send_header('Content-Length',str(len(data)));handler.send_header('Cache-Control','private, no-store');handler.end_headers();handler.wfile.write(data)
        except (OSError,ValueError) as error:handler._json(404,{'error':{'message':str(error)}})
        return True

    if path == '/local-audio':
        if handler._authorized():handler._json(200,svc.local_audio.status())
        return True

    if path == '/voicestudio/engines':
        try:handler._json(200,svc.voicestudio.engines())
        except (OSError,RuntimeError,ValueError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/open-webui/documents':
        from serve.open_webui_runtime import library as open_webui_library
        handler._json(200,open_webui_library(ROOT));return True

    if path == '/open-webui':
        from serve.open_webui_runtime import status as open_webui_status
        handler._json(200,svc.open_webui_setup.status());return True

    if path == '/airllm':
        if handler._authorized():handler._json(200,svc.airllm_setup.status())
        return True

    if path == '/voicestudio/workspace':
        if not handler._own_page('Profili vocali di questa pagina'):return True
        try:handler._json(200,svc.voicestudio.workspace())
        except (OSError,RuntimeError,ValueError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/voicestudio/activities':
        if not handler._own_page('Attività vocali di questa pagina'):return True
        try:handler._json(200,svc.voicestudio.activities())
        except (OSError,RuntimeError,ValueError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path in ('/voicestudio','/voicestudio/voices','/voicestudio/setup'):
        if not handler._authorized():return True
        try:handler._json(200,svc.voicestudio.voices() if path.endswith('/voices') else svc.voicestudio.setup() if path.endswith('/setup') else svc.voicestudio.status())
        except (OSError,RuntimeError,ValueError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/harness/antigravity/status':
        if handler._authorized():
            from serve.antigravity_desktop import status
            handler._json(200,{'status':'desktop','desktop':status(ROOT),'web':svc.antigravity_web.status()})
        return True

    if path == '/local-training':
        if handler._authorized():handler._json(200,svc.local_training.status())
        return True

    if path == '/updates/health':
        if handler._authorized():handler._json(200,svc.update_center.dependency_supervisor.status())
        return True

    if path == '/updates':
        if handler._authorized():handler._json(200,svc.update_center.status())
        return True

    if path == '/local-export':
        if handler._authorized():handler._json(200,svc.local_export.status())
        return True

    if path == '/optional-catalogue':
        if handler._authorized():handler._json(200,svc.optional_catalogue.status())
        return True

    if path == '/benchmark-lab':
        if handler._authorized():
            # In the mock shell the native engine is always "alive"; only an optional
            # backend that really holds a model means the GPU is occupied.
            data=svc.benchmark_lab.status();data['operational_loaded']=_native_model_loaded(svc)
            optional=svc.optional_backends.status();job,history=svc.optional_benchmark.status()
            data['optional_ready']=optional['status']=='ready'
            if data['optional_ready']:
                active_name=next((m['name'] for m in optional.get('local_models',[]) if m.get('path')==optional.get('model_path')),optional['public_model'])
                data['models'].insert(0,dict(id='optional_active',label=active_name+' · '+optional.get('backend','Motore locale')+' · '+optional['device_requested'],ready=True))
            for model in optional.get('local_models',[]):
                if model.get('runtime_supported') is False:continue
                # A native Strata pack needs the Strata engine, not llama.cpp:
                # offering it here only invites a failed load (and a huge RAM hit).
                if model.get('required_engine')=='strata':continue
                if data['optional_ready'] and model['path']==optional.get('model_path'):continue
                data['models'].append(dict(id='optional_local:'+model['path'],label=model['name']+' · '+model.get('format','GGUF')+' · Unsloth',ready=True,requires_load=True))
            from serve.benchmark_state import merge_benchmark_state
            data=merge_benchmark_state(data,job,history,optional.get('public_model') if data['optional_ready'] else None)
            handler._json(200,data)
        return True

    if path == "/power":
        if handler._authorized():
            handler._json(200, svc.power_manager.get_state().__dict__ | {
                "mode": svc.power_manager.config.mode,
                "temp_limit": svc.power_manager.config.temp_limit(),
                "power_limit": svc.power_manager.config.power_limit(),
                "history": [s.__dict__ for s in svc.power_manager.get_history()],
            })
        return True

    if path == "/catalogue":
        if handler._authorized():
            handler._json(200, svc.catalogue_state())
        return True

    if path == "/benchmarks":
        if handler._authorized():
            from serve.diagnostics import benchmark_reports
            from serve.benchmark_records import best_groups
            result=benchmark_reports(ROOT)
            from serve.optional_reports import reports as optional_reports
            optional_rows=optional_reports(ROOT)
            result['reports'] += optional_rows
            if os.environ.get('HYDRA_LAB_MODE')=='1' and os.environ.get('HYDRA_LAB_PROFILE'):
                from serve.hydra_lab_integration import existing_reports,service_lab
                rows=existing_reports(service_lab(svc).benchmarks)
                present={r.get('hydra_run_id') for r in result['reports']}
                result['reports'] += [r for r in rows if r['hydra_run_id'] not in present]
            result['best_groups']=best_groups(ROOT,svc.model)
            optional=svc.optional_backends.status()
            from serve.optional_reports import best_groups as optional_best
            groups=optional_best(optional_rows,optional['public_model']) if optional['status']=='ready' else []
            # Saved optional reports must survive stopping the backend: fall back to
            # the model of the newest report instead of hiding the record card.
            if not groups and optional_rows:
                groups=optional_best(optional_rows,optional_rows[0]['model'])
            if groups:result['best_groups']=groups
            handler._json(200, result)
        return True

    if path in ('/harness/mcp','/harness/browser-mcp','/harness/memory-mcp'):
        handler._json(405,{'error':{'message':'This stateless MCP bridge accepts POST only'}});return True

    if path.startswith("/harness/"):
        # one agent harness beside Strata (the Harness tabs): installed? running? where?
        parts = path.split("/")
        if len(parts) == 4 and parts[2] in ("opencode", "dsh", "trueforge", "hermes", "claude") and parts[3] == "status":
            if handler._authorized():
                from serve.harness_model import local_selection
                snapshot = {**agent_harness_for(svc, parts[2], handler.headers.get("Host")).status(), 'binding': local_selection(svc)}
                if parts[2] == 'claude':
                    from serve.claude_desktop import status as desktop_status
                    snapshot['desktop'] = desktop_status(ROOT)
                handler._json(200, snapshot)
        return True

    if path in ('/updates/restart-pending','/updates/restart','/updates/restart-dismiss'):
        if not handler._own_page('riavvio dopo aggiornamento gestito da questa pagina'):return True
        from serve.update_restart import restart_pending,clear_restart_pending,restart_command
        if path.endswith('/dismiss'):
            handler._json(200,{'dismissed':bool(clear_restart_pending(ROOT))});return True
        if path.endswith('/restart-pending'):
            pending=restart_pending(ROOT)
            handler._json(200,{'pending':pending});return True
        import subprocess,sys
        try:
            if not svc.update_center.operational_idle() or not svc.automatic_updates.activities_idle():raise ValueError('Il riavvio attende la fine delle attività in corso')
            pending=restart_pending(ROOT)
            if pending:pending['restarting']=True
            handler._json(202,{'restarting':True,'component':(pending or {}).get('component')})
            handler.wfile.flush()
        except (OSError,RuntimeError,ValueError) as error:
            handler._json(400,{'error':{'message':str(error)}});return True
        # The new process starts only after this one released the port.
        try:
            svc.automatic_restart()
        except (OSError,RuntimeError,ValueError) as error:
            print(f"[strata] restart requested but could not start: {error}", flush=True)
        return True

    if path == '/chat/archive':
        # Durable copy of the browser's chat archive: a lost profile or a private
        # window must never cost a conversation.
        if not handler._own_page('archivio conversazioni gestito da questa pagina'):return True
        from serve.chat_archive import read_archive,save_archive
        if handler.command=='POST':
            if not 0<int(handler.headers.get('Content-Length',0))<=24*1024**2:
                handler._json(413,{'error':{'message':'Archivio conversazioni oltre il limite'}});return True
            try:
                rows=json.loads(handler._read_body())
                if not isinstance(rows,list):raise ValueError('Atteso un elenco di conversazioni')
                count=save_archive(ROOT,rows)
                handler._json(200,{'saved':count})
            except (OSError,RuntimeError,ValueError) as error:handler._json(400,{'error':{'message':str(error)}})
            return True
        handler._json(200,{'conversations':read_archive(ROOT)})
        return True

    if path == "" or (path == "/api-monitor" and svc.api_monitor):
        from serve.web_asset_versions import versioned_html
        body = versioned_html(ROOT / "serve" / "web" / ("monitor.html" if path else "index.html"))
        if os.environ.get("HYDRA_LAB_MODE")=="1":
            from serve.hydra_lab_integration import render_lab_html
            body=render_lab_html(body)
        from serve.hydra_lab_integration import history_html
        body=history_html(body,ROOT)
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        # No caching on the page itself: without this the browser keeps serving an older
        # dashboard (older markup, older metrics) while the files on disk are current.
        handler.send_header("Cache-Control", "no-cache, must-revalidate")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return True

    if path in ("/v1/models", "/models"):
        if handler._authorized():
            loaded = svc.loaded()
            model = {"id": svc.model, "object": "model", "status": {"value": "loaded"},
                     "meta": {"n_ctx": svc.engine.max_context},
                     "architecture": {"input_modalities": ["text", "image"] if svc.vision is not None else ["text"],
                                      "output_modalities": ["text"]}}
            if not loaded and (svc.idle_unload_s or getattr(svc.engine, "unloaded", False)):
                model["status"] = {"value": "unloaded"}   # like llama-server's router: listed, loads on use
                loaded = True
            if svc.aliases:                       # #297: the aliases, and each one listed under its own id
                model["aliases"] = list(svc.aliases)
            data = [model, *({**model, "id": x, "alias_of": svc.model} for x in svc.aliases)]
            data=data if loaded else []
            optional=svc.optional_backends.status()
            if optional['status']=='ready':data.append({'id':optional['public_model'],'object':'model','owned_by':'local','status':{'value':'loaded'}})
            from serve.harness_model import local_selection
            selection=local_selection(svc)
            data=[row for row in data if row['id']!='strata']
            if loaded or optional.get('status')=='ready':
                data.append({'id':'strata','object':'model','alias_of':selection['model'],
                             'meta':{'n_ctx':selection['context']},'owned_by':'local',
                             'status':{'value':'loaded' if optional.get('status')=='ready' or svc.loaded() else 'unloaded'}})
            from serve.claude_desktop import gateway_models
            handler._json(200, {"object": "list", "data": gateway_models(data)})
        return True

    if path == "/config":
        if handler._authorized():
            handler._json(200, {**svc.resource_state(), "setup": svc.setup_state(),
                             "prepared": svc.prepared_models()})
        return True

    if path.startswith("/web/"):
        # the web app's own files (serve/web): styles, script, icon sprite - same origin, no CDN
        name = path[len("/web/"):]
        types = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
                 ".jpeg": "image/jpeg", ".webp": "image/webp", ".ico": "image/x-icon"}
        # Only this public evidence snapshot is served as JSON; configs
        # and other JSON files remain outside the static-file allowlist.
        if name == "performance-evidence.json":
            types[".json"] = "application/json; charset=utf-8"
        f = ROOT / "serve" / "web" / name
        ext = os.path.splitext(name)[1]
        if "/" in name or "\\" in name or ext not in types or f.is_symlink() or not f.is_file():
            handler._json(404, {"error": {"message": "not found"}})
            return True
        body = f.read_bytes()
        import hashlib
        etag='"'+hashlib.sha256(body).hexdigest()+'"'
        if handler.headers.get('If-None-Match')==etag:
            handler.send_response(304);handler.send_header('ETag',etag);handler.send_header('Cache-Control','no-cache');handler.end_headers();return True
        handler.send_response(200)
        handler.send_header('ETag',etag)
        handler.send_header("Content-Type", types[ext])
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return True

    return False


def handle_post(handler, svc, path) -> bool:
    """True when a custom route answered; False means upstream's do_POST runs."""
    # same as GET: the live catch-all answered True without writing for unknown paths
    if path.startswith("/harness/"):
        parts = path.split("/")
        known = ((len(parts) == 4 and parts[2] in ("opencode", "dsh", "trueforge", "hermes", "claude", "superara")
                  and parts[3] in ("start", "stop", "connect"))
                 or path in ("/harness/codex/terminal/start", "/harness/codex/terminal/input", "/harness/codex/terminal/stop", "/harness/claude/terminal/start", "/harness/claude/terminal/input", "/harness/claude/terminal/stop")
                 or path in ("/harness/mcp", "/harness/browser-mcp", "/harness/memory-mcp",
                             "/harness/claude/desktop", "/harness/claude/run", "/harness/claude/new-session",
                             "/harness/antigravity/web/start", "/harness/antigravity/web/stop",
                             "/harness/antigravity/desktop"))
        if not known:
            return False
    # the durable chat archive: the live line had this branch inside do_GET, where a
    # POST never arrives; the browser posts here
    if path == "/chat/archive":
        if not handler._own_page("archivio conversazioni gestito da questa pagina"):
            return True
        from serve.chat_archive import save_archive
        if not 0 < int(handler.headers.get("Content-Length", 0)) <= 24 * 1024 ** 2:
            handler._json(413, {"error": {"message": "Archivio conversazioni oltre il limite"}})
            return True
        try:
            rows = json.loads(handler._read_body())
            if not isinstance(rows, list):
                raise ValueError("Atteso un elenco di conversazioni")
            handler._json(200, {"saved": save_archive(ROOT, rows)})
        except (OSError, RuntimeError, ValueError) as error:
            handler._json(400, {"error": {"message": str(error)}})
        return True
    if os.environ.get('HYDRA_LAB_MODE')=='1' and path.startswith('/lab/benchmarks/'):
        from serve.hydra_lab_integration import route,service_lab
        try:route(handler,service_lab(svc),'POST',path)
        except (OSError,ValueError) as exc:handler._json(503,{'error':str(exc)})
        return True

    from serve.hydra_native import route as hydra_native_route
    if hydra_native_route(handler,svc,path,post=True):return True

    from serve.hydra_control import route as hydra_control_route
    if hydra_control_route(handler,svc,path):return True

    from serve.codex_original import route as codex_original_route
    if codex_original_route(handler,svc,path,post=True):return True

    from serve.groq_voice import route as groq_voice_route
    if groq_voice_route(handler,svc,path,post=True):return True

    from serve.cloud_providers import route as cloud_provider_route
    if cloud_provider_route(handler,svc,path,post=True):return True

    from serve.original_harness_routes import post as original_post
    if original_post(handler,svc,path):return True

    from serve.generation_routes import post as generation_post
    if generation_post(handler,svc,path):return True

    from serve.native_workspace_routes import post as native_post
    if native_post(handler,svc,path):return True

    from serve.automatic_update_routes import post as automatic_post
    if automatic_post(handler,svc,path):return True

    if path == '/open-webui/prepare':
        if not handler._own_page('Runtime Open WebUI interno richiesto da questa pagina'):return True
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=1024:raise ValueError('Invalid Open WebUI preparation request')
            payload=json.loads(handler._read_body())
            if not isinstance(payload,dict):raise ValueError('Invalid Open WebUI preparation request')
            handler._json(202,svc.open_webui_setup.prepare(payload.get('version')))
        except (OSError,ValueError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path in ('/open-webui/documents/upload','/open-webui/documents/metadata','/open-webui/documents/read','/open-webui/documents/search-library','/open-webui/documents/search','/open-webui/documents/remove','/open-webui/documents/attach','/open-webui/documents/cancel','/open-webui/documents/import-embedding','/open-webui/context'):
        if not handler._own_page('Funzioni Open WebUI interne richieste da questa pagina'):return True
        try:
            limit=12*1024*1024 if path.endswith('/upload') else 2*1024*1024 if path.endswith('/context') else 16384
            if not 0<int(handler.headers.get('Content-Length',0))<=limit:raise ValueError('Open WebUI request exceeds size limit')
            payload=json.loads(handler._read_body())
            if not isinstance(payload,dict):raise ValueError('Invalid Open WebUI request')
            from serve import open_webui_runtime
            if path.endswith('/import-embedding'):result=open_webui_runtime.import_embedding(ROOT,payload)
            elif path.endswith('/cancel'):result=open_webui_runtime.cancel(ROOT)
            elif path.endswith('/context'):result=open_webui_runtime.context(ROOT,payload.get('messages'))
            else:result={'metadata':open_webui_runtime.metadata,'read':open_webui_runtime.read,'search-library':open_webui_runtime.search_library,'upload':open_webui_runtime.upload,'search':open_webui_runtime.search,'remove':open_webui_runtime.remove,'attach':open_webui_runtime.attach}[path.rsplit('/',1)[1]](ROOT,payload)
            handler._json(200,result)
        except (OSError,RuntimeError,ValueError,KeyError,TypeError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path in ('/airllm/prepare','/airllm/rollback'):
        if not handler._own_page('installazione AirLLM isolata gestita da questa pagina'):return True
        try:
            payload=json.loads(handler._read_body())
            if not isinstance(payload,dict):raise ValueError('Invalid AirLLM setup request')
            handler._json(202,svc.airllm_setup.rollback() if path.endswith('/rollback') else svc.airllm_setup.prepare(payload.get('version')))
        except (OSError,RuntimeError,ValueError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/chat/context/compact':
        if not handler._own_page('Compattazione richiesta da questa chat'):return True
        if not 0<int(handler.headers.get('Content-Length',0))<=2*1024*1024:
            handler._json(413,{'error':{'message':'Contesto oltre il limite di compattazione'}});return True
        try:
            from serve.context_compaction import prepare
            handler._json(200,prepare(json.loads(handler._read_body()),root=ROOT))
        except (OSError,RuntimeError,ValueError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/voicestudio/audiobook/render':
        if not handler._own_page('Audiolibro gestito da questa pagina'):return True
        try:
            from serve.voicestudio_render import forward
            forward(handler,svc.voicestudio)
        except (OSError,RuntimeError,ValueError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/voicestudio/audiobook/cancel':
        if not handler._own_page('Audiolibro gestito da questa pagina'):return True
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=4096:raise ValueError('Richiesta interruzione non valida.')
            from serve.voicestudio_render import cancel
            handler._json(200,cancel(svc.voicestudio,json.loads(handler._read_body())))
        except (OSError,RuntimeError,ValueError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path in ('/voicestudio/launch','/voicestudio/speech','/voicestudio/connect-mcp','/voicestudio/install','/voicestudio/engine/select','/voicestudio/web/start','/voicestudio/stop','/voicestudio/pronunciation','/voicestudio/profile','/voicestudio/job'):
        if not handler._own_page('VoiceStudio gestito da questa pagina'):return True
        try:
            if path.endswith('/web/start'):
                result=svc.voicestudio.ensure_web()
                server=svc.mcp.servers.get('voicestudio') if svc.mcp else None
                if server and (result.get('starting') or server.status in ('failed','idle','stopped')):
                    if result.get('starting') and server.status=='ready':server.close()
                    def reconnect_voice():
                        deadline=time.monotonic()+120
                        while time.monotonic()<deadline:
                            if result.get('starting') and svc.voicestudio._web_process is None:return
                            if server.start(quiet=True,reuse_ready=True):return
                            time.sleep(2)
                    threading.Thread(target=reconnect_voice,daemon=True).start()
                    result['mcp_reconnecting']=True
            elif path.endswith('/engine/select'):result=svc.voicestudio.select_engine(json.loads(handler._read_body()))
            elif path.endswith('/launch'):result=svc.voicestudio.launch()
            elif path.endswith('/stop'):
                result=svc.voicestudio.stop()
                if result.get('stopped') and svc.mcp and 'voicestudio' in svc.mcp.servers:svc.mcp.servers['voicestudio'].close()
            elif path.endswith('/connect-mcp'):result=svc.voicestudio.connect_mcp(ROOT)
            elif path.endswith('/install'):result=svc.voicestudio.install(json.loads(handler._read_body()))
            elif path.endswith('/pronunciation'):result=svc.voicestudio.pronunciation(json.loads(handler._read_body()))
            elif path.endswith('/profile'):
                if not 0<int(handler.headers.get('Content-Length',0))<=28*1024*1024:raise ValueError('Richiesta del profilo oltre il limite consentito.')
                result=svc.voicestudio.profile(json.loads(handler._read_body()))
            elif path.endswith('/job'):
                if not 0<int(handler.headers.get('Content-Length',0))<=28*1024*1024+4096:raise ValueError('Richiesta attività oltre il limite consentito.')
                result=svc.voicestudio.job_action(json.loads(handler._read_body()))
            else:result=svc.voicestudio.speech(json.loads(handler._read_body()))
            handler._json(200,result)
        except (OSError,RuntimeError,ValueError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/harness/antigravity/web/start':
        if not handler._own_page('Antigravity originale dentro questa pagina'):return True
        try:handler._json(200,svc.antigravity_web.start())
        except (OSError,RuntimeError,ValueError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/harness/antigravity/web/stop':
        if not handler._own_page('Antigravity integrato gestito da questa pagina'):return True
        svc.antigravity_web.close();handler._json(200,{'ok':True,'stopped':True});return True

    if path == '/harness/antigravity/desktop':
        if not handler._own_page('Antigravity Desktop aperto da questa pagina'):return True
        try:
            from serve.original_harness_routes import antigravity
            handler._json(200,antigravity(svc).start())
        except (OSError,RuntimeError,ValueError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/local-separation/stop':
        if not handler._own_page('separazione audio gestita da questa pagina'):return True
        svc.local_separation.stop();handler._json(200,svc.local_separation.status());return True

    if path == '/local-separation/run':
        if not handler._own_page('separazione audio gestita da questa pagina'):return True
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=16*1024**2+4096:raise ValueError('Separation request exceeds limit')
            payload=json.loads(handler._read_body())
            if not isinstance(payload,dict):raise ValueError('Send a JSON object')
            handler._json(200,svc.local_separation.run(payload))
        except Exception as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/local-speech/library/import':
        if not handler._own_page('importazione audio locale gestita da questa pagina'):return True
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=16*1024**2+4096:raise ValueError('Audio upload exceeds limit')
            from serve.audio_edit import import_audio
            handler._json(200,import_audio(ROOT,json.loads(handler._read_body())))
        except (OSError,ValueError,EOFError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/local-speech/library/export':
        if not handler._own_page('esportazione audio locale gestita da questa pagina'):return True
        import wave
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=4096:raise ValueError('Audio export request exceeds limit')
            from serve.audio_edit import export_audio
            payload=json.loads(handler._read_body());data,mime=export_audio(ROOT,payload)
            handler.send_response(200);handler.send_header('Content-Type',mime);handler.send_header('Content-Length',str(len(data)));handler.send_header('Content-Disposition','attachment; filename="audio.'+payload['format']+'"');handler.send_header('Cache-Control','private, no-store');handler.end_headers();handler.wfile.write(data)
        except (OSError,ValueError,EOFError,wave.Error) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/local-speech/library/edit':
        if not handler._own_page('modifica audio locale gestita da questa pagina'):return True
        import wave
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=4096:raise ValueError('Audio edit request exceeds limit')
            from serve.audio_edit import edit_audio
            handler._json(200,edit_audio(ROOT,json.loads(handler._read_body())))
        except (OSError,ValueError,EOFError,wave.Error) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/local-speech/library/delete':
        if not handler._own_page('gli audio generati possono essere rimossi da questa pagina'):return True
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=4096:raise ValueError('Audio library request exceeds limit')
            payload=json.loads(handler._read_body())
            if not isinstance(payload,dict) or payload.get('confirm') is not True:raise ValueError('Confirm generated audio removal')
            from serve.audio_library import AudioLibrary
            handler._json(200,AudioLibrary(ROOT).delete(payload.get('id')))
        except (OSError,ValueError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/updates/vendor-allowlist':
        if not handler._own_page('aggiornamenti vendor gestiti da questa pagina'):return True
        try:
            payload=json.loads(handler._read_body());result=svc.update_center.prepare_vendor_allowlist(payload.get('environment'),payload.get('packages'))
            handler._json(200,result)
        except Exception as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path in ('/updates/harness-install','/updates/harness-activate','/updates/harness-rollback'):
        if not handler._own_page('aggiornamenti harness gestiti da questa pagina'):return True
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=4096:raise ValueError('Request size limit')
            payload=json.loads(handler._read_body());kind=payload.get('kind')
            if kind not in ('opencode','dsh','trueforge','browser','memory','hermes','claude'):raise ValueError('Unknown harness')
            svc.update_center.harness_updates.status()
            if path.endswith('/harness-install'):svc.update_center.harness_updates.start(kind,payload.get('version'))
            elif kind in ('browser','memory'):
                for agent_kind in ('opencode','dsh','trueforge','hermes','claude'):
                    if agent_harness_for(svc,agent_kind,handler.headers.get('Host')).status().get('busy'):
                        raise ValueError('Agente occupato: browser e memoria saranno aggiornabili al termine del lavoro')
                from serve.shared_agent_services import activate_shared_service
                activate_shared_service(svc,kind,rollback=path.endswith('/harness-rollback'))
            else:
                from serve.harness_activation import activate_managed
                activate_managed(svc,kind,lambda:agent_harness_for(svc,kind,handler.headers.get('Host')),rollback=path.endswith('/harness-rollback'))
            handler._json(200,svc.update_center.status())
        except Exception as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path in ('/updates/health-check','/updates/repair-missing'):
        if not handler._own_page('ripristino dipendenze gestito da questa pagina'):return True
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=4096:raise ValueError('Dependency request exceeds 4 KiB')
            payload=json.loads(handler._read_body())
            if not isinstance(payload,dict):raise ValueError('Send a JSON object')
            result=svc.update_center.check_dependency_health() if path.endswith('/health-check') else svc.automatic_updates.recover_missing()
            handler._json(200,result)
        except Exception as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path in ('/updates/validate-visual-python','/updates/select-visual-python','/updates/rollback-visual-python','/updates/validate-document-python','/updates/select-document-python','/updates/rollback-document-python','/updates/validate-inference-python','/updates/validate-audio-python','/updates/select-audio-python','/updates/rollback-audio-python','/updates/select-inference-python','/updates/rollback-inference-python','/updates/llama-gpu-activate','/updates/llama-gpu-rollback','/updates/soup-prepare','/updates/soup-activate','/updates/soup-rollback','/updates/check','/updates/stage','/updates/cancel','/updates/prepare','/updates/validate','/updates/activate','/updates/rollback','/updates/dependencies','/updates/install-dependencies','/updates/select-python','/updates/rollback-python','/updates/validate-python','/updates/validate-inference'):
        if not handler._own_page('aggiornamenti gestiti da questa pagina'):return True
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=4096:raise ValueError('Update request exceeds 4 KiB')
            payload=json.loads(handler._read_body())
            if not isinstance(payload,dict):raise ValueError('Send a JSON object')
            svc.update_center.status()
            result=svc.update_center.visual_python('validate') if path.endswith('/validate-visual-python') else svc.update_center.visual_python('activate') if path.endswith('/select-visual-python') else svc.update_center.visual_python('rollback') if path.endswith('/rollback-visual-python') else svc.update_center.document_python('validate') if path.endswith('/validate-document-python') else svc.update_center.document_python('activate') if path.endswith('/select-document-python') else svc.update_center.document_python('rollback') if path.endswith('/rollback-document-python') else svc.update_center.audio_python('validate') if path.endswith('/validate-audio-python') else svc.update_center.audio_python('activate') if path.endswith('/select-audio-python') else svc.update_center.audio_python('rollback') if path.endswith('/rollback-audio-python') else svc.update_center.inference_python('validate') if path.endswith('/validate-inference-python') else svc.update_center.inference_python('activate') if path.endswith('/select-inference-python') else svc.update_center.inference_python('rollback') if path.endswith('/rollback-inference-python') else svc.update_center.activate_llama_gpu() if path.endswith('/llama-gpu-activate') else svc.update_center.rollback_llama_gpu() if path.endswith('/llama-gpu-rollback') else svc.update_center.prepare_soup(payload.get('version')) if path.endswith('/soup-prepare') else svc.update_center.activate_soup() if path.endswith('/soup-activate') else svc.update_center.rollback_soup() if path.endswith('/soup-rollback') else svc.update_center.validate_strata_inference() if path.endswith('/validate-inference') else svc.update_center.check() if path.endswith('/check') else svc.update_center.cancel() if path.endswith('/cancel') else svc.update_center.validate_python() if path.endswith('/validate-python') else svc.update_center.select_python() if path.endswith('/select-python') else svc.update_center.select_python(rollback=True) if path.endswith('/rollback-python') else svc.update_center.install_dependencies() if path.endswith('/install-dependencies') else svc.update_center.dependency_plan(payload.get('environment'),payload.get('component'),payload.get('version'),payload.get('conservative',False)) if path.endswith('/dependencies') else svc.update_center.activate() if path.endswith('/activate') else svc.update_center.rollback(payload.get('component','llama.cpp')) if path.endswith('/rollback') else svc.update_center.validate(payload.get('model_path')) if path.endswith('/validate') else svc.update_center.prepare() if path.endswith('/prepare') else svc.update_center.stage(payload.get('component'),payload.get('asset_id'))
            handler._json(200,result)
        except Exception as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path in ('/local-export/preflight','/local-export/start','/local-export/stop'):
        if not handler._own_page('conversione locale gestita da questa pagina'):return True
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=65536:raise ValueError('Conversion request exceeds 64 KiB')
            payload=json.loads(handler._read_body())
            if not isinstance(payload,dict):raise ValueError('Send a JSON object')
            if path.endswith('/preflight'):result=svc.local_export.preflight(payload)
            elif path.endswith('/stop'):result=svc.local_export.stop()
            else:
                with svc.fifo:
                    result=svc.local_export.start(payload,not svc.loaded() and svc.local_training.status()['status']!='running')
            handler._json(200,result)
        except Exception as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path in ('/local-speech/start','/local-speech/stop','/local-speech/generate','/v1/audio/speech'):
        if path.startswith('/local-speech/') and not handler._own_page('voce locale gestita da questa pagina'):return True
        if path.startswith('/v1/') and handler._foreign_page():return True
        try:
            length=int(handler.headers.get('Content-Length',0))
            if not 0<length<=65536:raise ValueError('Speech request exceeds 64 KiB')
            payload=json.loads(handler._read_body())
            if not isinstance(payload,dict):raise ValueError('Send a JSON object')
            if path.endswith('/start'):result=svc.local_speech.start(payload)
            elif path.endswith('/stop'):
                if payload.get('automatic_idle'):
                    if not svc.local_speech.request_lock.acquire(blocking=False):
                        handler._json(200,{'busy':True});return True
                    try:result=svc.local_speech.stop()
                    finally:svc.local_speech.request_lock.release()
                else:result=svc.local_speech.stop()
            else:result=svc.local_speech.generate(payload)
            if path=='/v1/audio/speech':
                import base64
                data=base64.b64decode(result['audio_base64']);handler.send_response(200);handler.send_header('Content-Type','audio/wav');handler.send_header('Content-Length',str(len(data)));handler.end_headers();handler.wfile.write(data)
            else:handler._json(200,result)
        except Exception as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/local-audio/process':
        if not handler._own_page('audio locale gestito da questa pagina'):return True
        try:
            import base64
            from serve.local_audio import process_audio
            if not 0<int(handler.headers.get('Content-Length',0))<=29*1024**2:raise ValueError('Audio request exceeds limit')
            payload=json.loads(handler._read_body())
            data=base64.b64decode(payload.get('audio_base64',''),validate=True)
            audio,metrics=process_audio(data,payload.get('name',''),payload.get('start',0),payload.get('duration',60),payload.get('normalize',False))
            handler._json(200,{'audio_base64':base64.b64encode(audio).decode('ascii'),'metrics':metrics})
        except Exception as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path in ('/local-audio/start','/local-audio/stop','/local-audio/transcribe','/v1/audio/transcriptions','/v1/audio/translations'):
        if path.startswith('/local-audio/') and not handler._own_page('audio locale gestito da questa pagina'):return True
        if path.startswith('/v1/') and handler._foreign_page(allow_multipart=True):return True
        try:
            import base64
            size=int(handler.headers.get('Content-Length',0))
            if size<=0 or size>32*1024**2:raise ValueError('Audio request exceeds 32 MiB or is empty')
            raw=handler._read_body();content_type=handler.headers.get('Content-Type','')
            if content_type.startswith('multipart/form-data'):
                from email.parser import BytesParser
                from email import policy
                multipart=BytesParser(policy=policy.default).parsebytes(('Content-Type: '+content_type+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
                values={};audio=None;name='audio.wav'
                for part in multipart.iter_parts():
                    key=part.get_param('name',header='content-disposition')
                    if key=='file':audio=part.get_payload(decode=True);name=part.get_filename() or name
                    elif key in ('language','response_format','model'):values[key]=part.get_content()
                if audio is None:raise ValueError('Audio file missing')
                payload=values
            else:
                payload=json.loads(raw)
                if not isinstance(payload,dict):raise ValueError('Send a JSON object')
                audio=base64.b64decode(payload.get('audio_base64',''),validate=True);name=payload.get('name','audio.wav')
            if path.endswith('/start'):result=svc.local_audio.start(payload)
            elif path.endswith('/stop'):
                if payload.get('automatic_idle'):
                    if not svc.local_audio.request_lock.acquire(blocking=False):
                        handler._json(200,{'busy':True});return True
                    try:result=svc.local_audio.stop()
                    finally:svc.local_audio.request_lock.release()
                else:result=svc.local_audio.stop()
            else:
                if payload.get('response_format','json') not in ('json','text'):raise ValueError('Supported transcription formats: json, text')
                result=svc.local_audio.transcribe(audio,name,payload.get('language','auto'),path.endswith('/translations') or payload.get('translate') is True,model=payload.get('model'))
            if payload.get('response_format')=='text':
                data=result['text'].encode('utf-8');handler.send_response(200);handler.send_header('Content-Type','text/plain; charset=utf-8');handler.send_header('Content-Length',str(len(data)));handler.end_headers();handler.wfile.write(data)
            else:handler._json(200,result)
        except Exception as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path in ('/local-training/start','/local-training/stop','/local-training/preflight','/local-training/upload','/local-training/split','/local-training/session'):
        if not handler._own_page('il training locale può essere gestito da questa pagina'):return True
        try:
            if path.endswith('/upload') and not 0<int(handler.headers.get('Content-Length',0))<=8*1024**2:raise ValueError('Dataset request exceeds upload limit')
            payload=json.loads(handler._read_body() or b'{}')
            if not isinstance(payload,dict):raise ValueError('Send a JSON object')
            with svc.fifo:
                result=svc.local_training.session(payload) if path.endswith('/session') else svc.local_training.split_dataset(payload) if path.endswith('/split') else svc.local_training.upload_dataset(payload) if path.endswith('/upload') else svc.local_training.preflight(payload) if path.endswith('/preflight') else svc.local_training.start(payload,operational_idle=not svc.loaded()) if path.endswith('/start') else svc.local_training.stop()
            handler._json(200,result)
        except Exception as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path in ('/optional-catalogue/search','/optional-catalogue/download','/optional-catalogue/cancel','/optional-catalogue/details','/optional-catalogue/delete'):
        if not handler._own_page('il catalogo può essere gestito da questa pagina'):return True
        try:
            payload=json.loads(handler._read_body() or b'{}')
            if not isinstance(payload,dict):raise ValueError('Invia un oggetto JSON')
            if path.endswith('/delete'):
                if payload.get('confirm') is not True:raise ValueError('Conferma la rimozione del modello selezionato')
                training=svc.local_training.status()
                with svc.fifo:result=svc.optional_catalogue.delete_local(payload.get('path'),operational_idle=(not svc.loaded() or (os.environ.get('STRATA_MOCK_SHELL')=='1' and type(svc.engine).__name__=='MockEngine')) and svc.local_export.status()['status']!='running',training_model=training.get('model') if training.get('status')=='running' else None)
            elif path.endswith('/details'):result=svc.optional_catalogue.details(payload.get('id'))
            elif path.endswith('/search'):result=svc.optional_catalogue.search(payload)
            elif path.endswith('/download'):result=svc.optional_catalogue.download(payload.get('id'))
            else:svc.optional_catalogue.cancel.set();result=svc.optional_catalogue.status()
            handler._json(200,result)
        except Exception as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path in ('/harness/mcp','/harness/browser-mcp','/harness/memory-mcp'):
        from serve.trueforge_setup import bridge_token,bridge_response
        try:
            authorization=(handler.headers.get('Authorization') or '').encode('utf-8','replace')
            if not hmac.compare_digest(authorization,('Bearer '+bridge_token(ROOT)).encode('utf-8')):
                handler._json(401,{'error':{'message':'MCP bridge authentication required'}});return True
            if not 0<int(handler.headers.get('Content-Length',0))<=65536:raise ValueError('MCP request limit')
            request=json.loads(handler._read_body());response=bridge_response(svc.mcp,request,prefix='browser__' if path.endswith('browser-mcp') else 'memory__' if path.endswith('memory-mcp') else None)
            handler._json(200 if response is not None else 202,response or {})
        except Exception as error:handler._json(400,{'error':{'message':str(error)}})
        return True

    if path == '/harness/claude/desktop':
        if not handler._own_page("Claude Desktop ufficiale aperto da questa pagina"): return True
        try:
            from serve.original_harness_routes import claude
            handler._json(200, claude(svc).start())
        except Exception as error: handler._json(400, {'error': {'message': str(error)}})
        return True

    if path in ('/harness/claude/run', '/harness/claude/new-session'):
        if not handler._own_page("Claude Code gestito da questa pagina"): return True
        try:
            harness = agent_harness_for(svc, 'claude', handler.headers.get('Host'))
            if path.endswith('/run'):
                if not 0 < int(handler.headers.get('Content-Length', 0)) <= 65536: raise ValueError('Limite richiesta Claude Code')
                payload = json.loads(handler._read_body())
                model = payload.get('model') or harness.model if isinstance(payload, dict) else None
                optional = svc.optional_backends.status()
                if model not in svc.model_names() and model != optional.get('public_model'): raise ValueError('Seleziona un modello locale disponibile')
                if isinstance(model, str) and model.startswith('local/') and optional.get('status') != 'ready': raise ValueError('Il modello locale selezionato non è pronto')
                harness.context_budget = int((optional.get('context_per_slot') or 8192) if model.startswith('local/') else (getattr(svc, 'max_context', 0) or 131072))
                harness.output_budget = min(2048, max(128, harness.context_budget // 4))
                handler._json(202, harness.run(payload))
            else: handler._json(200, harness.new_session())
        except Exception as error: handler._json(400, {'error': {'message': str(error)}})
        return True

    if path.startswith("/harness/"):
        parts = path.split("/")
        if len(parts) == 4 and parts[2] in ("opencode", "dsh", "trueforge", "hermes", "claude") and parts[3] in ("start", "stop", "connect"):
            if not handler._own_page("l'harness può essere gestito da questa pagina"): return True
            try:
                harness = agent_harness_for(svc, parts[2], handler.headers.get("Host"))
                from serve.harness_model import local_selection
                response = harness.start() if parts[3] == "start" else harness.connect() if parts[3] == "connect" else harness.stop()
                handler._json(200, {**response, 'binding': local_selection(svc)})
            except Exception as error:
                handler._json(400, {"error": {"message": str(error)}})
        return True

    if path in ('/inference-backends/start','/inference-backends/stop','/inference-backends/chat','/inference-backends/probe','/inference-backends/context-plan','/inference-backends/fit','/inference-backends/rescan'):
        if not handler._own_page('i backend locali possono essere gestiti da questa pagina'):return True
        cancel=threading.Event();events=None;streaming=False
        try:
            payload=json.loads(handler._read_body() or b'{}')
            if not isinstance(payload,dict):raise ValueError('Invia un oggetto JSON')
            if path.endswith('/rescan'):
                discovery=svc.optional_backends.discovery
                if discovery is None:raise ValueError('Local model discovery unavailable')
                handler._json(202,discovery.rescan())
            elif path.endswith('/fit'):handler._json(200,svc.optional_backends.fit_model(payload))
            elif path.endswith('/context-plan'):handler._json(200,svc.optional_backends.context_plan(payload))
            elif path.endswith('/start'):
                with svc.fifo:
                    if getattr(svc,'cat_job',{}).get('state') in ('starting','downloading','verifying','packing','registering'):raise RuntimeError('Attendi la preparazione del catalogo')
                    if svc.airllm_setup.job['state']=='preparing':raise RuntimeError('Attendi la preparazione AirLLM')
                    mock_shell=os.environ.get('STRATA_MOCK_SHELL')=='1' and type(svc.engine).__name__=='MockEngine'
                    result=svc.optional_backends.start(payload,operational_idle=not svc.loaded() or mock_shell)
                handler._json(202,result)
            elif path.endswith('/stop'):handler._json(200,svc.optional_backends.stop())
            elif path.endswith('/probe'):handler._json(200,svc.optional_backends.probe_api(payload))
            else:handler._optional_chat(payload)
        except (BrokenPipeError,ConnectionResetError):cancel.set()
        except Exception as exc:
            if streaming:
                try:
                    handler.wfile.write(('data: '+json.dumps({'error':{'message':str(exc)}})+'\n\n').encode());handler.wfile.flush()
                except OSError:pass
            else:handler._json(400 if isinstance(exc,(ValueError,TypeError)) else 409,{'error':{'message':str(exc)}})
        finally:
            cancel.set()
            if events is not None:events.close()
        return True

    if path in ('/benchmark-lab/start','/benchmark-lab/stop'):
        if not handler._own_page('i benchmark possono essere avviati da questa pagina'):return True
        try:
            if path.endswith('/stop'):
                result=svc.optional_benchmark.stop() if svc.optional_benchmark.status()[0].get('status') in ('running','cancelling') else svc.benchmark_lab.cancel()
            else:
                with svc.fifo:
                    if getattr(svc,'cat_job',{}).get('state') in ('starting','downloading','verifying','packing','registering'):raise RuntimeError('Attendi la preparazione del catalogo')
                    payload=json.loads(handler._read_body() or b'{}')
                    if not isinstance(payload,dict):raise ValueError('Invia un oggetto JSON')
                    result=svc.optional_benchmark.start(payload) if payload.get('model')=='optional_active' else svc.benchmark_lab.start(payload,operational_idle=not svc.loaded())
            handler._json(202,result)
        except (ValueError,TypeError) as exc:handler._json(400,{'error':{'message':str(exc)}})
        except RuntimeError as exc:handler._json(409,{'error':{'message':str(exc)}})
        return True

    if path == "/power":
        if not handler._own_page("thermal alert settings can be changed"):
            return True
        try:
            req = json.loads(handler._read_body() or b"{}")
            if not isinstance(req, dict):
                raise ValueError("send a JSON object")
            if "mode" in req and req["mode"] not in ("performance", "balanced", "eco", "custom"):
                raise ValueError("unknown mode")
            if "temp_limit" in req or "power_limit" in req:
                svc.power_manager.set_custom_limits(
                    req.get("temp_limit", svc.power_manager.config.custom_temp_limit),
                    req.get("power_limit", svc.power_manager.config.custom_power_limit),
                )
            if "mode" in req:
                svc.power_manager.set_mode(req["mode"])
            if req.get("reset"):
                svc.power_manager.reset_throttle()
            handler._json(200, {"status": "ok", "mode": svc.power_manager.config.mode,
                             "temp_limit": svc.power_manager.config.temp_limit(),
                             "power_limit": svc.power_manager.config.power_limit()})
        except (ValueError, TypeError) as e:
            handler._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
        return True

    if path in ("/config", "/setup-download", "/switch-model", "/catalogue-inspect", "/catalogue-search", "/catalogue-fetch") and not handler._own_page("resources and models can be changed"):
        return True

    if path == "/config":
        try:
            req = json.loads(handler._read_body() or b"{}")
            if not isinstance(req, dict):
                raise ValueError("send a JSON object")
            svc.set_resources(vram_reserve_mib=req.get("vram_reserve_mib"),
                              kv_resident=req.get("kv_resident"),
                              max_context=req.get("max_context"), validate_only=True)
            vis = svc.set_vision(req.get("vision"))      # images on/off, now
            changed = svc.set_resources(vram_reserve_mib=req.get("vram_reserve_mib"),
                                        kv_resident=req.get("kv_resident"),
                                        max_context=req.get("max_context"))
            note = ("takes effect at the next engine start" if changed
                    else "images " + ("on" if vis.get("vision") else "off") if vis
                    else "nothing changed")
            handler._json(200, {"status": "ok", "changed": changed, **vis, **svc.resource_state(), "note": note})
        except GpuBusy as e:
            handler._json(409, {"error": {"type": "model_busy", "message": str(e)}})
        except ValueError as e:
            handler._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
        return True

    if path == "/setup-download":
        try:
            req = json.loads(handler._read_body() or b"{}")
            if not isinstance(req, dict): raise ValueError("send a JSON object")
            model = str(req.get("model") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,32}", model):
                raise ValueError("send a model key (e.g. IQ3_XXS)")
            handler._json(202, svc.start_setup(model))
        except ValueError as e:
            handler._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
        return True

    if path == "/catalogue-inspect":
        try:
            req = json.loads(handler._read_body() or b"{}")
            if not isinstance(req, dict): raise ValueError("send a JSON object")
            handler._json(200, svc.catalogue_inspect(str(req.get("repo") or ""),
                                                  (str(req["quant"]) if req.get("quant") else None)))
        except ValueError as e:
            handler._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
        return True

    if path == "/catalogue-search":
        try:
            req = json.loads(handler._read_body() or b"{}")
            if not isinstance(req, dict): raise ValueError("send a JSON object")
            handler._json(200, svc.catalogue_search(str(req.get("query") or "")))
        except ValueError as e:
            handler._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
        return True

    if path == "/catalogue-fetch":
        try:
            req = json.loads(handler._read_body() or b"{}")
            if not isinstance(req, dict): raise ValueError("send a JSON object")
            handler._json(202, svc.start_catalogue_fetch(str(req.get("repo") or ""),
                                                      str(req.get("quant") or ""),
                                                      (str(req["key"]) if req.get("key") else None),
                                                      bool(req.get("mtp"))))
        except ValueError as e:
            handler._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
        return True

    if path == "/switch-model":
        try:
            req = json.loads(handler._read_body() or b"{}")
            if not isinstance(req, dict): raise ValueError("send a JSON object")
            model = str(req.get("model") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,32}", model):
                raise ValueError("send a model key (e.g. IQ2_XS)")
            handler._json(202, svc.start_switch(model))
        except ValueError as e:
            handler._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
        return True


    # the live line's local-model routing (serve/optional_backends.py): upstream 0.2.9
    # has no optional backends, so /v1/chat/completions and /v1/messages are ours when
    # the body names a local/ model. Other bodies fall through to upstream unchanged.
    if path in ("/v1/chat/completions", "/v1/messages"):
        # the live line checked the page origin before routing a local/ model; without
        # it a cross-site page drives the optional backend with no CORS preflight
        if handler._foreign_page():
            return True
        try:
            req = json.loads(handler._read_body() or b"{}")
        except ValueError:
            return False
        model = req.get("model") if isinstance(req, dict) else None
        if isinstance(model, str) and model.startswith("local/"):
            optional = svc.optional_backends.status()
            if model != optional.get("public_model") or optional["status"] != "ready":
                handler._json(404, {"error": {"message": "Il modello locale richiesto non è pronto"}})
            else:
                try:
                    if path == "/v1/messages":
                        handler._optional_anthropic(req)
                    else:
                        handler._optional_chat(req)
                except ModelBusy as exc:
                    handler._json(409, {"error": {"type": "model_busy", "message": str(exc)}})
                except Exception as exc:            # noqa: BLE001 - answer, never drop the connection
                    handler._json(400, {"error": {"type": "invalid_request_error", "message": str(exc)}})
            return True
    return False

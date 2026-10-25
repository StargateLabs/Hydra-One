import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from serve.configuration import atomic_json, whole_number
from serve.diagnostics import diagnose
from serve.power_manager import PowerManager
from serve.server import ByteTokenizer, MockEngine, Service, GpuBusy
from serve.frontend import ChatTemplate


class ConfigurationTests(unittest.TestCase):
    def test_atomic_json_retries_transient_windows_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'state.json'
            from serve import configuration
            replace=configuration.os.replace
            calls=[]
            def transient(source,destination):
                calls.append(1)
                if len(calls)==1:raise PermissionError('temporary reader')
                return replace(source,destination)
            with mock.patch.object(configuration.os,'name','nt'),mock.patch.object(configuration.os,'replace',side_effect=transient),mock.patch.object(configuration.time,'sleep'):
                atomic_json(target,{'complete':True})
            self.assertEqual(json.loads(target.read_text()),{'complete':True})
            self.assertEqual(len(calls),2)
    def test_resident_budget_diagnostic_is_configured_not_measured(self):
        d = diagnose({"args":["--resident-budget-gib","16"]}, {}, {}, False, False)
        c = next(c for c in d["checks"] if c["id"] == "resident")
        self.assertEqual(c["state"],"info")
        self.assertIn("Budget configurato: 16 GiB", c["detail"])
        self.assertIn("non certifica", c["detail"])

    def test_budget_refuses_fraction_boolean_nan(self):
        for v in (True, 1.2, float("nan"), float("inf"), "1.2", {}, None):
            with self.subTest(value=v), self.assertRaises(ValueError):
                whole_number(v, "budget", 0, 100)
        self.assertEqual(whole_number("0", "budget", 0, 100), 0)

    def test_failed_replace_preserves_valid_config(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"config.json"
            atomic_json(p,{"args":["--max-context","32768"]})
            with mock.patch("serve.configuration.os.replace",side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    atomic_json(p,{"args":[]})
            self.assertEqual(json.loads(p.read_text())["args"],["--max-context","32768"])
            self.assertEqual(list(Path(d).glob("*.tmp")),[])

    def test_missing_sensors_are_unknown(self):
        d = diagnose({}, {}, {}, False, False)
        self.assertEqual(next(c for c in d["checks"] if c["id"] == "ram")["state"],"unknown")
        self.assertNotIn("input",json.dumps(d))

    def test_power_missing_sensors_and_atomic_validation(self):
        p = PowerManager()
        self.assertFalse(p.update(None,None,0).throttling)
        old = p.config.custom_temp_limit
        with self.assertRaises(ValueError):
            p.set_custom_limits(80,float("nan"))
        self.assertEqual(p.config.custom_temp_limit,old)

    def test_budget_changes_reach_next_engine_spawn(self):
        tok = ByteTokenizer()
        engine = MockEngine(tok,"ok",max_context=65536)
        engine.spawn = ("engine.exe",["--max-context","65536"],None,None,{})
        svc = Service(engine,tok,ChatTemplate(Path(__file__).parent/"chat_template.jinja"))
        svc.cfg = {"args":["--max-context","65536","--kv-resident","32768"]}
        svc.set_resources(vram_reserve_mib=1536)
        self.assertIn("--vram-reserve-mib",engine.spawn[1])
        original = list(engine.spawn[1])
        with self.assertRaises(ValueError):
            svc.set_resources(max_context=4096)
        self.assertEqual(engine.spawn[1],original)
        svc.set_resources(max_context=32768,validate_only=True)
        self.assertEqual(engine.spawn[1],original)

    def test_failed_shared_save_keeps_active_defaults(self):
        tok = ByteTokenizer()
        svc = Service(MockEngine(tok,"ok"),tok,ChatTemplate(Path(__file__).parent/"chat_template.jinja"))
        svc.shared = {"temperature":0.5}
        svc.shared_path = "settings.json"
        with mock.patch("serve.configuration.atomic_json",side_effect=OSError("locked")):
            with self.assertRaises(ValueError):
                svc.set_shared({"temperature":0.2})
        self.assertEqual(svc.shared,{"temperature":0.5})

    def test_pending_resources_are_visible(self):
        d = diagnose({"args":["--max-context","32768"]}, {"max_context":65536}, {}, True, False)
        self.assertEqual(next(c for c in d["checks"] if c["id"]=="restart")["state"],"warn")

    def test_failed_vision_start_keeps_config(self):
        tok=ByteTokenizer()
        svc=Service(MockEngine(tok,"ok"),tok,ChatTemplate(Path(__file__).parent/"chat_template.jinja"))
        svc.cfg={"args":["--native","model.gguf"],"cwd":str(Path(__file__).resolve().parents[1])}
        original=dict(svc.cfg)
        with mock.patch("serve.server.Path.exists",return_value=True), \
             mock.patch("serve.server.find_mmproj",return_value=Path("projector.gguf")), \
             mock.patch("serve.server.Vision",side_effect=RuntimeError("startup failed")):
            with self.assertRaises(ValueError): svc.set_vision(True)
        self.assertEqual(svc.cfg,original)
        self.assertIsNone(svc.vision)

    def test_failed_vision_save_stops_candidate(self):
        tok=ByteTokenizer()
        svc=Service(MockEngine(tok,"ok"),tok,ChatTemplate(Path(__file__).parent/"chat_template.jinja"))
        svc.cfg={"args":["--native","model.gguf"],"cwd":str(Path(__file__).resolve().parents[1])}
        svc.cfg_path="configuration.json"
        candidate=mock.Mock()
        with mock.patch("serve.server.Path.exists",return_value=True), \
             mock.patch("serve.server.find_mmproj",return_value=Path("projector.gguf")), \
             mock.patch("serve.server.Vision",return_value=candidate), \
             mock.patch("serve.configuration.atomic_json",side_effect=OSError("locked")):
            with self.assertRaises(ValueError): svc.set_vision(True)
        candidate.unload.assert_called_once()
        self.assertIsNone(svc.vision)
        self.assertNotIn("vision",svc.cfg)

    def test_vision_mode_reaches_engine_and_waits_for_idle(self):
        tok=ByteTokenizer()
        engine=MockEngine(tok,"ok")
        engine.spawn=("engine.exe",[],None,None,{})
        engine.alive=mock.Mock(return_value=True)
        engine.unload=mock.Mock()
        svc=Service(engine,tok,ChatTemplate(Path(__file__).parent/"chat_template.jinja"))
        svc.cfg={"args":["--native","model.gguf"],"cwd":"."}
        svc.fifo.acquire()
        try:
            with self.assertRaises(GpuBusy): svc.set_vision(True)
        finally: svc.fifo.release()
        candidate=mock.Mock()
        with mock.patch("serve.server.Path.exists",return_value=True), \
             mock.patch("serve.server.find_mmproj",return_value=Path("projector.gguf")), \
             mock.patch("serve.server.Vision",return_value=candidate):
            svc.set_vision(True)
        self.assertIn("--vision",engine.spawn[1])
        engine.unload.assert_called_once()
        svc.set_vision(False)
        self.assertNotIn("--vision",engine.spawn[1])
        self.assertNotIn("vision",svc.cfg)


if __name__ == "__main__":
    unittest.main()

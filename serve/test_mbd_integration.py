"""Focused checks of the unfinished MBD integration, without loading weights."""
import unittest
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MbdIntegrationTests(unittest.TestCase):
    def test_codec_rejects_non_24khz_model_before_registration(self):
        from serve.studio_model_import import validate
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as directory:
            folder = Path(directory)
            (folder / 'config.json').write_text(json.dumps({'model_type': 'encodec', 'sampling_rate': 48000}), encoding='utf-8')
            (folder / 'model.safetensors').write_bytes(b'fixture')
            with self.assertRaises(ValueError):
                validate(folder, 'codec24')

    def test_audio_ui_is_valid_utf8(self):
        for name in ('local-generation.js', 'studio-model-import.js'):
            with self.subTest(name=name):
                source=(ROOT / 'serve/web' / name).read_text(encoding='utf-8')
                self.assertNotIn('\u00c2\u00b7', source)

    def test_bandwidth_control_exists_for_submitted_field(self):
        source = (ROOT / 'serve/web/mbd-controls.js').read_text(encoding='utf-8')
        self.assertIn('mbd-bandwidth', source)
        self.assertIn('1.5', source)
        self.assertIn('6', source)
        index = (ROOT / 'serve/web/index.html').read_text(encoding='utf-8')
        self.assertIn('src="web/mbd-controls.js', index)


if __name__ == '__main__':
    unittest.main()

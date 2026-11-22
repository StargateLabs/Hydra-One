"""Check language inventory and our validation boundary; never load Whisper models."""
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from serve.local_audio import LocalAudio
from serve import whisper_languages


class WhisperLanguageBindingTests(unittest.TestCase):
    def test_public_runtime_table_is_read_without_model_initialization(self):
        library = SimpleNamespace(whisper_lang_max_id=Mock(return_value=2),
                                  whisper_lang_str=Mock(side_effect=[b'en', b'ar', b'ko']))
        with ExitStack() as stack:
            stack.enter_context(patch.object(whisper_languages.ctypes, 'CDLL', Mock(return_value=library)))
            if hasattr(whisper_languages.os, 'add_dll_directory'):
                stack.enter_context(patch.object(whisper_languages.os, 'add_dll_directory', Mock(return_value=Mock())))
            whisper_languages._read_table.cache_clear()
            try:
                self.assertEqual(whisper_languages._read_table('C:/fixture/whisper.dll', 1, 1), ('en', 'ar', 'ko'))
                self.assertFalse(hasattr(library, 'whisper_init_from_file'))
            finally:
                whisper_languages._read_table.cache_clear()

    def test_missing_runtime_retains_previous_language_choices(self):
        result = whisper_languages.language_inventory(Path('missing-fixture-runtime') / 'server.exe')
        self.assertEqual(result['languages_source'], 'compatibility-fallback')
        self.assertIn('it', result['languages'])

    def test_english_only_model_rejects_arabic_before_start(self):
        value = boundary('ggml-tiny.en.bin')
        with patch('serve.local_audio.language_inventory', lambda binary: {'languages': ['en', 'ar']}):
            with self.assertRaisesRegex(ValueError, 'English-only'):
                value.transcribe(b'fixture', model='ggml-tiny.en', language='ar')

    def test_registered_arabic_reaches_next_input_guard_without_start(self):
        value = boundary('ggml-tiny.bin')
        with patch('serve.local_audio.language_inventory', lambda binary: {'languages': ['en', 'ar']}):
            with self.assertRaisesRegex(ValueError, 'Unsupported audio file type'):
                value.transcribe(b'fixture', name='invalid.xyz', model='ggml-tiny', language='ar')


def boundary(name):
    value = object.__new__(LocalAudio)
    value.models = Mock()
    value.models.glob.return_value = [Path('C:/fixture') / name]
    value.binary = Path('C:/fixture/server.exe')
    value.state = {'status': 'idle'}
    value.status = Mock(return_value={'formats': ['wav']})
    return value


if __name__ == '__main__':
    unittest.main()

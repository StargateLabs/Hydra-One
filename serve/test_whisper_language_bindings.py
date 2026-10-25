"""Check language inventory and our validation boundary; never load Whisper models."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from serve.local_audio import LocalAudio
from serve import whisper_languages


def test_public_runtime_table_is_read_without_model_initialization(monkeypatch):
    library = SimpleNamespace(whisper_lang_max_id=Mock(return_value=2),
                              whisper_lang_str=Mock(side_effect=[b'en', b'ar', b'ko']))
    monkeypatch.setattr(whisper_languages.ctypes, 'CDLL', Mock(return_value=library))
    if hasattr(whisper_languages.os, 'add_dll_directory'):
        monkeypatch.setattr(whisper_languages.os, 'add_dll_directory', Mock(return_value=Mock()))
    whisper_languages._read_table.cache_clear()
    assert whisper_languages._read_table('C:/fixture/whisper.dll', 1, 1) == ('en', 'ar', 'ko')
    assert not hasattr(library, 'whisper_init_from_file')
    whisper_languages._read_table.cache_clear()


def test_missing_runtime_retains_previous_language_choices():
    result = whisper_languages.language_inventory(Path('missing-fixture-runtime') / 'server.exe')
    assert result['languages_source'] == 'compatibility-fallback'
    assert 'it' in result['languages']


def boundary(monkeypatch, name):
    value = object.__new__(LocalAudio)
    value.models = Mock()
    value.models.glob.return_value = [Path('C:/fixture') / name]
    value.binary = Path('C:/fixture/server.exe')
    value.state = {'status': 'idle'}
    value.status = Mock(return_value={'formats': ['wav']})
    monkeypatch.setattr('serve.local_audio.language_inventory', lambda binary: {'languages': ['en', 'ar']})
    return value


def test_english_only_model_rejects_arabic_before_start(monkeypatch):
    value = boundary(monkeypatch, 'ggml-tiny.en.bin')
    with pytest.raises(ValueError, match='English-only'):
        value.transcribe(b'fixture', model='ggml-tiny.en', language='ar')


def test_registered_arabic_reaches_next_input_guard_without_start(monkeypatch):
    value = boundary(monkeypatch, 'ggml-tiny.bin')
    with pytest.raises(ValueError, match='Unsupported audio file type'):
        value.transcribe(b'fixture', name='invalid.xyz', model='ggml-tiny', language='ar')

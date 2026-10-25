"""Check our native-parameter forwarding, without executing published models."""
import math
from pathlib import Path
from unittest.mock import Mock

import pytest

from serve.local_generative_audio import LocalGenerativeAudio
from tools.generate_local_audio import music_generation_options


def manager():
    value = object.__new__(LocalGenerativeAudio)
    value.status = Mock(return_value={'devices': ['cpu']})
    value.model_choices = Mock(return_value=[
        {'id': 'music/installed', 'task': 'music', 'path': 'C:/music'},
        {'id': 'conversion/installed', 'task': 'voice_conversion', 'path': 'C:/voice'},
    ])
    value.reference_audio = Mock(side_effect=lambda path: Path(path))
    return value


def music(**options):
    return {'task': 'music', 'model': 'music/installed', 'prompt': 'Piano', **options}


def test_music_native_options_reach_worker_unchanged():
    options = {'temperature': 0.7, 'top_k': 120, 'top_p': 0.85, 'guidance_scale': 4.0}
    request = manager()._validate(music(**options))
    assert music_generation_options(request) == options


def test_empty_options_keep_original_model_defaults():
    request = manager()._validate(music())
    assert music_generation_options(request) == {}


@pytest.mark.parametrize('key,value', [
    ('temperature', True), ('temperature', 0), ('temperature', math.nan),
    ('top_k', 1.5), ('top_k', -1), ('top_p', 0), ('top_p', math.inf),
    ('guidance_scale', True), ('guidance_scale', 21),
])
def test_invalid_music_options_are_rejected_before_worker(key, value):
    with pytest.raises(ValueError):
        manager()._validate(music(**{key: value}))


def test_openvoice_tau_is_forwarded_without_changing_audio_paths():
    request = manager()._validate({'task': 'voice_conversion', 'model': 'conversion/installed',
                                   'source_path': 'C:/source.wav', 'reference_path': 'C:/ref.wav', 'tau': 0.4})
    assert request['tau'] == 0.4
    assert request['source_path'].endswith('source.wav')


@pytest.mark.parametrize('tau', [True, -0.1, 1.1, math.nan])
def test_invalid_conversion_tau_is_rejected(tau):
    with pytest.raises(ValueError):
        manager()._validate({'task': 'voice_conversion', 'model': 'conversion/installed',
                             'source_path': 'C:/source.wav', 'reference_path': 'C:/ref.wav', 'tau': tau})

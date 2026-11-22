"""Check our native-parameter forwarding, without executing published models."""
import math
import unittest
from pathlib import Path
from unittest.mock import Mock

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


class AudioParameterBindingTests(unittest.TestCase):
    def test_music_native_options_reach_worker_unchanged(self):
        options = {'temperature': 0.7, 'top_k': 120, 'top_p': 0.85, 'guidance_scale': 4.0}
        request = manager()._validate(music(**options))
        self.assertEqual(music_generation_options(request), options)

    def test_empty_options_keep_original_model_defaults(self):
        request = manager()._validate(music())
        self.assertEqual(music_generation_options(request), {})

    def test_invalid_music_options_are_rejected_before_worker(self):
        for key, value in (
            ('temperature', True), ('temperature', 0), ('temperature', math.nan),
            ('top_k', 1.5), ('top_k', -1), ('top_p', 0), ('top_p', math.inf),
            ('guidance_scale', True), ('guidance_scale', 21),
        ):
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    manager()._validate(music(**{key: value}))

    def test_openvoice_tau_is_forwarded_without_changing_audio_paths(self):
        request = manager()._validate({'task': 'voice_conversion', 'model': 'conversion/installed',
                                       'source_path': 'C:/source.wav', 'reference_path': 'C:/ref.wav', 'tau': 0.4})
        self.assertEqual(request['tau'], 0.4)
        self.assertTrue(request['source_path'].endswith('source.wav'))

    def test_invalid_conversion_tau_is_rejected(self):
        for tau in (True, -0.1, 1.1, math.nan):
            with self.subTest(tau=tau):
                with self.assertRaises(ValueError):
                    manager()._validate({'task': 'voice_conversion', 'model': 'conversion/installed',
                                         'source_path': 'C:/source.wav', 'reference_path': 'C:/ref.wav', 'tau': tau})


if __name__ == '__main__':
    unittest.main()

"""Our conditioning adapters only: no published model is instantiated or run."""
import tempfile
import unittest
import os
import wave
from pathlib import Path
from unittest.mock import Mock

from serve.test_audio_parameter_bindings import manager, music
from tools.generate_local_audio import music_input_arguments, music_generation_options


class MusicConditioningBindingTests(unittest.TestCase):
    def test_unconditional_uses_original_native_inputs(self):
        model = Mock(); processor = Mock(); model.get_unconditional_inputs.return_value = {'native': 'inputs'}
        inputs, remaining = music_input_arguments({'music_mode': 'unconditional', 'seconds': 5}, processor, model, Mock())
        self.assertEqual(inputs, {'native': 'inputs'}); self.assertEqual(remaining, 5)
        model.get_unconditional_inputs.assert_called_once_with(num_samples=1); processor.assert_not_called()

    def test_greedy_false_is_forwarded_not_overwritten(self):
        request = manager()._validate(music(prompt='', music_mode='unconditional', do_sample=False))
        self.assertEqual(music_generation_options(request), {'do_sample': False})

    def test_unknown_modes_rejected(self):
        for mode in ('melody', 'remote', None):
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):
                    manager()._validate(music(music_mode=mode))

    def test_input_duration_must_leave_generation_space(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'audio.wav'; wav(path, 2)
            value = manager(); value.reference_audio = Mock(return_value=path)
            with self.assertRaisesRegex(ValueError, 'Total music duration'):
                value._validate(music(music_mode='continuation', music_prompt_path=str(path), seconds=2))
            request = value._validate(music(music_mode='continuation', music_prompt_path=str(path), seconds=5))
            self.assertEqual(request['music_prompt_seconds'], 2); self.assertEqual(request['music_prompt_path'], str(path))
            value.reference_audio.assert_called_with(str(path), minimum_seconds=0.1)

    def test_native_processor_receives_resampled_audio_and_correct_remaining_budget(self):
        import subprocess
        root = Path(__file__).resolve().parent.parent
        python = root / 'tools/local-generative-audio/.venv' / ('Scripts' if os.name == 'nt' else 'bin') / ('python.exe' if os.name == 'nt' else 'python')
        if not python.is_file(): self.skipTest('local generative-audio venv is not installed')
        result = subprocess.run([str(python), str(root / 'tools/verify_music_processor_bindings.py')], cwd=root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PASS:', result.stdout)


def wav(path, seconds):
    with wave.open(str(path), 'wb') as clip:
        clip.setnchannels(1); clip.setsampwidth(2); clip.setframerate(16000); clip.writeframes(b'\x01\x00' * int(seconds * 16000))


if __name__ == '__main__':
    unittest.main()

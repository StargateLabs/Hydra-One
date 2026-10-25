"""Our conditioning adapters only: no published model is instantiated or run."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import wave

import pytest

from serve.test_audio_parameter_bindings import manager,music
from tools.generate_local_audio import music_input_arguments,music_generation_options

def test_unconditional_uses_original_native_inputs():
    model=Mock();processor=Mock();model.get_unconditional_inputs.return_value={'native':'inputs'}
    inputs,remaining=music_input_arguments({'music_mode':'unconditional','seconds':5},processor,model,Mock())
    assert inputs=={'native':'inputs'} and remaining==5
    model.get_unconditional_inputs.assert_called_once_with(num_samples=1);processor.assert_not_called()

def test_greedy_false_is_forwarded_not_overwritten():
    request=manager()._validate(music(prompt='',music_mode='unconditional',do_sample=False))
    assert music_generation_options(request)=={'do_sample':False}

@pytest.mark.parametrize('mode',['melody','remote',None])
def test_unknown_modes_rejected(mode):
    with pytest.raises(ValueError):manager()._validate(music(music_mode=mode))

def wav(path,seconds):
    with wave.open(str(path),'wb') as clip:
        clip.setnchannels(1);clip.setsampwidth(2);clip.setframerate(16000);clip.writeframes(b'\x01\x00'*int(seconds*16000))

def test_input_duration_must_leave_generation_space(tmp_path):
    path=tmp_path/'audio.wav';wav(path,2)
    value=manager();value.reference_audio=Mock(return_value=path)
    with pytest.raises(ValueError,match='Total music duration'):value._validate(music(music_mode='continuation',music_prompt_path=str(path),seconds=2))
    request=value._validate(music(music_mode='continuation',music_prompt_path=str(path),seconds=5))
    assert request['music_prompt_seconds']==2 and request['music_prompt_path']==str(path)
    value.reference_audio.assert_called_with(str(path),minimum_seconds=0.1)

def test_native_processor_receives_resampled_audio_and_correct_remaining_budget():
    import subprocess
    root=Path(__file__).resolve().parent.parent
    result=subprocess.run([str(root/'tools/local-generative-audio/.venv/Scripts/python.exe'),str(root/'tools/verify_music_processor_bindings.py')],cwd=root,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert 'PASS:' in result.stdout

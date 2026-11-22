"""Run with the installed audio runtime. Verify our preprocessing, never a model."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import numpy as np
from tools.generate_local_audio import music_input_arguments

soundfile=Mock();soundfile.read.return_value=(np.ones((16000,2),dtype=np.float32),16000)
processor=Mock();processor.feature_extractor=SimpleNamespace(sampling_rate=32000)
model=SimpleNamespace(config=SimpleNamespace(audio_encoder=SimpleNamespace(audio_channels=1)))
_,remaining=music_input_arguments({'music_mode':'continuation','music_prompt_path':'snapshot.wav','prompt':'Piano','seconds':5},processor,model,soundfile)
passed=processor.call_args.kwargs
assert passed['audio'].shape==(32000,) and passed['sampling_rate']==32000
assert passed['text']==['Piano'] and remaining==4
soundfile.read.assert_called_once_with('snapshot.wav',dtype='float32',always_2d=True)
print('PASS: native processor receives audio, text and remaining generation budget')

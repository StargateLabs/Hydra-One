import io,tempfile,unittest,wave
from pathlib import Path
from unittest.mock import Mock
from serve.local_audio import LocalAudio,validate_wav
from serve.local_speech import LocalSpeech

def wav(frames=16000):
    output=io.BytesIO()
    with wave.open(output,'wb') as audio:audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(b'\0\0'*frames)
    return output.getvalue()
class AudioTests(unittest.TestCase):
    def test_wav_bounds_and_truncation(self):
        self.assertEqual(validate_wav(wav()),1)
        for data in (wav(0),wav(16000*301),wav()[:-10]):
            with self.assertRaises(ValueError):validate_wav(data)
    def test_wrong_asr_model_rejected_before_worker(self):
        with tempfile.TemporaryDirectory() as root:
            engine=LocalAudio(root)
            with self.assertRaises(ValueError):engine.transcribe(wav(),model='not-installed')
            self.assertIsNone(engine.child)
    def test_thread_change_requires_unload(self):
        with tempfile.TemporaryDirectory() as root:
            engine=LocalAudio(root);engine.models=Path(root);model=Path(root)/'tiny.bin';model.touch()
            engine.child=Mock();engine.child.poll.return_value=None;engine.state={'model_path':str(model.resolve()),'threads':2}
            with self.assertRaises(ValueError):engine.start({'model_path':str(model),'threads':4})
    def test_speech_format_language_and_text_validation(self):
        with tempfile.TemporaryDirectory() as root:
            engine=LocalSpeech(root)
            for payload in ({'input':'x','response_format':'mp3'},{'input':'x','language':'unknown'},{'input':''},{'input':'x','speed':True}):
                with self.assertRaises(ValueError):engine.generate(payload)
            self.assertIsNone(engine.child)

    def test_reference_voice_accepts_pcm24k_and_rejects_short_or_truncated(self):
        with tempfile.TemporaryDirectory() as root:
            engine=LocalSpeech(root);path=Path(root)/'reference.wav'
            output=io.BytesIO()
            with wave.open(output,'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(24000);audio.writeframes(b'\0\0'*48000)
            data=output.getvalue();path.write_bytes(data)
            self.assertEqual(engine.reference_audio(str(path)),path)
            path.write_bytes(data[:-10])
            with self.assertRaises(ValueError):engine.reference_audio(str(path))
            path.write_bytes(wav(8000))
            with self.assertRaises(ValueError):engine.reference_audio(str(path))

    def test_audio_processing_bounds(self):
        from serve.local_audio import process_audio
        for options in ({'start':-1},{'duration':301},{'normalize':'yes'}):
            with self.assertRaises(ValueError):process_audio(wav(),'input.wav',**options)

    def test_multiple_speech_models_keep_cached_voice_metadata(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            engine=LocalSpeech(root);engine.models=Path(root)
            for name in ('kokoro-first.gguf','kokoro-second.gguf'):(Path(root)/name).write_bytes(b'test')
            with patch('serve.gguf_metadata_light.metadata_string',return_value='{"ui":{"builtin_voices":["voice"]}}') as read:
                self.assertEqual(len(engine.model_choices()),2);engine.model_choices()
                self.assertEqual(read.call_count,2)
                (Path(root)/'kokoro-first.gguf').write_bytes(b'changed')
                engine.model_choices();self.assertEqual(read.call_count,3)

    def test_selected_audio_runtime_rejects_modified_files_and_wrong_scope(self):
        import json,hashlib
        from serve.local_speech import selected_audio_runtime
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'output/updates/candidates/test';folder.mkdir(parents=True)
            binary=folder/'audiocpp_server.exe';binary.write_bytes(b'candidate')
            selection={'scope':'audio_cpu','directory':str(folder),'binary':str(binary),'validation':{'task':'tts'},'files':[{'path':binary.name,'sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}]}
            registry=Path(root)/'data/audio-runtime-selection.json';registry.parent.mkdir();registry.write_text(json.dumps({'active':selection}))
            self.assertEqual(selected_audio_runtime(root),binary)
            binary.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):selected_audio_runtime(root)

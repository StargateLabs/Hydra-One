from pathlib import Path
from serve.local_audio import LocalAudio,process_audio,subtitle_text,transcript_segments
import json
root=Path.cwd();engine=LocalAudio(root)
assert transcript_segments({'segments':[{'start':0,'end':1,'text':'test'},{'start':float('nan'),'end':1,'text':'bad'}]},2)==[{'start':0,'end':1,'text':'test'}]
assert '00:00:00,000 --> 00:00:01,000' in subtitle_text([{'start':0,'end':1,'text':'test'}])
try:
 audio,metrics=process_audio((root/'output/verification/speech-italian-cpu.wav').read_bytes(),'sample.wav',duration=8)
 result=engine.transcribe(audio,language='it')
 assert result['text'] and result['segments'] and ' --> ' in result['srt'] and result['vtt'].startswith('WEBVTT')
 (root/'output/verification/whisper-subtitles-real.json').write_text(json.dumps({'passed':True,'scope':'Eight-second CPU transcription and engine timestamps; no accuracy claim','result':result},ensure_ascii=False,indent=2),encoding='utf-8')
 print('Real Whisper subtitles passed')
finally:engine.stop()

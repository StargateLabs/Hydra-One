import io,json,subprocess,urllib.request,urllib.error,wave
from pathlib import Path
import imageio_ffmpeg
root=Path.cwd();base='http://127.0.0.1:8088';report={'scope':'Actual CPU audio API checks, not voice-quality comparison'}
def request(path,body=None,content='application/json'):
 raw=json.dumps(body).encode() if isinstance(body,dict) else body
 req=urllib.request.Request(base+path,data=raw,headers={'Content-Type':content,'Origin':base})
 with urllib.request.urlopen(req,timeout=180) as response:
  data=response.read();return json.loads(data) if response.headers.get_content_type()=='application/json' else data
assert request('/local-audio')['status']=='idle';assert request('/local-speech')['status']=='idle'
try:
 mp3=root/'output/verification/audio-jfk-api.mp3'
 subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-nostdin','-hide_banner','-loglevel','error','-i',str(root/'output/verification/audio-jfk.wav'),'-threads','2',str(mp3)],check=True)
 boundary='StrataAudioVerification';parts=[]
 for key,value in [('model','ggml-tiny'),('language','en'),('response_format','text')]:parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+value+'\r\n').encode())
 parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="sample.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n').encode()+mp3.read_bytes()+b'\r\n--'+boundary.encode()+b'--\r\n')
 text=request('/v1/audio/transcriptions',b''.join(parts),'multipart/form-data; boundary='+boundary).decode()
 assert 'country' in text.lower(),text;report['transcription']={'format':'multipart MP3 to text','text':text,'status':request('/local-audio')}
 speech=request('/v1/audio/speech',{'model':'kokoro-82m-q8_0','input':'Ciao, benvenuto.','voice':'if_sara','language':'it','response_format':'wav'})
 with wave.open(io.BytesIO(speech)) as audio:report['speech']={'frames':audio.getnframes(),'rate':audio.getframerate(),'bytes':len(speech)}
 assert report['speech']['frames']>0
 for path,body in [('/v1/audio/speech',{'model':'not-installed','input':'Ciao'}),('/local-audio/transcribe',{'model':'not-installed','audio_base64':'AA==','name':'test.wav'})]:
  try:request(path,body)
  except urllib.error.HTTPError as error:assert error.code==400
  else:raise AssertionError('Unknown model accepted')
 report['unknown_models_rejected']=True;report['passed']=True
finally:
 request('/local-audio/stop',{});request('/local-speech/stop',{})
 (root/'output/verification/audio-api-cpu.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('Multipart MP3 transcription, Italian WAV speech and model identity checks passed')

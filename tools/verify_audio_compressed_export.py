import io,wave,json,sys,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from serve.audio_library import AudioLibrary
root=Path.cwd();library=AudioLibrary(root);buffer=io.BytesIO()
with wave.open(buffer,'wb') as writer:writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(8000);writer.writeframes(b'\x00\x00'*8000)
original=buffer.getvalue();record=library.save(original,{'model':'Export verification','audio_seconds':1,'device':'cpu'});rows=[]
try:
 for fmt,mime in [('mp3','audio/mpeg'),('flac','audio/flac'),('ogg','audio/ogg')]:
  req=urllib.request.Request('http://127.0.0.1:8088/local-speech/library/export',data=json.dumps({'id':record['id'],'format':fmt}).encode(),headers={'Content-Type':'application/json','Origin':'http://127.0.0.1:8088'})
  with urllib.request.urlopen(req,timeout=25) as response:
   data=response.read();assert response.headers.get_content_type()==mime and len(data)>100;rows.append({'format':fmt,'mime':mime,'bytes':len(data),'download':response.headers.get('Content-Disposition')})
 assert library.read(record['id'])==original
 (root/'output/verification/audio-compressed-export-api-real.json').write_text(json.dumps({'passed':True,'formats':rows,'original_preserved':True,'scope':'Real local HTTP conversion and download headers for three formats; no quality gain claim'},indent=2),encoding='utf-8')
 print('Three audio formats: HTTP downloads and original integrity passed')
finally:library.delete(record['id'])

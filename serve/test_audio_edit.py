import io,tempfile,unittest,wave
import numpy as np
from serve.audio_library import AudioLibrary
from serve.audio_edit import edit_audio,import_audio

class AudioEditTests(unittest.TestCase):
    def test_trim_gain_channels_and_original_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            buffer=io.BytesIO()
            with wave.open(buffer,'wb') as w:
                w.setnchannels(2);w.setsampwidth(2);w.setframerate(8000);w.writeframes(np.full((8000,2),1000,dtype='<i2').tobytes())
            library=AudioLibrary(root);original=buffer.getvalue();entry=library.save(original,{'audio_seconds':1})
            result=edit_audio(root,{'id':entry['id'],'start_seconds':.25,'end_seconds':.75,'gain_db':6.020599913,'channels':1})
            with wave.open(io.BytesIO(library.read(result['artifact']['id']))) as w:
                self.assertEqual(w.getnchannels(),1);self.assertEqual(w.getnframes(),4000)
                self.assertTrue(np.all(np.frombuffer(w.readframes(4000),dtype='<i2')==2000))
            self.assertEqual(library.read(entry['id']),original)
            self.assertEqual(library.list()[0]['operation']['source_id'],entry['id'])
            for extra in ({'start_seconds':2},{'gain_db':float('nan')},{'channels':True}):
                with self.assertRaises(ValueError):edit_audio(root,{'id':entry['id'],**extra})
            self.assertEqual(len(library.list()),2)
            import base64
            imported=import_audio(root,{'audio_base64':base64.b64encode(original).decode()})
            self.assertAlmostEqual(imported['artifact']['audio_seconds'],1)
            with wave.open(io.BytesIO(library.read(imported['artifact']['id']))) as w:self.assertEqual((w.getnchannels(),w.getframerate()),(1,44100))
            converted=edit_audio(root,{'id':entry['id'],'sample_rate':16000})
            with wave.open(io.BytesIO(library.read(converted['artifact']['id']))) as w:
                self.assertEqual(w.getframerate(),16000);self.assertEqual(w.getnframes(),16000)
            self.assertEqual(library.read(entry['id']),original)

class AudioExportTests(unittest.TestCase):
 def test_formats_original_preserved_and_flac_lossless(self):
  import subprocess,imageio_ffmpeg
  from serve.audio_edit import export_audio
  with tempfile.TemporaryDirectory() as root:
   library=AudioLibrary(root);buffer=io.BytesIO();pcm=np.arange(8000,dtype='<i2').tobytes()
   with wave.open(buffer,'wb') as writer:writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(8000);writer.writeframes(pcm)
   original=buffer.getvalue();entry=library.save(original,{'audio_seconds':1})
   for name,mime in [('mp3','audio/mpeg'),('flac','audio/flac'),('ogg','audio/ogg')]:
    data,kind=export_audio(root,{'id':entry['id'],'format':name});self.assertEqual(kind,mime);self.assertGreater(len(data),100)
    if name=='flac':
     result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-i','pipe:0','-f','s16le','pipe:1'],input=data,capture_output=True,check=True)
     self.assertEqual(result.stdout,pcm)
   self.assertEqual(library.read(entry['id']),original);self.assertEqual(len(library.list()),1)
   for name in ('wav','../bad','aac'):
    with self.assertRaises(ValueError):export_audio(root,{'id':entry['id'],'format':name})

if __name__=='__main__':unittest.main()

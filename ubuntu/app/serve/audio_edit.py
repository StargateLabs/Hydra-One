"""Local PCM editing of registered library artifacts; always creates a copy."""
import io, math, time, wave, subprocess, tempfile
import numpy as np
from serve.audio_library import AudioLibrary

def edit_audio(root, payload):
    if not isinstance(payload, dict):raise ValueError('Send a JSON object')
    def number(key, default):
        value=payload.get(key,default)
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Invalid '+key)
        return value
    library=AudioLibrary(root);identity=payload.get('id');source=library.read(identity)
    with wave.open(io.BytesIO(source)) as reader:
        channels=reader.getnchannels();rate=reader.getframerate();frames=reader.getnframes()
        if channels not in (1,2) or reader.getsampwidth()!=2 or not 8000<=rate<=48000:raise ValueError('Use PCM16 mono/stereo WAV at 8–48 kHz')
        raw=reader.readframes(frames)
        if len(raw)!=frames*channels*2:raise ValueError('Truncated audio')
    duration=frames/rate;start=number('start_seconds',0);end=number('end_seconds',duration);gain=number('gain_db',0)
    output_channels=payload.get('channels',channels)
    output_rate=payload.get('sample_rate',rate)
    if type(output_rate) is not int or output_rate not in (8000,16000,22050,24000,32000,44100,48000) and output_rate!=rate:raise ValueError('Choose a supported sample rate')
    if type(output_channels) is not int or output_channels not in (1,2):raise ValueError('Choose mono or stereo')
    if not 0<=start<end<=duration or end-start>180:raise ValueError('Choose a valid interval up to 180 seconds')
    if not -24<=gain<=12:raise ValueError('Volume must be between -24 and +12 dB')
    begin=time.monotonic();samples=np.frombuffer(raw,dtype='<i2').reshape(-1,channels)[int(start*rate):int(end*rate)].astype(np.float64)
    if not len(samples):raise ValueError('The selected interval contains no samples')
    if output_channels==1 and channels==2:samples=samples.mean(axis=1,keepdims=True)
    elif output_channels==2 and channels==1:samples=np.repeat(samples,2,axis=1)
    samples*=10**(gain/20);clipped=int(np.count_nonzero((samples>32767)|(samples<-32768)))
    pcm=np.clip(np.rint(samples),-32768,32767).astype('<i2').tobytes();buffer=io.BytesIO()
    with wave.open(buffer,'wb') as writer:
        writer.setnchannels(output_channels);writer.setsampwidth(2);writer.setframerate(rate);writer.writeframes(pcm)
    audio=buffer.getvalue()
    if output_rate!=rate:
        import imageio_ffmpeg
        with tempfile.TemporaryDirectory() as temporary:
            from pathlib import Path
            source_path=Path(temporary)/'input.wav';target=Path(temporary)/'output.wav';source_path.write_bytes(audio)
            try:subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-hide_banner','-loglevel','error','-i',str(source_path),'-ar',str(output_rate),'-c:a','pcm_s16le',str(target)],check=True,capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except (subprocess.SubprocessError,OSError) as error:raise ValueError('Local audio conversion failed') from error
            audio=target.read_bytes()
    with wave.open(io.BytesIO(audio)) as check:output_seconds=check.getnframes()/check.getframerate()
    operation={'source_id':identity,'start_seconds':start,'end_seconds':end,'gain_db':gain,'channels':output_channels,'sample_rate':output_rate,'clipped_samples':clipped}
    artifact=library.save(audio,{'model':'PCM edit','audio_seconds':output_seconds,'device':'cpu','elapsed_seconds':time.monotonic()-begin,'operation':operation})
    return {'artifact':artifact,'operation':operation}


def import_audio(root,payload):
    import base64,imageio_ffmpeg
    from pathlib import Path
    encoded=payload.get('audio_base64') if isinstance(payload,dict) else None
    if not isinstance(encoded,str) or not 0<len(encoded)<=16*1024**2:raise ValueError('Use an audio file up to 12 MiB')
    audio=base64.b64decode(encoded,validate=True)
    if not 0<len(audio)<=12*1024**2:raise ValueError('Use an audio file up to 12 MiB')
    begin=time.monotonic()
    with tempfile.TemporaryDirectory() as temporary:
        source=Path(temporary)/'input.audio';target=Path(temporary)/'output.wav';source.write_bytes(audio)
        try:subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-hide_banner','-loglevel','error','-protocol_whitelist','file,pipe','-i',str(source),'-map','0:a:0','-t','181','-ar','44100','-ac','1','-c:a','pcm_s16le',str(target)],check=True,capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except (subprocess.SubprocessError,OSError) as error:raise ValueError('Unsupported audio or local conversion failed') from error
        if target.stat().st_size>16*1024**2:raise ValueError('Use audio up to 180 seconds')
        result=target.read_bytes()
    with wave.open(io.BytesIO(result)) as reader:seconds=reader.getnframes()/reader.getframerate()
    if not 0<seconds<=180:raise ValueError('Use audio up to 180 seconds')
    artifact=AudioLibrary(root).save(result,{'model':'Imported audio','device':'cpu','audio_seconds':seconds,'elapsed_seconds':time.monotonic()-begin})
    return {'artifact':artifact,'sample_rate':44100,'channels':1}


# Compression produces a download only; originals and library records remain intact.
import threading
_EXPORT_LOCK=threading.Lock()
def export_audio(root,payload):
    if not isinstance(payload,dict) or set(payload)-{'id','format'}:raise ValueError('Invalid audio export request')
    format_name=payload.get('format')
    encoders={'mp3':('libmp3lame','audio/mpeg',['-q:a','2']),'flac':('flac','audio/flac',[]),'ogg':('libvorbis','audio/ogg',['-q:a','5'])}
    if not isinstance(format_name,str) or format_name not in encoders:raise ValueError('Choose MP3, FLAC or OGG')
    audio=AudioLibrary(root).read(payload.get('id'))
    with wave.open(io.BytesIO(audio)) as reader:
        if reader.getnchannels() not in (1,2) or reader.getsampwidth()!=2 or not 0<reader.getnframes()/reader.getframerate()<=180:raise ValueError('Export supports PCM16 audio up to 180 seconds')
    if not _EXPORT_LOCK.acquire(False):raise ValueError('An audio export is already running')
    try:
        from pathlib import Path
        import imageio_ffmpeg
        codec,mime,options=encoders[format_name]
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'input.wav';target=Path(temporary)/('export.'+format_name);source.write_bytes(audio)
            try:subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-hide_banner','-loglevel','error','-protocol_whitelist','file,pipe','-i',str(source),'-map','0:a:0','-c:a',codec,*options,str(target)],check=True,capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except (OSError,subprocess.SubprocessError) as error:raise ValueError('Local audio export failed') from error
            if not 0<target.stat().st_size<=32*1024**2:raise ValueError('Audio export exceeds size limit')
            return target.read_bytes(),mime
    finally:_EXPORT_LOCK.release()

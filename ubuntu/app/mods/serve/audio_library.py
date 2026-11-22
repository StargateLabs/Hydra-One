"""Bounded local generated-audio library. No uploads or network calls."""
import hashlib,json,re,time,uuid,threading
from pathlib import Path
from serve.configuration import atomic_json

class AudioLibrary:
    _lock=threading.RLock()
    def __init__(self,root):self.folder=Path(root)/'output/audio-library'
    def save(self,audio,metadata):
        with self._lock:return self._save(audio,metadata)
    def save_batch(self,items):
        if not isinstance(items,list) or not 1<=len(items)<=16:raise ValueError('Use 1–16 audio outputs per batch')
        if any(not isinstance(audio,bytes) or not 0<len(audio)<=32*1024**2 or not isinstance(metadata,dict) for audio,metadata in items):raise ValueError('Invalid audio batch')
        with self._lock:
            files=list(self.folder.glob('*.wav'))
            if len(files)+len(items)>100 or sum(p.stat().st_size for p in files)+sum(len(audio) for audio,_ in items)>1024**3:raise ValueError('Audio library capacity reached: download or remove older audio')
            created=[]
            try:
                for audio,metadata in items:created.append(self._save(audio,metadata))
            except Exception:
                for record in created:
                    target=self.folder/(record['id']+'.wav');target.unlink(missing_ok=True);target.with_suffix('.json').unlink(missing_ok=True)
                raise
            return created
    def _save(self,audio,metadata):
        if not isinstance(audio,bytes) or not 0<len(audio)<=32*1024**2:raise ValueError('Audio library output limit exceeded')
        self.folder.mkdir(parents=True,exist_ok=True)
        files=list(self.folder.glob('*.wav'))
        if len(files)>=100 or sum(path.stat().st_size for path in files)+len(audio)>1024**3:raise ValueError('Audio library capacity reached: download or remove older audio')
        identity=uuid.uuid4().hex;target=self.folder/(identity+'.wav')
        record={key:metadata.get(key) for key in ('model','device','voice','audio_seconds','elapsed_seconds','language')}
        if isinstance(metadata.get('operation'),dict):record['operation']=metadata['operation']
        record.update(id=identity,created_at=time.time(),bytes=len(audio),sha256=hashlib.sha256(audio).hexdigest(),mime_type='audio/wav')
        created=False
        try:
            with target.open('xb') as stream:
                created=True;stream.write(audio)
            atomic_json(target.with_suffix('.json'),record)
        except Exception:
            if created:target.unlink(missing_ok=True)
            raise
        return record
    def list(self):
        with self._lock:return self._list()
    def _list(self):
        rows=[]
        for path in self.folder.glob('*.json'):
            try:
                if path.is_symlink() or path.stat().st_size>8192:continue
                record=json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(record,dict):continue
                if not re.fullmatch('[a-f0-9]{32}',record.get('id','')) or record['id']!=path.stem:continue
                artifact=path.with_suffix('.wav')
                if not artifact.is_file() or artifact.is_symlink() or artifact.stat().st_size!=record.get('bytes'):continue
                rows.append(record)
            except (OSError,ValueError,TypeError):continue
        return sorted(rows,key=lambda row:row.get('created_at',0),reverse=True)[:100]
    def read(self,identity):
        with self._lock:return self._read(identity)
    def _read(self,identity):
        if not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{32}',identity):raise ValueError('Invalid generated audio identity')
        folder=self.folder.resolve();target=self.folder/(identity+'.wav')
        if target.is_symlink() or not target.resolve().is_relative_to(folder):raise ValueError('Invalid generated audio path')
        manifest=target.with_suffix('.json')
        if manifest.is_symlink() or not manifest.resolve().is_relative_to(folder) or manifest.stat().st_size>8192:raise ValueError('Invalid generated audio metadata')
        metadata=json.loads(manifest.read_text(encoding='utf-8'))
        if not isinstance(metadata,dict) or metadata.get('id')!=identity:raise ValueError('Invalid generated audio metadata')
        if not 0<target.stat().st_size<=32*1024**2:raise ValueError('Invalid generated audio size')
        data=target.read_bytes()
        if len(data)!=metadata.get('bytes') or hashlib.sha256(data).hexdigest()!=metadata.get('sha256'):raise ValueError('Generated audio integrity check failed')
        return data
    def delete(self,identity):
        with self._lock:return self._delete(identity)
    def _delete(self,identity):
        self.read(identity)
        target=self.folder/(identity+'.wav');target.unlink();target.with_suffix('.json').unlink()
        return {'removed':True,'id':identity}

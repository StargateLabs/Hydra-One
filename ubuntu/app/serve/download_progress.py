"""Hugging Face byte callbacks; file length is never a transfer counter."""
from collections import deque
import threading,time

class DownloadProgress:
    def __init__(self,total,publish,cached=0,clock=time.monotonic):
        self.total=int(total);self.cached=int(cached);self.publish=publish;self.clock=clock
        self.lock=threading.Lock();self.values={'model':0,'network':0};self.samples={'model':deque(maxlen=160),'network':deque(maxlen=160)};self.started=clock();self.last_publish=-1e20
        for samples in self.samples.values():samples.append((self.started,0))
    def record(self,channel,value,force=False):
        with self.lock:
            now=self.clock();old=self.values[channel];self.values[channel]=max(0,int(value));samples=self.samples[channel]
            if self.values[channel]<old:samples.clear()
            samples.append((now,self.values[channel]))
            while len(samples)>2 and samples[1][0]<now-8:samples.popleft()
            if not force and now-self.last_publish<0.2:return
            self.last_publish=now;result=self._snapshot(now)
        self.publish(result)
    def _rate(self,channel):
        s=self.samples[channel]
        if len(s)<2 or s[-1][0]-s[0][0]<1:return None
        return max(0,(s[-1][1]-s[0][1])/(s[-1][0]-s[0][0]))
    def _snapshot(self,now):
        received=min(self.total,self.cached+self.values['model']);network=self._rate('network');written=self._rate('model')
        return dict(total_bytes=self.total,received_bytes=received,network_bytes=self.values['network'],network_bytes_per_second=network,
                    percent=100*received/self.total if self.total else None,eta_seconds=(self.total-received)/written if written and received<self.total else None,
                    elapsed_seconds=now-self.started,updated_at=time.time(),source='Hugging Face transfer and reconstruction callbacks')
    def finish(self):self.record('model',self.total-self.cached,True)
    def progress_class(self):
        from huggingface_hub.utils import tqdm as HFProgress
        tracker=self
        class TrackedProgress(HFProgress):
            def __init__(self,*args,**kwargs):
                self._observed=float(kwargs.get('initial',0));self._transfer=0;self._counter_lock=threading.Lock();self._tracking=False
                name=kwargs.get('name','');desc=kwargs.get('desc','');self._channel='network' if name.endswith('.transfer') or desc=='Downloading bytes' else 'model'
                self._bytes=kwargs.get('unit')=='B'
                super().__init__(*args,**kwargs);self._tracking=True;self._emit(True)
            def _emit(self,force=False):
                if self._tracking and self._bytes:tracker.record(self._channel,self._observed,force)
            def update(self,n=1):
                with self._counter_lock:self._observed+=n or 0
                result=super().update(n);self._emit();return result
            def update_transfer(self,n):
                with self._counter_lock:self._transfer+=n
                tracker.record('network',self._transfer)
            def refresh(self,*args,**kwargs):
                result=super().refresh(*args,**kwargs);self._emit();return result
            def close(self):
                result=super().close();self._emit(True);return result
        return TrackedProgress

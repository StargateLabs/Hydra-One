"""Owned, cancellable offline GGUF conversion with persisted results."""
import json,os,re,shutil,subprocess,threading,time,uuid
from pathlib import Path
from serve.configuration import atomic_json
from serve.gpu_lease import GpuLease

class LocalExport:
    def __init__(self,manager):
        self.manager=manager;self.root=manager.root;self.lock=threading.RLock()
        self.process=None;self.lease=None;self.state={'status':'idle','device':'cpu'}
        self.state_path=self.root/'data/local-export-last.json'
        try:
            saved=json.loads(self.state_path.read_text(encoding='utf-8'))
            if saved.get('status') in ('complete','failed','cancelled'):self.state=saved
        except (OSError,ValueError,AttributeError):pass
    def preflight(self,payload):
        import psutil
        from serve.safetensors_runtime import inspect_model
        if payload.get('type','f16') not in ('f16','bf16','q8_0'):raise ValueError('Choose F16, BF16 or Q8_0')
        model=Path(payload.get('model','')).resolve(strict=True);info=inspect_model(model)
        converter=Path.home()/'.unsloth/llama.cpp/convert_hf_to_gguf.py'
        available=psutil.virtual_memory().available;disk=shutil.disk_usage(self.root).free
        ram_needed=info['bytes']*3+1024**3;disk_needed=info['bytes']*2+1024**3
        reasons=[]
        if not converter.is_file() or not self.manager.python_runtime.is_file():reasons.append('Installed converter unavailable')
        if ram_needed>available:reasons.append('Insufficient available RAM for conservative conversion estimate')
        if disk_needed>disk:reasons.append('Insufficient disk space')
        return dict(ready=not reasons,model=str(model),type=payload.get('type','f16'),source_bytes=info['bytes'],estimated_ram_bytes=ram_needed,available_ram_bytes=available,estimated_disk_bytes=disk_needed,available_disk_bytes=disk,reasons=reasons,estimate_scope='Conservative estimate; actual RAM is measured while running')
    def status(self):
        with self.lock:
            if self.process and self.process.poll() is not None:
                code=self.process.returncode;report_path=Path(self.state['output']).with_suffix('.export.json')
                try:report=json.loads(report_path.read_text(encoding='utf-8'))
                except (OSError,ValueError):report={}
                output=Path(self.state['output'])
                valid=code==0 and report.get('status')=='complete' and output.is_file() and report.get('bytes')==output.stat().st_size and output.stat().st_size>0 and bool(re.fullmatch('[a-f0-9]{64}',str(report.get('sha256',''))))
                self.state.update(status='cancelled' if self.state.get('cancel_requested') else 'complete' if valid else 'failed',returncode=code,result=report,finished_at=time.time())
                self.process=None
                folder=Path(self.state['output']).parent
                if folder.is_relative_to(self.root/'output/model-exports'):
                    for partial in folder.glob('*.partial.gguf'):partial.unlink(missing_ok=True)
                try:
                    self.state_path.parent.mkdir(parents=True,exist_ok=True)
                    atomic_json(self.state_path,self.state)
                except OSError as error:self.state['persistence_error']=str(error)
                finally:
                    if self.lease:self.lease.release();self.lease=None
                self.manager.model_cache_at=0
            result=dict(self.state)
            if self.process:
                try:
                    import psutil
                    parent=psutil.Process(self.process.pid)
                    result['process_rss_bytes']=sum(p.memory_info().rss for p in [parent,*parent.children(recursive=True)])
                except (OSError,psutil.Error):pass
                result['elapsed_seconds']=time.time()-self.state['started_at']
            return result
    def start(self,payload,operational_idle):
        with self.lock:
            if self.status()['status']=='running':raise ValueError('Conversion already running')
            if not operational_idle or self.manager.status()['status']!='idle':raise ValueError('Unload inference models before converting')
            plan=self.preflight(payload)
            if not plan['ready']:raise ValueError('; '.join(plan['reasons']))
            self.lease=GpuLease(self.root,'local-export-cpu').acquire()
            try:
                folder=self.root/'output/model-exports'/uuid.uuid4().hex;folder.mkdir(parents=True)
                name=Path(plan['model']).name;output=folder/(name+'-'+plan['type']+'.gguf');log=folder/'worker.log'
                env=dict(os.environ,CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
                with log.open('wb') as stream:
                    self.process=subprocess.Popen([str(self.manager.python_runtime),'-X','utf8',str(self.root/'tools/export_local_gguf.py'),'--model',plan['model'],'--output',str(output),'--type',plan['type']],cwd=self.root,env=env,stdout=stream,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                self.state=dict(status='running',device='cpu',model=plan['model'],type=plan['type'],output=str(output),log=str(log),started_at=time.time(),plan=plan)
                process=self.process
                threading.Thread(target=self._watch,args=(process,),daemon=True).start()
            except BaseException:
                self.lease.release();self.lease=None;raise
            return self.status()
    def _watch(self,process):
        process.wait()
        with self.lock:
            if self.process is process:self.status()
    def stop(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                import psutil
                self.state['cancel_requested']=True
                try:
                    descendants=psutil.Process(self.process.pid).children(recursive=True)
                    for child in reversed(descendants):
                        try:child.terminate()
                        except psutil.Error:pass
                    _,alive=psutil.wait_procs(descendants,timeout=3)
                    for child in alive:
                        try:child.kill()
                        except psutil.Error:pass
                except psutil.Error:pass
                self.process.terminate()
                try:self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
            return self.status()
    close=stop

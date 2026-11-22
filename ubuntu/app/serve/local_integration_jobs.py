"""Serialize isolated integration setup without blocking HTTP handlers."""
import copy
import threading
import time


class AirLLMSetup:
    def __init__(self, root, idle):
        self.root, self.idle = root, idle
        self.lock = threading.Lock()
        self.job = {'state': 'idle', 'error': None}

    def status(self):
        from serve.airllm_runtime import status
        with self.lock:
            return {**status(self.root), 'job': copy.deepcopy(self.job), 'can_prepare':self.idle()}

    def prepare(self, version=None):
        if not self.idle():
            raise ValueError('Arresta motori e attività prima di preparare AirLLM')
        with self.lock:
            if self.job['state'] == 'preparing':
                raise ValueError('Preparazione AirLLM già in corso')
            self.job = {'state': 'preparing', 'error': None, 'started_at': time.time()}
        threading.Thread(target=self._prepare, args=(version,), daemon=True).start()
        return self.status()

    def rollback(self):
        from serve.airllm_runtime import select_version
        if not self.idle():raise ValueError('Arresta motori e attività prima di ripristinare AirLLM')
        result=select_version(self.root,None,rollback=True)
        with self.lock:self.job={'state':'prepared','result':result,'finished_at':time.time(),'error':None}
        return self.status()

    def _prepare(self, version):
        from serve.airllm_runtime import prepare
        try:
            result = prepare(self.root, version)
            with self.lock:
                self.job.update(state='prepared', result=result, finished_at=time.time())
        except Exception as error:
            with self.lock:
                self.job.update(state='error', error=str(error)[:800], finished_at=time.time())


class OpenWebUISetup(AirLLMSetup):
    def status(self):
        from serve.open_webui_runtime import status
        state=status(self.root)
        with self.lock:
            state['job']=copy.deepcopy(self.job) if self.job['state']=='preparing' else state.get('job') or copy.deepcopy(self.job)
        state['can_prepare']=self.idle() and not state['setup_busy'] and not state['busy']
        return state

    def prepare(self,version=None):
        if not self.idle():raise ValueError('Arresta motori e attività prima di preparare Open WebUI')
        with self.lock:
            if self.job['state']=='preparing':raise ValueError('Preparazione Open WebUI già in corso')
            self.job={'state':'preparing','error':None,'started_at':time.time()}
        threading.Thread(target=self._prepare,args=(version,),daemon=True).start()
        return self.status()

    def _prepare(self,version):
        from serve.open_webui_runtime import prepare
        try:
            result=prepare(self.root,version)
            with self.lock:self.job.update(state='prepared',version=result['version'],finished_at=time.time())
        except Exception as error:
            with self.lock:self.job.update(state='error',error=str(error)[:1000],finished_at=time.time())

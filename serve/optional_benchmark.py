"""Benchmark the connected backend under its existing exclusive GPU lease."""
import copy
import hashlib
import json
import math
import statistics
import threading
import time
import uuid
from pathlib import Path

class OptionalBenchmark:
    def __init__(self, manager):
        self.manager=manager;self.lock=threading.Lock();self.cancel=threading.Event()
        self.job={'status':'idle','results':[]};self.history=[]
        for path in sorted((manager.root/'data/optional-benchmark').glob('*/job.json'),reverse=True)[:50]:
            try:self.history.append(json.loads(path.read_text(encoding='utf-8')))
            except (OSError,ValueError):pass

    def status(self):
        with self.lock:return copy.deepcopy(self.job),copy.deepcopy(self.history)

    def stop(self):
        self.cancel.set()
        with self.lock:
            if self.job['status']=='running':self.job['status']='cancelling'
        return self.status()[0]

    def start(self,payload):
        runs=payload.get('runs',5);tokens=payload.get('tokens',128)
        stream=payload.get('stream',False)
        if type(stream) is not bool:raise ValueError('Stream option must be boolean')
        if type(payload.get('quality',False)) is not bool:raise ValueError('Quality option must be boolean')
        if type(runs) is not int or runs not in tuple(range(3,11))+(20,30) or type(tokens) is not int or not 32<=tokens<=1024:
            raise ValueError('Usa 3–10, 20 o 30 misure e 32–1024 token')
        prompt=payload.get('prompt') or 'Write a detailed continuous story about a researcher exploring a futuristic city. Continue until the output budget is exhausted. Do not end early.'
        if not isinstance(prompt,str) or len(prompt)>20000:raise ValueError('Prompt non valido')
        state=self.manager.status()
        if state['status']!='ready':raise ValueError('Collega prima un motore pronto')
        if not self.manager.conversation_lock.acquire(blocking=False):raise RuntimeError('Una richiesta è già in corso')
        self.cancel=threading.Event()
        stamp=time.strftime('%Y%m%d-%H%M%S')+'-optional-lab-'+uuid.uuid4().hex[:8]
        with self.lock:
            self.job=dict(id=stamp,status='running',mode='manual',model=state['public_model'],backend=state.get('backend'),
                started_at=time.time(),phase='Misure del motore collegato',protocol=dict(tokens=tokens,runs=runs,warmup=1,cache_prompt=False,output_policy='actual_output',stream=stream,prompt_sha256=hashlib.sha256(prompt.encode('utf-8')).hexdigest(),generation_parameters={'temperature':0}),
                total_samples=runs+1+(12 if payload.get('quality') else 0),completed_samples=0,results=[],sample_series=[],configuration={key:state.get(key) for key in ('context','context_per_slot','model_max_context','runtime','gpu_requested','fit_mode','framework','framework_version','architecture','model_type','attention_implementation','speculative_decoding','cache_policy','native_loader','quantization','device','dtype','engine_addon','hydra')})
            if state.get('engine_addon')=='hydra-one':
                from serve.hydra_one import BUNDLE_SHA256
                self.job['configuration']['hydra_bundle_sha256']=BUNDLE_SHA256
        threading.Thread(target=self._run,args=(state,prompt,payload.get('quality',False)),daemon=True).start()
        return self.status()[0]

    def _run(self,state,prompt,quality):
        rows=[];check=None
        try:
            job=self.status()[0];protocol=job['protocol']
            # llama.cpp extensions are not part of the OpenAI API contract.
            # Sending them to other inference engines can cause HTTP 400.
            extras=dict(cache_prompt=False,chat_template_kwargs={'enable_thinking':False}) if state.get('mode')=='gguf' else {}
            for i in range(protocol['runs']+1):
                if self.cancel.is_set():break
                started=time.perf_counter()
                stream=protocol.get('stream',False);events=[];first_content=None;parts=[];timing={};usage={}
                for event in self.manager.chat(dict(messages=[{'role':'user','content':prompt}],stream=stream,
                    max_tokens=protocol['tokens'],temperature=0,**extras),self.cancel):
                    if event.get('error'):raise RuntimeError('Errore di generazione dal backend')
                    events.append(event)
                    if isinstance(event.get('timings'),dict):timing.update(event['timings'])
                    if isinstance(event.get('usage'),dict):usage.update(event['usage'])
                    for choice in event.get('choices',[]):
                        message=choice.get('delta' if stream else 'message') or {}
                        if any(message.get(key) for key in ('content','reasoning_content','tool_calls')):
                            if first_content is None:first_content=time.perf_counter()-started
                            parts.append(message)
                if self.cancel.is_set():break
                if not events:raise RuntimeError('Risposta vuota')
                count=usage.get('completion_tokens',timing.get('predicted_n'))
                if count is not None and (type(count) is not int or count<=0 or count>protocol['tokens']):raise RuntimeError('Conteggio token non valido')
                if not parts:raise RuntimeError('Risposta priva di contenuto utilizzabile')
                speed=timing.get('predicted_per_second');prefill=timing.get('prompt_per_second')
                speed=speed if type(speed) in (int,float) and math.isfinite(speed) and speed>0 else None
                prefill=prefill if type(prefill) in (int,float) and math.isfinite(prefill) and prefill>0 else None
                wall=time.perf_counter()-started
                row=dict(warmup=i==0,output_tokens=count,output_budget_met=count==protocol['tokens'],decode_tok_s=speed,
                         prefill_tok_s=prefill,wall_s=wall,wall_tok_s=count/wall if count is not None else None,
                         ttft_s=first_content if stream else None,http_timing_scope='HTTP request through response completion',
                         generation_ms=timing.get('generation_ms') if type(timing.get('generation_ms')) in (int,float) and math.isfinite(timing['generation_ms']) and timing['generation_ms']>0 else None,
                         timing_scope=timing.get('timing_scope'))
                rows.append(row)
                with self.lock:self.job.update(completed_samples=i+1,sample_series=copy.deepcopy(rows))
            if not self.cancel.is_set():
                if quality:
                    from serve.quality_suite import CASES,evaluate,DATASET_SHA256,CATEGORIES
                    check={'cases':[],'dataset_sha256':DATASET_SHA256,'scope':'12 closed-reference tasks; not general model quality'}
                    for name,task,expected in CASES:
                        if self.cancel.is_set():break
                        with self.lock:self.job['phase']='Controllo risposte · '+name
                        started=time.perf_counter()
                        packets=list(self.manager.chat(dict(messages=[{'role':'user','content':task+' Rispondi soltanto con JSON, senza spiegazioni.'}],stream=False,max_tokens=160,temperature=0,**extras),self.cancel))
                        answer=''.join(event.get('choices',[{}])[0].get('message',{}).get('content') or '' for event in packets)
                        if not packets or not answer:raise RuntimeError('Empty quality response')
                        check['cases'].append({'case':name,'category':CATEGORIES[name],'expected':expected,'answer':answer,'passed':evaluate(answer,expected),'wall_s':time.perf_counter()-started})
                        with self.lock:self.job.update(completed_samples=len(rows)+len(check['cases']),quality_progress=copy.deepcopy(check))
                    if self.cancel.is_set():
                        with self.lock:self.job['status']='cancelled'
                        return
                    check.update(correct=sum(row['passed'] for row in check['cases']),total=len(check['cases']),passed=all(row['passed'] for row in check['cases']))
                from serve.lab_metrics import summarize
                from serve.benchmark_comparison import model_fingerprint
                model_path=state.get('model_path') or state.get('model')
                try:model_digest=model_fingerprint(model_path) if model_path else None
                except (OSError,ValueError):model_digest=None
                with self.lock:self.job['protocol']['model_sha256']=model_digest
                measures=rows[1:];summary=summarize(rows)
                result=dict(variant=state.get('profile','connected'),label=state.get('profile','API locale'),samples=len(measures),summary=summary,series=rows,full_budget=all(row['output_budget_met'] for row in rows),
                    quality={key:check[key] for key in ('correct','total','dataset_sha256','scope')} if check else None)
                with self.lock:self.job.update(status='complete',results=[result],phase='Prova completata')
            else:
                with self.lock:self.job['status']='cancelled'
        except Exception as error:
            with self.lock:self.job.update(status='cancelled' if self.cancel.is_set() else 'failed',error=str(error))
        finally:
            with self.lock:
                self.job['finished_at']=time.time();job=copy.deepcopy(self.job)
                self.history.insert(0,job);self.history=self.history[:50]
            try:
                self._save(job,state,rows,check)
            finally:
                self.manager.conversation_lock.release()

    def _save(self,job,state,rows,check):
            from serve.host_adaptation import host_profile
            host=host_profile(getattr(self.manager,'memory_snapshot',lambda:{})())
            folder=self.manager.root/'data/optional-benchmark'/job['id'];folder.mkdir(parents=True,exist_ok=True)
            (folder/'job.json').write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8')
            report=dict(kind='backend_check',verification_fixture=state.get('verification_fixture',False),id=job['id'],started_at=job['started_at'],backend=state.get('backend'),model_file=state.get('model_path') or state['model'],
                host=host,status=job['status'],publisher=state.get('publisher'),protocol={**job['protocol'],'configuration':job.get('configuration')},runs=[dict(arm='manual',profile=state.get('profile','api'),public_model=state['public_model'],rows=rows,arithmetic_check=check)])
            target=self.manager.root/'data/benchmark-checks';target.mkdir(parents=True,exist_ok=True)
            (target/(job['id']+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

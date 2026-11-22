"""Local benchmark campaigns. Own subprocesses only; never mutate operational configs."""
import copy
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import uuid
import urllib.request
from serve.configuration import atomic_json
from serve.benchmark_monitor import snapshot
from serve.gpu_lease import GpuLease,reserved
from serve.lab_metrics import summarize

VARIANTS={'auto':'Originale · PCIe automatico','pcie20':'Quota PCIe 20%','pcie55':'Quota PCIe 55%','tsum':'Somme raggruppate'}
ACTIVE={'queued','running','cancelling'}

def validate_request(payload,models):
    if not isinstance(payload,dict) or set(payload)-{'model','mode','variants','tokens','runs','paragraphs','prompt','quality','ram_gib','workers','spec','reserve_mib'}:
        raise ValueError('Parametri del benchmark non validi')
    model=next((m for m in models if m['id']==payload.get('model') and m['ready']),None)
    if not model:raise ValueError('Modello locale non disponibile')
    mode=payload.get('mode','manual')
    variants=payload.get('variants',['auto'])
    if mode not in ('manual','automatic') or not isinstance(variants,list) or not variants or len(variants)>4 or len(set(variants))!=len(variants) or any(v not in VARIANTS for v in variants):
        raise ValueError('Seleziona profili di prova validi')
    if mode=='manual' and len(variants)!=1:raise ValueError('La prova manuale usa un solo profilo')
    values={}
    for key,default,allowed in (('tokens',256,(128,256,512)),('runs',5,tuple(range(5,11))+(20,30)),('paragraphs',24,(8,16,24,48)),
        ('ram_gib',16,(8,12,16,20,24,28)),('workers',16,(4,7,8,12,16,20,24)),('spec',4,(2,3,4)),('reserve_mib',2560,(2560,3072,4096))):
        value=payload.get(key,default)
        if type(value) is not int or value not in allowed:raise ValueError('Valore non valido: '+key)
        values[key]=value
    prompt=payload.get('prompt','')
    quality=payload.get('quality',False)
    if not isinstance(prompt,str) or len(prompt)>6000 or type(quality) is not bool:raise ValueError('Prompt o opzione qualità non validi')
    return dict(model=model['id'],mode=mode,variants=variants,prompt=prompt.strip(),quality=quality,**values)

def set_arg(args,key,value):
    if key in args:args[args.index(key)+1]=str(value)
    else:args.extend([key,str(value)])

class BenchmarkLab:
    def __init__(self,root):
        self.root=Path(root);self.lock=threading.Lock();self.stop=threading.Event();self.thread=None;self.child=None
        self.state={'status':'idle','phase':'Pronto','results':[]}
        recent=sorted((self.root/'data/benchmark-lab').glob('*/job.json'),reverse=True)
        if recent:
            try:
                saved=json.loads(recent[0].read_text(encoding='utf-8-sig'))
                if saved.get('status') in ('complete','failed','cancelled'):
                    self.state=saved;self.directory=recent[0].parent
                    if saved['status']=='complete':self.state['completed_samples']=saved.get('total_samples',0)
            except (OSError,ValueError):pass
    def models(self):
        from serve.model_inventory import inventory
        return [dict(id=m['config'],label=m.get('label',m['key']),ready=m['ready'] and m.get('backend')=='hip',reason=m['error'] or ('' if m.get('backend')=='hip' else 'Backend HIP non disponibile')) for m in inventory(self.root)]
    def status(self):
        with self.lock:state=copy.deepcopy(self.state)
        feed=snapshot(self.root/'data/benchmark-live.json')
        occupied=reserved(self.root)
        try:reservation=json.loads((self.root/'data/.gpu-campaign.lock').read_text())
        except (OSError,ValueError):reservation={}
        optional=reservation.get('owner')=='optional-backend'
        external=bool(((feed and feed['active']) or (occupied and not optional)) and state['status'] not in ACTIVE)
        history=[]
        for path in sorted((self.root/'data/benchmark-lab').glob('*/job.json'),reverse=True)[:20]:
            try:
                row=json.loads(path.read_text(encoding='utf-8-sig'));history.append({k:row.get(k) for k in ('id','status','model','mode','started_at','finished_at','protocol','prompt_sha256','variant','sample_series','completed_samples','total_samples','results','error')})
            except (OSError,ValueError):continue
        try:campaign=json.loads((self.root/'data/optimization-campaign.json').read_text())
        except (OSError,ValueError):campaign=None
        if campaign and campaign.get('status')=='running' and not external:
            campaign=dict(campaign,status='interrupted')
        history.extend(self.imported_history(history))
        if campaign:
            for job in history:
                if job.get('mode')=='external' and job['id']==campaign.get('id'):
                    job['status']=campaign['status'];job['error']=campaign.get('error')
                    job['total_samples']=campaign.get('total_arms',len(job['results']))*(job['protocol']['warmup']+job['protocol']['runs'])
        history.sort(key=lambda row:row.get('started_at') or 0,reverse=True)
        if state['status'] not in ACTIVE and history and (history[0].get('started_at') or 0)>(state.get('started_at') or 0):state=copy.deepcopy(history[0])
        checks=[]
        for path in sorted((self.root/'data/benchmark-checks').glob('*.json'),reverse=True):
            try:
                row=json.loads(path.read_text(encoding='utf-8-sig'))
                if row.get('kind')=='backend_check' and isinstance(row.get('runs'),list):checks.append(row)
            except (OSError,ValueError):continue
        external_snapshot={'label':feed.get('label'),'metrics':feed.get('metrics'),'active':feed.get('active'),'stale':feed.get('stale')} if feed else None
        quality=[]
        for path in sorted((self.root/'output/verification').glob('*-tasks.json'),reverse=True)[:100]:
            try:
                report=json.loads(path.read_text(encoding='utf-8-sig'));cases=report.get('cases')
                if report.get('status')!='complete' or not isinstance(cases,list) or not cases or any(type(row.get('passed')) is not bool for row in cases):continue
                quality.append(dict(id=path.stem,model=report.get('model'),started_at=report.get('started_at'),correct=sum(row['passed'] for row in cases),total=len(cases),source=path.relative_to(self.root).as_posix()))
            except (OSError,ValueError,TypeError,AttributeError):continue
        from serve.verification_history import verification_history
        return dict(job=state,models=self.models(),variants=VARIANTS,external_active=external,gpu_reserved=occupied,reservation_owner=reservation.get('owner'),external_campaign=campaign,external_snapshot=external_snapshot,history=history,backend_checks=checks,quality_checks=quality,software_checks=verification_history(self.root))

    def imported_history(self,existing):
        """Include externally written measures without changing their protocol."""
        known={r.get('source') for job in existing for r in job.get('results') or []}
        groups={}
        for path in sorted((self.root/'data/benchmarks').glob('*.json')):
            source=path.relative_to(self.root).as_posix()
            if source in known:continue
            try:
                report=json.loads(path.read_text(encoding='utf-8-sig'))
                model=report['engine']['model'];protocol=report['protocol'];label=report.get('label',path.stem)
                started=datetime.fromisoformat(report['started_at'].replace('Z','+00:00')).timestamp()
                import re
                match=re.match(r'^(\d{8}-\d{6})-iq3-memory-(.+)$',label)
                identity=match[1] if match else label
                key=(identity,model,json.dumps(protocol,sort_keys=True))
                job=groups.setdefault(key,dict(id=identity,model=model,mode='external',status='complete',phase='Campagna esterna',started_at=started,protocol=protocol,results=[],completed_samples=0,total_samples=0))
                job['started_at']=min(job['started_at'],started)
                rows=report.get('rows',[])
                if report.get('status')!='complete':job.update(status=report.get('status','failed'),error=report.get('error'));continue
                if len(rows)!=protocol['warmup']+protocol['runs']:continue
                measured=[r for r in rows if not r.get('warmup')]
                if len(measured)!=protocol['runs'] or any(r.get('output_tokens')!=protocol['tokens'] or r.get('reused')!=0 or r.get('warmup')!=(index<protocol['warmup']) for index,r in enumerate(rows)):continue
                if any(type(r.get(k)) not in (int,float) or not math.isfinite(r[k]) or r[k]<=0 for r in rows for k in ('decode_tok_s','prefill_tok_s','wall_s')):continue
                import statistics
                summary={k:dict(median=statistics.median(r[k] for r in measured),min=min(r[k] for r in measured),max=max(r[k] for r in measured),n=len(measured)) for k in ('decode_tok_s','prefill_tok_s','wall_s')}
                variant=match[2] if match else label
                job['results'].append(dict(variant=variant,label=variant,summary=summary,source=source,samples=len(measured),started_at=started,series=[{k:r.get(k) for k in ('decode_tok_s','prefill_tok_s','wall_tok_s','wall_s','output_tokens','warmup')} for r in rows]))
                job['completed_samples']+=len(rows);job['total_samples']+=len(rows)
            except (OSError,ValueError,KeyError,TypeError,OverflowError):continue
        for job in groups.values():job['results'].sort(key=lambda row:row['started_at'])
        return [job for job in groups.values() if job['results'] or job['status']!='complete']
    def update(self,**fields):
        with self.lock:
            self.state.update(fields)
            if 'id' in self.state:atomic_json(self.directory/'job.json',self.state)
    def start(self,payload,operational_idle):
        request=validate_request(payload,self.models())
        with self.lock:
            if self.state['status'] in ACTIVE:raise RuntimeError('Una campagna è già in corso')
            if not operational_idle:raise RuntimeError('Scarica il motore da Control prima di avviare la prova')
            feed=snapshot(self.root/'data/benchmark-live.json')
            with socket.socket() as probe:occupied=probe.connect_ex(('127.0.0.1',8089))==0
            if occupied or (feed and feed['active']) or (self.root/'data/benchmarks/.benchmark.lock').exists():
                raise RuntimeError('Un altro benchmark sta usando la GPU')
            identity=time.strftime('%Y%m%d-%H%M%S',time.gmtime())+'-'+uuid.uuid4().hex[:6]
            # The scratch server is an actual descendant under this bounded check.
            self.lease=GpuLease(self.root,'strata-bounded-check').acquire()
            self.directory=self.root/'data/benchmark-lab'/identity
            try:self.directory.mkdir(parents=True)
            except BaseException:
                self.lease.release();raise
            self.stop.clear();self.state=dict(id=identity,status='queued',phase='Preparazione',model=request['model'],mode=request['mode'],
                started_at=time.time(),protocol={k:v for k,v in request.items() if k!='prompt'},prompt_sha256=hashlib.sha256(request['prompt'].encode()).hexdigest(),results=[],completed_samples=0,total_samples=len(request['variants'])*(5+request['runs']+(12 if request['quality'] else 0)))
            try:
                atomic_json(self.directory/'job.json',self.state)
                self.thread=threading.Thread(target=self.run,args=(request,),daemon=True);self.thread.start()
            except BaseException as exc:
                self.state.update(status='failed',phase='Avvio fallito',error=str(exc))
                self.lease.release()
                raise
            return copy.deepcopy(self.state)
    def cancel(self):
        with self.lock:
            if self.state['status'] not in ACTIVE:return {'status':self.state['status']}
        self.stop.set();self.update(status='cancelling',phase='Arresto in corso')
        (self.directory/'stop').write_text('stop',encoding='utf-8')
        return {'status':'cancelling'}
    def active(self):
        with self.lock:return self.state['status'] in ACTIVE
    def publish_feed(self,stop,label):
        latest={'live':{'state':'loading','queued':0}}
        while not stop.is_set():
            try:latest=self.request('/metrics');latest.pop('benchmark',None)
            except (OSError,ValueError):pass
            atomic_json(self.root/'data/benchmark-live.json',dict(label=label,source_port=8089,updated_at=time.time(),active=True,metrics=latest))
            stop.wait(1)
        latest['live']={**latest.get('live',{}),'state':'unloaded','queued':0}
        atomic_json(self.root/'data/benchmark-live.json',dict(label=label,source_port=8089,updated_at=time.time(),active=False,metrics=latest))
    def request(self,path,payload=None):
        data=None if payload is None else json.dumps(payload).encode()
        headers={'Content-Type':'application/json'}
        if getattr(self,'key',''):headers['Authorization']='Bearer '+self.key
        req=urllib.request.Request('http://127.0.0.1:8089'+path,data=data,headers=headers)
        with urllib.request.urlopen(req,timeout=1200 if path=='/load' else 65 if path=='/unload' else 5) as response:return json.load(response)
    def end_process(self,process):
        if process and process.poll() is None:
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
            else:process.terminate()
            process.wait(timeout=20)
    def wait_process(self,process,deadline,report=None,offset=0,graceful=False,quality_report=None):
        self.child=process
        stop_deadline=None
        while process.poll() is None:
            if self.stop.is_set() and (report is not None or graceful) and stop_deadline is None:stop_deadline=time.monotonic()+120
            if (self.stop.is_set() and report is None and not graceful) or time.monotonic()>min(deadline,stop_deadline or deadline):
                self.end_process(process)
                raise RuntimeError('Prova interrotta' if self.stop.is_set() else 'Tempo massimo della prova superato')
            if report and report.exists():
                try:
                    rows=json.loads(report.read_text(encoding='utf-8-sig'))['rows']
                    self.update(completed_samples=offset+len(rows),sample_series=[{k:r.get(k) for k in ('decode_tok_s','prefill_tok_s','wall_tok_s','wall_s','output_tokens','warmup')} for r in rows])
                except (OSError,ValueError,KeyError):pass
            if quality_report and quality_report.exists():
                try:
                    cases=json.loads(quality_report.read_text(encoding='utf-8-sig'))['cases']
                    self.update(completed_samples=offset+len(cases),quality_progress={'completed':len(cases),'total':12,'correct':sum(row.get('passed') is True for row in cases)})
                except (OSError,ValueError,KeyError):pass
            time.sleep(.5)
        return process.returncode
    def child_environment(self):
        environment=dict(os.environ)
        environment['STRATA_VALIDATION_LEASE_TOKEN']=self.lease.token
        if self.key:environment['STRATA_API_KEY']=self.key
        return environment

    def run(self,request):
        from tools.benchmark_guard import require_startup_vram_margin
        server=None;monitor_stop=threading.Event();monitor=None;own_lock=False;log=None
        try:
            self.update(status='running',phase='Controllo GPU')
            probe=subprocess.Popen([str(self.root/'engine/strata-device.exe'),'--selftest'],cwd=self.root,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if self.wait_process(probe,time.monotonic()+60):raise RuntimeError('Controllo GPU fallito; nessun modello caricato')
            original_path=self.root/request['model'];original_bytes=original_path.read_bytes();base=json.loads(original_bytes)
            monitor=threading.Thread(target=self.publish_feed,args=(monitor_stop,'lab-'+self.state['id']),daemon=True);monitor.start()
            if request['prompt']:(self.directory/'prompt.txt').write_text(request['prompt'],encoding='utf-8')
            for index,variant in enumerate(request['variants']):
                if self.stop.is_set():raise RuntimeError('Prova interrotta')
                cfg=copy.deepcopy(base);args=cfg['args']
                cfg.pop('vision',None)
                cfg['benchmark_owner']=self.state['id']+'-'+variant
                self.key=cfg.get('api_key','')
                child_env=self.child_environment()
                cfg.pop('before_load',None)
                for flag,value in (('--resident-budget-gib',request['ram_gib']),('--prefill',512),('--expert-cache',6500),('--vram-reserve-mib',request['reserve_mib']),('--pool-workers',request['workers']),('--spec',request['spec'])):
                    set_arg(args,flag,value)
                if '--pcie-frac' in args:
                    position=args.index('--pcie-frac');del args[position:position+2]
                cfg.pop('expert_profile_save',None)
                if '--expert-profile-save' in args:raise ValueError('Il banco richiede un profilo senza salvataggio operativo')
                if variant.startswith('pcie'):set_arg(args,'--pcie-frac',int(variant[4:])/100)
                cfg.setdefault('env',{})['STRATA_TSUM']='1' if variant=='tsum' else '0'
                label=f'lab-{self.state["id"]}-{variant}'
                cfg['log']=str(self.directory/f'{variant}-engine.log');config_path=self.directory/f'{variant}-config.json';atomic_json(config_path,cfg)
                self.update(phase='Caricamento · '+VARIANTS[variant],variant=variant,sample_series=[])
                log=open(self.directory/f'{variant}-server.log','w',encoding='utf-8')
                server=subprocess.Popen([sys.executable,'serve/server.py','--engine','strata','--config',str(config_path),'--port','8089','--lazy'],cwd=self.root,stdout=log,stderr=subprocess.STDOUT,env=child_env)
                deadline=time.monotonic()+45
                while True:
                    if self.stop.is_set() or server.poll() is not None:raise RuntimeError('Caricamento interrotto')
                    try:
                        health=self.request('/health')
                        if health.get('benchmark_owner')!=cfg['benchmark_owner']:raise RuntimeError('La porta del banco è occupata da un altro processo')
                        break
                    except OSError:
                        if time.monotonic()>deadline:raise RuntimeError('Server di prova non disponibile')
                        time.sleep(.2)
                # Loading runs in a cancellable child; a stuck request cannot block cancellation.
                load=subprocess.Popen([sys.executable,'-c',"import urllib.request,os;h={'Content-Type':'application/json'};k=os.getenv('STRATA_API_KEY');h.update({'Authorization':'Bearer '+k} if k else {});urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8089/load',data=b'{}',headers=h),timeout=1200).read()"],stdout=log,stderr=log,env=child_env)
                if self.wait_process(load,time.monotonic()+1200):raise RuntimeError('Caricamento del modello fallito')
                engine=self.request('/metrics')['engine'];free=require_startup_vram_margin(engine)
                self.update(phase='Misurazione · '+VARIANTS[variant],vram_free_mib=free)
                report=self.root/f'data/benchmarks/{label}.json'
                command=[sys.executable,'tools/benchmark_local.py','--url','http://127.0.0.1:8089','--config',str(config_path),'--label',label,
                    '--tokens',str(request['tokens']),'--runs',str(request['runs']),'--warmup','5','--paragraphs',str(request['paragraphs']),
                    '--prompt-set',self.state['id'],'--output',str(report),'--stop-file',str(self.directory/'stop')]
                if request['prompt']:command+=['--prompt-file',str(self.directory/'prompt.txt')]
                own_lock=not (self.root/'data/benchmarks/.benchmark.lock').exists()
                client=subprocess.Popen(command,cwd=self.root,stdout=log,stderr=log,env=child_env)
                code=self.wait_process(client,time.monotonic()+1800,report,index*(5+request['runs']+(12 if request['quality'] else 0)))
                if self.stop.is_set():raise RuntimeError('Prova interrotta dopo la richiesta in corso')
                if code:raise RuntimeError('Richiesta o misura fallita; campagna fermata')
                data=json.loads(report.read_text(encoding='utf-8-sig'));rows=data['rows']
                if data['status']!='complete' or len(rows)!=5+request['runs'] or any(r['output_tokens']!=request['tokens'] or r['reused']!=0 for r in rows):
                    raise RuntimeError('Rapporto incompleto o non confrontabile')
                if any(not isinstance(r.get(k),(int,float)) or not math.isfinite(r[k]) or r[k]<=0 for r in rows for k in ('decode_tok_s','prefill_tok_s','wall_s','wall_tok_s')):
                    raise RuntimeError('Statistiche non valide')
                result=dict(variant=variant,label=VARIANTS[variant],summary=summarize(rows),source=report.relative_to(self.root).as_posix(),samples=request['runs'],series=[{k:r.get(k) for k in ('decode_tok_s','prefill_tok_s','wall_tok_s','wall_s','output_tokens','warmup')} for r in rows])
                if request['quality']:
                    self.update(phase='Controllo risposte · '+VARIANTS[variant])
                    tasks=self.directory/f'{variant}-tasks.json'
                    process=subprocess.Popen([sys.executable,'tools/verify_iq3_tasks.py','--url','http://127.0.0.1:8089','--output',str(tasks),'--stop-file',str(self.directory/'stop')],cwd=self.root,stdout=log,stderr=log,env=child_env)
                    code=self.wait_process(process,time.monotonic()+600,graceful=True,quality_report=tasks,offset=index*(5+request['runs']+12)+5+request['runs'])
                    if self.stop.is_set():raise RuntimeError('Prova interrotta dopo il compito in corso')
                    quality=json.loads(tasks.read_text(encoding='utf-8-sig'))
                    if code not in (0,2) or quality.get('status')!='complete':raise RuntimeError('Valutazione risposte incompleta')
                    result['quality']={'correct':quality['correct'],'total':quality['total'],'dataset_sha256':quality.get('dataset_sha256'),'scope':quality.get('kind')}
                self.update(results=self.state['results']+[result],sample_series=result['series'],completed_samples=(index+1)*(5+request['runs']+(12 if request['quality'] else 0)))
                self.request('/unload',{});self.end_process(server);server=None;log.close()
            if original_path.read_bytes()!=original_bytes:raise RuntimeError('Configurazione originale cambiata durante la campagna')
            self.update(status='complete',phase='Campagna completata',finished_at=time.time())
        except BaseException as exc:
            self.update(status='cancelled' if self.stop.is_set() else 'failed',phase='Interrotta' if self.stop.is_set() else 'Prova fallita',error=str(exc),finished_at=time.time())
        finally:
            self.end_process(self.child)
            if server and server.poll() is None:
                try:self.request('/unload',{})
                except (OSError,ValueError):pass
            self.end_process(server);monitor_stop.set()
            if log:log.close()
            if monitor:monitor.join(timeout=5)
            if own_lock:
                path=self.root/'data/benchmarks/.benchmark.lock'
                try:
                    if path.read_text(encoding='utf-8-sig').strip()==str(getattr(self.child,'pid',None)):path.unlink()
                except OSError:pass
            self.lease.release()
    def close(self):
        if self.active():
            self.cancel()
            if self.thread:self.thread.join(timeout=150)

"""Managed local training with explicit device selection and isolated exports."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
from serve.gpu_lease import GpuLease
from serve.configuration import atomic_json
from serve.training_options import training_options
from tools.train_local_lora import dataset_rows,validate_destination,validate_checkpoint

class LocalTraining:
    @property
    def training_python(self):
        # Loading AirLLM or a CPU inference candidate must not change training's base.
        return Path(getattr(self.manager,'training_python_runtime',None) or self.manager.python_runtime)
    def __init__(self, manager):
        self.manager=manager;self.root=manager.root;self.lock=threading.RLock();self.process=None;self.lease=None
        self.state={'status':'idle','device':'cpu'}
        self.soup_runtime=self.root/'.venv-soup/Scripts/python.exe'
        self.state_path=self.root/'data/local-training-last.json'
        self.history_path=self.root/'data/local-training-history.json'
        try:
            saved=json.loads(self.state_path.read_text(encoding='utf-8'))
            if isinstance(saved,dict) and saved.get('status') in ('complete','failed','cancelled'):self.state=saved
        except (OSError,ValueError):pass
    def soup_available(self):
        import hashlib
        try:
            evidence=json.loads((self.root/'data/soup-runtime-validation.json').read_text())
            return self.soup_runtime.is_file() and evidence.get('cpu_training_verified') is True and evidence.get('bridge_sha256')==hashlib.sha256((self.root/'tools/train_soup_cpu.py').read_bytes()).hexdigest()
        except (OSError,ValueError):return False
    def native_soup(self,verify=False):
        from serve.soup_runtime import selected_package
        return selected_package(self.root,verify=verify)
    def soup_metadata(self,planner=None,planner_error=None):
        try:native=self.native_soup()
        except (OSError,ValueError,KeyError):native=None
        return dict(source='https://github.com/MakazhanAlpamys/Soup',
            version=native.get('version') if native else '0.75.0',
            planner_version='0.75.0',planner_revision='61e8c2bf354393cea85002401d0bde803b48f614',
            cpu_training_enabled=bool(native) or self.soup_available(),
            gpu_training_enabled=bool(native and native.get('validation',{}).get('gpu_verified')),
            layer_streaming_enabled=self.native_streaming_available(),runtime_enabled=self.native_streaming_available(),planner=planner,planner_error=planner_error,
            reason='Selected CPU/GPU training and experimental layer-streaming planning are separate workflows.')
    def native_streaming_available(self):
        import hashlib
        try:
            native=self.native_soup()
            proof_path=self.root/('output/verification/soup-0760-streaming-real.json' if native and native.get('version')=='0.76.0' else 'output/verification/soup-streaming-candidate-real.json')
            proof=json.loads(proof_path.read_text(encoding='utf-8'))
            workflow=proof.get('workflow',{})
            digest=hashlib.sha256((self.root/'tools'/('train_soup_streaming_candidate_0760.py' if native and native.get('version')=='0.76.0' else 'train_soup_streaming_candidate.py')).read_bytes()).hexdigest()
            return bool(native and proof.get('passed') is True and proof.get('exit_code')==0 and workflow.get('status')=='complete' and workflow.get('streaming_active') is True and workflow.get('device')=='cuda' and workflow.get('updated_adapter_tensors',0)>0 and workflow.get('export_greedy_tokens_equal') is True and workflow.get('export_logits_verified') is True and workflow.get('bridge_sha256')==digest and workflow.get('soup_version')==native.get('version'))
        except (OSError,ValueError,KeyError,TypeError):return False
    def native_qlora_available(self):
        try:
            evidence=json.loads((self.root/'output/verification/unsloth-qlora-native-gpu-real.json').read_text(encoding='utf-8'))
            return self.training_python.is_file() and evidence.get('passed') is True and evidence.get('quantization')=='nf4' and evidence.get('export_greedy_tokens_equal') is True
        except (OSError,ValueError):return False
    def status(self):
        with self.lock:
            result=dict(self.state,soup_layer_streaming_available=self.native_streaming_available())
            try:
                native=self.native_soup();result['soup_native_available']=bool(native);result['soup_native_gpu']=bool(native and native.get('validation',{}).get('gpu_verified'));result['soup_native_version']=native.get('version') if native else None
            except (OSError,ValueError,KeyError) as error:result.update(soup_native_available=False,soup_native_gpu=False,soup_candidate_error=str(error))
            if self.process and self.process.poll() is not None:
                code=self.process.returncode;self.process=None
                report=Path(result['output'])/'workflow.json'
                try:workflow=json.loads(report.read_text(encoding='utf-8'))
                except (OSError,ValueError):workflow={}
                result.update(status='cancelled' if result.get('cancel_requested') else 'complete' if code==0 and workflow.get('status')=='complete' and (workflow.get('export_logits_verified') or (result.get('runner')=='audiocraft' and workflow.get('native_training_verified') is True and workflow.get('export_tensors_verified') is True) or (result.get('runner')=='unsloth_qlora' and workflow.get('export_greedy_tokens_equal') is True)) else 'failed',returncode=code,workflow=workflow,finished_at=time.time())
                self.state=result
                try:
                    self.state_path.parent.mkdir(parents=True,exist_ok=True)
                    atomic_json(self.state_path,result)
                    try:history=json.loads(self.history_path.read_text(encoding='utf-8'))
                    except (OSError,ValueError):history=[]
                    if not isinstance(history,list):history=[]
                    entry={key:result.get(key) for key in ('status','model','runner','output','started_at','finished_at','steps','length')}
                    history=[row for row in history if isinstance(row,dict) and row.get('output')!=entry['output']]
                    atomic_json(self.history_path,(history+[entry])[-100:])
                except OSError as error:result['persistence_error']=str(error)
                finally:
                    if self.lease:self.lease.release();self.lease=None
            if result.get('status')=='running':
                try:result['workflow']=json.loads((Path(result['output'])/'workflow.json').read_text(encoding='utf-8'))
                except (OSError,ValueError):pass
            try:history=json.loads(self.history_path.read_text(encoding='utf-8'))
            except (OSError,ValueError):history=[]
            result['history']=list(reversed(history)) if isinstance(history,list) else []
            result['runners']=(['unsloth_qlora'] if self.native_qlora_available() else [])+['trl_cpu']+(['soup_cpu'] if self.soup_available() else [])+(['soup_native'] if result.get('soup_native_available') else [])
            return result
    def session(self,payload):
        output=payload.get('output')
        if not isinstance(output,str):raise ValueError('Choose a saved training session')
        history=self.status().get('history',[])
        entry=next((row for row in history if isinstance(row,dict) and row.get('output')==output),None)
        if not entry:raise ValueError('Training session not registered')
        folder=Path(output)
        if folder.is_symlink() or not folder.resolve().is_relative_to((self.root/'output/training').resolve()):raise ValueError('Invalid training session path')
        report=folder/'workflow.json'
        if report.is_symlink() or not report.resolve().is_relative_to(folder.resolve()) or report.stat().st_size>2*1024**2:raise ValueError('Invalid training report')
        workflow=json.loads(report.read_text(encoding='utf-8'))
        if not isinstance(workflow,dict):raise ValueError('Invalid training report')
        options=workflow.get('options',{})
        return {**entry,'workflow':workflow,'options':options,'device':options.get('device',workflow.get('device','cpu')),'model':workflow.get('base',entry.get('model')),'train_path':workflow.get('train_path'),'validation_path':workflow.get('validation_path'),'steps':options.get('steps',entry.get('steps',20))}
    def upload_dataset(self,payload):
        if payload.get('method')=='audiocraft':
            from serve.audiocraft_training import prepare_dataset
            return prepare_dataset(self.root,payload)
        import hashlib
        if payload.get('method')=='vlm' and payload.get('images') is not None:
            from serve.vision_dataset_upload import upload
            return upload(self.root,payload)
        content=payload.get('content');kind=payload.get('kind')
        if kind not in ('train','validation') or not isinstance(content,str):raise ValueError('Send a training or validation JSONL file')
        raw=content.encode('utf-8')
        if not raw or len(raw)>5*1024**2:raise ValueError('Uploaded dataset must be between 1 byte and 5 MiB')
        suffix=Path(payload.get('name','dataset.jsonl')).suffix.lower()
        if suffix=='.json':
            parsed=json.loads(content)
            records=parsed if isinstance(parsed,list) else [parsed]
            content='\n'.join(json.dumps(row,ensure_ascii=False) for row in records)+'\n'
        elif suffix=='.csv':
            import csv,io
            reader=csv.DictReader(io.StringIO(content))
            if not reader.fieldnames or 'text' not in reader.fieldnames:raise ValueError('CSV must contain a text column')
            content='\n'.join(json.dumps({'text':row['text']},ensure_ascii=False) for row in reader)+'\n'
        elif suffix=='.txt':
            content=json.dumps({'text':content},ensure_ascii=False)+'\n'
        elif suffix!='.jsonl':raise ValueError('Supported dataset formats: JSONL, JSON, CSV with text column, TXT')
        raw=content.encode('utf-8')
        if len(raw)>8*1024**2:raise ValueError('Normalized dataset exceeds 8 MiB')
        folder=self.root/'output/training-datasets';folder.mkdir(parents=True,exist_ok=True)
        target=folder/(uuid.uuid4().hex+'.jsonl')
        try:
            target.write_bytes(raw)
            if payload.get('method')=='vlm':
                from tools.train_vlm_lora import rows as vision_rows
                rows=vision_rows(target)
            else:
                rows=dataset_rows(target,method='auto')
            return {'path':str(target),'kind':kind,'rows':len(rows),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        except Exception:
            target.unlink(missing_ok=True)
            raise

    def split_dataset(self,payload):
        import hashlib,random
        source=Path(payload.get('path','')).resolve(strict=True)
        folder=(self.root/'output/training-datasets').resolve()
        if not source.is_file() or not source.is_relative_to(folder):raise ValueError('Split a dataset uploaded through this page')
        fraction=payload.get('validation_percent',20);seed=payload.get('seed',7)
        if type(fraction) is not int or not 5<=fraction<=40:raise ValueError('Validation percentage must be in 5..40')
        if type(seed) is not int or not 0<=seed<=2147483647:raise ValueError('Invalid split seed')
        rows=dataset_rows(source,method='auto');groups={}
        for row in rows:groups.setdefault(row['text'],[]).append(row)
        identities=sorted(groups)
        if len(identities)<2:raise ValueError('At least two distinct examples are required for a separate validation set')
        random.Random(seed).shuffle(identities)
        count=max(1,min(len(identities)-1,round(len(identities)*fraction/100)))
        validation=set(identities[:count])
        if all(type(row.get('label')) is bool for row in rows):
            validation=set()
            for label in (True,False):
                members=[identity for identity in identities if groups[identity][0]['label'] is label]
                if len(members)<2:raise ValueError('KTO split needs at least two distinct examples for each boolean label')
                selected_count=max(1,min(len(members)-1,round(len(members)*fraction/100)))
                validation.update(members[:selected_count])
        targets={};written=[]
        try:
            for kind in ('train','validation'):
                selected=[row for row in rows if (row['text'] in validation)==(kind=='validation')]
                target=folder/(uuid.uuid4().hex+'.jsonl')
                content='\n'.join(json.dumps({key:value for key,value in row.items() if key not in ('text','image_sha256')} if row.get('prompt') else {'messages':row['messages']} if row.get('messages') else {'text':row['text']},ensure_ascii=False) for row in selected)+'\n'
                target.write_text(content,encoding='utf-8');written.append(target)
                targets[kind]={'path':str(target),'rows':len(selected),'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
            return {'datasets':targets,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'seed':seed,'validation_percent_requested':fraction,'validation_percent_actual':100*targets['validation']['rows']/len(rows),'distinct_examples':len(groups),'overlap':False}
        except Exception:
            for target in written:target.unlink(missing_ok=True)
            raise

    def preflight(self,payload):
        if payload.get('method')=='audiocraft':
            from serve.audiocraft_training import preflight
            return preflight(self.root,payload)
        from serve.safetensors_runtime import inspect_model
        import psutil
        options=training_options(payload)
        if options.get('method')=='vlm':
            from serve.vlm_training_runtime import checked
            checked(self.root)
        elif options.get('method','sft')!='sft':
            from serve.advanced_training_runtime import checked
            checked(self.root,options['method'])
        if options['runner']=='unsloth_qlora' and not self.native_qlora_available():raise ValueError('Native QLoRA runtime has not passed local validation')
        if options['runner']=='soup_cpu' and not self.soup_available():raise ValueError('Soup CPU runtime has not passed local validation')
        if options['runner']=='soup_native':
            native=self.native_soup(verify=True)
            if not native:raise ValueError('Soup candidate unavailable')
            if options['device']=='cuda' and not native.get('validation',{}).get('gpu_verified'):raise ValueError('Soup GPU candidate is not verified')
        if options['layer_streaming'] and not self.native_streaming_available():raise ValueError('Soup layer streaming requires current local training/export validation')
        model=Path(payload.get('model','')).resolve(strict=True);info=inspect_model(model)
        if options.get('method')=='vlm':
            from serve.transformers_vision import inspect_vision
            info=inspect_vision(model)
        elif info.get('model_type')=='llava':raise ValueError('Choose the VLM method for a vision model')
        if options['layer_streaming']:
            architecture=json.loads((model/'config.json').read_text(encoding='utf-8')).get('model_type')
            if architecture not in ('llama','qwen2','qwen3','mistral','gemma','gemma2','gemma3_text','phi','phi3'):raise ValueError('Architecture not enabled for the local streaming workflow')
        train=dataset_rows(Path(payload.get('train','')),method=options.get('method','sft'));validation=dataset_rows(Path(payload.get('validation','')),method=options.get('method','sft'))
        conversational=bool(train[0].get('messages'))
        if conversational!=bool(validation[0].get('messages')):raise ValueError('Training and validation must use the same dataset format')
        if {r['text'] for r in train}&{r['text'] for r in validation}:raise ValueError('Training and validation must be distinct')
        memory=psutil.virtual_memory();available=memory.available;estimated=info['bytes']*(12 if options.get('method','sft')!='sft' else 8)+2*1024**3
        soup_plan=None;soup_error=None
        if options['runner']=='soup_cpu':
            try:
                result=subprocess.run([str(self.training_python),str(self.root/'tools/soup_memory_plan.py')],input=json.dumps({'model':str(model),'rank':options['rank'],'length':options['length'],'available_ram_bytes':available,'total_ram_bytes':memory.total}),capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if result.returncode==0:soup_plan=json.loads(result.stdout)
                else:soup_error='Original Soup planner does not support this model or the planning environment'
            except (OSError,ValueError,subprocess.TimeoutExpired):soup_error='Soup planning environment unavailable'
        reasons=[]
        if options.get('method')=='vlm' and options['length']<=info.get('image_tokens_per_image',0)+8:reasons.append('Vision sequence must leave space for image tokens, prompt and answer')
        if options['device']=='cuda':
            try:
                probe=json.loads((self.root/'output/verification/amd-gpu-bounded-probe.json').read_text(encoding='utf-8'))
                if probe.get('passed') is not True or not 0<=time.time()-probe.get('finished_at',0)<=86400:reasons.append('A recent successful GPU runtime probe is required')
            except (OSError,ValueError):reasons.append('GPU runtime probe unavailable')
        gpu_available=None
        if options['device']=='cuda':
            snapshot=getattr(self.manager,'memory_snapshot',lambda:{})() or {}
            now=snapshot.get('now') or {}
            if isinstance(now.get('gpu_mem_total'),(int,float)) and isinstance(now.get('gpu_mem_used'),(int,float)):
                gpu_available=max(0,now['gpu_mem_total']-now['gpu_mem_used'])
                if estimated+4*1024**3>gpu_available:reasons.append('Insufficient free VRAM including 4 GiB reserve')
            else:reasons.append('GPU memory sensor unavailable; cannot approve loading')
        if options['resume_checkpoint']:
            try:validate_checkpoint(self.root,options['resume_checkpoint'],model,payload['train'],payload['validation'],options)
            except (OSError,ValueError,KeyError,TypeError) as error:reasons.append('Checkpoint: '+str(error))
        if conversational and options['layer_streaming']:reasons.append('Layer streaming currently accepts text datasets, not assistant-only conversations')
        if conversational and options['runner']=='soup_cpu':reasons.append('Conversational assistant-only training currently requires the TRL runner')
        if conversational:
            from types import SimpleNamespace
            from tools.train_local_lora import assistant_template
            try:
                template=json.loads((model/'tokenizer_config.json').read_text(encoding='utf-8')).get('chat_template')
                assistant_template(SimpleNamespace(chat_template=template))
            except (OSError,ValueError) as error:reasons.append(str(error))
        if info['bytes']>1024**3:reasons.append('Validated training workflow supports at most 1 GiB of base weights')
        if options['length']>info['model_max_context']:reasons.append('Training sequence exceeds model context')
        if estimated>available:reasons.append('Insufficient available RAM')
        return {'ready':not reasons,'device':options['device'],'model':info,'options':options,'dataset_format':'vision_pairs' if options.get('method')=='vlm' else 'conversations' if conversational else 'text','loss_scope':'assistant_only' if conversational or options.get('method')=='vlm' else 'all_text','train_rows':len(train),'validation_rows':len(validation),'estimated_gpu_bytes':estimated if options['device']=='cuda' else None,'available_gpu_bytes':gpu_available,'gpu_reserve_bytes':4*1024**3 if options['device']=='cuda' else None,'estimated_ram_bytes':estimated,'available_ram_bytes':available,'reasons':reasons,'estimate_scope':'Conservative planning estimate, not measured peak memory','soup':self.soup_metadata(soup_plan,soup_error)}
    def start(self,payload,operational_idle):
        with self.lock:
            if self.status()['status']=='running':raise ValueError('Training already running')
            if not operational_idle or self.manager.status()['status']!='idle':raise ValueError('Unload inference models before training')
            if payload.get('method')=='audiocraft':
                from serve.audiocraft_training import start
                return start(self,payload)
            requested=training_options(payload)
            independent=requested.get('method','sft')!='sft' or requested['runner'] in ('soup_cpu','soup_native') and requested['device']=='cpu'
            if not independent and not self.training_python.is_file():raise ValueError('Installed Unsloth Python environment unavailable')
            model=Path(payload.get('model','')).resolve(strict=True)
            train=Path(payload.get('train','')).resolve(strict=True);validation=Path(payload.get('validation','')).resolve(strict=True)
            checked=self.preflight(payload)
            if not checked['ready']:raise ValueError('; '.join(checked['reasons']))
            options=checked['options'];steps=options['steps'];length=options['length']
            if type(steps) is not int or not 1<=steps<=1000 or type(length) is not int or not 16<=length<=(2048 if options.get('method')=='vlm' else 512):raise ValueError('Invalid training steps or sequence length')
            output=self.root/'output/training'/uuid.uuid4().hex
            validate_destination(model,output)
            lease=GpuLease(self.root,'local-training-gpu' if options['device']=='cuda' else 'local-training-cpu');lease.acquire()
            log=self.root/'output/training'/f'{output.name}.log';log.parent.mkdir(parents=True,exist_ok=True)
            env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
            if options['device']=='cpu':env.update(CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
            extra=['--rank',str(options['rank']),'--alpha',str(options['alpha']),'--learning-rate',str(options['learning_rate']),'--accumulation',str(options['accumulation']),'--seed',str(options['seed'])]
            if options['checkpointing']:extra.append('--checkpointing')
            if options['runner'] in ('trl_cpu','unsloth_qlora') or options['layer_streaming']:
                extra+=['--save-steps',str(options['save_steps'])]
                if options['runner']=='trl_cpu':extra+=['--device',options['device']]
                if options['resume_checkpoint']:extra+=['--resume-checkpoint',options['resume_checkpoint']]
            if options['runner']=='soup_native':
                native=self.native_soup(verify=True);extra+=['--device',options['device'],'--package-root',native['package_root']]
            runtime=self.soup_runtime if options['runner'] in ('soup_cpu','soup_native') and options['device']=='cpu' else self.training_python
            if options.get('method')=='vlm':
                from serve.vlm_training_runtime import checked
                try:runtime=checked(self.root)
                except BaseException:lease.release();raise
            elif options.get('method','sft')!='sft':
                from serve.advanced_training_runtime import checked
                try:runtime=checked(self.root,options['method'])
                except BaseException:lease.release();raise
            elif options['runner'] in ('trl_cpu','unsloth_qlora'):
                from serve.training_runtime_candidates import selected_python
                try:runtime=selected_python(self.root,runtime,options['runner'],options['device'])
                except BaseException:lease.release();raise
            if options.get('method','sft')!='sft':extra+=['--method',options['method']]
            script='train_vlm_lora.py' if options.get('method')=='vlm' else 'train_trl_advanced.py' if options.get('method','sft')!='sft' else 'train_soup_streaming_candidate.py' if options['layer_streaming'] else 'train_soup_candidate.py' if options['runner']=='soup_native' else 'train_soup_cpu.py' if options['runner']=='soup_cpu' else 'train_unsloth_qlora.py' if options['runner']=='unsloth_qlora' else 'train_local_lora.py'
            if options['runner']=='soup_native' and self.native_soup().get('version')=='0.76.0':script=script.replace('.py','_0760.py')
            try:
                with log.open('wb') as stream:
                    self.process=subprocess.Popen([str(runtime),'-u',str(self.root/'tools'/script),'--model',str(model),'--train',str(train),'--validation',str(validation),'--output',str(output),'--steps',str(steps),'--length',str(length),*extra],cwd=self.root,env=env,stdout=stream,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except BaseException:lease.release();raise
            self.lease=lease;self.state={'status':'running','device':options['device'],'output':str(output),'log':str(log),'started_at':time.time(),'steps':steps,'length':length,'model':str(model),'train_path':str(train),'validation_path':str(validation),'options':options,'runner':options['runner']}
            threading.Thread(target=self._watch,args=(self.process,),daemon=True).start()
            return self.status()
    def _watch(self,process):
        if process:process.wait()
        self.status()
    def stop(self):
        self.close()
        return self.status()

    def close(self):
        from serve.process_lifecycle import stop_owned_tree
        with self.lock:
            process=self.process
            if process and process.poll() is None:self.state['cancel_requested']=True
        stop_owned_tree(process,timeout=10)
        self.status()

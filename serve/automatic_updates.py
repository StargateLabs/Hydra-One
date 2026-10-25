"""Persistent, serialized update policy over the existing verified installers."""
import copy,json,threading,time
from pathlib import Path
from serve.configuration import atomic_json
HARNESS={'opencode','dsh','trueforge','browser','memory','hermes','claude'}
ARCHIVE={'strata','llama.cpp','audio.cpp','whisper.cpp','colibri'}
BUSY={'downloading','preparing','validating','resolving','installing_candidate','validating_python'}

def build_queue(data,include_missing=False):
    result=[]
    missing_components={r['id'].removeprefix('component:') for r in data.get('dependency_health',{}).get('checks',[]) if r.get('state')=='missing' and r.get('id','').startswith('component:')} if include_missing else set()
    for row in data.get('components',[]):
        identity=row['id'];item={'id':identity,'name':row.get('name',identity),'installed_version':row.get('installed_version'),'version':row.get('version'),'state':'current','type':'archive'}
        selected=(data.get('strata_runtime_selection') or {}).get('active') or {}
        if identity=='strata' and str(selected.get('version','')).removeprefix('v')==str(row.get('version','')).removeprefix('v') and data.get('strata_candidate_validation_current'):
            item.update(installed_version=selected['version'],state='complete');result.append(item);continue
        if not row.get('installed_version') or identity in missing_components:
            item.update(state='not_installed',reason='not_installed')
            if include_missing and row.get('version') and row.get('automatic_update_supported') is True:
                if identity in HARNESS:item.update(state='queued',type='harness',reason=None)
                elif identity in ('soup','airllm'):item.update(state='queued',type=identity,reason=None)
                elif identity in ARCHIVE and row.get('package_selection',{}).get('asset_id'):
                    item.update(state='queued',reason=None,asset_id=row['package_selection']['asset_id'])
        elif row.get('update_state') not in ('available','ahead','current'):item.update(state='protected',reason=row.get('update_block_reason') or 'channel_not_verified')
        elif row.get('update_state')=='available':
            if row.get('automatic_update_supported') is False or row.get('version_comparable') is False:item.update(state='protected',reason=row.get('update_block_reason') or 'channel_not_verified')
            elif identity in HARNESS:item.update(state='queued',type='harness')
            elif identity=='airllm':item.update(state='queued',type='airllm')
            elif identity=='soup':item.update(state='queued',type='soup')
            elif identity in ARCHIVE:
                asset=row.get('package_selection',{}).get('asset_id')
                item.update(state='queued',asset_id=asset) if asset else item.update(state='protected',reason=row.get('package_selection',{}).get('reason') or 'compatible_package_unavailable')
            else:item.update(state='protected',reason='managed_by_compatible_environment')
        result.append(item)
    for environment in data.get('environments',[]):
        packages=environment.get('packages',[]);name=environment.get('name')
        updates=[p for p in packages if p.get('update_state')=='available' and p.get('name','').lower() not in ('torch','torchvision','torchaudio','triton','pytorch-triton-rocm')]
        broken=include_missing and environment.get('dependency_health',{}).get('state')=='broken'
        if not updates and not broken:continue
        torch=next((p.get('version','') for p in packages if p.get('name','').lower()=='torch'),'')
        safe=not environment.get('selection_error') and name in ('Strata','Unsloth','Audio generativo','Open WebUI','Visuale') and environment.get('update_check',{}).get('state')=='checked' and (not torch or '+' in torch)
        component=None;version=None
        if 'rocm' in torch.lower():
            release=next((r for r in data.get('components',[]) if r.get('id')=='transformers' and r.get('compatible_release') and r.get('update_state')=='available'),None)
            safe=bool(safe and name=='Unsloth' and release)
            if safe:component='transformers';version=release['version']
        result.append({'id':'environment:'+str(name),'name':str(name)+' · librerie','environment':name,'type':'dependency','version':version or str(data.get('checked_at','')),'component':component,
                       'state':'queued' if safe else 'protected','reason':None if safe else 'environment_channel_not_verified','packages':len(updates)})
    for runtime in data.get('runtimes',[]):
        if runtime.get('update_method')=='python_dependency_plan':continue
        if runtime.get('state')=='available' and runtime.get('family')!='python':result.append({'id':'runtime:'+runtime['id'],'name':runtime.get('name',runtime['id']),'type':'runtime','version':runtime.get('available_version'),
            'installed_version':runtime.get('installed_version'),'state':'protected','reason':'owning_engine_bundle' if runtime.get('update_method')=='owning_engine_bundle' else 'runtime_compatibility_not_verified'})
    if include_missing and any(row.get('id')=='core' and row.get('state')=='missing' for row in data.get('dependency_health',{}).get('checks',[])):
        result=[row for row in result if row.get('id')!='environment:Strata']
        result.insert(0,{'id':'environment:Strata','name':'Ripristino dipendenze dashboard','environment':'Strata','type':'dependency','state':'queued','repair_missing':True,'version':str(data.get('checked_at',''))})
    if include_missing and any(row.get('id')=='audiocraft' and row.get('state')=='missing' for row in data.get('dependency_health',{}).get('checks',[])):
        result.append({'id':'audiocraft','name':'Ripristino AudioCraft','type':'audiocraft','state':'queued','version':'extended'})
    if include_missing and any(row.get('id')=='hydra-external' and row.get('state')=='missing' and row.get('repair')=='local_hydra_capsule' for row in data.get('dependency_health',{}).get('checks',[])):
        result.insert(0,{'id':'hydra-local-recovery','name':'Ripristino locale HYDRA','type':'hydra-recovery','state':'queued','version':str(data.get('checked_at',''))})
    return result

class AutomaticUpdates:
    def __init__(self,service,start_worker=True):
        self.service=service;self.center=service.update_center;self.root=Path(self.center.root)
        self.path=self.root/'data/automatic-updates.json';self.lock=threading.RLock();self.event=threading.Event();self.closed=False
        self.data={'enabled':True,'state':'checking','items':[],'checked_at':0,'last_error':None};self.plan_check=0
        try:
            saved=json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(saved,dict):self.data.update(saved)
        except (OSError,ValueError):pass
        if start_worker:threading.Thread(target=self._run,daemon=True,name='automatic-updates').start()

    def persist(self):self.path.parent.mkdir(parents=True,exist_ok=True);atomic_json(self.path,self.data)
    def status(self):
        from serve.update_restart import restart_pending
        with self.lock:
            result=copy.deepcopy(self.data);result['restart_pending']=bool(restart_pending(self.root))
            try:
                selection=json.loads((self.root/'data/colibri/runtime-selection.json').read_text(encoding='utf-8'))
                result['colibri_rollback_available']=bool(selection.get('previous') and not selection.get('transition'))
            except (OSError,ValueError):result['colibri_rollback_available']=False
            return result
    def configure(self,enabled=True):
        with self.lock:self.data['enabled']=bool(enabled);self.data['state']='checking' if enabled else 'disabled';self.data['requested_check']=bool(enabled);self.persist()
        self.event.set();return self.status()
    def check(self):
        with self.lock:
            job=self.center.status().get('download',{})
            existing=next((row for row in self.data.get('items',[]) if row.get('type')=='dependency' and row.get('environment')==job.get('name') and row.get('state')=='protected'),None)
            if existing and job.get('state')=='candidate_installed' and job.get('result',{}).get('installed') and not job.get('error'):
                existing.update(state='working',reason=None,message=None);self.data['state']='updating'
            else:self.data['requested_check']=True
            self.persist()
        self.event.set();return self.status()
    def close(self):self.closed=True;self.event.set()
    def recover_missing(self):
        with self.lock:
            if any(row.get('state')=='working' for row in self.data.get('items',[])):
                raise ValueError('Attendi la fine dell’operazione in corso')
            health=self.center.status().get('dependency_health',{})
            if health.get('checking') or health.get('state') in ('not_checked','error',None):
                self.center.check_dependency_health()
                raise ValueError('Controllo dipendenze in corso: attendi il rapporto prima del ripristino')
            self.data.update(enabled=True,repair_missing=True,recover_missing_enabled=True,requested_check=True,checked_at=0)
            self.persist()
        self.event.set();return self.status()
    def _run(self):
        while not self.closed:
            try:self.step()
            except Exception as error:
                with self.lock:self.data.update(state='protected',last_error=str(error)[:600]);self.persist()
            self.event.wait(2 if any(r['state'] in ('queued','working') for r in self.data.get('items',[])) else 20);self.event.clear()

    def step(self):
        with self.lock:
            if not self.data['enabled']:return
            snapshot=self.center.status();items=self.data.get('items',[])
            health=snapshot.get('dependency_health')
            if health and not health.get('checking') and time.time()-health.get('checked_at',0)>300:
                self.center.check_dependency_health()
            installed={r['id']:r.get('installed_version') for r in snapshot.get('components',[])}
            for saved in items:
                if installed.get(saved['id']):saved['installed_version']=installed[saved['id']]
            self.data['operation']={key:snapshot.get('download',{}).get(key) for key in ('state','component','bytes','total','error')}
            self.data['harness_operation']={key:snapshot.get('harness_update',{}).get(key) for key in ('state','kind','error')}
            item=next((r for r in items if r['state']=='working'),None) or next((r for r in items if r['state']=='queued'),None)
            if item is None:
                if self.data.get('restart_required'):
                    if not self.center.operational_idle() or not self.activities_idle():self.data['state']='waiting';self.persist();return
                    restart=getattr(self.service,'automatic_restart',None)
                    if restart:
                        self.data.update(restart_required=False,state='restarting');self.persist();restart();return
                requested=self.data.pop('requested_check',False)
                if self.data.get('waiting_check'):
                    if snapshot.get('state')=='complete' and snapshot.get('checked_at',0)>=self.plan_check:
                        recover=self.data.get('recover_missing_enabled',False) or self.data.pop('repair_missing',False)
                        self.plan_check=snapshot['checked_at'];self.data.update(items=build_queue(snapshot,include_missing=recover),checked_at=time.time(),waiting_check=False,state='ready',last_error=None)
                    elif snapshot.get('state') in ('error','failed'):
                        self.data.update(state='protected',last_error=snapshot.get('error'),waiting_check=False,checked_at=time.time())
                    self.persist();return
                if requested or time.time()-self.data.get('checked_at',0)>=6*3600:
                    if snapshot.get('state')!='checking':self.center.check()
                    self.data['state']='checking';self.data['waiting_check']=True;self.persist();return
                self.data['state']='ready';self.persist()
                return
            if not self.center.operational_idle() or not self.activities_idle():self.data['state']='waiting';self.persist();return
            job=snapshot.get('harness_update',{}) if item['type']=='harness' else snapshot.get('download',{})
            if item['state']=='queued':
                if snapshot.get('state')=='checking' or snapshot.get('download',{}).get('state') in BUSY or snapshot.get('harness_update',{}).get('state')=='installing':self.data['state']='waiting';return
                try:
                    if item['type']=='hydra-recovery':
                        self.center.repair_hydra_assets();self.complete(item);self.center.check_dependency_health();self.persist();return
                    if item['type']=='harness':self.center.harness_updates.start(item['id'],item['version'])
                    elif item['type']=='audiocraft':self.service.audiocraft_setup.prepare('extended')
                    elif item['type']=='dependency':
                        if item.get('repair_missing'):self.center.repair_core_dependencies()
                        else:self.center.dependency_plan(item['environment'],item.get('component'),item.get('version') if item.get('component') else None)
                    elif item['type']=='airllm':self.service.airllm_setup.prepare(item['version'])
                    elif item['type']=='soup':self.center.prepare_soup(item['version'])
                    else:self.center.stage(item['id'],item['asset_id'])
                    item['state']='working';item['started_at']=time.time();self.data['state']='updating'
                except (OSError,RuntimeError,ValueError) as error:self.protect(item,error)
                self.persist();return
            self.data['state']='updating'
            try:self.advance(item,snapshot,job)
            except (OSError,RuntimeError,ValueError,KeyError) as error:self.protect(item,error)
            self.persist()

    def protect(self,item,error):item.update(state='protected',reason='validation_or_compatibility_failed',message=str(error)[:700])
    def complete(self,item):
        item.update(state='complete',completed_at=time.time())
        if item.get('id')=='strata' or item.get('environment')=='Strata':self.data['restart_required']=True

    def activities_idle(self):
        from serve.studio_model_import import status as import_status
        if import_status(self.root).get('state')=='copying':return False
        from serve.studio_model_download import status as download_status
        if download_status(self.root).get('state') in ('downloading','verifying'):return False
        for attribute in ('local_visual','local_generative_audio','local_training','local_export','local_separation','unsloth_workspace','audiocraft_setup','colibri_workspace'):
            manager=getattr(self.service,attribute,None)
            if manager is None:continue
            state=manager.status()
            if state.get('busy') or state.get('status') in ('running','generating','loading','starting'):return False
        for attribute in ('agent_harness','agent_harness_dsh','agent_harness_trueforge','agent_harness_hermes','agent_harness_claude'):
            manager=getattr(self.service,attribute,None)
            if manager is None:continue
            terminal=getattr(manager,'terminal',None)
            if terminal is not None:
                native=terminal.status()
                if native.get('ready') and (native.get('busy') or native.get('activity_known') is not True):return False
            state=manager.status()
            if state.get('busy') or state.get('status')=='starting' or state.get('owned_process') and state.get('activity_known') is not True:return False
        return not getattr(self.service,'status',{}).get('busy',False)

    def activate_harness(self,item):
        kind=item['id']
        if kind in ('browser','memory'):
            from serve.shared_agent_services import activate_shared_service
            activate_shared_service(self.service,kind)
        else:
            from serve.harness_activation import activate_managed
            from serve.server import agent_harness_for
            host='127.0.0.1:'+str(getattr(self.service,'dashboard_port',8090))
            activate_managed(self.service,kind,lambda:agent_harness_for(self.service,kind,host))

    def model_for(self,component):
        manager=self.service.local_audio if component=='whisper.cpp' else self.service.local_speech if component=='audio.cpp' else self.service.optional_backends
        rows=manager.status().get('models',[]) if component!='llama.cpp' else manager.status().get('local_models',[])
        suffix='.bin' if component=='whisper.cpp' else '.gguf'
        row=next((r for r in rows if str(r.get('path','')).endswith(suffix) and 0<r.get('bytes',0)<1024**3),None)
        if not row:raise ValueError('Modello locale compatibile per la verifica automatica non disponibile. Versione attuale conservata.')
        return row['path']

    def advance(self,item,snapshot,job):
        if item['type']=='audiocraft':
            state=self.service.audiocraft_setup.status()
            if state.get('state')=='failed':self.protect(item,state.get('error') or 'AudioCraft preparation failed')
            elif state.get('state')=='ready' and state.get('active_python') and not state.get('selection_error'):
                self.complete(item);self.center.check_dependency_health()
            return
        if item['type']=='airllm':
            state=self.service.airllm_setup.status();step=state.get('job',{}).get('state')
            if step=='error':self.protect(item,state['job'].get('error'))
            elif step=='prepared':
                if not state.get('installed') or str(state.get('version','')).removeprefix('v')!=str(item.get('version','')).removeprefix('v'):
                    self.protect(item,'AirLLM candidate is prepared but the requested version is not selected')
                else:self.complete(item)
            return
        state=job.get('state')
        if job.get('error') or state in ('failed','error','cancelled','resolution_failed','candidate_failed'):
            self.protect(item,job.get('error') or state);return
        if item['type']=='harness':
            if job.get('kind')!=item['id']:raise ValueError('Update ownership changed; current version preserved')
            if state=='validated':self.activate_harness(item);self.complete(item)
            elif state=='selected':self.complete(item)
            return
        if item['type']=='dependency':
            if job.get('name')!=item['environment']:raise ValueError('Dependency update ownership changed; current environment preserved')
            if state=='resolved':self.center.install_dependencies()
            elif state=='candidate_installed':
                if item['environment']=='Strata':
                    if snapshot.get('python_candidate_validation_current'):self.center.select_python();self.complete(item)
                    else:self.center.validate_python()
                elif item['environment']=='Visuale':
                    if job.get('result',{}).get('visual_validation',{}).get('passed'):self.center.visual_python('activate');self.complete(item)
                    else:self.center.visual_python('validate')
                elif item['environment']=='Open WebUI':
                    if job.get('result',{}).get('document_validation',{}).get('passed'):self.center.document_python('activate');self.complete(item)
                    else:self.center.document_python('validate')
                elif item['environment']=='Audio generativo':
                    if job.get('result',{}).get('audio_validation',{}).get('passed'):self.center.audio_python('activate');self.complete(item)
                    else:self.center.audio_python('validate')
                elif job.get('result',{}).get('inference_validation',{}).get('passed'):self.center.inference_python('activate');self.complete(item)
                else:self.center.inference_python('validate')
            return
        if job.get('component')!=item['id']:raise ValueError('Update ownership changed; current version preserved')
        if state=='staged':self.center.prepare()
        elif state in ('prepared','validated'):
            if item['id']=='strata':
                if snapshot.get('strata_candidate_validation_current'):self.center.activate();self.complete(item)
                else:self.center.validate_strata_inference()
            elif item['id']=='colibri':
                if job.get('result',{}).get('runtime_validated'):self.center.activate();self.complete(item)
                else:self.center.validate_colibri()
            elif item['type']=='soup':self.center.activate_soup();self.complete(item)
            elif job.get('result',{}).get('runtime_validated'):
                self.center.activate_llama_gpu() if job['result'].get('gpu_validated') else self.center.activate();self.complete(item)
            else:self.center.validate(self.model_for(item['id']))
        elif state in ('selected_strata','activated_cpu','selected_gpu','selected_colibri'):self.complete(item)

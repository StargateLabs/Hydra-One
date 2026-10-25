"""Local generation and training-candidate HTTP integration."""
import json
from pathlib import Path

def prepare_idle_media(service):
    """Release only idle local model processes, preserving queued requests."""
    managers=[]
    for name in ('local_audio','local_speech','optional_backends'):
        engine=getattr(service,name,None)
        if engine is None or not hasattr(engine,'status'):continue
        state=engine.status()
        if state.get('busy') or state.get('status') in ('loading','starting','running'):
            raise ValueError('Attendi la fine del lavoro o del caricamento: i processi attivi restano protetti.')
        managers.append((name,engine,state))
    for name,engine,state in managers:
        if state.get('status')!='ready':continue
        if name=='optional_backends':engine.stop();continue
        if not engine.request_lock.acquire(blocking=False):raise ValueError('Un lavoro audio è appena iniziato: attesa del completamento.')
        try:engine.stop()
        finally:engine.request_lock.release()
    if hasattr(service,'unload') and service.unload()=='busy':raise ValueError('Una richiesta di chat è attiva: attesa del completamento.')

def get(handler, service, path):
    if path=='/colibri/telemetry':
        if not handler._authorized():return True
        try:
            from serve.colibri_controls import telemetry
            handler._json(200,telemetry(service.colibri_workspace))
        except (OSError,ValueError,RuntimeError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True
    if path in ('/colibri/workspace','/colibri/catalogue'):
        if not handler._authorized():return True
        try:
            handler._json(200,service.colibri_workspace.catalogue() if path.endswith('/catalogue') else service.colibri_workspace.status())
        except (OSError,ValueError,RuntimeError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True
    if path.startswith('/local-generative-audio/codes/'):
        if not handler._authorized():return True
        try:
            import re,hashlib
            identity=path.rsplit('/',1)[-1]
            if not re.fullmatch('[a-f0-9]{32}',identity):raise ValueError('Invalid codec artifact')
            folder=service.optional_backends.root/'data/generative-audio'/identity
            if folder.is_symlink():raise ValueError('Invalid codec folder')
            report=json.loads((folder/'result.json').read_text(encoding='utf-8'));metadata=report.get('codec',{});target=folder/'codes.safetensors'
            if report.get('task')!='codec' or target.is_symlink() or not 0<target.stat().st_size<=16*1024**2:raise ValueError('Codec artifact unavailable')
            data=target.read_bytes()
            if len(data)!=metadata.get('bytes') or hashlib.sha256(data).hexdigest()!=metadata.get('sha256'):raise ValueError('Codec artifact changed')
            handler.send_response(200);handler.send_header('Content-Type','application/octet-stream');handler.send_header('Content-Length',str(len(data)));handler.send_header('Content-Disposition','attachment; filename="codes.safetensors"');handler.send_header('Cache-Control','private, no-store');handler.end_headers();handler.wfile.write(data)
        except (OSError,ValueError,KeyError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True
    if path=='/audiocraft/setup':
        if handler._authorized():handler._json(200,service.audiocraft_setup.status())
        return True
    if path=='/unsloth/workspace':
        if handler._authorized():handler._json(200,service.unsloth_workspace.status())
        return True
    if path=='/studio/models/download':
        if handler._authorized():
            from serve.studio_model_download import status
            handler._json(200,status(service.optional_backends.root))
        return True
    if path=='/studio/models/import':
        if handler._authorized():
            from serve.studio_model_import import status
            handler._json(200,status(service.optional_backends.root))
        return True
    if path=='/updates/notifications':
        if not handler._authorized():return True
        automatic=service.automatic_updates.status().get('enabled') is True
        if automatic:
            handler._json(200,{'items':[],'automatic':True,'checking':False,'operation':{}});return True
        from serve.component_notifications import available_rows,check_releases
        center=service.update_center;check_releases(center);status=center.status()
        handler._json(200,{'items':available_rows(service.optional_backends.root,status.get('components',[])),'checking':getattr(center,'notification_check_running',False),'operation':status.get('download',{})});return True
    if path not in ('/local-visual','/local-generative-audio','/training-runtime','/benchmark-comparison','/catalogue-audit') and not path.startswith('/local-visual/artifact/'):
        return False
    if not handler._authorized():return True
    try:
        if path=='/local-visual':result=service.local_visual.status()
        elif path=='/local-generative-audio':result=service.local_generative_audio.status()
        elif path=='/training-runtime':
            from serve.training_runtime_candidates import status
            result=status(service.optional_backends.root)
        elif path=='/catalogue-audit':
            from serve.catalogue_audit import audit
            result=audit(service.optional_backends.root,service.optional_backends.status().get('local_models',[]))
        elif path=='/benchmark-comparison':
            result={'reports':[p.name for p in sorted((service.optional_backends.root/'data/benchmark-checks').glob('*.json'),reverse=True)[:100]]}
        else:
            target=service.local_visual.artifact(path.rsplit('/',1)[-1]);data=target.read_bytes()
            handler.send_response(200);handler.send_header('Content-Type','image/png' if target.suffix=='.png' else 'video/mp4');handler.send_header('Content-Length',str(len(data)));handler.send_header('Cache-Control','private, no-store');handler.end_headers();handler.wfile.write(data)
            return True
        handler._json(200,result)
    except (OSError,ValueError,RuntimeError,KeyError) as error:handler._json(400,{'error':{'message':str(error)}})
    return True

def post(handler,service,path):
    if path in ('/colibri/workspace/stop','/colibri/workspace/restart','/colibri/decide','/colibri/context'):
        if not handler._own_page('gestione Colibri'):return True
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=262144:raise ValueError('Richiesta Colibri non valida')
            payload=json.loads(handler._read_body())
            if not isinstance(payload,dict):raise ValueError('Richiesta Colibri non valida')
            from serve.colibri_controls import decide,stop
            backend=service.optional_backends
            if not backend.conversation_lock.acquire(blocking=False):raise ValueError('Una conversazione è in corso')
            try:
                if path=='/colibri/context':
                    result=service.colibri_workspace.configure_context(payload)
                elif path=='/colibri/decide':
                    if not backend.request_lock.acquire(blocking=False):raise ValueError('Una risposta è in corso')
                    import threading
                    cancel=threading.Event();handler._watch_client(cancel)
                    try:result=decide(service.colibri_workspace,payload,cancel)
                    finally:cancel.set();backend.request_lock.release()
                else:
                    if backend.request_lock.locked():raise ValueError('Una risposta è in corso')
                    result=stop(service.colibri_workspace)
                    if backend.state.get('mode')=='api' and backend.state.get('publisher')=='colibri':backend.stop(_conversation_owned=True)
                    if path.endswith('/restart'):result=service.colibri_workspace.start()
            finally:backend.conversation_lock.release()
            handler._json(200,result)
        except (OSError,ValueError,RuntimeError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True
    if path in ('/colibri/workspace/prepare','/colibri/workspace/start'):
        if not handler._own_page('workspace Colibri originale isolato'):return True
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=8192:raise ValueError('Richiesta Colibri non valida')
            payload=json.loads(handler._read_body())
            if not isinstance(payload,dict):raise ValueError('Richiesta Colibri non valida')
            handler._json(200,service.colibri_workspace.prepare(payload) if path.endswith('/prepare') else service.colibri_workspace.start())
        except (OSError,ValueError,RuntimeError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True
    if path in ('/audiocraft/setup','/audiocraft/conditioning','/audiocraft/rollback','/audiocraft/resume'):
        if not handler._own_page('preparazione AudioCraft isolata'):return True
        try:
            if service.local_generative_audio.status().get('busy'):raise ValueError('Finish the current audio job before changing its runtime')
            handler._json(200,service.audiocraft_setup.resume(json.loads(handler._read_body()).get('folder','')) if path.endswith('/resume') else service.audiocraft_setup.rollback() if path.endswith('/rollback') else service.audiocraft_setup.prepare_conditioning(json.loads(handler._read_body()).get('encoder','t5-large')) if path.endswith('/conditioning') else service.audiocraft_setup.prepare(json.loads(handler._read_body()).get('channel','stable')))
        except (OSError,ValueError,RuntimeError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True
    if path=='/unsloth/workspace/start':
        if not handler._own_page('workspace originale Unsloth locale'):return True
        try:handler._json(200,service.unsloth_workspace.start())
        except (OSError,ValueError,RuntimeError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True
    if path in ('/studio/models/inspect','/studio/models/download','/studio/models/download/cancel'):
        if not handler._own_page('preparazione modelli gestita internamente da Strata'):return True
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=8192:raise ValueError('Richiesta preparazione non valida')
            payload=json.loads(handler._read_body())
            if not isinstance(payload,dict):raise ValueError('Richiesta preparazione non valida')
            from serve import studio_model_download as download
            operation=download.inspect if path.endswith('/inspect') else download.start
            result=download.cancel(service.optional_backends.root) if path.endswith('/cancel') else operation(service.optional_backends.root,payload)
            handler._json(200,result)
        except Exception as error:handler._json(400,{'error':{'message':str(error)[:800]}})
        return True
    if path=='/studio/models/import/cancel':
        if not handler._own_page('annullamento copia modelli gestita dallo Studio'):return True
        from serve.studio_model_import import cancel
        handler._json(200,cancel(service.optional_backends.root));return True
    if path=='/studio/models/import':
        if not handler._own_page('importazione modelli locale nello Studio'):return True
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=8192:raise ValueError('Richiesta importazione non valida')
            payload=json.loads(handler._read_body())
            if not isinstance(payload,dict):raise ValueError('Richiesta importazione non valida')
            from serve.studio_model_import import start
            handler._json(202,start(service.optional_backends.root,payload))
        except (OSError,ValueError,TypeError,KeyError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True
    if path=='/updates/notification-preference':
        if not handler._own_page('preferenze notifiche aggiornamenti'):return True
        try:
            if not 0<int(handler.headers.get('Content-Length',0))<=2048:raise ValueError('Invalid request size')
            payload=json.loads(handler._read_body())
            if not isinstance(payload,dict):raise ValueError('Send an object')
            from serve.component_notifications import preference
            handler._json(200,preference(service.optional_backends.root,payload))
        except (ValueError,TypeError,OSError) as error:handler._json(400,{'error':{'message':str(error)}})
        return True
    if path not in ('/local-visual/start','/local-visual/stop','/local-generative-audio/start','/local-generative-audio/batch','/local-generative-audio/stop','/training-runtime/validate','/training-runtime/select','/training-runtime/rollback','/training-runtime/open-studio','/benchmark-comparison'):return False
    if not handler._own_page('generazione e runtime locali gestiti da questa pagina'):return True
    try:
        limit=36*1024**2 if path=='/local-visual/start' else 512*1024 if path=='/local-generative-audio/start' else 16384
        if not 0<int(handler.headers.get('Content-Length',0))<=limit:raise ValueError('Request exceeds '+('36 MiB' if path=='/local-visual/start' else '16 KiB')+' limit')
        payload=json.loads(handler._read_body())
        if not isinstance(payload,dict):raise ValueError('Send a JSON object')
        root=service.optional_backends.root
        if path=='/benchmark-comparison':
            from serve.benchmark_comparison import compare_reports
            result=compare_reports(root,payload.get('reports'))
        elif path.startswith('/training-runtime/'):
            from serve.training_runtime_candidates import activate,status,validate
            if not path.endswith('/open-studio') and not service.update_center.operational_idle():raise ValueError('Unload models and finish active operations first')
            runner=payload.get('runner','trl_cpu');device=payload.get('device','cpu')
            if path.endswith('/open-studio'):
                from serve.studio_inventory import launch_studio
                result=launch_studio()
            elif path.endswith('/validate'):result=validate(root,payload.get('folder',''),runner,device,payload.get('validation_model'))
            else:
                activate(root,payload.get('folder',''),service.optional_backends.python_runtime,runner,device,rollback=path.endswith('/rollback'));result=status(root)
        elif path.endswith('/stop'):
            manager=service.local_visual if path.startswith('/local-visual') else service.local_generative_audio
            manager.stop();result=manager.status()
        else:
            if not service.update_center.operational_idle():
                prepare_idle_media(service)
                if not service.update_center.operational_idle():raise ValueError('Attendi il termine delle attività in corso. I lavori attivi restano protetti.')
            if path.startswith('/local-visual'):result=service.local_visual.start(payload,operational_idle=True)
            else:
                from serve.audio_library import AudioLibrary
                for name in ('source','reference','music_prompt'):
                    identity=payload.pop(name+'_artifact',None)
                    if identity:
                        AudioLibrary(root).read(identity)
                        payload[name+'_path']=str(Path(root)/'output/audio-library'/(identity+'.wav'))
                if path.endswith('/batch'):
                    identities=payload.pop('source_artifacts',None)
                    if not isinstance(identities,list) or not 1<=len(identities)<=16:raise ValueError('Choose 1–16 source artifacts')
                    payload['source_paths']=[]
                    for identity in identities:
                        AudioLibrary(root).read(identity)
                        payload['source_paths'].append(str(Path(root)/'output/audio-library'/(identity+'.wav')))
                    result=service.local_generative_audio.start_batch(payload)
                else:result=service.local_generative_audio.start(payload)
        handler._json(200,result)
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as error:handler._json(400,{'error':{'message':str(error)}})
    return True

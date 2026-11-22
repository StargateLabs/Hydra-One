"""Additive native Hydra VibeVoice lifecycle and original UI entry point."""
from pathlib import Path
import subprocess,threading,secrets,os,json
from contextlib import nullcontext
import urllib.request
ROOT=Path('D:\\BACKUP 22-11-2026\\Stargate\\Desktop\\ARA')
LOCK=threading.RLock();PROCESS=None;TOKEN='';DEVICE=None

def gpu_enabled():
    try:
        path=ROOT/'ara-gpu-policy.json'
        if path.stat().st_size>4096:return False
        value=json.loads(path.read_text(encoding='utf-8'))
        return value.get('enabled') is True or value.get('vibevoice_enabled') is True
    except (OSError,ValueError,AttributeError):return False


def status():
    model=ROOT/'voice_line/models/vibevoice-realtime-0.5b/ARA-MODEL.json'
    python=ROOT/'output/vibevoice/environment/Scripts/python.exe'
    running=PROCESS is not None and PROCESS.poll() is None
    ready=False
    if running:
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8892/ara/ready',timeout=1) as response:ready=json.load(response).get('ready') is True
        except Exception:pass
    return {'prepared':model.is_file() and python.is_file() and (ROOT/'output/vibevoice/TOKENIZER.json').is_file() and (ROOT/'output/vibevoice/VOICES.json').is_file(),'running':running,'ready':ready and (DEVICE=='cpu' or gpu_enabled()),'device':DEVICE,'cpu_available':model.is_file() and python.is_file(),'start_device':'cuda' if gpu_enabled() else 'cpu','blocked_reason':None if DEVICE=='cpu' or gpu_enabled() or (model.is_file() and python.is_file()) else 'Preparazione CPU incompleta.','original_ui':'/ara/vibevoice/ui','language':'Italian experimental','voice':'it-Spk0_woman','voices':['it-Spk0_woman','it-Spk1_man'],'quality_validated':False}

def stop():
    global PROCESS
    if PROCESS is not None and PROCESS.poll() is None:
        import psutil
        parent=psutil.Process(PROCESS.pid);children=parent.children(recursive=True)
        for child in reversed(children):child.terminate()
        parent.terminate();_,alive=psutil.wait_procs(children+[parent],timeout=4)
        for process in alive:process.kill()
        _,alive=psutil.wait_procs(alive,timeout=3)
        if alive:raise ValueError('Worker termination not verified')
    PROCESS=None
    return status()

def cancel_stream(owned):
    if PROCESS is not owned:return
    import time
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request=urllib.request.Request('http://127.0.0.1:8892/ara/cancel',data=b'{}',headers={'Content-Type':'application/json','X-ARA-Worker':TOKEN})
    try:
        with opener.open(request,timeout=2) as response:response.read(512)
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            with opener.open('http://127.0.0.1:8892/ara/ready',timeout=1) as response:value=json.load(response)
            if value.get('busy') is False:return
            time.sleep(.05)
    except (OSError,ValueError) as error:print('[ARA VibeVoice] cancel_failed='+type(error).__name__,flush=True)
    stop()


def start(device='cuda'):
    global PROCESS,TOKEN,DEVICE
    if device not in ('cpu','cuda'):raise ValueError('Unsupported device')
    if device!='cpu' and not gpu_enabled():raise ValueError('GPU suspended')
    if status()['running']:return status()
    if not status()['prepared']:raise ValueError('VibeVoice preparation incomplete')
    check=urllib.request.Request('http://127.0.0.1:8090/inference-backends',headers={'Content-Type':'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(check,timeout=3) as response:backend=json.load(response)
    if backend.get('status')!='idle' or backend.get('busy') is not False:raise ValueError('Unload local LLM before starting VibeVoice')
    import psutil
    from bridge.inference_guard import require_local_memory
    require_local_memory()
    DEVICE=device
    TOKEN=secrets.token_urlsafe(32);environment=os.environ.copy();environment['ARA_VIBEVOICE_TOKEN']=TOKEN
    environment['ARA_VIBEVOICE_DEVICE']=device
    if device=='cpu':environment['CUDA_VISIBLE_DEVICES']=''
    environment['ARA_HYDRA_PARENT_PID']=str(os.getpid());environment['ARA_HYDRA_PARENT_CREATED']=str(psutil.Process().create_time())
    logs=ROOT/'.logs';logs.mkdir(exist_ok=True)
    with (logs/'vibevoice-worker.log').open('ab') as output:
        PROCESS=subprocess.Popen([str(ROOT/'output/vibevoice/environment/Scripts/python.exe'),'-u',str(ROOT/'tools/vibevoice_worker.py')],cwd=ROOT,env=environment,stdout=output,stderr=output,creationflags=subprocess.CREATE_NO_WINDOW)
    owned=PROCESS
    def startup_deadline():
        with LOCK:
            if PROCESS is owned and PROCESS.poll() is None and not status()['ready']:stop()
    timer=threading.Timer(180,startup_deadline);timer.daemon=True;timer.start()
    return status()

def route(handler,svc,path,post=False):
    if path not in ('/ara/vibevoice','/ara/vibevoice/start','/ara/vibevoice/stop','/ara/vibevoice/speech','/ara/vibevoice/speech/stream','/ara/vibevoice/ui'):return False
    if not handler._authorized() or not handler._own_page('VibeVoice locale'):return True
    try:
        with (nullcontext() if '/speech' in path else LOCK):
            if not post:
                if path=='/ara/vibevoice':handler._json(200,status());return True
                if path=='/ara/vibevoice/ui':
                    if not status()['ready']:raise ValueError('Start VibeVoice and wait for readiness')
                    handler.send_response(302);handler.send_header('Location','http://127.0.0.1:8892/');handler.end_headers();return True
                raise ValueError('Method not allowed')
            if not 0<int(handler.headers.get('Content-Length','0'))<=10000:raise ValueError('Body limit')
            payload=json.loads(handler._read_body())
            if path.endswith('/start'):
                if payload not in ({},{'device':'cpu'},{'device':'cuda'}):raise ValueError('Invalid start device')
                handler._json(200,start(payload.get('device','cuda')));return True
            if path.endswith('/stop'):
                if payload!={}:raise ValueError('No stop arguments')
                handler._json(200,stop());return True
            if path.endswith('/speech/stream'):
                if not isinstance(payload,dict) or set(payload)!={'text','voice'} or payload.get('voice') not in ('it-Spk0_woman','it-Spk1_man') or not isinstance(payload.get('text'),str) or not 1<=len(payload['text'])<=2000:raise ValueError('Text limit')
                if not status()['ready']:raise ValueError('VibeVoice not ready')
                owned=PROCESS;started=False
                request=urllib.request.Request('http://127.0.0.1:8892/ara/speech/stream',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','X-ARA-Worker':TOKEN})
                def expire():
                    with LOCK:
                        if PROCESS is owned:stop()
                timer=threading.Timer(45,expire);timer.daemon=True;timer.start()
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=45) as response:
                        total=0;done=False
                        while line:=response.readline(262145):
                            total+=len(line)
                            if len(line)>262144 or total>4321000:raise ValueError('Audio limit')
                            value=json.loads(line)
                            if not isinstance(value,dict) or set(value) not in ({'pcm'},{'done'}):raise ValueError('Invalid stream')
                            if not started:
                                handler.send_response(200);handler.send_header('Content-Type','application/x-ndjson');handler.send_header('Connection','close');handler.send_header('Cache-Control','no-store');handler.end_headers();handler.close_connection=True;started=True
                            handler.wfile.write(line);handler.wfile.flush()
                            if value.get('done') is True:done=True;break
                        if not done:raise ValueError('Incomplete stream')
                except ConnectionError:
                    with LOCK:cancel_stream(owned)
                except Exception as error:
                    print('[ARA VibeVoice] stream_failed='+type(error).__name__,flush=True)
                    with LOCK:
                        if PROCESS is owned:stop()
                    if not started:raise ValueError('VibeVoice streaming failed') from None
                finally:timer.cancel()
                return True
            if path.endswith('/speech'):
                if not isinstance(payload,dict) or set(payload)!={'text','voice'} or payload.get('voice') not in ('it-Spk0_woman','it-Spk1_man') or not isinstance(payload['text'],str) or not 1<=len(payload['text'])<=2000:raise ValueError('Text limit')
                if not status()['ready']:raise ValueError('VibeVoice not ready')
                owned=PROCESS
                request=urllib.request.Request('http://127.0.0.1:8892/ara/speech',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','X-ARA-Worker':TOKEN})
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=45) as response:raw=response.read(4320045)
                except Exception:
                    with LOCK:
                        if PROCESS is owned:stop()
                    raise ValueError('VibeVoice failed or timed out; original owned worker stopped') from None
                if len(raw)>4320044 or not raw.startswith(b'RIFF'):raise ValueError('Invalid WAV')
                handler.send_response(200);handler.send_header('Content-Type','audio/wav');handler.send_header('Content-Length',str(len(raw)));handler.end_headers();handler.wfile.write(raw);return True
            raise ValueError('Method not allowed')
    except (ValueError,OSError,TypeError):handler._json(400,{'error':{'message':'VibeVoice non disponibile: controlla preparazione, stato e log locali. Nessun cambio automatico della voce.'}})
    return True

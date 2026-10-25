"""Minimal real CPU layer-streaming proof using the existing untrained fixture."""
import argparse,hashlib,json,socket,subprocess,time,urllib.request,urllib.error
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from serve.airllm_runtime import selected_python


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model');options=parser.parse_args()
    fixture=Path(options.model).resolve() if options.model else ROOT/'output/verification/safetensors-cpu-fixture'
    untrained=(fixture/'FIXTURE-NOT-A-TRAINED-MODEL.txt').is_file()
    if not options.model and not untrained:raise ValueError('Missing untrained fixture marker')
    if not (fixture/'model.safetensors').is_file() or (fixture/'model.safetensors').stat().st_size>1024**3:raise ValueError('Proof requires a single local Safetensors model below 1 GiB')
    original=hashlib.sha256((fixture/'model.safetensors').read_bytes()).hexdigest()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}';child=None
    destination=ROOT/'output/verification/airllm-real-runtime.json'
    with (destination.with_suffix('.log')).open('w',encoding='utf-8') as log:
        try:
            child=subprocess.Popen([str(selected_python(ROOT)),str(ROOT/'serve/safetensors_runtime.py'),
                '--model',str(fixture),'--loader','airllm','--device','cpu','--context','1024',
                '--threads','2','--port',str(port)],cwd=ROOT,stdout=log,stderr=log,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            deadline=time.monotonic()+60
            while True:
                if child.poll() is not None:raise ValueError('AirLLM startup failed; inspect proof log')
                try:
                    with urllib.request.urlopen(url+'/v1/models',timeout=1) as response:models=json.load(response)
                    break
                except OSError:
                    if time.monotonic()>deadline:raise ValueError('AirLLM startup timeout')
                    time.sleep(.2)
            request=urllib.request.Request(url+'/v1/chat/completions',data=json.dumps({
                'model':'optional-model','messages':[{'role':'user','content':'hello'}],
                'max_tokens':4,'temperature':0}).encode(),headers={'Content-Type':'application/json'})
            started=time.monotonic()
            try:
                with urllib.request.urlopen(request,timeout=20) as response:result=json.load(response)
            except urllib.error.HTTPError as error:
                raise ValueError(error.read(4096).decode('utf-8')) from None
            usage=result.get('usage') or {}
            if usage.get('completion_tokens',0)<1:raise ValueError('No actual generated tokens')
            if hashlib.sha256((fixture/'model.safetensors').read_bytes()).hexdigest()!=original:raise ValueError('Original weights changed')
            proof={'passed':True,'scope':'Real AirLLM CPU execution on '+('tiny untrained fixture' if untrained else 'local trained model')+'; no large-model performance claim', 'model_path':str(fixture),'untrained_fixture':untrained,
                   'models':models,'usage':usage,'elapsed_seconds':time.monotonic()-started,
                   'original_weights_preserved':True,'response':result,'gpu_tested':False}
            destination.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({key:proof[key] for key in ('passed','scope','usage','original_weights_preserved')}))
        finally:
            if child and child.poll() is None:child.terminate();child.wait(timeout=10)


if __name__=='__main__':main()

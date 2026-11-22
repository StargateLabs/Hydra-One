import subprocess,socket,time,json,urllib.request
from pathlib import Path
root=Path.cwd();model=root/'output/verification/safetensors-cpu-fixture';assert (model/'config.json').is_file()
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
python=Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe';log=root/'output/verification/safetensors-generation-timing-real.log'
with log.open('w',encoding='utf-8') as stream:
 process=subprocess.Popen([str(python),str(root/'serve/safetensors_runtime.py'),'--model',str(model),'--device','cpu','--threads','2','--context','1024','--port',str(port)],stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
 try:
  deadline=time.monotonic()+35
  while True:
   if process.poll() is not None:raise RuntimeError(log.read_text()[-1500:])
   try:
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/models',timeout=1) as response:json.load(response)
    break
   except OSError:
    if time.monotonic()>deadline:raise TimeoutError('CPU startup')
    time.sleep(.2)
  results=[]
  for streaming in (False,True):
   body=dict(model='optional-model',messages=[dict(role='user',content='hello world')],max_tokens=8,temperature=0,stream=streaming)
   request=urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
   with urllib.request.urlopen(request,timeout=15) as response:raw=response.read().decode()
   packets=[json.loads(line[6:]) for line in raw.splitlines() if line.startswith('data: ') and line!='data: [DONE]'] if streaming else [json.loads(raw)]
   packet=next(p for p in packets if p.get('timings'));timing=packet['timings'];assert timing['generation_ms']>0 and timing['generation_tokens']==packet['usage']['completion_tokens'];assert 'predicted_per_second' not in timing
   results.append({'stream':streaming,'timings':timing,'usage':packet['usage']})
  (root/'output/verification/safetensors-generation-timing-real.json').write_text(json.dumps({'passed':True,'runs':results,'scope':'Real CPU untrained fixture; streaming and nonstreaming generation time including prefill, not decode throughput'},indent=2),encoding='utf-8');print('CPU timing: streaming and nonstreaming passed')
 finally:
  process.terminate();process.wait(timeout=10)

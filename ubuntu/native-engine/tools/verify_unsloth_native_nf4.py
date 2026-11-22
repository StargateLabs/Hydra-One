"""Bounded native Unsloth load; no dependency changes or downloads."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
def worker(model_path):
 os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1')
 from unsloth import FastLanguageModel
 import torch
 from serve.safetensors_runtime import inspect_model
 info=inspect_model(model_path)
 if info['bytes']>1024**3:raise ValueError('Probe only supports up to 1 GiB of local weights')
 if not torch.cuda.is_available():raise ValueError('GPU unavailable')
 free,total=torch.cuda.mem_get_info()
 if free<info['bytes']*3+6*1024**3:raise ValueError('Insufficient VRAM reserve')
 started=time.perf_counter()
 model,tokenizer=FastLanguageModel.from_pretrained(model_name=str(model_path),max_seq_length=1024,dtype=torch.float16,load_in_4bit=True,local_files_only=True,trust_remote_code=False)
 quantized=[module.weight for module in model.modules() if getattr(getattr(module,'weight',None),'quant_state',None) is not None]
 if not quantized or not all(weight.device.type=='cuda' for weight in quantized):raise ValueError('No actual GPU quantized weights found')
 if not all(weight.quant_state.quant_type=='nf4' for weight in quantized):raise ValueError('Quantization is not NF4')
 FastLanguageModel.for_inference(model)
 prompt=tokenizer.apply_chat_template([dict(role='user',content='Say hello briefly.')],tokenize=False,add_generation_prompt=True)
 inputs=tokenizer(prompt,return_tensors='pt',add_special_tokens=False).to('cuda')
 with torch.inference_mode():output=model.generate(**inputs,max_new_tokens=8,do_sample=False,pad_token_id=tokenizer.eos_token_id)
 torch.cuda.synchronize();answer=tokenizer.decode(output[0,inputs['input_ids'].shape[-1]:],skip_special_tokens=True)
 if not answer.strip():raise ValueError('Empty native GPU answer')
 print(json.dumps(dict(passed=True,quantization='nf4',quantized_gpu_modules=len(quantized),answer=answer,device=str(model.device),dtype=str(model.dtype),model=str(model_path),seconds=time.perf_counter()-started,peak_allocated_bytes=torch.cuda.max_memory_allocated(),scope='Native FastLanguageModel, one 8-token answer; not a performance or stability benchmark')))
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--worker',type=Path);args=parser.parse_args()
 if args.worker:return worker(args.worker)
 from urllib.request import urlopen
 from serve.gpu_lease import GpuLease
 with urlopen('http://127.0.0.1:8088/metrics',timeout=5) as response:state=json.load(response)
 with urlopen('http://127.0.0.1:8088/inference-backends',timeout=5) as response:optional=json.load(response)
 if state['live']['state']!='unloaded' or optional['status']!='idle':raise RuntimeError('Models must be unloaded before probe')
 model=Path(json.loads((ROOT/'output/verification/chat-regenerate-safetensors-real.json').read_text(encoding='utf-8'))['path'])
 runtime=Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe'
 report=dict(passed=False,started_at=time.time(),model=str(model),scope='Isolated native Unsloth NF4 GPU probe, 135M local model, eight tokens; no installations or downloads')
 try:
  with GpuLease(ROOT,'unsloth-native-nf4-bounded'):
   result=subprocess.run([str(runtime),'-X','utf8',str(Path(__file__).resolve()),'--worker',str(model)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120,env={**os.environ,'PYTHONPATH':str(ROOT)},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  report.update(exit_code=result.returncode,stdout_tail=result.stdout[-16000:],stderr_tail=result.stderr[-8000:])
  if result.returncode==0:
   evidence=next((json.loads(line) for line in reversed(result.stdout.splitlines()) if line.startswith('{') and '"passed"' in line),None)
   if evidence and evidence.get('passed'):report.update(evidence)
 except Exception as error:report['error']=str(error)
 report['finished_at']=time.time();(ROOT/'output/verification/unsloth-native-nf4-gpu-real.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k not in ('stdout_tail','stderr_tail')},indent=2))
 if not report['passed']:print(report.get('stderr_tail','')[-2500:]);raise SystemExit(1)
if __name__=='__main__':main()

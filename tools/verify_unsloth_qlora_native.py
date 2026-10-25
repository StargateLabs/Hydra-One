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
 model,tokenizer=FastLanguageModel.from_pretrained(model_name=str(model_path),max_seq_length=1024,dtype=torch.bfloat16,load_in_4bit=True,local_files_only=True,trust_remote_code=False)
 quantized=[module.weight for module in model.modules() if getattr(getattr(module,'weight',None),'quant_state',None) is not None]
 if not quantized or not all(weight.device.type=='cuda' for weight in quantized):raise ValueError('No actual GPU quantized weights found')
 if not all(weight.quant_state.quant_type=='nf4' for weight in quantized):raise ValueError('Quantization is not NF4')
 from datasets import Dataset
 from trl import SFTConfig,SFTTrainer
 import uuid,hashlib,math,gc
 destination=ROOT/'output/verification'/('qlora-native-'+uuid.uuid4().hex);destination.mkdir()
 model=FastLanguageModel.get_peft_model(model,r=4,target_modules=['q_proj','k_proj','v_proj','o_proj','gate_proj','up_proj','down_proj'],lora_alpha=8,lora_dropout=0,bias='none',use_gradient_checkpointing=False,random_state=7)
 FastLanguageModel.for_training(model,use_gradient_checkpointing=False)
 train=Dataset.from_list([{'text':'Local training keeps the source model unchanged.'},{'text':'The assistant explains steps in clear language.'}])
 valid=Dataset.from_list([{'text':'A saved adapter can be checked independently.'}])
 options=SFTConfig(output_dir=str(destination/'trainer'),max_steps=1,max_length=64,per_device_train_batch_size=1,gradient_accumulation_steps=1,learning_rate=2e-4,warmup_steps=0,lr_scheduler_type='constant',logging_steps=1,save_strategy='no',eval_strategy='no',report_to=[],optim='adamw_torch',seed=7,fp16=False,bf16=True,dataset_text_field='text',gradient_checkpointing=False,packing=False)
 trainer=SFTTrainer(model=model,args=options,train_dataset=train,eval_dataset=valid,processing_class=tokenizer)
 result=trainer.train()
 if not torch.cuda.is_bf16_supported():raise ValueError('BF16 is unsupported on this host')
 if any(not math.isfinite(float(row['grad_norm'])) for row in trainer.state.log_history if 'grad_norm' in row):raise ValueError('Non-finite training gradients')
 if result.global_step!=1 or not math.isfinite(result.training_loss):raise ValueError('Training did not complete one finite step')
 changed=sum(bool(torch.count_nonzero(parameter).item()) for name,parameter in model.named_parameters() if 'lora_B' in name)
 if changed==0:raise ValueError('No adapter parameters changed')
 model=trainer.accelerator.unwrap_model(trainer.model,keep_fp32_wrapper=False)
 adapter=destination/'adapter';model.save_pretrained(adapter,safe_serialization=True);tokenizer.save_pretrained(adapter)
 FastLanguageModel.for_inference(model)
 prompt=tokenizer.apply_chat_template([{'role':'user','content':'Say hello briefly.'}],tokenize=False,add_generation_prompt=True)
 inputs=tokenizer(prompt,return_tensors='pt').to('cuda')
 with torch.inference_mode():first=model.generate(**inputs,max_new_tokens=8,do_sample=False)
 expected=first[0,inputs['input_ids'].shape[1]:].tolist()
 del model,trainer;gc.collect();torch.cuda.empty_cache()
 # Load the saved adapter through its declared local base, preserving NF4.
 restored,tokenizer=FastLanguageModel.from_pretrained(model_name=str(adapter),max_seq_length=1024,dtype=torch.bfloat16,load_in_4bit=True,local_files_only=True,trust_remote_code=False)
 FastLanguageModel.for_inference(restored)
 with torch.inference_mode():second=restored.generate(**inputs,max_new_tokens=8,do_sample=False)
 actual=second[0,inputs['input_ids'].shape[1]:].tolist()
 if expected!=actual:raise ValueError('Saved QLoRA adapter produced different greedy tokens')
 files=[dict(name=p.name,bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in adapter.glob('*.safetensors')]
 if not files:raise ValueError('No Safetensors adapter exported')
 print(json.dumps(dict(passed=True,quantization='nf4',quantized_gpu_modules=len(quantized),device='cuda',steps=result.global_step,loss=result.training_loss,changed_lora_modules=changed,adapter=str(adapter),files=files,export_greedy_tokens_equal=True,peak_allocated_bytes=torch.cuda.max_memory_allocated(),scope='One real NF4 LoRA training step and adapter reload on 135M; not model quality or large-model training validation')))

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
 report=dict(passed=False,started_at=time.time(),model=str(model),scope='One bounded native Unsloth NF4 LoRA step on the 135M local model; no installations or downloads')
 try:
  with GpuLease(ROOT,'unsloth-qlora-native-bounded'):
   result=subprocess.run([str(runtime),'-X','utf8',str(Path(__file__).resolve()),'--worker',str(model)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180,env={**os.environ,'PYTHONPATH':str(ROOT)},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  report.update(exit_code=result.returncode,stdout_tail=result.stdout[-16000:],stderr_tail=result.stderr[-8000:])
  if result.returncode==0:
   evidence=next((json.loads(line) for line in reversed(result.stdout.splitlines()) if line.startswith('{') and '"passed"' in line),None)
   if evidence and evidence.get('passed'):report.update(evidence)
 except Exception as error:report['error']=str(error)
 report['finished_at']=time.time();(ROOT/'output/verification/unsloth-qlora-native-gpu-real.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k not in ('stdout_tail','stderr_tail')},indent=2))
 if not report['passed']:print(report.get('stderr_tail','')[-2500:].encode('ascii','backslashreplace').decode());raise SystemExit(1)
if __name__=='__main__':main()

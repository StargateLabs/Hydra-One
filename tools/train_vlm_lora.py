"""Bounded offline LLaVA CPU LoRA with image-aware assistant-only labels."""
import argparse,base64,hashlib,json,os,sys,random,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def rows(path):
 from PIL import Image
 path=Path(path).resolve(strict=True)
 if path.stat().st_size>8*1024**2:raise ValueError('Vision dataset exceeds 8 MiB')
 output=[]
 for line in path.read_text(encoding='utf-8').splitlines():
  if not line.strip():continue
  row=json.loads(line)
  if not isinstance(row,dict) or set(row)!={'prompt','response','image'} or any(not isinstance(row[key],str) or not row[key].strip() or len(row[key])>16000 for key in row):raise ValueError('Vision JSONL requires prompt, response and local image path')
  image=Path(row['image']);image=(image if image.is_absolute() else path.parent/image).resolve(strict=True)
  if image.is_symlink() or image.stat().st_size>2*1024**2:raise ValueError('Vision image exceeds 2 MiB or is a link')
  with Image.open(image) as decoded:
   if decoded.format not in ('PNG','JPEG','WEBP') or decoded.width*decoded.height>1024**2 or getattr(decoded,'n_frames',1)!=1:raise ValueError('Use one PNG/JPEG/WebP image up to one megapixel')
   decoded.verify()
  output.append({**row,'image':str(image),'image_sha256':hashlib.sha256(image.read_bytes()).hexdigest()})
 if not output:raise ValueError('Vision dataset is empty')
 return output

def main():
 p=argparse.ArgumentParser()
 for name in ('model','train','validation','output'):p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--method',default='vlm');p.add_argument('--device',default='cpu')
 for name,value in [('steps',20),('length',128),('rank',2),('alpha',4),('accumulation',1),('seed',7),('save-steps',0)]:p.add_argument('--'+name,type=int,default=value)
 p.add_argument('--learning-rate',type=float,default=.001);p.add_argument('--checkpointing',action='store_true');p.add_argument('--resume-checkpoint')
 a=p.parse_args()
 from serve.training_options import training_options
 training_options(vars(a))
 if a.device!='cpu':raise ValueError('Vision workflow supports CPU only')
 if not 1<=a.steps<=1000 or not 16<=a.length<=2048 or not 1<=a.rank<=64 or not 0<a.learning_rate<=.01:raise ValueError('Invalid vision training limits')
 from tools.train_local_lora import validate_destination,validate_checkpoint
 from serve.transformers_vision import inspect_vision,load_vision
 modelpath,out=validate_destination(a.model,a.output);info=inspect_vision(modelpath)
 import psutil
 if info['bytes']>1024**3 or psutil.virtual_memory().available<info['bytes']*12+2*1024**3:raise ValueError('Vision base or RAM exceeds bounded CPU workflow')
 train=rows(a.train);validation=rows(a.validation)
 identity=lambda row:(row['prompt'],row['response'],row['image_sha256'])
 if {identity(row) for row in train}&{identity(row) for row in validation}:raise ValueError('Vision train and validation overlap')
 os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
 import torch
 from peft import LoraConfig,get_peft_model
 from PIL import Image
 torch.set_num_threads(2);torch.manual_seed(a.seed);random.seed(a.seed)
 model,processor=load_vision(modelpath,torch,{'attn_implementation':'sdpa'})
 tokenizer=processor.tokenizer
 if tokenizer.eos_token is None:raise ValueError('Vision tokenizer requires EOS')
 targets=[name for name,module in model.named_modules() if 'language_model' in name and name.endswith(('.q_proj','.v_proj'))]
 if not targets:raise ValueError('Vision language adapter targets unavailable')
 model=get_peft_model(model,LoraConfig(r=a.rank,lora_alpha=a.alpha,target_modules=targets,task_type='CAUSAL_LM'))
 cache_before_training=[(config,config.use_cache) for config in (model.config,getattr(model.config,'text_config',None)) if hasattr(config,'use_cache')]
 if a.checkpointing:
  model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
  model.enable_input_require_grads()
  for config,_ in cache_before_training:config.use_cache=False
 def batch(row):
  image=Path(row['image'])
  if hashlib.sha256(image.read_bytes()).hexdigest()!=row['image_sha256']:raise ValueError('Vision input changed during training')
  messages=[{'role':'user','content':[{'type':'image'},{'type':'text','text':row['prompt']}]}]
  prompt=processor.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
  with Image.open(image) as source:rgb=source.convert('RGB')
  prefix=processor(text=prompt,images=rgb,return_tensors='pt')
  data=processor(text=prompt+row['response']+tokenizer.eos_token,images=rgb,return_tensors='pt')
  size=prefix['input_ids'].shape[-1]
  if data['input_ids'].shape[-1]>min(a.length,info['model_max_context']) or not torch.equal(data['input_ids'][0,:size],prefix['input_ids'][0]):raise ValueError('Vision prompt/answer exceeds length or prefix alignment changed')
  labels=data['input_ids'].clone();labels[:,:size]=-100;labels[labels==model.config.image_token_index]=-100
  if not (labels!=-100).any():raise ValueError('No assistant tokens in vision sample')
  return {**data,'labels':labels}
 train_batches=[batch(row) for row in train];validation_batches=[batch(row) for row in validation]
 from serve.vlm_training_runtime import fingerprint
 resume=validate_checkpoint(ROOT,a.resume_checkpoint,modelpath,a.train,a.validation,vars(a)|{'device':'cpu'}) if a.resume_checkpoint else None
 out.mkdir(parents=True);report={'source_sha256':fingerprint(ROOT),'status':'running','method':'vlm','base':str(modelpath),'options':vars(a)|{'device':'cpu'},'scope':'Bounded LLaVA CPU training; fixture proofs do not certify image understanding quality','assistant_only_labels':True,'resumed_from':str(resume) if resume else None}
 report['options']={k:str(v) if isinstance(v,Path) else v for k,v in report['options'].items()}
 report['train_sha256']=hashlib.sha256(a.train.read_bytes()).hexdigest();report['validation_sha256']=hashlib.sha256(a.validation.read_bytes()).hexdigest()
 def write():(out/'workflow.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 before={n:p.detach().clone() for n,p in model.named_parameters() if p.requires_grad};optimizer=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=a.learning_rate)
 scheduler=torch.optim.lr_scheduler.LambdaLR(optimizer,lambda step:1.0)
 def save_checkpoint(step):
  destination=out/'trainer'/('checkpoint-'+str(step))
  folder=destination.with_name(destination.name+'.partial-'+uuid.uuid4().hex);folder.mkdir(parents=True)
  model.save_pretrained(folder,safe_serialization=True);processor.save_pretrained(folder)
  torch.save(optimizer.state_dict(),folder/'optimizer.pt')
  torch.save(scheduler.state_dict(),folder/'scheduler.pt')
  torch.save({'python':random.getstate(),'torch_cpu':torch.random.get_rng_state()},folder/'rng_state.pth')
  (folder/'trainer_state.json').write_text(json.dumps({'global_step':step}),encoding='utf-8')
  folder.rename(destination);report['checkpoint']=str(destination);write()
 start=0
 if resume:
  import shutil
  restored=frozenset(p.name for p in resume.iterdir())
  for name in ('optimizer.pt','scheduler.pt','rng_state.pth','adapter_config.json','adapter_model.safetensors','trainer_state.json'):
   if name not in restored:raise ValueError('Incomplete vision checkpoint: '+name)
  state=json.loads((resume/'trainer_state.json').read_text(encoding='utf-8'))
  start=state.get('global_step',0)
  if type(start) is not int or not 1<=start<a.steps:raise ValueError('Vision resume step must exceed the saved checkpoint and stay below the target')
  target=out/'trainer'/('checkpoint-'+str(start))
  shutil.copytree(resume,target)
  optimizer.load_state_dict(torch.load(target/'optimizer.pt',map_location='cpu',weights_only=True))
  scheduler.load_state_dict(torch.load(target/'scheduler.pt',map_location='cpu',weights_only=True))
  model.load_adapter(target,'default',is_trainable=True)
  rng=torch.load(target/'rng_state.pth',map_location='cpu',weights_only=True)
  random.setstate(rng['python']);torch.random.set_rng_state(rng['torch_cpu'])
  report.update(checkpoint=str(target))
 try:
  for step in range(start,a.steps):
   model.train();optimizer.zero_grad();loss_sum=0.
   for index in range(a.accumulation):
    loss=model(**train_batches[(step*a.accumulation+index)%len(train_batches)]).loss
    if not torch.isfinite(loss):raise ValueError('Nonfinite vision training loss')
    (loss/a.accumulation).backward();loss_sum+=float(loss.detach())/a.accumulation
   torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad],1.);optimizer.step();scheduler.step();report.update(completed_steps=step+1,total_steps=a.steps,loss=loss_sum,training_loss=loss_sum);write()
   if a.save_steps and (step+1)%a.save_steps==0:save_checkpoint(step+1)
  delta=max(float((p.detach()-before[n]).abs().max()) for n,p in model.named_parameters() if n in before)
  if not delta>0:raise ValueError('No vision adapter update observed')
  model.eval()
  if a.checkpointing:model.gradient_checkpointing_disable()
  for config,value in cache_before_training:config.use_cache=value
  with torch.inference_mode():scores=model(**validation_batches[0]).logits;validation_loss=float(model(**validation_batches[0]).loss)
  model.save_pretrained(out/'adapter',safe_serialization=True);processor.save_pretrained(out/'adapter');merged=model.merge_and_unload();merged.save_pretrained(out/'merged',safe_serialization=True);processor.save_pretrained(out/'merged')
  restored,_=load_vision(out/'merged',torch,{'attn_implementation':'sdpa'})
  with torch.inference_mode():export=restored(**validation_batches[0]).logits
  torch.testing.assert_close(scores,export,rtol=1e-4,atol=1e-4)
  if not torch.equal(scores.argmax(-1),export.argmax(-1)):raise ValueError('Vision export changed greedy tokens')
  report.update(status='complete',parameter_update_detected=True,max_adapter_parameter_delta=delta,validation_loss=validation_loss,export_greedy_tokens_equal=True,export_logits_verified=True,adapter=str(out/'adapter'),merged=str(out/'merged'),adopted=False);write()
 except BaseException as error:report.update(status='failed',error=str(error));write();raise
if __name__=='__main__':main()

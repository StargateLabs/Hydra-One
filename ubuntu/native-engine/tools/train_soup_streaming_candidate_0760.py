"""Isolated Soup layer-streaming candidate; resident bridge remains unchanged."""
import argparse,json,math,os,sys,time,hashlib
from pathlib import Path
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',WANDB_DISABLED='true')
ROOT=Path(__file__).resolve().parents[1];os.environ['SOUP_LAYER_STREAM_CACHE_DIR']=str(ROOT/'data/soup-layer-cache');sys.path.insert(0,str(ROOT))
from serve.training_options import training_options
from tools.train_local_lora import dataset_rows,validate_destination,validate_checkpoint
from serve.safetensors_runtime import inspect_model

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--device',choices=('cpu','cuda'),default='cpu')
 parser.add_argument('--package-root',required=True,type=Path)
 for name in ('model','train','validation','output'):parser.add_argument('--'+name,required=True,type=Path)
 for name,default in [('steps',20),('length',128),('rank',2),('alpha',4),('accumulation',1),('seed',7)]:parser.add_argument('--'+name,type=int,default=default)
 parser.add_argument('--save-steps',type=int,default=0);parser.add_argument('--resume-checkpoint',default=None)
 parser.add_argument('--learning-rate',type=float,default=0.001);parser.add_argument('--checkpointing',action='store_true');args=parser.parse_args();payload={k:v for k,v in vars(args).items() if k not in ('package_root','device')};options=training_options({**payload,'runner':'soup_native','device':args.device,'layer_streaming':True});options['device']=args.device
 package=args.package_root.resolve()
 if not package.is_relative_to((ROOT/'output/updates/soup-candidates').resolve()) or not (package/'soup_cli').is_dir():raise ValueError('Choose an isolated verified Soup package')
 sys.path.insert(0,str(package))
 if args.device=='cpu':os.environ.update(CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
 if args.length<64:raise ValueError('Soup supports training sequences from 64 tokens in this bridge')
 model,out=validate_destination(args.model,args.output);train=dataset_rows(args.train);validation=dataset_rows(args.validation)
 resume=validate_checkpoint(ROOT,args.resume_checkpoint,model,args.train,args.validation,options)
 if train[0].get('messages') or validation[0].get('messages'):raise ValueError('Conversational assistant-only training requires the TRL runner')
 if {r['text'] for r in train}&{r['text'] for r in validation}:raise ValueError('Training and validation must be distinct')
 info=inspect_model(model)
 import psutil
 if info['bytes']>1024**3 or args.length>info['model_max_context'] or psutil.virtual_memory().available<info['bytes']*8+2*1024**3:raise ValueError('CPU model or resource limits exceeded')
 out.mkdir(parents=True);report={'status':'running','device':args.device,'runner':'soup_native','base':str(model),'steps':args.steps,'options':options,'train_path':str(args.train.resolve()),'validation_path':str(args.validation.resolve()),'resumed_from':str(resume) if resume else None,'scope':'Isolated layer-streaming candidate; no speed or quality claim','layer_streaming':True}
 report['bridge_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
 report['train_sha256']=hashlib.sha256(args.train.read_bytes()).hexdigest();report['validation_sha256']=hashlib.sha256(args.validation.read_bytes()).hexdigest()
 def write():(out/'workflow.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 write()
 try:
  import torch
  import importlib.metadata
  report['soup_version']=importlib.metadata.version('soup-cli')
  if args.device=='cuda':
   if not torch.cuda.is_available():raise ValueError('GPU unavailable')
   free,total=torch.cuda.mem_get_info()
   if info['bytes']*8+2*1024**3>free-4*1024**3:raise ValueError('GPU memory reserve insufficient')
  from transformers import AutoModelForCausalLM,AutoTokenizer,TrainerCallback
  from datasets import Dataset,DatasetDict
  from soup_cli.config.schema import SoupConfig
  from soup_cli.trainer.sft import SFTTrainerWrapper
  from soup_cli.data.formats import format_to_messages
  torch.set_num_threads(2)
  config=SoupConfig(base=str(model),task='sft',backend='transformers',data={'train':str(args.train),'format':'pre_tokenized','tokenized_path':str(out/'tokenized'),'val_split':0,'max_length':args.length,'train_on_responses_only':False},training={'epochs':1,'lr':args.learning_rate,'batch_size':1,'gradient_accumulation_steps':args.accumulation,'seed':args.seed,'quantization':'none','stream_layers':True,'stream_source':'ram','stream_pin':False,'gradient_checkpointing':args.checkpointing,'logging_steps':1,'save_steps':10000,'warmup_ratio':0,'weight_decay':0,'optimizer':'adamw_torch','lora':{'r':args.rank,'alpha':args.alpha,'target_modules':['q_proj','v_proj']}},output=str(out/'soup'))
  (out/'soup.yaml').write_text(json.dumps(config.model_dump(mode='json'),indent=2),encoding='utf-8')
  tokenizer=AutoTokenizer.from_pretrained(model,local_files_only=True,trust_remote_code=False)
  def tokenized(rows):
   result=[]
   for row in rows:
    data=tokenizer(row['text'],truncation=True,max_length=args.length)
    if len(data['input_ids'])<2:raise ValueError('Training text must contain at least two tokens')
    result.append({'input_ids':data['input_ids'],'attention_mask':data['attention_mask'],'labels':data['input_ids'].copy()})
   return Dataset.from_list(result)
  DatasetDict({'train':tokenized(train),'validation':tokenized(validation)}).save_to_disk(str(out/'tokenized'))
  from soup_cli.utils.data_pipeline import make_preprocess_cache_key,preprocess_mask_mode,preprocess_dataset_key_input
  from soup_cli.data.chat_templates import resolve_chat_template
  dataset_key=preprocess_dataset_key_input(config.data)
  mask=preprocess_mask_mode(config.data,config.training)
  template=resolve_chat_template(config.data.chat_template)
  metadata={'format':'pre_tokenized','source_sha256':hashlib.sha256(args.train.read_bytes()).hexdigest(),'dataset_key':dataset_key,'mask_mode':mask,'chat_template':template,'cache_key':make_preprocess_cache_key(dataset_path=dataset_key,tokenizer_name=str(model),max_length=args.length,format_name=config.data.format,mask_mode=mask,task=config.task,chat_template=template)}
  (out/'tokenized/metadata.json').write_text(json.dumps(metadata),encoding='utf-8')
  wrapper=SFTTrainerWrapper(config,device=args.device,trust_remote_code=False);wrapper.setup({'train':train,'val':validation});wrapper.trainer.args.max_steps=args.steps
  if args.save_steps:
   wrapper.trainer.args.save_steps=args.save_steps
   wrapper.trainer.args.save_strategy='steps'
   class CheckpointIntegrity(TrainerCallback):
    def on_save(self,arguments,state,control,**kwargs):
     folder=Path(arguments.output_dir)/f'checkpoint-{state.global_step}'
     names=('optimizer.pt','scheduler.pt','rng_state.pth','adapter_config.json','adapter_model.safetensors','trainer_state.json')
     manifest={name:{'bytes':(folder/name).stat().st_size,'sha256':hashlib.sha256((folder/name).read_bytes()).hexdigest()} for name in names}
     (folder/'CHECKPOINT-INTEGRITY.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8');report['checkpoint']=str(folder);write()
   wrapper.trainer.add_callback(CheckpointIntegrity())
  if not wrapper._stream_runtime:raise ValueError('Streaming runtime did not activate')
  report['streaming_active']=True
  base_dtype=next(p.dtype for p in wrapper.model.parameters() if not p.requires_grad and p.device.type!='meta')
  report['precision']='bf16_autocast' if wrapper.trainer.args.bf16 else 'fp16_autocast' if wrapper.trainer.args.fp16 else 'float32'
  assert any(p.requires_grad and p.device.type==args.device for p in wrapper.model.parameters())
  def loss():
   wrapper.model.eval();values=[]
   with torch.inference_mode():
    for row in validation:
     tokens=wrapper.tokenizer(row['text'],return_tensors='pt',truncation=True,max_length=args.length).to(args.device)
     if tokens['input_ids'].shape[-1]<2:raise ValueError('Validation must contain at least two tokens')
     value=wrapper.model(**tokens,labels=tokens['input_ids']).loss.item()
     if not math.isfinite(value):raise ValueError('Nonfinite validation loss')
     values.append(value)
   return sum(values)/len(values)
  report['validation_loss_before']=loss();write()
  class Progress(TrainerCallback):
   def on_log(self,args,state,control,logs=None,**kwargs):
    report.update(completed_steps=state.global_step,total_steps=args.max_steps)
    if logs and isinstance(logs.get('loss'),(int,float)) and math.isfinite(logs['loss']):report['current_loss']=logs['loss'];report['loss_history']=(report.get('loss_history',[])+[{'step':state.global_step,'loss':logs['loss']}])[-256:]
    write()
  captured={};adapter=out/'adapter';args_length=args.length
  before={name:value.detach().cpu().clone() for name,value in wrapper.model.named_parameters() if value.requires_grad}
  class CaptureBeforeCleanup(TrainerCallback):
   def on_train_end(self,args,state,control,**kwargs):
    report['validation_loss_after']=loss()
    probe=wrapper.tokenizer(validation[0]['text'],return_tensors='pt',truncation=True,max_length=args_length).to(args_device)
    with torch.inference_mode():captured['reference']=wrapper.model(**probe).logits.detach().float().cpu()
    captured['probe']={key:value.cpu() for key,value in probe.items()}
    changed=sum(not torch.equal(before[name],value.detach().cpu()) for name,value in wrapper.model.named_parameters() if name in before)
    report['updated_adapter_tensors']=changed
    if not changed:raise ValueError('No adapter tensors changed')
    wrapper.model.save_pretrained(adapter,safe_serialization=True);wrapper.tokenizer.save_pretrained(adapter)
    write()
  args_device=args.device
  wrapper.trainer.add_callback(Progress());wrapper.trainer.add_callback(CaptureBeforeCleanup());summary=wrapper.train(resume_from_checkpoint=str(resume) if resume else None)
  reference=captured['reference'];probe=captured['probe']
  report['export_check_precision']=str(base_dtype)
  from peft import PeftModel
  resident=AutoModelForCausalLM.from_pretrained(model,local_files_only=True,trust_remote_code=False,dtype=base_dtype,device_map=args.device)
  reloaded=PeftModel.from_pretrained(resident,adapter).eval()
  with torch.inference_mode(),torch.autocast(device_type=args.device,dtype=base_dtype,enabled=args.device=='cuda'):
   actual=reloaded(**{key:value.to(args.device) for key,value in probe.items()}).logits.detach().float().cpu()
  report['export_max_abs_error']=float((reference-actual.float()).abs().max())
  report['export_greedy_tokens_equal']=bool(torch.equal(reference.argmax(-1),actual.argmax(-1)))
  if not report['export_greedy_tokens_equal']:raise ValueError('Export changed greedy tokens')
  torch.testing.assert_close(reference,actual,rtol=2e-2 if args.device=='cuda' else 1e-4,atol=2e-2 if args.device=='cuda' else 5e-5)
  if args.device=='cuda':report['gpu_peak_allocated_bytes']=torch.cuda.max_memory_allocated()
  report.update(status='complete',summary=summary,adapter=str(adapter),merged=None,export_kind='lora_adapter',export_logits_verified=True,adopted=False)
  write();print(json.dumps(report,indent=2))
 except BaseException as error:report.update(status='failed',error=str(error));write();raise
if __name__=='__main__':main()

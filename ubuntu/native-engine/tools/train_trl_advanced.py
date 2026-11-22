"""Bounded offline DPO and GRPO LoRA, using official installed TRL trainers."""
import argparse,hashlib,json,math,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.train_local_lora import dataset_rows,validate_destination,validate_checkpoint
def main():
 p=argparse.ArgumentParser()
 for name in ('model','train','validation','output'):p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--method',choices=['dpo','grpo','kto','reward'],required=True);p.add_argument('--device',choices=['cpu','cuda'],default='cpu')
 for name,value in [('steps',20),('length',128),('rank',2),('alpha',4),('accumulation',1),('seed',7),('save-steps',0)]:p.add_argument('--'+name,type=int,default=value)
 p.add_argument('--learning-rate',type=float,default=.001);p.add_argument('--checkpointing',action='store_true');p.add_argument('--resume-checkpoint')
 args=p.parse_args();from serve.training_options import training_options
 options=training_options(vars(args));modelpath,out=validate_destination(args.model,args.output)
 train=dataset_rows(args.train,method=args.method);validation=dataset_rows(args.validation,method=args.method)
 if any('prompt' not in row for row in train+validation):raise ValueError('Advanced training requires the selected method dataset format')
 if {row['text'] for row in train}&{row['text'] for row in validation}:raise ValueError('Training and validation must be distinct')
 resume=validate_checkpoint(ROOT,options['resume_checkpoint'],modelpath,args.train,args.validation,options) if options['resume_checkpoint'] else None
 os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',WANDB_DISABLED='true',TOKENIZERS_PARALLELISM='false')
 if args.device=='cpu':os.environ.update(CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
 from serve.safetensors_runtime import inspect_model
 import psutil
 info=inspect_model(modelpath);required=info['bytes']*12+2*1024**3
 if info['bytes']>1024**3 or psutil.virtual_memory().available<required or args.length>info['model_max_context']:raise ValueError('Model, context or memory exceeds bounded advanced workflow')
 import torch
 from transformers import AutoTokenizer,AutoModelForCausalLM,AutoModelForSequenceClassification,TrainerCallback
 from datasets import Dataset
 from peft import LoraConfig
 from trl import DPOConfig,DPOTrainer,GRPOConfig,GRPOTrainer,KTOConfig,KTOTrainer,RewardConfig,RewardTrainer
 if args.device=='cuda' and (not torch.cuda.is_available() or torch.cuda.mem_get_info()[0]<required+4*1024**3):raise ValueError('Advanced GPU training requires sufficient verified device memory')
 torch.set_num_threads(2);torch.manual_seed(args.seed)
 tokenizer=AutoTokenizer.from_pretrained(modelpath,local_files_only=True,trust_remote_code=False)
 if tokenizer.pad_token_id is None:tokenizer.pad_token=tokenizer.eos_token
 if tokenizer.pad_token_id is None:raise ValueError('Tokenizer has no padding or EOS token')
 if tokenizer.eos_token is None:raise ValueError('Advanced TRL workflow requires a declared EOS token')
 if args.method=='grpo' and any(len(tokenizer(row['prompt'])['input_ids'])+min(32,args.length//2)>args.length for row in train+validation):raise ValueError('GRPO prompt plus completion exceeds configured length')
 factory=AutoModelForSequenceClassification if args.method=='reward' else AutoModelForCausalLM
 model=factory.from_pretrained(modelpath,local_files_only=True,trust_remote_code=False,dtype=torch.float32,device_map=args.device,**({'num_labels':1} if args.method=='reward' else {}))
 model.config.pad_token_id=tokenizer.pad_token_id
 from serve.advanced_training_runtime import source_fingerprint
 out.mkdir(parents=True);report=dict(source_sha256=source_fingerprint(ROOT),status='running',base=str(modelpath),options=options,method=args.method,train_path=str(args.train.resolve()),validation_path=str(args.validation.resolve()),train_sha256=hashlib.sha256(args.train.read_bytes()).hexdigest(),validation_sha256=hashlib.sha256(args.validation.read_bytes()).hexdigest(),scope='Functional local advanced training; no general quality improvement claim',resumed_from=str(resume) if resume else None)
 def write():(out/'workflow.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 phase={'evaluation':False}
 class Progress(TrainerCallback):
  def on_save(self,args,state,control,**kwargs):
   report['checkpoint']=str(out/'trainer'/('checkpoint-'+str(state.global_step)));write()
  def on_log(self,args,state,control,logs=None,**kwargs):
   report.update(completed_steps=state.global_step,total_steps=args.max_steps)
   if logs:report['validation_metrics' if phase['evaluation'] else 'training_metrics']={key:value for key,value in logs.items() if type(value) in (int,float) and math.isfinite(value)}
   write()
 shared=dict(output_dir=str(out/'trainer'),use_cpu=args.device=='cpu',bf16=False,fp16=False,max_steps=args.steps,learning_rate=args.learning_rate,gradient_accumulation_steps=args.accumulation,seed=args.seed,data_seed=args.seed,logging_steps=1,save_strategy='steps' if args.save_steps else 'no',save_steps=max(1,args.save_steps),save_total_limit=2,report_to='none',gradient_checkpointing=args.checkpointing,optim='adamw_torch')
 data=lambda rows:Dataset.from_list([{key:value for key,value in row.items() if key!='text'} for row in rows])
 adapter=LoraConfig(r=args.rank,lora_alpha=args.alpha,target_modules=['q_proj','v_proj'],task_type='SEQ_CLS' if args.method=='reward' else 'CAUSAL_LM')
 try:
  if args.method=='reward':
   config=RewardConfig(**shared,max_length=args.length,per_device_train_batch_size=1)
   reward_data=lambda rows:Dataset.from_list([{'chosen':row['prompt']+' '+row['chosen'],'rejected':row['prompt']+' '+row['rejected']} for row in rows])
   trainer=RewardTrainer(model=model,args=config,processing_class=tokenizer,train_dataset=reward_data(train),eval_dataset=reward_data(validation),peft_config=adapter,callbacks=[Progress()]);report['output_kind']='scalar_reward_model';report['reward_scope']='Learned preference score; not a chat generator or a general semantic quality guarantee'
  elif args.method=='dpo':
   config=DPOConfig(**shared,max_length=args.length,per_device_train_batch_size=1,beta=.1)
   trainer=DPOTrainer(model=model,ref_model=None,args=config,processing_class=tokenizer,train_dataset=data(train),eval_dataset=data(validation),peft_config=adapter,callbacks=[Progress()])
  elif args.method=='kto':
   if {row['label'] for row in train}!={True,False} or {row['label'] for row in validation}!={True,False}:raise ValueError('KTO requires both positive and negative examples in train and validation')
   config=KTOConfig(**shared,max_length=args.length,per_device_train_batch_size=2,per_device_eval_batch_size=2,beta=.1)
   trainer=KTOTrainer(model=model,ref_model=None,args=config,processing_class=tokenizer,train_dataset=data(train),eval_dataset=data(validation),peft_config=adapter,callbacks=[Progress()])
  else:
   def target_similarity(completions,target,**kwargs):
    from difflib import SequenceMatcher
    return [SequenceMatcher(None,(completion if isinstance(completion,str) else completion[0]['content']).strip(),expected.strip(),autojunk=False).ratio() for completion,expected in zip(completions,target)]
   config=GRPOConfig(**shared,max_completion_length=min(32,args.length//2),per_device_train_batch_size=2,num_generations=2,use_vllm=False,temperature=1.,beta=0.)
   trainer=GRPOTrainer(model=model,reward_funcs=target_similarity,args=config,processing_class=tokenizer,train_dataset=data(train),eval_dataset=data(validation),peft_config=adapter,callbacks=[Progress()]);report['reward_scope']='Normalized character-sequence similarity to the explicit target, 0–1; not a semantic quality judge'
  before_parameters={name:parameter.detach().float().cpu().clone() for name,parameter in trainer.model.named_parameters() if parameter.requires_grad}
  if not before_parameters:raise ValueError('No trainable adapter parameters')
  write();result=trainer.train(resume_from_checkpoint=str(resume) if resume else None)
  deltas=[float((parameter.detach().float().cpu()-before_parameters[name]).abs().max()) for name,parameter in trainer.model.named_parameters() if name in before_parameters]
  if not all(math.isfinite(value) for value in deltas):raise ValueError('Nonfinite adapter parameter update')
  report.update(parameter_update_detected=any(value>0 for value in deltas),max_adapter_parameter_delta=max(deltas),updated_parameter_tensors=sum(value>0 for value in deltas))
  if not report['parameter_update_detected']:report['warning']='No adapter update observed; revise examples or rewards before claiming learning'
  if not math.isfinite(result.training_loss):raise ValueError('Nonfinite advanced training loss')
  phase['evaluation']=True;evaluated=trainer.evaluate();finite={key:value for key,value in evaluated.items() if type(value) in (int,float) and math.isfinite(value)}
  if not finite:raise ValueError('No finite validation metrics')
  trainer.model.eval();probe=tokenizer(validation[0]['prompt'],return_tensors='pt',truncation=True,max_length=args.length).to(trainer.model.device)
  with torch.inference_mode():before=trainer.model(**probe).logits.cpu()
  adapter_path=out/'adapter';trainer.model.save_pretrained(adapter_path,safe_serialization=True);tokenizer.save_pretrained(adapter_path)
  merged=trainer.model.merge_and_unload();export=out/'merged';merged.save_pretrained(export,safe_serialization=True);tokenizer.save_pretrained(export)
  reloaded=factory.from_pretrained(export,local_files_only=True,trust_remote_code=False,dtype=torch.float32,device_map='cpu').eval()
  with torch.inference_mode():after=reloaded(**{key:value.cpu() for key,value in probe.items()}).logits
  torch.testing.assert_close(before,after,rtol=1e-4,atol=1e-3 if args.device=='cuda' else 1e-4)
  if args.method!='reward' and not torch.equal(before.argmax(-1),after.argmax(-1)):raise ValueError('Export changed greedy decisions')
  if args.method!='reward':inspect_model(export)
  report.update(status='complete',training_loss=result.training_loss,validation_metrics=finite,adapter=str(adapter_path),merged=str(export),export_greedy_tokens_equal=True,export_logits_verified=True,export_max_abs_logit_error=float((before-after).abs().max()),adopted=False)
  if args.method=='reward':report.pop('export_greedy_tokens_equal',None);report['export_scores_equal']=True;report['validation_score']=float(after.reshape(-1)[0])
  write();print(json.dumps(report,indent=2))
 except BaseException as error:report.update(status='failed',error=str(error));write();raise
if __name__=='__main__':main()

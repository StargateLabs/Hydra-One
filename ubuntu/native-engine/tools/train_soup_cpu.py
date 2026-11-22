"""Soup SFT bridge: local CPU only, separate environment, validated export."""
import argparse,json,math,os,sys,time,hashlib
from pathlib import Path
os.environ.update(CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',WANDB_DISABLED='true')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from serve.training_options import training_options
from tools.train_local_lora import dataset_rows,validate_destination
from serve.safetensors_runtime import inspect_model

def main():
 parser=argparse.ArgumentParser()
 for name in ('model','train','validation','output'):parser.add_argument('--'+name,required=True,type=Path)
 for name,default in [('steps',20),('length',128),('rank',2),('alpha',4),('accumulation',1),('seed',7)]:parser.add_argument('--'+name,type=int,default=default)
 parser.add_argument('--learning-rate',type=float,default=0.001);parser.add_argument('--checkpointing',action='store_true');args=parser.parse_args();options=training_options({**vars(args),'runner':'soup_cpu'})
 if args.length<64:raise ValueError('Soup supports training sequences from 64 tokens in this bridge')
 model,out=validate_destination(args.model,args.output);train=dataset_rows(args.train);validation=dataset_rows(args.validation)
 if train[0].get('messages') or validation[0].get('messages'):raise ValueError('Conversational assistant-only training requires the TRL runner')
 if {r['text'] for r in train}&{r['text'] for r in validation}:raise ValueError('Training and validation must be distinct')
 info=inspect_model(model)
 import psutil
 if info['bytes']>1024**3 or args.length>info['model_max_context'] or psutil.virtual_memory().available<info['bytes']*8+2*1024**3:raise ValueError('CPU model or resource limits exceeded')
 out.mkdir(parents=True);report={'status':'running','device':'cpu','runner':'soup_cpu','soup_version':'0.75.0','base':str(model),'steps':args.steps,'options':options,'scope':'Actual Soup SFT CPU bridge; not GPU streaming or a quality/speed claim'}
 def write():(out/'workflow.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 write()
 try:
  import torch
  from transformers import AutoModelForCausalLM,AutoTokenizer,TrainerCallback
  from datasets import Dataset,DatasetDict
  from soup_cli.config.schema import SoupConfig
  from soup_cli.trainer.sft import SFTTrainerWrapper
  from soup_cli.data.formats import format_to_messages
  torch.set_num_threads(2)
  config=SoupConfig(base=str(model),task='sft',backend='transformers',data={'train':str(args.train),'format':'pre_tokenized','tokenized_path':str(out/'tokenized'),'val_split':0,'max_length':args.length,'train_on_responses_only':False},training={'epochs':1,'lr':args.learning_rate,'batch_size':1,'gradient_accumulation_steps':args.accumulation,'seed':args.seed,'quantization':'none','stream_layers':False,'gradient_checkpointing':args.checkpointing,'logging_steps':1,'save_steps':10000,'warmup_ratio':0,'weight_decay':0,'optimizer':'adamw_torch','lora':{'r':args.rank,'alpha':args.alpha,'target_modules':['q_proj','v_proj']}},output=str(out/'soup'))
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
  from soup_cli.utils.data_pipeline import make_preprocess_cache_key,preprocess_dataset_key_input,preprocess_mask_mode
  from soup_cli.data.chat_templates import resolve_chat_template
  dataset_key=preprocess_dataset_key_input(config.data);template=resolve_chat_template(config.data.chat_template);mask=preprocess_mask_mode(config.data,config.training)
  metadata={'format':'plaintext','chat_template':template,'mask_mode':mask,'dataset_key':dataset_key,'key_schema':1,'cache_key':make_preprocess_cache_key(dataset_path=dataset_key,tokenizer_name=str(model),max_length=args.length,format_name='plaintext',chat_template=template,mask_mode=mask,task=config.task)}
  (out/'tokenized/metadata.json').write_text(json.dumps(metadata),encoding='utf-8')
  wrapper=SFTTrainerWrapper(config,device='cpu',trust_remote_code=False);wrapper.setup({'train':train,'val':validation});wrapper.trainer.args.max_steps=args.steps
  wrapper.model.float() # CPU bridge uses the same explicit FP32 precision for train and reload.
  report['precision']='float32'
  assert next(wrapper.model.parameters()).device.type=='cpu'
  def loss():
   wrapper.model.eval();values=[]
   with torch.inference_mode():
    for row in validation:
     tokens=wrapper.tokenizer(row['text'],return_tensors='pt',truncation=True,max_length=args.length)
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
  wrapper.trainer.add_callback(Progress());summary=wrapper.train();report['validation_loss_after']=loss()
  adapter=out/'adapter';wrapper.model.save_pretrained(adapter,safe_serialization=True);wrapper.tokenizer.save_pretrained(adapter)
  probe=wrapper.tokenizer(validation[0]['text'],return_tensors='pt',truncation=True,max_length=args.length)
  with torch.inference_mode():reference=wrapper.model(**probe).logits.clone()
  merged=wrapper.model.merge_and_unload();export=out/'merged';merged.save_pretrained(export,safe_serialization=True);wrapper.tokenizer.save_pretrained(export)
  reloaded=AutoModelForCausalLM.from_pretrained(export,local_files_only=True,trust_remote_code=False,dtype=torch.float32,device_map='cpu').eval()
  with torch.inference_mode():actual=reloaded(**probe).logits
  torch.testing.assert_close(reference,actual,rtol=1e-4,atol=1e-5);inspect_model(export)
  report.update(status='complete',summary=summary,adapter=str(adapter),merged=str(export),export_logits_verified=True,adopted=False)
  write();print(json.dumps(report,indent=2))
 except BaseException as error:report.update(status='failed',error=str(error));write();raise
if __name__=='__main__':main()

"""Managed offline NF4 training; exports an adapter and verifies its reload."""
import argparse
import gc
import hashlib
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def conversation_tokens(tokenizer,row,length):
    encoded=tokenizer.apply_chat_template(row['messages'],tokenize=True,return_dict=True,return_assistant_tokens_mask=True,truncation=True,max_length=length)
    ids=encoded['input_ids'];mask=encoded.get('assistant_masks',[])
    if len(ids)!=len(mask) or not any(mask[1:]) or not any(not bit for bit in mask):
        raise ValueError('Conversation needs both prompt and supervised assistant tokens after truncation')
    return dict(input_ids=ids,attention_mask=encoded.get('attention_mask',[1]*len(ids)),labels=[token if bit else -100 for token,bit in zip(ids,mask)])

def main():
    parser = argparse.ArgumentParser()
    for name in ('model', 'train', 'validation', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name, default in (('steps',20),('length',128),('rank',2),('alpha',4),('accumulation',1),('seed',7)):
        parser.add_argument('--' + name, type=int, default=default)
    parser.add_argument('--learning-rate', type=float, default=0.001)
    parser.add_argument('--checkpointing', action='store_true')
    parser.add_argument('--save-steps',type=int,default=0);parser.add_argument('--resume-checkpoint')
    args = parser.parse_args()
    from serve.training_options import training_options
    from tools.train_local_lora import dataset_rows, validate_destination, assistant_template, validate_checkpoint
    from serve.safetensors_runtime import inspect_model
    from serve.configuration import atomic_json
    options = training_options({**vars(args), 'runner':'unsloth_qlora','device':'cuda'})
    base, output = validate_destination(args.model, args.output)
    resume=validate_checkpoint(ROOT,args.resume_checkpoint,base,args.train,args.validation,options)
    info = inspect_model(base)
    train, validation = dataset_rows(args.train), dataset_rows(args.validation)
    conversational=bool(train[0].get('messages'))
    if conversational!=bool(validation[0].get('messages')):raise ValueError('Training and validation formats must match')
    if {r['text'] for r in train} & {r['text'] for r in validation}:
        raise ValueError('Training and validation must be distinct')
    if info['bytes'] > 1024**3 or args.length > info['model_max_context']:
        raise ValueError('Base weights or sequence exceed the validated native workflow')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1')
    from unsloth import FastLanguageModel
    import torch
    from datasets import Dataset
    from transformers import TrainerCallback
    from trl import SFTConfig, SFTTrainer
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise ValueError('Native QLoRA requires a BF16 GPU')
    if torch.cuda.mem_get_info()[0] < info['bytes']*8 + 6*1024**3:
        raise ValueError('Insufficient free GPU memory including reserve')
    output.mkdir(parents=True, exist_ok=False)
    from serve.transformers_integration import runtime_versions
    workflow = dict(runtime_versions=runtime_versions(),status='running',base=str(base),runner='unsloth_qlora',quantization='nf4',options=options,completed_steps=0,train_path=str(args.train.resolve()),validation_path=str(args.validation.resolve()),train_sha256=hashlib.sha256(args.train.read_bytes()).hexdigest(),validation_sha256=hashlib.sha256(args.validation.read_bytes()).hexdigest())
    # Paths are serialized as strings, never implementation-specific Path objects.
    workflow['options'] = {k:str(v) if isinstance(v,Path) else v for k,v in options.items()}
    def persist(): atomic_json(output/'workflow.json',workflow)
    persist()
    try:
        model, tokenizer = FastLanguageModel.from_pretrained(model_name=str(base),max_seq_length=args.length,dtype=torch.bfloat16,load_in_4bit=True,local_files_only=True,trust_remote_code=False)
        weights = [m.weight for m in model.modules() if getattr(getattr(m,'weight',None),'quant_state',None) is not None]
        if not weights or any(w.device.type!='cuda' or w.quant_state.quant_type!='nf4' for w in weights):
            raise ValueError('Expected actual NF4 weights on the GPU')
        original_template=tokenizer.chat_template
        if conversational:tokenizer.chat_template=assistant_template(tokenizer)
        model = FastLanguageModel.get_peft_model(model,r=args.rank,lora_alpha=args.alpha,lora_dropout=0,bias='none',target_modules=['q_proj','k_proj','v_proj','o_proj','gate_proj','up_proj','down_proj'],use_gradient_checkpointing=args.checkpointing,random_state=args.seed)
        FastLanguageModel.for_training(model,use_gradient_checkpointing=args.checkpointing)
        if resume:
            from peft import set_peft_model_state_dict
            from safetensors.torch import load_file
            loaded=set_peft_model_state_dict(model,load_file(str(resume/'adapter_model.safetensors')))
            if loaded.unexpected_keys or any('lora_' in key for key in loaded.missing_keys):raise ValueError('Checkpoint adapter did not match the native model')
            workflow['resumed_from']=str(resume)
        class Progress(TrainerCallback):
            def on_save(self,args,state,control,**kwargs):
                checkpoint=output/'trainer'/('checkpoint-'+str(state.global_step))
                names=('optimizer.pt','scheduler.pt','rng_state.pth','adapter_config.json','adapter_model.safetensors','trainer_state.json')
                manifest={name:dict(bytes=(checkpoint/name).stat().st_size,sha256=hashlib.sha256((checkpoint/name).read_bytes()).hexdigest()) for name in names}
                atomic_json(checkpoint/'CHECKPOINT-INTEGRITY.json',manifest)
                workflow['checkpoint']=str(checkpoint);persist()
            def on_step_end(self,args,state,control,**kwargs):
                workflow['completed_steps']=state.global_step;persist()
            def on_log(self,args,state,control,logs=None,**kwargs):
                if logs and isinstance(logs.get('loss'),(int,float)) and math.isfinite(logs['loss']):
                    workflow.setdefault('loss_history',[]).append(dict(step=state.global_step,loss=logs['loss']))
                    workflow['current_loss']=logs['loss'];persist()
        settings=SFTConfig(output_dir=str(output/'trainer'),max_steps=args.steps,max_length=args.length,per_device_train_batch_size=1,gradient_accumulation_steps=args.accumulation,learning_rate=args.learning_rate,warmup_steps=0,lr_scheduler_type='constant',logging_steps=1,save_strategy='steps' if args.save_steps else 'no',save_steps=max(1,args.save_steps),save_total_limit=2,eval_strategy='no',report_to=[],optim='adamw_torch',seed=args.seed,fp16=False,bf16=True,dataset_text_field='text',gradient_checkpointing=args.checkpointing,packing=False,assistant_only_loss=False)
        prepared_train=[conversation_tokens(tokenizer,row,args.length) for row in train] if conversational else train
        prepared_validation=[conversation_tokens(tokenizer,row,args.length) for row in validation] if conversational else validation
        if conversational:workflow['supervised_tokens_per_row']=[sum(token!=-100 for token in row['labels'][1:]) for row in prepared_train+prepared_validation];persist()
        trainer=SFTTrainer(model=model,args=settings,train_dataset=Dataset.from_list(prepared_train),eval_dataset=Dataset.from_list(prepared_validation),processing_class=tokenizer,callbacks=[Progress()])
        before=trainer.evaluate().get('eval_loss',float('nan'))
        if not math.isfinite(before):raise ValueError('Initial validation loss is invalid')
        workflow['validation_loss_before']=before;persist()
        trained=trainer.train(resume_from_checkpoint=str(resume) if resume else None)
        if trained.global_step!=args.steps or not math.isfinite(trained.training_loss) or any(not math.isfinite(float(r['grad_norm'])) for r in trainer.state.log_history if 'grad_norm' in r):
            raise ValueError('Training steps or gradients are invalid')
        evaluation=trainer.evaluate()
        if not math.isfinite(evaluation.get('eval_loss',float('nan'))):raise ValueError('Validation loss is invalid')
        model=trainer.accelerator.unwrap_model(trainer.model,keep_fp32_wrapper=False)
        changed=sum(bool(torch.count_nonzero(p).item()) for n,p in model.named_parameters() if 'lora_B' in n)
        if not changed:raise ValueError('Adapter parameters did not change')
        tokenizer.chat_template=original_template
        adapter=output/'adapter';model.save_pretrained(adapter,safe_serialization=True);tokenizer.save_pretrained(adapter)
        verification_text=tokenizer.apply_chat_template(validation[0]['messages'],tokenize=False) if conversational else validation[0]['text']
        inputs=tokenizer(verification_text,return_tensors='pt',truncation=True,max_length=args.length).to('cuda')
        FastLanguageModel.for_inference(model)
        with torch.inference_mode(): expected=model.generate(**inputs,max_new_tokens=8,do_sample=False)[0].tolist()
        del model,trainer,weights;gc.collect();torch.cuda.empty_cache()
        restored,_=FastLanguageModel.from_pretrained(model_name=str(adapter),max_seq_length=args.length,dtype=torch.bfloat16,load_in_4bit=True,local_files_only=True,trust_remote_code=False)
        FastLanguageModel.for_inference(restored)
        with torch.inference_mode(): actual=restored.generate(**inputs,max_new_tokens=8,do_sample=False)[0].tolist()
        if actual!=expected:raise ValueError('Export reload changed greedy tokens')
        files=[dict(name=p.name,bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in adapter.glob('*.safetensors')]
        if not files:raise ValueError('No adapter exported')
        workflow.update(status='complete',adapter=str(adapter),train_loss=trained.training_loss,validation_loss_after=evaluation['eval_loss'],loss_scope='assistant_only' if conversational else 'all_text',changed_lora_modules=changed,export_greedy_tokens_equal=True,export_verification='greedy_tokens_equal_nf4_reload',files=files,peak_allocated_bytes=torch.cuda.max_memory_allocated(),adopted=False)
        persist()
    except Exception as error:
        workflow.update(status='failed',error=str(error));persist();raise

if __name__=='__main__':main()

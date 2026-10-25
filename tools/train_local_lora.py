"""Local-only CPU SFT and Safetensors export in the installed Unsloth environment.

Never promotes a model or changes operational configuration. GPU is not enabled.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def dataset_rows(path,method='sft'):
    path=Path(path).resolve(strict=True)
    if path.stat().st_size>8*1024*1024:raise ValueError('Dataset exceeds 8 MiB for this CPU workflow')
    rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not rows:raise ValueError('Dataset is empty')
    normalized=[]
    if method in ('vlm','auto') and isinstance(rows[0],dict) and 'image' in rows[0]:
        from tools.train_vlm_lora import rows as vision_rows
        return [{**row,'text':json.dumps({key:value for key,value in row.items() if key!='image'},ensure_ascii=False,sort_keys=True)} for row in vision_rows(path)]
    if method=='vlm':raise ValueError('Vision dataset requires prompt, response and image')
    if method in ('kto','auto') and isinstance(rows[0],dict) and 'label' in rows[0]:
        for row in rows:
            if not isinstance(row,dict) or set(row)!={'prompt','completion','label'} or type(row['label']) is not bool or any(not isinstance(row[key],str) or not row[key].strip() or len(row[key])>16000 for key in ('prompt','completion')):raise ValueError('KTO requires prompt, completion and boolean label')
            normalized.append({**row,'text':json.dumps(row,ensure_ascii=False,sort_keys=True)})
        return normalized
    if method=='kto':raise ValueError('Dataset format does not match KTO')
    if method=='reward':method='dpo'
    if method in ('dpo','grpo','auto') and isinstance(rows[0],dict) and ('chosen' in rows[0] or 'target' in rows[0]):
        inferred='dpo' if 'chosen' in rows[0] else 'grpo'
        if method!='auto' and method!=inferred:raise ValueError('Dataset format does not match training method')
        method=inferred
        fields={'prompt','chosen','rejected'} if method=='dpo' else {'prompt','target'}
        for row in rows:
            if not isinstance(row,dict) or set(row)!=fields or any(not isinstance(row[key],str) or not row[key].strip() or len(row[key])>16000 for key in fields):raise ValueError('Invalid '+method+' dataset; use nonempty text fields '+', '.join(sorted(fields)))
            if method=='dpo' and row['chosen']==row['rejected']:raise ValueError('Chosen and rejected answers must differ')
            normalized.append({**row,'text':json.dumps(row,ensure_ascii=False,sort_keys=True)})
        return normalized
    if method in ('dpo','grpo'):raise ValueError('Dataset format does not match advanced training method')
    for row in rows:
        if isinstance(row,dict) and set(row)=={'text'} and isinstance(row['text'],str) and row['text'].strip():normalized.append(row);continue
        if not isinstance(row,dict) or set(row)!={'messages'} or not isinstance(row['messages'],list):raise ValueError('Use JSONL text rows or messages conversations')
        messages=row['messages'];roles=[]
        for message in messages:
            if not isinstance(message,dict) or set(message)!={'role','content'} or message['role'] not in ('system','user','assistant') or not isinstance(message['content'],str) or not message['content'].strip():raise ValueError('Use nonempty text messages with system, user and assistant roles')
            roles.append(message['role'])
        turns=roles[1:] if roles and roles[0]=='system' else roles
        if not turns or len(turns)%2 or any(role!=('user' if i%2==0 else 'assistant') for i,role in enumerate(turns)):raise ValueError('Conversations must alternate user and assistant, ending with assistant')
        normalized.append({'text':json.dumps(messages,ensure_ascii=False,sort_keys=True,separators=(',',':')),'messages':messages})
    if len({bool(row.get('messages')) for row in normalized})!=1:raise ValueError('Do not mix plain text and conversations in a dataset')
    return normalized

def assistant_template(tokenizer):
    """Add transparent loss markers only to the recognized SmolLM template."""
    original=tokenizer.chat_template
    if not isinstance(original,str):raise ValueError('Conversational training requires a chat template')
    if '{% generation %}' in original:return original
    expression="{{'<|im_start|>' + message['role'] + '\n' + message['content'] + '<|im_end|>' + '\n'}}"
    if expression not in original:raise ValueError('This tokenizer has no supported assistant loss mask; use a template with generation markers')
    replacement="{{'<|im_start|>' + message['role'] + '\n'}}{% if message['role'] == 'assistant' %}{% generation %}{{message['content'] + '<|im_end|>' + '\n'}}{% endgeneration %}{% else %}{{message['content'] + '<|im_end|>' + '\n'}}{% endif %}"
    return original.replace(expression,replacement)

def validate_destination(model,output):
    model=Path(model).resolve(strict=True);output=Path(output).resolve()
    if not output.is_relative_to(ROOT) or output==ROOT or output.exists():raise ValueError('Choose a new output directory inside the project')
    if output.is_relative_to(model) or model.is_relative_to(output):raise ValueError('Output must be separate from base model')
    return model,output

def validate_checkpoint(root,checkpoint,model,train,validation,options):
    """Reject incompatible resumes before launching a training subprocess."""
    if not checkpoint:return None
    resume=Path(checkpoint).resolve(strict=True)
    if not resume.is_dir() or not resume.is_relative_to((Path(root)/'output/training').resolve()) or not resume.name.startswith('checkpoint-'):
        raise ValueError('Resume requires a checkpoint created by this local training workflow')
    source=json.loads((resume.parent.parent/'workflow.json').read_text(encoding='utf-8'))
    if not source.get('train_sha256') or not source.get('validation_sha256'):
        raise ValueError('Checkpoint precedente senza impronte dei dataset: conservato, ma ripresa non verificabile')
    if Path(source['base']).resolve()!=Path(model).resolve() or source['train_sha256']!=hashlib.sha256(Path(train).read_bytes()).hexdigest() or source['validation_sha256']!=hashlib.sha256(Path(validation).read_bytes()).hexdigest():
        raise ValueError('Resume model or dataset differs from the checkpoint source')
    for key in ('rank','alpha','length','accumulation','seed','learning_rate','checkpointing'):
        if source['options'].get(key)!=options[key]:raise ValueError('Resume configuration differs: '+key)
    if source['options'].get('runner','trl_cpu')!=options.get('runner','trl_cpu') or source['options'].get('device','cpu')!=options.get('device','cpu'):
        raise ValueError('Resume runner or device differs from the checkpoint source')
    if bool(source['options'].get('layer_streaming'))!=bool(options.get('layer_streaming')):
        raise ValueError('Resume streaming mode differs from the checkpoint source')
    if options.get('runner')=='unsloth_qlora' or options.get('layer_streaming'):
        manifest=json.loads((resume/'CHECKPOINT-INTEGRITY.json').read_text(encoding='utf-8'))
        required={'optimizer.pt','scheduler.pt','rng_state.pth','adapter_config.json','adapter_model.safetensors','trainer_state.json'}
        if not isinstance(manifest,dict) or set(manifest)!=required:raise ValueError('Invalid native checkpoint integrity manifest')
        for name,record in manifest.items():
            path=resume/name
            if path.is_symlink() or not path.is_file() or path.stat().st_size!=record['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:
                raise ValueError('Native checkpoint integrity failure: '+name)
    state=json.loads((resume/'trainer_state.json').read_text(encoding='utf-8'))
    if type(state.get('global_step')) is not int or state['global_step']<1 or state['global_step']>=options['steps']:
        raise ValueError('Resume target steps must exceed the saved checkpoint step')
    for name in ('optimizer.pt','scheduler.pt','rng_state.pth','adapter_config.json','adapter_model.safetensors'):
        if not (resume/name).is_file():raise ValueError('Incomplete training checkpoint: '+name)
    return resume

def main():
    parser=argparse.ArgumentParser()
    for name in ('model','train','validation','output'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--steps',type=int,default=20);parser.add_argument('--length',type=int,default=128)
    parser.add_argument('--rank',type=int,default=2);parser.add_argument('--alpha',type=int,default=4)
    parser.add_argument('--learning-rate',type=float,default=0.001);parser.add_argument('--accumulation',type=int,default=1)
    parser.add_argument('--seed',type=int,default=7);parser.add_argument('--checkpointing',action='store_true')
    parser.add_argument('--save-steps',type=int,default=0);parser.add_argument('--resume-checkpoint')
    parser.add_argument('--device',choices=('cpu','cuda'),default='cpu')
    args=parser.parse_args()
    from serve.training_options import training_options
    options=training_options(vars(args))
    model_path,out=validate_destination(args.model,args.output)
    train=dataset_rows(args.train);validation=dataset_rows(args.validation)
    resume=validate_checkpoint(ROOT,args.resume_checkpoint,model_path,args.train,args.validation,options)
    conversational=bool(train[0].get('messages'))
    if conversational!=bool(validation[0].get('messages')):raise ValueError('Training and validation must use the same dataset format')
    if {r['text'] for r in train}&{r['text'] for r in validation}:raise ValueError('Training and validation must be distinct')
    if not 1<=args.steps<=1000 or not 16<=args.length<=512:raise ValueError('CPU workflow supports 1..1000 steps and 16..512 training tokens')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',WANDB_DISABLED='true')
    if args.device=='cpu':os.environ.update(CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
    from serve.safetensors_runtime import inspect_model
    info=inspect_model(model_path)
    if args.length>info['model_max_context']:raise ValueError('Training length exceeds declared model context')
    import psutil
    if info['bytes']>1024**3 or psutil.virtual_memory().available<info['bytes']*8+2*1024**3:
        raise ValueError('Insufficient RAM or base exceeds 1 GiB CPU validation workflow limit')
    import torch
    from transformers import AutoTokenizer,AutoModelForCausalLM,TrainerCallback
    from datasets import Dataset
    from peft import LoraConfig
    from trl import SFTConfig,SFTTrainer
    if args.device=='cuda':
        if not torch.cuda.is_available():raise ValueError('GPU training runtime unavailable')
        free,total=torch.cuda.mem_get_info()
        if info['bytes']*8+2*1024**3>free-4*1024**3:raise ValueError('Insufficient VRAM including 4 GiB reserve')
    torch.set_num_threads(2);torch.manual_seed(args.seed)
    tokenizer=AutoTokenizer.from_pretrained(model_path,local_files_only=True,trust_remote_code=False)
    original_template=tokenizer.chat_template
    if conversational:
        from trl.data_utils import apply_chat_template
        marked=assistant_template(tokenizer)
        for row in train+validation:
            before_text=apply_chat_template({'messages':row['messages']},tokenizer)['text']
            tokenizer.chat_template=marked
            after_text=apply_chat_template({'messages':row['messages']},tokenizer)['text']
            tokenizer.chat_template=original_template
            if before_text!=after_text:raise ValueError('Loss markers changed the original conversation format')
        tokenizer.chat_template=marked
    if tokenizer.pad_token_id is None:tokenizer.pad_token=tokenizer.eos_token
    if tokenizer.pad_token_id is None:raise ValueError('Tokenizer requires a declared padding or EOS token')
    tokenized=[]
    for row in ([] if conversational else train):
        ids=tokenizer(row['text'],truncation=True,max_length=args.length)['input_ids']
        if len(ids)<2:raise ValueError('Training text must tokenize to at least two tokens')
        tokenized.append({'input_ids':ids})
    model=AutoModelForCausalLM.from_pretrained(model_path,local_files_only=True,trust_remote_code=False,dtype=torch.float32,device_map=args.device)
    def loss(current):
        current.eval();values=[]
        with torch.inference_mode():
            for row in validation:
                inputs=tokenizer(row['text'],return_tensors='pt',truncation=True,max_length=args.length).to(current.device)
                if inputs['input_ids'].shape[-1]<2:raise ValueError('Validation text must tokenize to at least two tokens')
                value=current(**inputs,labels=inputs['input_ids']).loss.item()
                if not math.isfinite(value):raise ValueError('Nonfinite validation loss')
                values.append(value)
        return sum(values)/len(values)
    before=None if conversational else loss(model)
    out.mkdir(parents=True)
    from serve.transformers_integration import runtime_versions
    report=dict(runtime_versions=runtime_versions(),status='running',device=args.device,base=str(model_path),steps=args.steps,validation_loss_before=before,
        train_path=str(args.train.resolve()),validation_path=str(args.validation.resolve()),
        train_sha256=hashlib.sha256(args.train.read_bytes()).hexdigest(),validation_sha256=hashlib.sha256(args.validation.read_bytes()).hexdigest(),
        scope='Functional local SFT and export; no quality or speed promotion',options=options)
    def write(): (out/'workflow.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    write()
    class Progress(TrainerCallback):
        def on_save(self,args,state,control,**kwargs):
            report['checkpoint']=str(out/'trainer'/('checkpoint-'+str(state.global_step)));write()
        def on_log(self,args,state,control,logs=None,**kwargs):
            report.update(completed_steps=state.global_step,total_steps=args.max_steps)
            if logs and isinstance(logs.get('loss'),(int,float)) and math.isfinite(logs['loss']):
                report['current_loss']=logs['loss']
                report['loss_history']=(report.get('loss_history',[])+[{'step':state.global_step,'loss':logs['loss']}])[-256:]
            write()
    try:
        config=SFTConfig(output_dir=str(out/'trainer'),use_cpu=args.device=='cpu',bf16=False,fp16=False,
            max_steps=args.steps,max_length=args.length,per_device_train_batch_size=1,
            learning_rate=args.learning_rate,gradient_accumulation_steps=args.accumulation,seed=args.seed,data_seed=args.seed,logging_steps=1,save_strategy='steps' if args.save_steps else 'no',save_steps=max(1,args.save_steps),save_total_limit=2,report_to='none',
            packing=False,assistant_only_loss=conversational,gradient_checkpointing=args.checkpointing,optim='adamw_torch',dataset_num_proc=None)
        trainer=SFTTrainer(model=model,args=config,callbacks=[Progress()],processing_class=tokenizer,train_dataset=Dataset.from_list([{'messages':r['messages']} for r in train] if conversational else tokenized),
            eval_dataset=Dataset.from_list([{'messages':r['messages']} for r in validation]) if conversational else None,
            peft_config=LoraConfig(r=args.rank,lora_alpha=args.alpha,target_modules=['q_proj','v_proj'],task_type='CAUSAL_LM'))
        if conversational:
            counts=[sum(row.get('assistant_masks',[])[1:]) for dataset in (trainer.train_dataset,trainer.eval_dataset) for row in dataset]
            if not counts or min(counts)<1:raise ValueError('Truncation removed every assistant token from a conversation')
            report.update(loss_scope='assistant_only',supervised_tokens_per_row=counts,validation_loss_before=trainer.evaluate()['eval_loss'])
            write()
        else:report['loss_scope']='all_text'
        trained=trainer.train(resume_from_checkpoint=str(resume) if resume else None);after=trainer.evaluate()['eval_loss'] if conversational else loss(trainer.model)
        if not math.isfinite(trained.training_loss):raise ValueError('Nonfinite training loss')
        tokenizer.chat_template=original_template
        adapter=out/'adapter';trainer.model.save_pretrained(adapter,safe_serialization=True);tokenizer.save_pretrained(adapter)
        trainer.model.eval()
        probe={'input_ids':torch.tensor([trainer.eval_dataset[0]['input_ids']])} if conversational else tokenizer(validation[0]['text'],return_tensors='pt',truncation=True,max_length=args.length)
        probe={k:v.to(trainer.model.device) for k,v in probe.items()}
        with torch.inference_mode():reference=trainer.model(**probe).logits.clone().cpu()
        merged=trainer.model.merge_and_unload();export=out/'merged';merged.save_pretrained(export,safe_serialization=True);tokenizer.save_pretrained(export)
        reloaded=AutoModelForCausalLM.from_pretrained(export,local_files_only=True,trust_remote_code=False,dtype=torch.float32,device_map='cpu').eval()
        probe={k:v.cpu() for k,v in probe.items()}
        with torch.inference_mode():actual=reloaded(**probe).logits
        # Merging changes FP32 matrix-operation order. Check both numerical
        # proximity and every greedy token decision, including near-zero logits.
        # The same FP32 merge occurs for text and conversations. A two-step
        # control without checkpointing reproduced the identical 3.82e-5
        # near-zero error; use one absolute bound and retain exact greedy parity.
        tolerance=1e-4 if args.device=='cpu' else 1e-3
        torch.testing.assert_close(reference,actual,rtol=1e-4,atol=tolerance)
        greedy_equal=bool(torch.equal(reference.argmax(-1),actual.argmax(-1)))
        if not greedy_equal:raise ValueError('Merged export changes greedy token decisions on the validation probe')
        report.update(export_max_abs_logit_error=float((reference-actual).abs().max()),export_absolute_tolerance=tolerance,export_greedy_tokens_equal=greedy_equal)
        inspect_model(export)
        report.update(status='complete',validation_loss_after=after,training_loss=trained.training_loss,
            adapter=str(adapter),merged=str(export),export_logits_verified=True,adopted=False)
        write();print(json.dumps(report,indent=2))
    except BaseException as error:
        report.update(status='failed',error=str(error));write();raise

if __name__=='__main__':main()

"""Real owned Python lifecycle on an explicitly untrained CPU fixture and LoRA."""
import json,os,subprocess,time,urllib.request,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'output/verification/safetensors-cpu-fixture'
ADAPTER=ROOT/'output/verification/safetensors-lora-fixture'
PYTHON=Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe'
def call(path,body=None):
    request=urllib.request.Request('http://127.0.0.1:8088'+path,data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)
def create():
    os.environ.update(CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
    import torch
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import Qwen2Config,Qwen2ForCausalLM,PreTrainedTokenizerFast
    from peft import LoraConfig,get_peft_model
    torch.manual_seed(7)
    vocab={word:i for i,word in enumerate(['[PAD]','[UNK]','hello','world','test','response','model','user','assistant','system','yes','no','one','two','three','four'])}
    core=Tokenizer(WordLevel(vocab,unk_token='[UNK]'));core.pre_tokenizer=Whitespace()
    tok=PreTrainedTokenizerFast(tokenizer_object=core,unk_token='[UNK]',pad_token='[PAD]')
    tok.chat_template="{% for message in messages %}{{ message['role'] + ' ' + message['content'] + ' ' }}{% endfor %}{% if add_generation_prompt %}assistant {% endif %}"
    config=Qwen2Config(vocab_size=len(vocab),hidden_size=32,intermediate_size=64,num_hidden_layers=1,
        num_attention_heads=2,num_key_value_heads=2,max_position_embeddings=2048,eos_token_id=None,pad_token_id=0)
    model=Qwen2ForCausalLM(config).cpu();model.save_pretrained(FOLDER,safe_serialization=True);tok.save_pretrained(FOLDER)
    lora=get_peft_model(model,LoraConfig(r=2,lora_alpha=4,target_modules=['q_proj','v_proj'],task_type='CAUSAL_LM'))
    lora.save_pretrained(ADAPTER)
    path=ADAPTER/'adapter_config.json';data=json.loads(path.read_text());data['base_model_name_or_path']=str(FOLDER)
    path.write_text(json.dumps(data,indent=2))
    (FOLDER/'FIXTURE-NOT-A-TRAINED-MODEL.txt').write_text('Random CPU fixture. No quality or model performance claim.')
def main():
    if '--create-fixture' in sys.argv:create();return
    subprocess.run([str(PYTHON),'-X','utf8',__file__,'--create-fixture'],check=True,timeout=90)
    if call('/metrics')['live']['state']!='unloaded' or call('/inference-backends')['status']!='idle':raise RuntimeError('Engines busy')
    report=dict(scope='Untrained fixture, CPU only. Functional Python/LoRA verification, no quality/performance claim.',runs=[])
    for adapter in (None,str(ADAPTER)):
        try:
            call('/inference-backends/start',dict(mode='safetensors',model_path=str(FOLDER),context=1024,
                gpu=False,runtime={'threads':2},adapter_path=adapter))
            deadline=time.monotonic()+90
            while True:
                state=call('/inference-backends')
                if state['status']=='ready':break
                if state['status']=='error':raise RuntimeError(state['error'])
                if time.monotonic()>deadline:raise RuntimeError('Readiness timeout')
                time.sleep(.5)
            model=state['public_model']
            result=call('/v1/chat/completions',dict(model=model,messages=[dict(role='user',content='hello world')],
                max_tokens=16,stream=False,temperature=0))
            assert result['usage']['completion_tokens']==16 and result['choices'][0]['message']['content'].strip()
            assert state['owned_process'] and state['gpu_requested'] is False and state['context_source']=='owned_python_runtime'
            report['runs'].append(dict(adapter=bool(adapter),state=state,response=result))
            if adapter is None:
                request=urllib.request.Request('http://127.0.0.1:8088/v1/chat/completions',data=json.dumps(dict(model=model,
                    messages=[dict(role='user',content='hello world')],max_tokens=16,stream=True,temperature=0)).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=60) as response:stream=response.read().decode()
                assert 'data: [DONE]' in stream
                report['stream_completed']=True
                call('/benchmark-lab/start',dict(model='optional_active',tokens=32,runs=3))
                deadline=time.monotonic()+60
                while True:
                    job=call('/benchmark-lab')['job']
                    if job['status'] not in ('running','cancelling'):break
                    if time.monotonic()>deadline:raise RuntimeError('Fixture benchmark timeout')
                    time.sleep(.5)
                assert job['status']=='complete',job.get('error')
                assert 'wall_tok_s' in job['results'][0]['summary'] and 'decode_tok_s' not in job['results'][0]['summary']
                report['benchmark']=job
        finally:
            state=call('/inference-backends')
            if state.get('model_path')==str(FOLDER) and not state.get('busy'):call('/inference-backends/stop',{})
    report.update(passed=True,finished_at=time.time())
    (ROOT/'output/verification/safetensors-direct-cpu-20261010.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=True,base_and_lora_verified=True,device='CPU',untrained_fixture=True)))
if __name__=='__main__':main()

"""Owned local text-model runtime in the existing Unsloth Python environment.

CPU uses Transformers/PEFT. No remote model code, pickle weights or implicit downloads.
GPU activation remains gated separately after the recorded hardware incident.
"""
import argparse,copy,json,os,re,threading,time,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

def _loaded_rocm_blas():
    """Bind only the vendor BLAS already loaded in this Windows child process."""
    if os.name!='nt':return None
    import ctypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetModuleHandleW.argtypes=[ctypes.c_wchar_p]
    kernel.GetModuleHandleW.restype=ctypes.c_void_p
    handle=kernel.GetModuleHandleW('rocm-openblas.dll')
    if not handle:return None
    library=ctypes.CDLL('rocm-openblas.dll',handle=handle)
    library.openblas_set_num_threads.argtypes=[ctypes.c_int]
    library.openblas_set_num_threads.restype=None
    library.openblas_get_num_threads.argtypes=[]
    library.openblas_get_num_threads.restype=ctypes.c_int
    return library


def configure_runtime_threads(torch,threads,device):
    """Apply the selected count to both PyTorch and its independent ROCm CPU BLAS."""
    torch.set_num_threads(threads)
    policy=dict(requested=threads,torch_threads=torch.get_num_threads(),
                blas_before=None,blas_threads=None)
    if device=='cpu' and getattr(torch.version,'hip',None):
        library=_loaded_rocm_blas()
        if library is not None:
            policy['blas_before']=library.openblas_get_num_threads()
            library.openblas_set_num_threads(threads)
            policy['blas_threads']=library.openblas_get_num_threads()
            if not 1<=policy['blas_threads']<=threads:
                raise RuntimeError('OpenBLAS CPU thread limit was not applied')
    return policy


def load_local_tokenizer(folder,auto_factory=None):
    """Respect an explicitly serialized generic backend instead of model-type guessing."""
    path=Path(folder)/'tokenizer_config.json'
    config=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    declared=config.get('tokenizer_class')
    if declared in ('TokenizersBackend','PreTrainedTokenizerFast'):
        import transformers
        factory=getattr(transformers,declared).from_pretrained
    else:
        if auto_factory is None:
            from transformers import AutoTokenizer
            auto_factory=AutoTokenizer.from_pretrained
        factory=auto_factory
    return factory(str(folder),local_files_only=True,trust_remote_code=False)

def attention_options(loader,attention):
    if attention not in ('auto','sdpa','eager'):raise ValueError('Unsupported attention implementation')
    if loader in ('unsloth','airllm') and attention!='auto':raise ValueError('This loader manages its own attention implementation')
    return {} if attention=='auto' else {'attn_implementation':attention}

def cache_options(loader,cache):
    if cache not in ('auto','dynamic','off'):raise ValueError('Unsupported cache implementation')
    if loader in ('unsloth','airllm') and cache!='auto':raise ValueError('This loader manages its own cache')
    return {} if cache=='auto' else {'use_cache':False} if cache=='off' else {'use_cache':True,'cache_implementation':'dynamic'}

def checkpoint_quantization(config):
    """Describe saved weights separately from quantization requested at load time."""
    declared=config.get('quantization_config')
    if declared is None:return dict(method='none',bits=None,scheme=None,prequantized=False)
    if not isinstance(declared,dict):raise ValueError('Invalid checkpoint quantization configuration')
    method=declared.get('quant_method')
    if not isinstance(method,str) or not method.strip():
        method='bitsandbytes' if any(key in declared for key in ('load_in_4bit','load_in_8bit','_load_in_4bit','_load_in_8bit','bnb_4bit_quant_type')) else 'unknown'
    method=method.lower().strip()
    bits=declared.get('bits')
    if method=='bitsandbytes':
        bits=4 if declared.get('load_in_4bit') is True or declared.get('_load_in_4bit') is True else 8 if declared.get('load_in_8bit') is True or declared.get('_load_in_8bit') is True else bits
    if type(bits) is not int:bits=None
    scheme=declared.get('bnb_4bit_quant_type') if method=='bitsandbytes' else None
    return dict(method=method,bits=bits,scheme=scheme if isinstance(scheme,str) else None,prequantized=True)

def validate_adapter(adapter,model):
    """Require an explicit local base identity before any PEFT or Unsloth load."""
    adapter=Path(adapter).expanduser()
    if not adapter.is_absolute() or not (adapter/'adapter_config.json').is_file() or not (adapter/'adapter_model.safetensors').is_file():
        raise ValueError('Select an absolute local LoRA directory with configuration and Safetensors weights')
    declared=json.loads((adapter/'adapter_config.json').read_text(encoding='utf-8'))
    base=declared.get('base_model_name_or_path')
    if not isinstance(base,str) or not base or not Path(base).is_absolute() or Path(base).resolve()!=Path(model).resolve():
        raise ValueError('Adapter base does not match selected local model')
    return declared

def inspect_model(folder,allow_unsupported=False):
    folder=Path(folder)
    if not folder.is_absolute() or not folder.is_dir():raise ValueError('Select an absolute local model directory')
    config=json.loads((folder/'config.json').read_text(encoding='utf-8'))
    if config.get('model_type')=='llava':
        from serve.transformers_vision import inspect_vision
        return inspect_vision(folder)
    quantization=checkpoint_quantization(config)
    reason=('Pre-quantized '+quantization['method'].upper()+' Python checkpoints need a validated device-specific loader; choose an unquantized Safetensors base') if quantization['prequantized'] else None
    if reason and not allow_unsupported:raise ValueError(reason)
    architectures=config.get('architectures') or []
    if not any(isinstance(name,str) and name.endswith('ForCausalLM') for name in architectures):
        raise ValueError('This runtime supports text causal language models, not embeddings/audio/diffusion')
    weights=list(folder.glob('*.safetensors'))
    if not weights:raise ValueError('No local Safetensors weights found')
    index=folder/'model.safetensors.index.json'
    if index.is_file():
        names=set(json.loads(index.read_text(encoding='utf-8'))['weight_map'].values())
        if any(not isinstance(name,str) or Path(name).name!=name or not (folder/name).is_file() for name in names):
            raise ValueError('Missing or invalid Safetensors shard')
    maximum=config.get('max_position_embeddings')
    if type(maximum) is not int or maximum<1024:raise ValueError('Model context limit unavailable')
    layers=config.get('num_hidden_layers',config.get('n_layer'));heads=config.get('num_attention_heads',config.get('n_head'))
    width=config.get('hidden_size',config.get('n_embd'));kvheads=config.get('num_key_value_heads',heads)
    # Some architectures declare a head dimension different from hidden_size/heads.
    # Respect it or automatic fit can underestimate the cache and overcommit RAM.
    head_dim=config.get('head_dim')
    if head_dim is None and all(type(v) is int and v>0 for v in (width,heads)) and width%heads==0:
        head_dim=width//heads
    kv=2*4*layers*kvheads*head_dim if all(type(v) is int and v>0 for v in (layers,kvheads,head_dim)) else None
    return dict(path=str(folder),bytes=sum(path.stat().st_size for path in weights),kv_bytes_per_token=kv,
                model_max_context=maximum,architecture=architectures[0],model_type=config.get('model_type'),
                checkpoint_quantization=quantization,runtime_supported=reason is None,runtime_error=reason)

def tool_protocol(tokenizer):
    if getattr(tokenizer,'response_schema',None):return 'tokenizer_schema'
    template=getattr(tokenizer,'chat_template','')
    if isinstance(template,str) and all(marker in template for marker in ('<tool_call>','</tool_call>','arguments','tools')):return 'qwen_xml'
    return None

def parsed_message(tokenizer,text,allowed_names=None):
    protocol=tool_protocol(tokenizer)
    if protocol=='tokenizer_schema':message=tokenizer.parse_response(text)
    elif protocol=='qwen_xml':
        content=text;reasoning=None
        if '</think>' in content:
            reasoning,content=content.split('</think>',1);reasoning=reasoning.removeprefix('<think>').strip()
        blocks=re.findall(r'<tool_call>\s*(.*?)\s*</tool_call>',content,re.S)
        if content.count('<tool_call>')!=len(blocks) or content.count('</tool_call>')!=len(blocks):
            raise ValueError('Incomplete tool call')
        calls=[]
        for block in blocks:
            value=json.loads(block)
            if not isinstance(value,dict) or not isinstance(value.get('name'),str) or not isinstance(value.get('arguments'),dict):raise ValueError('Invalid tool call')
            calls.append(dict(function=dict(name=value['name'],arguments=value['arguments'])))
        content=re.sub(r'<tool_call>.*?</tool_call>','',content,flags=re.S).strip()
        message=dict(content=content or None)
        if calls:message['tool_calls']=calls
        if reasoning:message['reasoning_content']=reasoning
    else:message=dict(content=text)
    if not isinstance(message,dict):raise ValueError('Invalid tokenizer response parser result')
    message=copy.deepcopy(message)
    for key in ('content','reasoning_content'):
        if message.get(key) is not None and not isinstance(message[key],str):
            raise ValueError('Invalid tokenizer response text')
    message['role']='assistant'
    calls=message.get('tool_calls',[])
    if calls is None:calls=[]
    if not isinstance(calls,list):raise ValueError('Invalid tokenizer tool calls')
    identities=set()
    for call in calls:
        if not isinstance(call,dict) or not isinstance(call.get('function'),dict):raise ValueError('Invalid tokenizer tool call')
        call.setdefault('id','call_'+uuid.uuid4().hex);call['type']='function'
        if not isinstance(call['id'],str) or not call['id'] or call['id'] in identities:raise ValueError('Invalid or duplicate tool call identity')
        identities.add(call['id'])
        fn=call['function']
        if not isinstance(fn.get('name'),str) or not fn['name']:raise ValueError('Invalid tool name')
        if allowed_names is not None and fn.get('name') not in allowed_names:raise ValueError('Model requested an unavailable tool')
        arguments=fn.get('arguments',{})
        for _ in range(2):
            if isinstance(arguments,str):arguments=json.loads(arguments)
        if not isinstance(arguments,dict):raise ValueError('Tool arguments must be an object')
        fn['arguments']=json.dumps(arguments,ensure_ascii=False,allow_nan=False)
    return message

def requested_tools(body):
    """Validate the OpenAI tool contract before applying a model template."""
    tools=body.get('tools') or []
    if not isinstance(tools,list):raise ValueError('Tools must be a list')
    names=[]
    for tool in tools:
        if not isinstance(tool,dict) or tool.get('type')!='function':raise ValueError('Only function tools are supported')
        function=tool.get('function')
        if not isinstance(function,dict) or not isinstance(function.get('name'),str) or not function['name']:raise ValueError('Invalid tool function')
        names.append(function['name'])
    if len(set(names))!=len(names):raise ValueError('Duplicate tool names')
    choice=body.get('tool_choice','auto')
    if choice=='none':return None
    if choice!='auto':raise ValueError('Required or forced tool selection is not supported by this runtime')
    if body.get('parallel_tool_calls') is True:raise ValueError('Parallel tool calls are not supported by this runtime')
    return tools or None

def normalize_messages(messages):
    result=copy.deepcopy(messages)
    if not isinstance(result,list) or not result:raise ValueError('Messages required')
    for message in result:
        if not isinstance(message,dict) or message.get('role') not in ('system','user','assistant','tool','developer'):
            raise ValueError('Invalid message role')
        if message.get('content') is not None and not isinstance(message['content'],str):
            raise ValueError('This runtime accepts text only')
        for call in message.get('tool_calls') or []:
            fn=call.get('function',{})
            args=fn.get('arguments',{})
            for _ in range(2):
                if isinstance(args,str):args=json.loads(args)
            if not isinstance(args,dict):raise ValueError('Tool arguments must be an object')
            fn['arguments']=args
    instructions=[message.get('content') or '' for message in result if message['role'] in ('system','developer')]
    result=([{'role':'system','content':'\n\n'.join(instructions)}] if instructions else [])+[message for message in result if message['role'] not in ('system','developer')]
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',required=True,type=Path)
    parser.add_argument('--adapter',type=Path)
    parser.add_argument('--context',type=int,default=4096)
    parser.add_argument('--threads',type=int,default=8)
    parser.add_argument('--device',choices=('cpu','cuda'),default='cpu')
    parser.add_argument('--loader',choices=('transformers','unsloth','airllm'),default='transformers')
    parser.add_argument('--quantization',choices=('none','nf4'),default='none')
    parser.add_argument('--cache',choices=('auto','dynamic','off'),default='auto')
    parser.add_argument('--draft-model',type=Path)
    parser.add_argument('--attention',choices=('auto','sdpa','eager'),default='auto')
    parser.add_argument('--telemetry-file',type=Path)
    parser.add_argument('--port',type=int,default=8091)
    args=parser.parse_args()
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    if args.loader=='airllm':
        # This script is also launched directly from outside the package.
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
        from serve.airllm_runtime import validate_options
        validate_options(args.device,args.adapter,args.draft_model,args.quantization,args.attention,args.cache)
    attention=attention_options(args.loader,args.attention)
    cache=cache_options(args.loader,args.cache)
    if args.draft_model and args.cache=='off':raise ValueError('Local assistant requires KV cache')
    if args.quantization=='nf4' and (args.device!='cuda' or args.loader!='unsloth'):raise ValueError('NF4 requires native Unsloth GPU')
    info=inspect_model(args.model)
    vision_model='image' in info.get('input_modalities',[])
    if vision_model and (args.device!='cpu' or args.loader!='transformers' or args.adapter or args.draft_model or args.quantization!='none'):
        raise ValueError('LLaVA vision currently requires CPU Transformers without adapter, draft or quantization')
    if args.adapter:validate_adapter(args.adapter,args.model)
    draft_info=inspect_model(args.draft_model) if args.draft_model else None
    if draft_info and (args.loader!='transformers' or args.adapter or draft_info['bytes']>1024**3 or args.context>draft_info['model_max_context']):raise ValueError('Local draft requires Transformers without adapters, weights <= 1 GiB and sufficient context')
    if not 1024<=args.context<=info['model_max_context']:raise ValueError('Invalid context')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    if args.device=='cpu':
        os.environ.update(CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
    if draft_info and args.device=='cpu':
        import psutil
        combined_cache=sum(args.context*row['kv_bytes_per_token'] if row['kv_bytes_per_token'] else 2*2**30 for row in (info,draft_info))
        if psutil.virtual_memory().available<(info['bytes']+draft_info['bytes'])*2+combined_cache+10*2**30:raise ValueError('Insufficient RAM for main and draft model with protected reserve')
    if args.loader=='unsloth':
        if args.device!='cuda' or (args.adapter and args.quantization!='nf4'):raise ValueError('Native Unsloth adapters require GPU NF4')
        from unsloth import FastLanguageModel
    import torch
    from transformers import AutoTokenizer,AutoModelForCausalLM,TextIteratorStreamer,StoppingCriteria,StoppingCriteriaList
    thread_policy=configure_runtime_threads(torch,args.threads,args.device)
    if args.device=='cuda':
        if not torch.cuda.is_available():raise ValueError('Requested GPU is unavailable')
        free,total=torch.cuda.mem_get_info()
        kv=args.context*(info['kv_bytes_per_token']//2) if info['kv_bytes_per_token'] else 2*2**30
        draft_memory=(draft_info['bytes']+args.context*(draft_info['kv_bytes_per_token']//2 if draft_info['kv_bytes_per_token'] else 1024*1024)) if draft_info else 0
        required=info['bytes']+kv+draft_memory+2*2**30
        if required>min(free-4*2**30,total*.85):
            raise ValueError('GPU memory budget exceeded before loading weights')
    if args.loader=='unsloth':
        model,tokenizer=FastLanguageModel.from_pretrained(model_name=str(args.adapter or args.model),max_seq_length=args.context,
            dtype=torch.bfloat16 if args.adapter else torch.float16,load_in_4bit=args.quantization=='nf4',local_files_only=True,trust_remote_code=False)
        if args.quantization=='nf4':
            quantized=[module.weight for module in model.modules() if getattr(getattr(module,'weight',None),'quant_state',None) is not None]
            if not quantized or not all(weight.device.type=='cuda' and weight.quant_state.quant_type=='nf4' for weight in quantized):raise ValueError('Actual GPU NF4 weights could not be confirmed')
        FastLanguageModel.for_inference(model)
    elif args.loader=='airllm':
        from serve.airllm_runtime import load_cpu_model
        model,tokenizer,airllm_owner=load_cpu_model(Path(__file__).resolve().parent.parent,args.model,args.context,torch)
    elif vision_model:
        from serve.transformers_vision import load_vision
        model,processor=load_vision(args.model,torch,attention)
        tokenizer=processor.tokenizer
    else:
        tokenizer=load_local_tokenizer(args.model)
        model=AutoModelForCausalLM.from_pretrained(str(args.model),local_files_only=True,trust_remote_code=False,
            use_safetensors=True,dtype=torch.float16 if args.device=='cuda' else torch.float32,device_map=args.device,**attention)
    assistant_model=None
    if args.draft_model:
        draft_tokenizer=load_local_tokenizer(args.draft_model)
        if tokenizer.get_vocab()!=draft_tokenizer.get_vocab() or tokenizer.all_special_ids!=draft_tokenizer.all_special_ids:raise ValueError('Draft tokenizer must match the selected model')
        assistant_model=AutoModelForCausalLM.from_pretrained(str(args.draft_model),local_files_only=True,trust_remote_code=False,use_safetensors=True,dtype=model.dtype,device_map=args.device,**attention).eval()
    if args.adapter and args.loader!='unsloth':
        from peft import PeftModel
        model=PeftModel.from_pretrained(model,str(args.adapter),local_files_only=True,is_trainable=False)
    model.eval();lock=threading.Lock()
    if args.telemetry_file:
        def telemetry():
            while True:
                try:
                    row=dict(pid=os.getpid(),sampled_at=time.time(),device=args.device)
                    if args.device=='cuda':
                        row.update(allocated_bytes=torch.cuda.memory_allocated(),reserved_bytes=torch.cuda.memory_reserved(),peak_allocated_bytes=torch.cuda.max_memory_allocated())
                    target=args.telemetry_file;target.parent.mkdir(parents=True,exist_ok=True)
                    temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(row),encoding='utf-8');os.replace(temporary,target)
                except (OSError,RuntimeError):pass
                time.sleep(2)
        threading.Thread(target=telemetry,daemon=True).start()
    class Stop(StoppingCriteria):
        def __init__(self,event):self.event=event
        def __call__(self,*unused,**kw):return self.event.is_set()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*unused):pass
        def reply(self,status,body):
            raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.path=='/v1/models':return self.reply(200,dict(data=[dict(id='optional-model',object='model',owned_by='local',
                max_model_len=info['model_max_context'],active_context_length=args.context,input_modalities=info.get('input_modalities',['text']),native_loader=args.loader,quantization=args.quantization,loader_quantization=args.quantization,checkpoint_quantization=info['checkpoint_quantization'],adapter_loaded=bool(args.adapter),device=args.device,dtype=str(model.dtype),framework='transformers',framework_version=__import__('importlib.metadata',fromlist=['version']).version('transformers'),architecture=info['architecture'],model_type=info['model_type'],attention_implementation=getattr(model.config,'_attn_implementation',None),cache_policy=args.cache,speculative_decoding='local_assistant' if assistant_model is not None else 'off',tool_calling=bool(tool_protocol(tokenizer)),tool_protocol=tool_protocol(tokenizer))]))
            if self.path=='/health':return self.reply(200,dict(status='ready',device=args.device,thread_policy=thread_policy))
            return self.reply(404,dict(error=dict(message='Not found')))
        def do_POST(self):
            if self.path!='/v1/chat/completions':return self.reply(404,dict(error=dict(message='Not found')))
            if not lock.acquire(False):return self.reply(409,dict(error=dict(message='Inference busy')))
            cancelled=threading.Event();worker=None;streaming=False
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=8*1024*1024:raise ValueError('Invalid request size')
                body=json.loads(self.rfile.read(length));messages=body.get('messages') if vision_model else normalize_messages(body.get('messages'))
                if body.get('model')!='optional-model':raise ValueError('Unknown model')
                count=body.get('max_tokens',128)
                if type(count) is not int or not 1<=count<=4096:raise ValueError('Invalid output budget')
                if type(body.get('stream',False)) is not bool:raise ValueError('Invalid stream option')
                if body.get('response_format') or body.get('stop'):raise ValueError('Structured output and custom stop are not supported by this runtime')
                tools=requested_tools(body)
                structured=bool(tool_protocol(tokenizer))
                allowed_names={tool['function']['name'] for tool in tools or []}
                if tools and not tool_protocol(tokenizer):raise ValueError('This tokenizer has no tool-response parser; use a model with a supported tool schema')
                template=body.get('chat_template_kwargs') or {}
                if not isinstance(template,dict) or template.keys()-{'enable_thinking'}:raise ValueError('Unsupported chat template override')
                if 'enable_thinking' in template and type(template['enable_thinking']) is not bool:raise ValueError('Invalid thinking switch')
                if vision_model:
                    if tools or template:raise ValueError('Vision tools and thinking overrides are not enabled')
                    from serve.transformers_vision import prepare_inputs
                    inputs=prepare_inputs(processor,messages,model.device)
                else:
                    prompt=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,tools=tools,**template)
                    inputs=tokenizer(prompt,return_tensors='pt',add_special_tokens=False).to(model.device)
                n=inputs['input_ids'].shape[-1]
                if n==0:raise ValueError('The local tokenizer produced an empty prompt; verify the tokenizer files')
                if n+count>args.context:raise ValueError('Context limit exceeded')
                temp=body.get('temperature',0)
                if type(temp) not in (int,float) or not 0<=temp<=2:raise ValueError('Invalid temperature')
                top_p=body.get('top_p',1)
                if type(top_p) not in (int,float) or not 0<top_p<=1:raise ValueError('Invalid top_p')
                top_k=body.get('top_k')
                if top_k is not None and (type(top_k) is not int or not 0<=top_k<=1000):raise ValueError('Invalid top_k')
                if 'seed' in body:
                    if type(body['seed']) is not int:raise ValueError('Invalid seed')
                    torch.manual_seed(body['seed'])
                options=dict(**inputs,max_new_tokens=count,do_sample=temp>0,stopping_criteria=StoppingCriteriaList([Stop(cancelled)]),
                    pad_token_id=tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id)
                options.update(cache)
                if assistant_model is not None:
                    if temp!=0:raise ValueError('Local draft currently requires temperature 0')
                    options.update(assistant_model=assistant_model)
                if temp>0:options.update(temperature=temp,top_p=top_p)
                if temp>0 and top_k is not None:options['top_k']=top_k
                identity='chatcmpl-'+uuid.uuid4().hex;created=int(time.time());generated={}
                def generate():
                    try:
                        if args.device=='cuda':torch.cuda.synchronize()
                        began=time.perf_counter()
                        with torch.inference_mode():generated['tokens']=model.generate(**options)
                        if args.device=='cuda':torch.cuda.synchronize()
                        generated['generation_ms']=(time.perf_counter()-began)*1000
                    except Exception as error:
                        generated['error']=str(error)
                        if 'streamer' in options:options['streamer'].end()
                if body.get('stream'):
                    streamer=TextIteratorStreamer(tokenizer,skip_prompt=True,skip_special_tokens=True,timeout=60)
                    options['streamer']=streamer;worker=threading.Thread(target=generate);worker.start()
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers();streaming=True
                    def emit(delta,finish=None,usage=None,timings=None):
                        packet=dict(id=identity,object='chat.completion.chunk',created=created,model='optional-model',
                            choices=[dict(index=0,delta=delta,finish_reason=finish)])
                        if usage is not None:packet['usage']=usage
                        if timings is not None:packet['timings']=timings
                        self.wfile.write(('data: '+json.dumps(packet)+'\n\n').encode());self.wfile.flush()
                    parts=[]
                    for text in streamer:
                        parts.append(text)
                        if not structured:emit(dict(content=text))
                    worker.join(timeout=10)
                    if generated.get('error'):raise RuntimeError(generated['error'])
                    if 'tokens' not in generated:raise RuntimeError('Generation did not finish')
                    out=generated['tokens'].shape[-1]-n
                    message=parsed_message(tokenizer,''.join(parts),allowed_names) if structured else None
                    if message:
                        delta={key:value for key,value in message.items() if key!='role'}
                        if delta.get('tool_calls'):delta['tool_calls']=[{**call,'index':index} for index,call in enumerate(delta['tool_calls'])]
                        emit(delta)
                    emit({},'tool_calls' if message and message.get('tool_calls') else 'length' if out==count else 'stop',dict(prompt_tokens=n,completion_tokens=out,total_tokens=n+out),dict(generation_ms=generated['generation_ms'],generation_tokens=out,timing_scope='model.generate_including_prefill'))
                    self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
                else:
                    generate()
                    if generated.get('error'):raise RuntimeError(generated['error'])
                    tokens=generated['tokens'][0,n:];out=len(tokens);text=tokenizer.decode(tokens,skip_special_tokens=True)
                    message=parsed_message(tokenizer,text,allowed_names)
                    self.reply(200,dict(id=identity,object='chat.completion',created=created,model='optional-model',
                        choices=[dict(index=0,message=message,finish_reason='tool_calls' if message.get('tool_calls') else 'length' if out==count else 'stop')],
                        usage=dict(prompt_tokens=n,completion_tokens=out,total_tokens=n+out),timings=dict(generation_ms=generated['generation_ms'],generation_tokens=out,timing_scope='model.generate_including_prefill')))
            except (BrokenPipeError,ConnectionResetError):cancelled.set()
            except Exception as error:
                if not streaming:self.reply(400,dict(error=dict(message=str(error))))
                else:
                    try:self.wfile.write(('data: '+json.dumps(dict(error=dict(message=str(error))))+'\n\n').encode());self.wfile.flush()
                    except (BrokenPipeError,ConnectionResetError):pass
            finally:
                cancelled.set()
                if worker:worker.join()
                lock.release()
    print(json.dumps(dict(runtime='Unsloth native' if args.loader=='unsloth' else 'AirLLM CPU layer streaming' if args.loader=='airllm' else 'Transformers local runtime',device=args.device,context=args.context)),flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
if __name__=='__main__':main()

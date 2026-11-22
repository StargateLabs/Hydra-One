"""Explicit training options shared by dashboard and CPU runner."""
import math
DEFAULTS={'device':'cpu','runner':'trl_cpu','steps':20,'length':128,'rank':2,'alpha':4,'learning_rate':0.001,'accumulation':1,'seed':7,'checkpointing':False,'layer_streaming':False,'save_steps':0,'resume_checkpoint':None}
def training_options(payload):
    unknown=set(payload)-set(DEFAULTS)-{'model','train','validation','output','method'}
    if unknown:raise ValueError('Unsupported training options: '+', '.join(sorted(unknown)))
    options={key:payload.get(key,value) for key,value in DEFAULTS.items()}
    method=payload.get('method','sft')
    if method not in ('sft','dpo','grpo','kto','reward','vlm'):raise ValueError('Unsupported training method')
    if method!='sft':
        if options['device']!='cpu':raise ValueError('Advanced TRL methods are locally verified on CPU only')
        if options['runner']!='trl_cpu' or options['layer_streaming']:raise ValueError('Advanced methods require TRL without layer streaming')
        options['method']=method
    for key,low,high in [('steps',1,1000),('length',16,2048 if method=='vlm' else 512),('rank',1,64),('alpha',1,128),('accumulation',1,32),('seed',0,2147483647),('save_steps',0,1000)]:
        if type(options[key]) is not int or not low<=options[key]<=high:raise ValueError(f'{key} must be an integer in {low}..{high}')
    if options['runner'] not in ('trl_cpu','soup_cpu','soup_native','unsloth_qlora'):raise ValueError('Unsupported training runner')
    if options['runner'] in ('soup_cpu','soup_native') and options['length']<64:raise ValueError('Soup CPU requires at least 64 training tokens')
    if options['device'] not in ('cpu','cuda'):raise ValueError('Unsupported training device')
    if options['runner']=='soup_cpu' and options['device']!='cpu':raise ValueError('Soup GPU is not locally validated')
    if options['runner']=='unsloth_qlora' and options['device']!='cuda':raise ValueError('Native QLoRA requires GPU')
    if type(options['layer_streaming']) is not bool:raise ValueError('layer_streaming must be boolean')
    if options['layer_streaming'] and (options['runner']!='soup_native' or options['device']!='cuda'):raise ValueError('Layer streaming requires selected Soup GPU')
    rate=options['learning_rate']
    if type(rate) not in (int,float) or not math.isfinite(rate) or not 0<rate<=0.01:raise ValueError('learning_rate must be finite and in (0, 0.01]')
    if type(options['checkpointing']) is not bool:raise ValueError('checkpointing must be boolean')
    if options['resume_checkpoint'] is not None and (not isinstance(options['resume_checkpoint'],str) or not options['resume_checkpoint'].strip() or len(options['resume_checkpoint'])>4096):raise ValueError('Invalid resume checkpoint')
    if options['runner'] in ('soup_cpu','soup_native') and not options['layer_streaming'] and (options['save_steps'] or options['resume_checkpoint']):raise ValueError('Soup checkpoint save/resume requires the layer-streaming workflow')
    return options

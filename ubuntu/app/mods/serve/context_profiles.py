"""Conservative FP16 KV estimates; runtime allocation remains authoritative."""
CONTEXTS=(1024,2048,4096,8192,16384,32768,65536,131072,262144,524288,1048576)

def plan(metadata,weights,ram_free,gpu_free=None,*,kv_type='f16',slots=1,cache_ram_mib=1024,checkpoints=8,gpu_total=None,vram_percent=85):
    arch=metadata.get('general.architecture','')
    maximum=metadata.get(arch+'.context_length')
    if type(maximum) is not int or maximum<=0:maximum=None
    layers=metadata.get(arch+'.block_count');heads=metadata.get(arch+'.attention.head_count_kv')
    key=metadata.get(arch+'.attention.key_length');value=metadata.get(arch+'.attention.value_length')
    embedding=metadata.get(arch+'.embedding_length');attention=metadata.get(arch+'.attention.head_count')
    if key is None and type(embedding) is int and type(attention) is int and attention>0:key=embedding//attention
    if value is None:value=key
    known=all(type(v) is int and v>0 for v in (layers,heads,key,value))
    pattern=metadata.get(arch+'.attention.sliding_window_pattern')
    window=metadata.get(arch+'.attention.sliding_window')
    sliding=0
    if known and isinstance(pattern,list) and len(pattern)==layers and type(window) is int and window>0 and all(v in (0,1,False,True) for v in pattern):sliding=sum(bool(v) for v in pattern)
    full_layers=layers-sliding if known else 0
    type_bytes={'f16':2,'q8_0':34/32,'q4_0':18/32}[kv_type]
    bytes_per_token=type_bytes*full_layers*heads*(key+value) if known else None
    swa_bytes=type_bytes*sliding*heads*(key+value)*window if sliding else 0
    checkpoint_bytes=swa_bytes*slots*checkpoints
    cache_bytes=cache_ram_mib*2**20
    budget=gpu_total*vram_percent/100 if gpu_total else None
    options=[]
    choices=set(CONTEXTS)
    if maximum and maximum*slots<=4194304:choices.add(maximum*slots)
    for context in sorted(choices):
        if maximum and context//slots>maximum:continue
        if context//slots<1024:continue
        if not known and context>min(4096,maximum or 4096):continue
        kv=(bytes_per_token or 0)*context+swa_bytes*slots
        ram_need=weights+kv+8*2**30+cache_bytes+checkpoint_bytes+(2**30 if gpu_free is None else 0)
        gpu_need=weights+kv+4*2**30
        mixed=False
        if gpu_free is not None:
            usable=max(0,min(gpu_free-4*2**30,budget if budget is not None else gpu_free-4*2**30))
            spill=max(0,weights+kv+2**30-usable)
            mixed_ram=weights+spill+checkpoint_bytes+cache_bytes+8*2**30
            mixed=usable>=2**30 and ram_free>=mixed_ram
        fits=ram_free>=ram_need and (gpu_free is None or gpu_free>=gpu_need) and (budget is None or weights+kv+2**30<=budget)
        full_gpu=fits
        if not fits and mixed:fits=True;ram_need=mixed_ram
        allocation_capacity=max(0,(gpu_total or gpu_free)-4*2**30) if gpu_free is not None else 0
        if budget is not None:allocation_capacity=min(allocation_capacity,budget)
        gpu_allocation=min(weights+kv+2**30,allocation_capacity) if gpu_free is not None else 0
        options.append(dict(gpu_estimated_alloc_gib=gpu_allocation/2**30,ram_estimated_upper_gib=max(0,ram_need/2**30-8),full_gpu=full_gpu if gpu_free is not None else None,mixed_cpu_gpu=mixed and not full_gpu,context=context,total_context=context,context_per_slot=context//slots,compute_buffers_gib=1,checkpoint_ram_gib=checkpoint_bytes/2**30,cache_ram_gib=cache_bytes/2**30,kv_gib=kv/2**30 if known else None,ram_required_gib=ram_need/2**30,
                            gpu_required_gib=gpu_need/2**30 if gpu_free is not None else None,fits=fits))
    safe=[row['context'] for row in options if row['fits']]
    return dict(model_max_context=maximum,kv_bytes_per_token=bytes_per_token,options=options,
                recommended_context=max(safe) if safe else None,weights_gib=weights/2**30,
                kv_type=kv_type,slots=slots,attention_layers=full_layers,sliding_layers=sliding,vram_percent=vram_percent,gpu_budget_gib=budget/2**30 if budget else None,device='gpu' if gpu_free is not None else 'cpu',ram_free_gib=ram_free/2**30,
                gpu_free_gib=gpu_free/2**30 if gpu_free is not None else None,
                estimate='Weights + typed KV (sliding-window pattern when declared) + 1 GiB compute estimate + safety margins; checkpoint RAM is a conservative bound')

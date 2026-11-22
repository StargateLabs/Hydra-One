"""Call Meta's original conditioned generators using verified local resources."""
import json
import sys
from pathlib import Path

def mert_state_compatibility(state):
    """Torch's weight_norm representation changed; keep every original tensor."""
    result=dict(state)
    for old,new in [('encoder.pos_conv_embed.conv.weight_g','encoder.pos_conv_embed.conv.parametrizations.weight.original0'),('encoder.pos_conv_embed.conv.weight_v','encoder.pos_conv_embed.conv.parametrizations.weight.original1')]:
        if old in result:
            if new in result:raise ValueError('Ambiguous MERT weight normalization state')
            result[new]=result.pop(old)
    return result

def run(request,torch,sf):
    project_root=str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0,project_root)
    from serve.audiocraft_native import model_contract
    folder=Path(request['model_path']);kind=request['task'];model_contract(folder,kind)
    torch.manual_seed(request['seed']);device=request['device']
    if kind=='style':
        from serve.audiocraft_conditioning import style_dependency
        dependency=style_dependency(Path(__file__).resolve().parents[1],verify=True)
        from audiocraft.models import MusicGen
        from transformers import AutoModel
        import inspect
        descriptor=inspect.getattr_static(AutoModel,'from_pretrained');original=AutoModel.from_pretrained
        def load(name,*args,**kwargs):
            if name!='m-a-p/MERT-v1-95M':return original(name,*args,**kwargs)
            state=torch.load(str(Path(dependency['folder'])/'pytorch_model.bin'),map_location='cpu',weights_only=True)
            kwargs.update(state_dict=mert_state_compatibility(state),output_loading_info=True,local_files_only=True)
            loaded,info=original(name,*args,**kwargs)
            if info.get('missing_keys') or info.get('unexpected_keys') or info.get('mismatched_keys') or info.get('error_msgs'):raise ValueError('MERT tensors did not load exactly: '+json.dumps(info))
            return loaded
        AutoModel.from_pretrained=load
        try:model=MusicGen.get_pretrained(str(folder),device=device)
        finally:AutoModel.from_pretrained=descriptor
        model.set_style_conditioner_params(eval_q=request['style_eval_q'],excerpt_length=request['style_excerpt'],ds_factor=request['style_ds_factor'],encodec_n_q=request['style_encodec_n_q'])
        options=dict(duration=request['seconds'],cfg_coef=request['style_cfg_coef'],cfg_coef_beta=request['style_cfg_coef_beta'],temperature=request['temperature'],top_k=request['top_k'],top_p=request['top_p'],use_sampling=request['do_sample'])
        model.set_generation_params(**options)
        wav,rate=sf.read(request['source_path'],dtype='float32',always_2d=True)
        with torch.inference_mode():audio=model.generate_with_chroma([request['prompt'] or None],torch.from_numpy(wav.T).unsqueeze(0).to(device),rate)
        options.update({k:request[k] for k in ('style_eval_q','style_excerpt','style_ds_factor','style_encodec_n_q')})
        options['mert_tensor_load']='all original tensors loaded; weight_norm keys mapped without changing values'
    else:
        from audiocraft.models import JASCO
        model=JASCO.get_pretrained(str(folder),device=device,chords_mapping_path=str(folder/'chord_to_index_mapping.pkl'))
        options=dict(cfg_coef_all=request['jasco_cfg_all'],cfg_coef_txt=request['jasco_cfg_text'],euler=request['jasco_euler'],euler_steps=request['jasco_euler_steps'],ode_rtol=request['jasco_ode_rtol'],ode_atol=request['jasco_ode_atol'])
        model.set_generation_params(**options);conditions={'chords':[tuple(v) for v in request['chords']] or None}
        if request.get('source_path'):
            wav,rate=sf.read(request['source_path'],dtype='float32',always_2d=True);conditions.update(drums_wav=torch.from_numpy(wav.T).to(device),drums_sample_rate=rate)
        if request.get('melody_salience') is not None:conditions['melody_salience_matrix']=torch.tensor(request['melody_salience'],device=device)
        with torch.inference_mode():audio=model.generate_music([request['prompt']],**conditions)
    return audio[0].float().cpu().numpy().T,model.sample_rate,options

"""Offline subprocess entry point for local MusicGen and OpenVoice conversion."""
import argparse, hashlib, json, os, sys, time
from pathlib import Path

def music_generation_options(request):
    """Omitted dashboard options retain the installed model's generation defaults."""
    return {key:request[key] for key in ('temperature','top_k','top_p','guidance_scale','do_sample') if key in request}

def music_input_arguments(request,processor,model,soundfile):
    """Prepare native processor inputs; keep the source clip and output budget explicit."""
    if request.get('music_mode','text')=='unconditional':
        return model.get_unconditional_inputs(num_samples=1),request['seconds']
    arguments={'text':[request['prompt']],'padding':True,'return_tensors':'pt'}
    remaining=request['seconds']
    if request.get('music_mode')=='melody':
        samples,rate=soundfile.read(request['music_prompt_path'],dtype='float32',always_2d=True)
        arguments.update(audio=samples.mean(axis=1),sampling_rate=rate)
    if request.get('music_mode')=='continuation':
        import math
        import numpy as np
        from scipy.signal import resample_poly
        samples,rate=soundfile.read(request['music_prompt_path'],dtype='float32',always_2d=True)
        target_rate=processor.feature_extractor.sampling_rate
        channels=model.config.audio_encoder.audio_channels
        if channels==1:samples=samples.mean(axis=1)
        elif channels==2:samples=np.repeat(samples,2,axis=1) if samples.shape[1]==1 else samples;samples=samples.T
        else:raise ValueError('Unsupported MusicGen input channels')
        if rate!=target_rate:
            divisor=math.gcd(rate,target_rate)
            samples=resample_poly(samples,target_rate//divisor,rate//divisor,axis=-1)
        duration=samples.shape[-1]/target_rate
        remaining=request['seconds']-duration
        if remaining+1/target_rate<0.1:raise ValueError('Music continuation exceeds the total duration budget')
        arguments.update(audio=samples,sampling_rate=target_rate)
    return processor(**arguments),remaining

def run(request):
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1')
    import numpy as np
    import torch
    import soundfile as sf
    torch.set_num_threads(2)
    device=request['device']
    if device not in ('cpu','cuda') or (device=='cuda' and not torch.cuda.is_available()):raise ValueError('Requested device is unavailable; CPU fallback is not implicit')
    model_path=Path(request['model_path'])
    if not model_path.is_dir():raise ValueError('Local model directory is missing')
    import psutil
    weight_bytes=sum(p.stat().st_size for p in model_path.rglob('*') if p.is_file() and p.suffix in ('.pth','.bin','.safetensors','.pt') and (request['task']!='codec' or p.name=='compression_state_dict.bin') and (request['task']!='mbd' or p.name=='mbd_comp_'+str(request['mbd_codebooks'])+'.pt'))
    required=weight_bytes*3+1024**3
    if psutil.virtual_memory().available<required:raise ValueError('Insufficient available RAM for local audio generation')
    if device=='cuda':
        free,_=torch.cuda.mem_get_info()
        if free<required+1024**3:raise ValueError('Insufficient free GPU memory including protected reserve')
    model_files={}
    for path in sorted(model_path.glob('*')):
        if request['task']=='mbd' and path.name not in ('mbd_comp_'+str(request['mbd_codebooks'])+'.pt','audiogen.json','provenance.json'):continue
        if path.is_file() and path.suffix in ('.pth','.bin','.safetensors','.pt','.json','.pkl') and (request['task']!='codec' or path.name in ('compression_state_dict.bin','audiogen.json','provenance.json')):
            digest=hashlib.sha256()
            with path.open('rb') as stream:
                while chunk:=stream.read(1024*1024):digest.update(chunk)
            model_files[path.name]=digest.hexdigest()
    provenance=json.loads((model_path/'provenance.json').read_text()) if (model_path/'provenance.json').is_file() else {}
    for key,filename in (('checkpoint_sha256','checkpoint.pth'),('model_sha256','model.safetensors')):
        if provenance.get(key) and provenance[key]!=model_files.get(filename):raise RuntimeError('Model integrity check failed')
    output=Path(request['output_path']);temporary=output.with_suffix('.partial.wav');started=time.monotonic()
    try:
        if request['task'] in ('style','jasco'):
            from audiocraft_conditioned import run as run_conditioned
            manifest=json.loads((model_path/'audiogen.json').read_text(encoding='utf-8'))
            for name in ('state_dict.bin','compression_state_dict.bin')+ (('chord_to_index_mapping.pkl',) if request['task']=='jasco' else ()):
                if manifest.get('sha256',{}).get(name)!=model_files.get(name):raise ValueError('Pesi AudioCraft diversi dalla revisione verificata')
            samples,rate,options=run_conditioned(request,torch,sf);engine='audiocraft-'+request['task']
        elif request['task']=='music':
            from transformers import AutoProcessor, MusicgenForConditionalGeneration
            processor=AutoProcessor.from_pretrained(str(model_path),local_files_only=True,trust_remote_code=False)
            model_class=MusicgenForConditionalGeneration
            if json.loads((model_path/'config.json').read_text(encoding='utf-8')).get('model_type')=='musicgen_melody':
                from transformers import MusicgenMelodyForConditionalGeneration
                model_class=MusicgenMelodyForConditionalGeneration
            model=model_class.from_pretrained(str(model_path),local_files_only=True,trust_remote_code=False,use_safetensors=True).to(device)
            torch.manual_seed(request['seed'])
            inputs,remaining=music_input_arguments(request,processor,model,sf)
            inputs=inputs.to(device)
            rate=model.config.audio_encoder.sampling_rate
            options=music_generation_options(request);options.setdefault('do_sample',True)
            with torch.inference_mode():audio=model.generate(**inputs,max_new_tokens=max(1,int(remaining*model.config.audio_encoder.frame_rate)),**options)
            samples=audio[0].float().cpu().numpy().T
            samples=samples[:int(rate*request['seconds'])];engine='transformers-musicgen-melody' if model_class.__name__=='MusicgenMelodyForConditionalGeneration' else 'transformers-musicgen'
        elif request['task']=='effects':
            from audiocraft.models import AudioGen
            manifest=json.loads((model_path/'audiogen.json').read_text(encoding='utf-8'))
            if manifest.get('repository')!='facebook/audiogen-medium':raise ValueError('Use the official AudioGen publication')
            for name in ('state_dict.bin','compression_state_dict.bin'):
                if manifest.get('sha256',{}).get(name)!=model_files.get(name):raise ValueError('AudioGen weights require pinned original hashes')
            model=AudioGen.get_pretrained(str(model_path),device=device)
            torch.manual_seed(request['seed'])
            options={'duration':request['seconds']}
            for source,target in [('do_sample','use_sampling'),('temperature','temperature'),('top_k','top_k'),('top_p','top_p'),('guidance_scale','cfg_coef')]:
                if source in request:options[target]=request[source]
            for key in ('two_step_cfg','extend_stride'):
                if key in request:options[key]=request[key]
            if options.get('extend_stride',2)>=model.max_duration:raise ValueError('AudioGen stride must be below native model maximum duration')
            model.set_generation_params(**options)
            mode=request.get('music_mode','text')
            with torch.inference_mode():
                if mode=='unconditional':audio=model.generate_unconditional(1)
                elif mode=='continuation':
                    samples,input_rate=sf.read(request['music_prompt_path'],dtype='float32',always_2d=True)
                    prompt=torch.from_numpy(samples.T).unsqueeze(0).to(device)
                    audio=model.generate_continuation(prompt,input_rate,descriptions=[request['prompt']] if request['prompt'].strip() else None)
                else:audio=model.generate([request['prompt']])
            samples=audio[0].float().cpu().numpy().T;rate=model.sample_rate;engine='audiocraft-audiogen'
        elif request['task']=='magnet':
            from audiocraft.models import MAGNeT
            manifest=json.loads((model_path/'audiogen.json').read_text(encoding='utf-8'))
            for name in ('state_dict.bin','compression_state_dict.bin'):
                if manifest.get('sha256',{}).get(name)!=model_files.get(name):raise ValueError('Original MAGNeT hash required')
            model=MAGNeT.get_pretrained(str(model_path),device=device);torch.manual_seed(request['seed'])
            options={key:request[key] for key in ('top_k','top_p','temperature','min_cfg_coef','max_cfg_coef','decoding_steps','span_arrangement')};options['use_sampling']=request['do_sample']
            model.set_generation_params(**options)
            with torch.inference_mode():audio=model.generate([request['prompt']])
            samples=audio[0].float().cpu().numpy().T;rate=model.sample_rate;engine='audiocraft-magnet'
        elif request['task']=='mbd':
            from audiocraft_mbd import run as run_mbd
            samples,rate,options=run_mbd(request,torch,sf);engine='audiocraft-multiband-diffusion'
        elif request['task']=='watermark':
            from audiocraft.models.loaders import load_audioseal_models
            from audiocraft.data.audio_utils import convert_audio
            manifest=json.loads((model_path/'audiogen.json').read_text(encoding='utf-8'))
            for name in ('generator_base.pth','detector_base.pth','base.yaml'):
                with (model_path/name).open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
                if digest!=manifest.get('sha256',{}).get(name):raise ValueError('Original AudioSeal asset hash required')
            model=load_audioseal_models(str(model_path),filename='base',device=device)
            waveform,input_rate=sf.read(request['source_path'],dtype='float32',always_2d=True)
            x=convert_audio(torch.from_numpy(waveform.T),input_rate,16000,1).unsqueeze(0).to(device)
            action=request['watermark_action'];message=request.get('watermark_message','')
            if message and len(message)!=model.nbits:raise ValueError('This AudioSeal model requires '+str(model.nbits)+' message bits')
            bits=torch.tensor([[int(bit) for bit in message]],device=device) if message else None
            with torch.inference_mode():
                y=x+request['watermark_alpha']*model.get_watermark(x,message=bits,sample_rate=16000) if action in ('embed','both') else x
                detected=model.detect_watermark(y) if action in ('detect','both') else None
            watermark_report={'action':action,'alpha':request['watermark_alpha'] if action!='detect' else None,'nbits':model.nbits,'detection_probability':float(detected[0,1].mean().item()) if detected is not None else None,'decoded_message':''.join(str(int(value)) for value in (detected[0,2:].mean(dim=-1)>.5).int().cpu().tolist()) if detected is not None else None,'input_preserved':True,'output_sample_rate':16000,'output_channels':1}
            options=watermark_report;samples=y[0].float().cpu().numpy().T;rate=16000;engine='audiocraft-audioseal'
        elif request['task']=='codec':
            from audiocraft.models.loaders import load_compression_model
            from audiocraft.data.audio_utils import convert_audio
            from safetensors.torch import save_file
            manifest=json.loads((model_path/'audiogen.json').read_text(encoding='utf-8'))
            if manifest.get('sha256',{}).get('compression_state_dict.bin')!=model_files.get('compression_state_dict.bin'):raise ValueError('Original codec hash required')
            codec=load_compression_model(str(model_path),device=device)
            if request.get('codec_codebooks'):
                if request['codec_codebooks']>codec.total_codebooks:raise ValueError('Codebook count exceeds this codec')
                codec.set_num_codebooks(request['codec_codebooks'])
            source,source_rate=sf.read(request['source_path'],dtype='float32',always_2d=True)
            wave=torch.from_numpy(source.T).unsqueeze(0).to(device)
            wave=convert_audio(wave,source_rate,codec.sample_rate,codec.channels)
            with torch.inference_mode():
                codes,scale=codec.encode(wave);audio=codec.decode(codes,scale)[...,:wave.shape[-1]]
            tensors={'codes':codes.detach().cpu().contiguous()}
            if scale is not None:tensors['scale']=scale.detach().cpu().contiguous()
            save_file(tensors,str(output.parent/'codes.safetensors'),metadata={'sample_rate':str(codec.sample_rate),'channels':str(codec.channels),'original_samples':str(wave.shape[-1])})
            samples=audio[0].float().cpu().numpy().T;rate=codec.sample_rate;engine='audiocraft-encodec'
            options={'codebooks':codec.num_codebooks,'total_codebooks':codec.total_codebooks,'cardinality':codec.cardinality,'frame_rate':codec.frame_rate}
        elif request['task']=='voice_conversion':
            from openvoice.api import ToneColorConverter, OpenVoiceBaseClass
            # Upstream forwards enable_watermark to a base that rejects it. Initialize
            # the same official converter without loading its optional network model.
            converter=ToneColorConverter.__new__(ToneColorConverter)
            OpenVoiceBaseClass.__init__(converter,str(model_path/'config.json'),device=device)
            converter.watermark_model=None;converter.version=getattr(converter.hps,'_version_','v1')
            converter.load_ckpt(str(model_path/'checkpoint.pth'))
            source=converter.extract_se([request['source_path']]);target=converter.extract_se([request['reference_path']])
            samples=converter.convert(request['source_path'],src_se=source,tgt_se=target,output_path=None,message=None,**({'tau':request['tau']} if 'tau' in request else {}))
            rate=converter.hps.data.sampling_rate;engine='openvoice-tone-color-converter'
        else:raise ValueError('Unsupported generation task')
        if not np.isfinite(samples).all() or samples.size==0 or not np.any(samples):raise RuntimeError('Model returned empty, non-finite or silent audio')
        sf.write(str(temporary),np.clip(samples,-1,1),rate,subtype='PCM_16')
        os.replace(temporary,output)
        report={'task':request['task'],'device':device,'engine':engine,'sample_rate':rate,'audio_seconds':len(samples)/rate,'elapsed_seconds':time.monotonic()-started,'offline':True,'model_files':model_files,'license':provenance.get('license'),'native_options':music_generation_options(request) if request['task']=='music' else options if request['task'] in ('effects','codec','magnet','watermark','mbd','style','jasco') else ({'tau':request['tau']} if 'tau' in request else {}),'watermark':watermark_report if request['task']=='watermark' else False if request['task']=='voice_conversion' else None}
        if request['task'] in ('music','effects'):report.update(music_mode=request.get('music_mode','text'),music_prompt_seconds=request.get('music_prompt_seconds',0),music_prompt_sha256=request.get('music_prompt_path_sha256'))
        if request['task']=='codec':
            codes_path=output.parent/'codes.safetensors';report['codec']={'file':codes_path.name,'bytes':codes_path.stat().st_size,'sha256':hashlib.sha256(codes_path.read_bytes()).hexdigest(),**options}
        target=Path(request['report_path']);partial=target.with_suffix('.partial.json');partial.write_text(json.dumps(report),encoding='utf-8');os.replace(partial,target)
    finally:temporary.unlink(missing_ok=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True);args=parser.parse_args()
    if args.request.stat().st_size>512*1024:raise ValueError('Request too large')
    run(json.loads(args.request.read_text(encoding='utf-8')))


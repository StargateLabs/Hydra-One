"""Whitelisted flags exposed by the installed Whisper server help."""
import math
def decoding_options(payload):
    prompt=payload.get('initial_prompt','')
    if not isinstance(prompt,str) or len(prompt)>1000 or '\x00' in prompt:
        raise ValueError('Whisper initial prompt must contain at most 1000 characters')
    result={'initial_prompt':prompt}
    for key,default,low,high in [('best_of',2,1,16),('beam_size',-1,-1,16),('max_segment_length',0,0,500)]:
        value=payload.get(key,default)
        if type(value) is not int or not low<=value<=high or (key=='beam_size' and value==0):
            raise ValueError('Invalid Whisper '+key)
        result[key]=value
    for key in ['split_on_word','suppress_non_speech','diarize','tinydiarize']:
        value=payload.get(key,False)
        if type(value) is not bool:raise ValueError('Invalid Whisper '+key)
        result[key]=value
    dtw=payload.get('dtw',False)
    if type(dtw) is not bool:raise ValueError('Invalid Whisper dtw')
    result['dtw']=dtw
    if dtw:
        model=payload.get('dtw_model')
        if not isinstance(model,str) or not model or len(model)>4096:raise ValueError('Choose an installed DTW timestamp model')
        result['dtw_model']=model
    if 'word_thold' in payload:
        threshold=payload['word_thold']
        if type(threshold) not in (int,float) or not math.isfinite(threshold) or not 0<=threshold<=1:raise ValueError('Invalid Whisper word_thold')
        result['word_thold']=float(threshold)
    vad=payload.get('vad',False)
    if type(vad) is not bool:raise ValueError('Invalid Whisper vad')
    result['vad']=vad
    if vad:
        model=payload.get('vad_model')
        if not isinstance(model,str) or not model or len(model)>4096:raise ValueError('Choose an installed VAD model')
        result['vad_model']=model
        for key,default,low,high,integer in [('vad_threshold',.5,0,1,False),('vad_min_speech_ms',250,0,300000,True),
                ('vad_min_silence_ms',100,0,300000,True),('vad_speech_pad_ms',30,0,5000,True),('vad_overlap_s',.1,0,1,False)]:
            value=payload.get(key,default)
            if type(value) not in ((int,) if integer else (int,float)) or not math.isfinite(value) or not low<=value<=high:raise ValueError('Invalid Whisper '+key)
            result[key]=value
        maximum=payload.get('vad_max_speech_s')
        if maximum is not None:
            if type(maximum) not in (int,float) or not math.isfinite(maximum) or not .1<=maximum<=300:raise ValueError('Invalid Whisper vad_max_speech_s')
            result['vad_max_speech_s']=maximum
    return result

def decoding_flags(options):
    flags=['--best-of',str(options['best_of']),'--beam-size',str(options['beam_size']),'--max-len',str(options['max_segment_length'])]
    if options['initial_prompt']:flags+=['--prompt',options['initial_prompt']]
    if options['split_on_word']:flags+=['--split-on-word']
    if options['suppress_non_speech']:flags+=['--suppress-nst']
    if options.get('diarize'):flags+=['--diarize']
    if options.get('tinydiarize'):flags+=['--tinydiarize']
    if options.get('dtw'):flags+=['--dtw',options['dtw_model']]
    if 'word_thold' in options:flags+=['--word-thold',str(options['word_thold'])]
    if options.get('vad'):
        flags+=['--vad','--vad-model',options['vad_model']]
        for key,flag in [('vad_threshold','--vad-threshold'),('vad_min_speech_ms','--vad-min-speech-duration-ms'),
                ('vad_min_silence_ms','--vad-min-silence-duration-ms'),('vad_max_speech_s','--vad-max-speech-duration-s'),
                ('vad_speech_pad_ms','--vad-speech-pad-ms'),('vad_overlap_s','--vad-samples-overlap')]:
            if key in options:flags+=[flag,str(options[key])]
    return flags

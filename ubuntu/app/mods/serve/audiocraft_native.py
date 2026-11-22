"""Contracts for original MusicGen-Style and JASCO; no inference reimplementation."""
import json,math,re,wave
from pathlib import Path

REPOSITORIES={'style':('facebook/musicgen-style',),'jasco':('facebook/jasco-chords-drums-400M','facebook/jasco-chords-drums-1B','facebook/jasco-chords-drums-melody-400M','facebook/jasco-chords-drums-melody-1B')}

def model_contract(folder,kind):
    folder=Path(folder);manifest=json.loads((folder/'audiogen.json').read_text(encoding='utf-8'))
    if manifest.get('repository') not in REPOSITORIES[kind]:raise ValueError('Usa i pesi originali Meta per '+kind)
    names=['state_dict.bin','compression_state_dict.bin']+(['chord_to_index_mapping.pkl'] if kind=='jasco' else [])
    if any(not (folder/name).is_file() or (folder/name).is_symlink() or not re.fullmatch('[a-f0-9]{64}',manifest.get('sha256',{}).get(name,'')) for name in names):raise ValueError('Pesi o risorse originali AudioCraft mancanti o privi di provenienza')
    return manifest

def validate_options(kind,payload,reference):
    prompt=payload.get('prompt','');seed=payload.get('seed',0)
    if not isinstance(prompt,str) or len(prompt)>1000 or (kind=='jasco' and not prompt.strip()):raise ValueError('Descrizione musicale: massimo 1000 caratteri')
    if type(seed) is not int or not 0<=seed<=2147483647:raise ValueError('Seed intero da 0 a 2147483647')
    result=dict(prompt=prompt,seed=seed)
    def number(key,default,low,high,integer=False):
        value=payload.get(key,default)
        if type(value) not in ((int,) if integer else (int,float)) or not math.isfinite(value) or not low<=value<=high:raise ValueError('Parametro AudioCraft non valido: '+key)
        result[key]=value;return value
    if kind=='style':
        audio=reference(payload.get('source_path'),minimum_seconds=1.5)
        with wave.open(str(audio)) as clip:duration=clip.getnframes()/clip.getframerate()
        excerpt=number('style_excerpt',3.,1.5,4.5)
        if excerpt>duration:raise ValueError('L’estratto di stile supera la durata dell’audio scelto')
        number('seconds',5,1,30);number('style_eval_q',3,1,6,True);number('style_ds_factor',15,1,32,True)
        number('style_encodec_n_q',4,1,8,True);number('style_cfg_coef',3.,0,20);number('style_cfg_coef_beta',5.,0,20)
        for key,default,low,high,integer in [('temperature',1.,.01,5,False),('top_k',250,0,4096,True),('top_p',0.,0,1,False)]:number(key,default,low,high,integer)
        sampling=payload.get('do_sample',True)
        if type(sampling) is not bool:raise ValueError('Campionamento AudioCraft non valido')
        result.update(source_path=str(audio),do_sample=sampling)
    elif kind=='jasco':
        chords=payload.get('chords',[])
        if not isinstance(chords,list) or len(chords)>128:raise ValueError('Accordi: elenco di massimo 128 coppie accordo/secondi')
        previous=-1
        for chord in chords:
            if not isinstance(chord,(list,tuple)) or len(chord)!=2 or not isinstance(chord[0],str) or not re.fullmatch(r'[A-Za-z0-9#b:+/()_-]{1,24}',chord[0]) or type(chord[1]) not in (int,float) or not math.isfinite(chord[1]) or not 0<=chord[1]<10 or chord[1]<=previous:raise ValueError('Accordi ordinati per inizio, da 0 a meno di 10 secondi')
            previous=chord[1]
        result.update(chords=chords,seconds=10)
        if payload.get('source_path'):result['source_path']=str(reference(payload['source_path']))
        for key,default,low,high in [('jasco_cfg_all',5.,0,20),('jasco_cfg_text',0.,0,20),('jasco_ode_rtol',1e-5,1e-7,.01),('jasco_ode_atol',1e-5,1e-7,.01)]:number(key,default,low,high)
        number('jasco_euler_steps',100,1,1000,True);euler=payload.get('jasco_euler',False)
        if type(euler) is not bool:raise ValueError('Selettore del solver JASCO non valido')
        result['jasco_euler']=euler
        melody=payload.get('melody_salience')
        if melody is not None:
            if not isinstance(melody,list) or len(melody)!=53 or any(not isinstance(row,list) or len(row)!=500 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in row) for row in melody):raise ValueError('Melodia JASCO: matrice 53 × 500, valori da 0 a 1')
            result['melody_salience']=melody
    else:raise ValueError('Famiglia AudioCraft non supportata')
    return result

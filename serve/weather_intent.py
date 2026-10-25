"""A narrow deterministic weather route for models that ignore tool calls."""
import json
import re
import time
import uuid

def intent(messages):
    text=next((m.get('content') for m in reversed(messages) if m.get('role')=='user'),None)
    if not isinstance(text,str):return None
    if re.search(r'\b(api|docs|documentazione|documentation|codice|tutorial)\b',text,re.I) and not re.search(r'che tempo',text,re.I):return None
    if not re.search(r'\b(meteo|che tempo|weather|forecast)\b',text,re.I):
        assistant=next((m.get('content','') for m in reversed(messages[:-1]) if m.get('role')=='assistant'),'')
        previous=next((m.get('content','') for m in reversed(messages[:-1]) if m.get('role')=='user'),'')
        if not isinstance(assistant,str) or not re.search(r'(quale citt|which city)',assistant,re.I) or not re.search(r'\b(meteo|che tempo|weather|forecast)\b',str(previous),re.I) or len(text)>100:return None
        day='tomorrow' if re.search(r'\b(domani|tomorrow)\b',str(previous),re.I) else 'today'
        text='meteo '+day+' '+(text if re.search(r'\b(?:a|in)\s+',text,re.I) else 'a '+text)

    match=re.search(r'\b(?:a|in)\s+([^?!.;\n]+)',text,re.I) or re.search(r'\b(?:per|for)\s+([^?!.;\n]+)',text,re.I)
    if not match:return None
    location=match[1].strip()
    # Don't infer a place from unrelated text or a missing location.
    if len(location)>100:return None
    date='tomorrow' if re.search(r'\b(domani|tomorrow)\b',text,re.I) else 'today'
    explicit=re.search(r'\b\d{4}-\d{2}-\d{2}\b',text)
    if explicit:date=explicit[0];location=location.replace(date,'').strip(' ,')
    location=re.sub(r'\b(domani|oggi|tomorrow|today)\b','',location,flags=re.I).strip()
    city=location.split(',')[0].strip()
    if not city:return None
    args={'city':city,'date':date}
    if re.search(r'\b(italia|italy)\b',location,re.I):args['country_code']='IT'
    return args

def run(hub,tool,args,model,cancel,english=False):
    identity='weather_'+uuid.uuid4().hex[:12]
    base=dict(id='chatcmpl-'+uuid.uuid4().hex,created=int(time.time()),model=model,object='chat.completion.chunk')
    def event(delta=None,finish=None,**extra):
        return {**base,'choices':[dict(index=0,delta=delta or {},finish_reason=finish)],**extra}
    yield event(strata_mcp=dict(event='call',id=identity,name=tool,arguments=args,round=1))
    result=hub.call(tool,args,cancel)
    yield event(strata_mcp={'event':'result','id':identity,**{k:result[k] for k in ('ok','text','chars','truncated','ms')}})
    if cancel.is_set():return
    if result['ok']:
        data=json.loads(result['text'])
        text=(f"**{data['city']} · {data['date']}**\n\n"
              f"{data['conditions'].capitalize()}. Temperature tra **{data['temperature_min_c']} e {data['temperature_max_c']} °C**. "
              f"Probabilità di pioggia **{data['rain_probability_percent']}%**, precipitazioni {data['precipitation_mm']} mm. "
              f"Vento massimo {data['wind_max_kmh']} km/h.\n\n"
              f"[Fonte: Open-Meteo]({data['source_url']}). Previsione aggiornata, soggetta a variazioni.")
        if english:
            conditions={0:'clear',1:'mainly clear',2:'partly cloudy',3:'overcast',45:'fog',48:'rime fog',51:'light drizzle',53:'drizzle',55:'heavy drizzle',61:'light rain',63:'rain',65:'heavy rain',71:'light snow',73:'snow',75:'heavy snow',80:'light showers',81:'showers',82:'heavy showers',95:'thunderstorms',96:'thunderstorms with hail',99:'severe thunderstorms with hail'}
            text=(f"**{data['city']} · {data['date']}**\n\n{conditions.get(data.get('weather_code'),'Weather code '+str(data.get('weather_code')))}. "
                  f"Temperatures **{data['temperature_min_c']}–{data['temperature_max_c']} °C**. Rain probability **{data['rain_probability_percent']}%**, precipitation {data['precipitation_mm']} mm. Maximum wind {data['wind_max_kmh']} km/h.\n\n[Source: Open-Meteo]({data['source_url']}). Forecasts may change.")
    else:text='Non riesco a ottenere una previsione verificata per questa località. Specifica città e paese oppure riprova. Dettaglio: '+result['text'][:250]
    yield event({'content':text},strata_execution='tool')
    yield event(finish='stop',usage=dict(prompt_tokens=0,completion_tokens=0,total_tokens=0),strata_execution='tool')

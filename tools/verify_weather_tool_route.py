"""Real city forecast through the existing MCP route; do not run model inference."""
import json,time,urllib.request
from pathlib import Path
BASE='http://127.0.0.1:8088'
def call(path,body=None):
    req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','Origin':BASE})
    with urllib.request.urlopen(req,timeout=65) as response:return json.load(response)
def main():
    from serve.weather_intent import intent
    prompt='Che tempo fa domani a Caserta, Italia?'
    assert intent([{'role':'user','content':prompt}])=={'city':'Caserta','date':'tomorrow','country_code':'IT'}
    deadline=time.monotonic()+30
    while True:
        state=call('/inference-backends')
        if not state.get('busy'):break
        if time.monotonic()>deadline:raise RuntimeError('Existing model request is still running; no diagnostic request sent')
        time.sleep(.5)
    model=state.get('public_model') if state['status']=='ready' else call('/v1/models')['data'][0]['id']
    response=call('/v1/chat/completions',{'model':model,'messages':[{'role':'user','content':prompt}],'max_tokens':16,'stream':False,'strata_mcp':True,'strata_web':True,'strata_locale':'it'})
    message=response['choices'][0]['message'];events=message.get('strata_mcp',[])
    assert any(event.get('event')=='call' and event.get('name','').endswith('__weather_forecast') for event in events)
    assert any(event.get('event')=='result' and event.get('ok') for event in events)
    assert response['usage']['completion_tokens']==0
    assert 'Caserta' in message['content'] and 'Open-Meteo' in message['content']
    report={'scope':'Actual MCP forecast via deterministic tool-only chat route, no LLM/GPU generation; operational model preserved','model':model,'response':response,'completed_at':time.time()}
    Path('output/verification/weather-tool-route-real.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print('Real city forecast, source and MCP result passed; zero generated model tokens')
if __name__=='__main__':main()

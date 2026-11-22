"""Explicit city-based forecasts; no inferred user location."""
import json
import urllib.request
import urllib.parse
from datetime import datetime,timedelta
from datetime import timezone as utc_timezone

def get_json(url):
    with urllib.request.urlopen(url,timeout=15) as response:
        return json.loads(response.read(512000))

def forecast(arguments):
    city=arguments.get('city')
    if not isinstance(city,str) or not 2<=len(city.strip())<=120:raise ValueError('Indica la città della previsione')
    geourl='https://geocoding-api.open-meteo.com/v1/search?'+urllib.parse.urlencode(dict(name=city.strip(),count=5,language='it',format='json'))
    places=get_json(geourl).get('results') or []
    country=arguments.get('country_code')
    if country:
        places=[p for p in places if p.get('country_code','').upper()==str(country).upper()]
    if not places:raise ValueError('Località non trovata: specifica città e paese')
    place=places[0];timezone=place.get('timezone') or 'Europe/Rome'
    clock=get_json('https://api.open-meteo.com/v1/forecast?'+urllib.parse.urlencode(dict(latitude=place['latitude'],longitude=place['longitude'],timezone=timezone,daily='weather_code',forecast_days=1)))
    today=datetime.strptime(clock['daily']['time'][0],'%Y-%m-%d').date()
    date=arguments.get('date') or 'tomorrow'
    if date in ('tomorrow','domani'):target=today+timedelta(days=1)
    elif date in ('today','oggi'):target=today
    else:target=datetime.strptime(date,'%Y-%m-%d').date()
    if not today<=target<=today+timedelta(days=6):raise ValueError('Scegli una data nei prossimi sette giorni')
    params=dict(latitude=place['latitude'],longitude=place['longitude'],timezone=timezone,
        start_date=target.isoformat(),end_date=target.isoformat(),
        daily='weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max')
    url='https://api.open-meteo.com/v1/forecast?'+urllib.parse.urlencode(params)
    data=get_json(url);daily=data['daily']
    if daily.get('time')!=[target.isoformat()]:raise ValueError('Data della previsione non corrispondente')
    code=daily['weather_code'][0]
    conditions={0:'sereno',1:'prevalentemente sereno',2:'parzialmente nuvoloso',3:'coperto',45:'nebbia',48:'nebbia con brina',
        51:'pioviggine debole',53:'pioviggine',55:'pioviggine intensa',61:'pioggia debole',63:'pioggia',65:'pioggia intensa',
        71:'neve debole',73:'neve',75:'neve intensa',80:'rovesci deboli',81:'rovesci',82:'rovesci intensi',95:'temporali',96:'temporali con grandine',99:'temporali con grandine intensa'}
    return dict(city=place['name'],region=place.get('admin1'),country=place.get('country'),timezone=timezone,date=target.isoformat(),
        retrieved_at=datetime.now(utc_timezone.utc).isoformat(),conditions=conditions.get(code,'codice WMO '+str(code)),weather_code=code,
        temperature_min_c=daily['temperature_2m_min'][0],temperature_max_c=daily['temperature_2m_max'][0],
        rain_probability_percent=daily['precipitation_probability_max'][0],precipitation_mm=daily['precipitation_sum'][0],
        wind_max_kmh=daily['wind_speed_10m_max'][0],source='Open-Meteo',source_url=url,
        note='Previsione, non certezza. Località restituita dalla geocodifica: verificarla nella risposta.')

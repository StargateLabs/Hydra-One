import unittest
from unittest.mock import patch
from serve.weather_tools import forecast

class WeatherTests(unittest.TestCase):
 def test_missing_city(self):
  with self.assertRaises(ValueError):forecast({})
 def test_tomorrow_uses_city_date(self):
  responses=[{'results':[{'name':'Vercelli','latitude':45,'longitude':8,'country_code':'IT','timezone':'Europe/Rome'}]},
   {'daily':{'time':['2026-10-10']}}, {'daily':{'time':['2026-10-11'],'weather_code':[3],'temperature_2m_min':[10],'temperature_2m_max':[20],'precipitation_probability_max':[30],'precipitation_sum':[1],'wind_speed_10m_max':[12]}}]
  with patch('serve.weather_tools.get_json',side_effect=responses):
   result=forecast({'city':'Vercelli','date':'tomorrow','country_code':'IT'})
  self.assertEqual(result['date'],'2026-10-11');self.assertEqual(result['rain_probability_percent'],30);self.assertIn('start_date=2026-10-11',result['source_url'])
 def test_out_of_range_rejected(self):
  with patch('serve.weather_tools.get_json',side_effect=[{'results':[{'name':'X','latitude':1,'longitude':1}]},{'daily':{'time':['2026-10-10']}}]):
   with self.assertRaises(ValueError):forecast({'city':'Test','date':'2026-12-01'})
class IntentTests(unittest.TestCase):
 def test_city_and_day(self):
  from serve.weather_intent import intent
  for text in ['Che tempo fa domani a Vercelli, Italia?','Meteo per domani a Vercelli, Italia?']:
   self.assertEqual(intent([{'role':'user','content':text}]),{'city':'Vercelli','date':'tomorrow','country_code':'IT'})
 def test_city_reply_completes_weather_request(self):
  from serve.weather_intent import intent
  result=intent([{'role':'user','content':'Che tempo fa domani?'},{'role':'assistant','content':'Per quale città vuoi la previsione?'},{'role':'user','content':'Vercelli, Italia'}])
  self.assertEqual(result,{'city':'Vercelli','date':'tomorrow','country_code':'IT'})
 def test_missing_city_is_not_guessed(self):
  from serve.weather_intent import intent
  self.assertIsNone(intent([{'role':'user','content':'Che tempo fa domani?'}]))
 def test_english_date_removed_from_city(self):
  from serve.weather_intent import intent
  self.assertEqual(intent([{'role':'user','content':'Weather in Rome tomorrow?'}])['city'],'Rome')
if __name__=='__main__':unittest.main()

from html.parser import HTMLParser
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
class Extract(HTMLParser):
    def __init__(self):super().__init__();self.ignored=0;self.items=[]
    def add(self,value):
        text=' '.join(value.split())
        if text and text not in self.items and any(c.isalpha() for c in text):self.items.append(text)
    def handle_starttag(self,tag,attrs):
        if tag in ('style','script'):self.ignored+=1
        if not self.ignored:
            for name,value in attrs:
                if name in ('aria-label','placeholder','title','alt') and value:self.add(value)
    def handle_endtag(self,tag):
        if tag in ('style','script'):self.ignored=max(0,self.ignored-1)
    def handle_data(self,text):
        if not self.ignored:self.add(text)
parser=Extract();parser.feed((ROOT/'serve/web/index.html').read_text(encoding='utf-8'))
(ROOT/'output/verification/ui-language-inventory.json').write_text(json.dumps(parser.items,ensure_ascii=False,indent=2),encoding='utf-8')
for i,text in enumerate(parser.items):print(f'{i}: {text}')

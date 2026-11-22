"""Compile the explicit reviewed translation catalogue; no network dependencies."""
import json
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]

def validate(data):
    if set(data)!= {'pairs','aliases'}:raise ValueError('Invalid language catalogue schema')
    for source,target in data['pairs'].items():
        if not isinstance(source,str) or not isinstance(target,str) or not source.strip() or not target.strip():raise ValueError('Empty translation')
        if set(re.findall(r'\{\d+\}',source))!=set(re.findall(r'\{\d+\}',target)):raise ValueError('Placeholder mismatch: '+source)
    if any(target not in data['pairs'] for target in data['aliases'].values()):raise ValueError('Alias has no reviewed translation')
    return data

def main():
    data=validate(json.loads((ROOT/'serve/locales/ui-it-en.json').read_text(encoding='utf-8')))
    target=ROOT/'serve/web/language-data.js'
    target.write_text('// Reviewed interface translations. User content and API identifiers are excluded.\nwindow.StrataLanguageData='+json.dumps(data,ensure_ascii=False,indent=2)+';\n',encoding='utf-8')
    print(f"{len(data['pairs'])} reviewed entries; {len(data['aliases'])} legacy aliases")

if __name__=='__main__':main()

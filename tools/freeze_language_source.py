"""Migrate the reviewed inventory to explicit, stable translation keys."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
raw=(ROOT/'serve/web/language-data.js').read_text(encoding='utf-8')
payload=json.loads(raw.split('window.StrataLanguageData=',1)[1].removesuffix(';\n'))
directory=ROOT/'serve/locales';directory.mkdir(exist_ok=True)
(directory/'ui-it-en.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

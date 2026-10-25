from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'serve/web/app.js';s=p.read_text(encoding='utf-8')
s=s.replace(' · installato</option>'," · ${esc(StrataI18n.text('installato'))}</option>")
s=s.replace("m.ready?'':' · non disponibile'", "m.ready?'':' · '+StrataI18n.text('non disponibile')")
s=s.replace("attachments:'Nomi conservati; contenuti da riallegare'", "attachments:StrataI18n.text('Nomi conservati; contenuti da riallegare')")
s=s.replace(" if(tab==='tuning'){renderPerformanceReports();renderPerformanceRecord();}", " for(const option of $('ctrl-model').options){const index=option.textContent.lastIndexOf(' · ');if(index>=0)option.textContent=option.textContent.slice(0,index)+' · '+StrataI18n.text('installato');}\n if(tab==='tuning'){renderPerformanceReports();renderPerformanceRecord();}")
p.write_text(s,encoding='utf-8')
p=ROOT/'tools/build_language_data.py';s=p.read_text(encoding='utf-8');s=s.replace(" 'Waiting for a request':", " 'Thinking…':'Ragionamento…','Thoughts':'Ragionamento',\n 'Waiting for a request':")
p.write_text(s,encoding='utf-8')
p=ROOT/'tools/english_dynamic_translations.txt';s=p.read_text(encoding='utf-8');s+='\nRagionamento per {0} s|Thought for {0} s\n';p.write_text(s,encoding='utf-8')

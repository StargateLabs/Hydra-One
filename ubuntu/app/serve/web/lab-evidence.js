/* Observed statistics and portable raw samples; no estimates substituted for data. */
(()=>{
 const byId=id=>document.getElementById(id),en=()=>document.documentElement.lang.startsWith('en');
 const panel=document.createElement('section');panel.className='ai-lab-evidence';panel.dataset.i18nIgnore='';
 byId('lab-results').after(panel);
 const button=document.createElement('button');button.type='button';button.className='st-btn st-btn--secondary';button.id='lab-export-csv';button.disabled=true;byId('lab-export').before(button);
 let current={};
 const label=(it,english)=>en()?english:it;
 const number=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString(en()?'en-US':'it-IT',{maximumFractionDigits:3}):'—';
 const appendText=(tag,value,parent)=>{const node=document.createElement(tag);node.textContent=value;parent.append(node);return node;};
 function render(job){
  const opened=new Set(current.id===job?.id?[...panel.querySelectorAll('details[open][data-evidence-key]')].map(node=>node.dataset.evidenceKey):[]);
  current=job||{};button.textContent=label('Esporta campioni CSV','Export samples CSV');button.disabled=!(current.results||[]).some(r=>r.series?.length);
  panel.replaceChildren();if(!current.results?.length){panel.hidden=true;return;}panel.hidden=false;
  appendText('h3',label('Precisione delle misure','Measurement precision'),panel);
  const grid=document.createElement('div');grid.className='ai-lab-evidence-grid';panel.append(grid);
  for(const result of current.results){
   const article=document.createElement('article');grid.append(article);appendText('strong',result.label,article);
   const metric=result.summary?.decode_tok_s?'decode_tok_s':'wall_tok_s',s=result.summary?.[metric];
   appendText('small',metric==='decode_tok_s'?label('Generazione · token/s','Generation · tokens/s'):label('Richiesta completa · token/s','End-to-end request · tokens/s'),article);
   if(s){const dl=document.createElement('dl');article.append(dl);for(const [name,value]of [[label('Campioni','Samples'),s.count??result.samples],[label('Mediana','Median'),s.median],[label('Deviazione standard','Standard deviation'),s.sample_stddev],['P95',s.p95]]){appendText('dt',name,dl);appendText('dd',number(value),dl);}}
   if(result.quality){appendText('p',label('Risposte corrette','Correct answers')+': '+result.quality.correct+'/'+result.quality.total,article);if(result.quality.dataset_sha256){const hash=appendText('code','SHA-256 · '+result.quality.dataset_sha256,article);hash.title=result.quality.dataset_sha256;}}
  }
  const cases=Array.isArray(current.quality_progress?.cases)?current.quality_progress.cases.filter(row=>typeof row?.passed==='boolean'&&typeof row.case==='string').slice(0,12):[];
  if(cases.length){
   const details=document.createElement('details');details.className='ai-lab-quality-details';details.dataset.evidenceKey='quality';details.open=opened.has('quality');panel.append(details);appendText('summary',label('Dettaglio dei compiti registrati','Recorded task details')+' · '+cases.length,details);
   appendText('p',label('Confronto con risposte fisse: misura questi compiti, non la qualità generale del modello.','Fixed-reference checks measure these tasks, not general model quality.'),details);
   const groups={};for(const row of cases){const key=row.category||'other';(groups[key]||=[]).push(row);}
   const names={arithmetic:['Calcolo','Arithmetic'],code:['Codice','Code'],logic:['Logica','Logic'],data:['Dati','Data'],other:['Altro','Other']};
   const categories=document.createElement('div');categories.className='ai-lab-quality-categories';details.append(categories);
   for(const [category,rows]of Object.entries(groups)){const item=document.createElement('article');appendText('span',label(...(names[category]||names.other)),item);const count=rows.filter(row=>row.passed).length;item.dataset.result=count===rows.length?'correct':count===0?'incorrect':'mixed';appendText('strong',count+' / '+rows.length,item);categories.append(item);}
   const taskNames={invoice:['Fattura','Invoice'],sort:['Ordinamento','Sorting'],aggregate:['Aggregazione','Aggregation'],trace_python:['Traccia Python','Python trace'],trace_loop:['Traccia del ciclo','Loop trace'],interval:['Intervalli','Intervals'],deduplicate:['Deduplicazione','Deduplication'],join:['Join dei dati','Data join'],schedule:['Pianificazione','Scheduling'],nested:['JSON annidato','Nested JSON'],logic:['Logica','Logic'],date:['Calcolo delle date','Date arithmetic']};
   for(const row of cases){const item=document.createElement('details');item.className='ai-lab-quality-case';item.dataset.evidenceKey='case:'+row.case;item.open=opened.has('case:'+row.case);item.dataset.result=row.passed?'correct':'incorrect';const summary=document.createElement('summary');const name=appendText('span',taskNames[row.case]?label(...taskNames[row.case]):row.case,summary);name.title=row.case;appendText('b',row.passed?label('Corretto','Correct'):label('Non corretto','Incorrect'),summary);item.append(summary);const body=document.createElement('div');body.className='ai-lab-quality-comparison';item.append(body);for(const [name,value]of [[label('Risposta attesa','Expected answer'),JSON.stringify(row.expected,null,2)],[label('Risposta del modello','Model answer'),row.answer]]){const column=document.createElement('section');appendText('h4',name,column);appendText('pre',String(value??'—').slice(0,8192),column);body.append(column);}details.append(item);}
  }
  const cfg=current.configuration;
  if(cfg){const details=document.createElement('details');details.dataset.evidenceKey='configuration';details.open=opened.has('configuration');panel.append(details);appendText('summary',label('Configurazione registrata','Recorded configuration'),details);appendText('pre',JSON.stringify(cfg,null,2),details);}
 }
 function csvCell(value){if(value==null)return '""';let s=String(value);if(/^[=+@\-\t\r]/.test(s)&&typeof value!=='number')s="'"+s;return '"'+s.replaceAll('"','""')+'"';}
 button.onclick=()=>{
  const columns=['session','model','backend','profile','sample','warmup','output_tokens','decode_tok_s','prefill_tok_s','wall_s','wall_tok_s','ttft_s','error'];
  const lines=[columns.map(csvCell).join(',')];
  for(const r of current.results||[])for(const [i,s]of(r.series||[]).entries())lines.push([current.id,current.model,current.backend,r.label,i+1,s.warmup,s.output_tokens,s.decode_tok_s,s.prefill_tok_s,s.wall_s,s.wall_tok_s,s.ttft_s,s.error].map(csvCell).join(','));
  const url=URL.createObjectURL(new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='benchmark-'+current.id+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 };
 window.StrataLabEvidence={render};window.addEventListener('strata:languagechange',()=>render(current));render(current);
})();

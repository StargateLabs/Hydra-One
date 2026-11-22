/* Recorded benchmark observations. No smoothing, synthetic samples or inferred confidence. */
((root)=>{
 const finite=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0;
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function describe(series,key){
  const points=series.map((r,index)=>({index,value:r[key],warmup:r.warmup===true,measured:r.warmup===false})).filter(p=>finite(p.value));
  const values=points.filter(p=>p.measured).map(p=>p.value).sort((a,b)=>a-b),n=values.length;
  return {points,count:n,warmup:points.filter(p=>p.warmup).length,median:n?(n%2?values[(n-1)/2]:(values[n/2-1]+values[n/2])/2):null,min:n?values[0]:null,max:n?values.at(-1):null};
 }
 function trace(points,x,y){return points.map((p,i)=>(i&&p.index===points[i-1].index+1?'L':'M')+x(p.index).toFixed(2)+','+y(p.value).toFixed(2)).join(' ');}
 function render(series,results,key){
  const trend=document.getElementById('lab-trend'),comparison=document.getElementById('lab-comparison');if(!trend||!comparison)return;
  const section=trend.closest('.bench-panel');section.classList.add('benchmark-signals');
  const en=document.documentElement.lang.startsWith('en'),t=(it,english)=>en?english:it;
  const fmt=v=>finite(v)?v.toLocaleString(en?'en-US':'it-IT',{maximumFractionDigits:2}):'—';
  const unit=key==='generation_ms'?'ms':key==='wall_s'?'s':'token/s';
  const names={decode_tok_s:t('Generazione','Generation'),prefill_tok_s:t('Lettura del prompt','Prompt processing'),wall_tok_s:t('Richiesta completa','End-to-end request'),wall_s:t('Durata della richiesta','Request duration'),generation_ms:t('Tempo modello','Model time')};
  const tones={decode_tok_s:'blue',prefill_tok_s:'mint',wall_tok_s:'violet',wall_s:'amber',generation_ms:'violet'};section.dataset.signalTone=tones[key]||'blue';
  const signature=JSON.stringify([series,results,key,en]);if(section.dataset.signalSignature===signature)return;section.dataset.signalSignature=signature;
  const data=describe(series,key);
  let summary=section.querySelector('.benchmark-signal-summary');
  if(!summary){summary=document.createElement('div');summary.className='benchmark-signal-summary';section.querySelector('.bench-chart-grid').before(summary);}
  summary.innerHTML=`<div class="signal-summary-title"><span class="signal-summary-mark" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M3 20h5l4-11 7 17 4-12h6"/></svg></span><div><span>${esc(names[key]||key)}</span><strong>${t('Osservazioni della sessione','Session observations')}</strong></div></div><dl><div><dt>${t('Misure valide','Measured samples')}</dt><dd>${data.count}</dd></div><div><dt>${t('Mediana','Median')}</dt><dd>${fmt(data.median)}<small>${unit}</small></dd></div><div><dt>${t('Intervallo osservato','Observed range')}</dt><dd>${fmt(data.min)}<span>—</span>${fmt(data.max)}</dd></div></dl>`;
  const sourceProfile=results.find(r=>r.series===series)?.label;
  if(sourceProfile)summary.querySelector('.signal-summary-title strong').textContent=sourceProfile;
  if(!data.points.length){trend.innerHTML=`<div class="signal-empty"><svg viewBox="0 0 80 40" aria-hidden="true"><path d="M4 29h16l8-17 13 24 12-19h23"/></svg><strong>${t('In attesa delle osservazioni','Waiting for observations')}</strong><span>${t('Seleziona una sessione salvata oppure avvia una prova.','Select a saved session or start a test.')}</span></div>`;}
  else{
   const values=data.points.map(p=>p.value),min=Math.min(...values),max=Math.max(...values),pad=Math.max((max-min)*.18,max*.04,.01),low=Math.max(0,min-pad),high=max+pad;
   const x=i=>60+i*610/Math.max(1,series.length-1),y=v=>224-(v-low)/(high-low)*170;
   const grid=[0,.5,1].map(f=>{const v=low+(high-low)*f;return `<line x1="60" x2="670" y1="${y(v)}" y2="${y(v)}" class="signal-grid"/><text x="48" y="${y(v)+4}" text-anchor="end">${fmt(v)}</text>`;}).join('');
   const median=data.median===null?'':`<line x1="60" x2="670" y1="${y(data.median)}" y2="${y(data.median)}" class="signal-median"/>`;
   const marks=data.points.map(p=>{const label=`${t('Richiesta','Request')} ${p.index+1} · ${p.warmup?t('Riscaldamento','Warmup'):p.measured?t('Misura valida','Measured sample'):t('Fase non registrata','Phase unavailable')} · ${fmt(p.value)} ${unit}`;return `<g tabindex="0" role="img" aria-label="${esc(label)}" class="signal-observation ${p.warmup?'is-warm':p.measured?'is-measured':'is-unknown'}"><title>${esc(label)}</title><line class="signal-crosshair" x1="${x(p.index)}" x2="${x(p.index)}" y1="42" y2="232"/><circle class="signal-hit" cx="${x(p.index)}" cy="${y(p.value)}" r="14"/>${p.warmup?`<path class="signal-point" d="M${x(p.index)},${y(p.value)-5}l5,5 -5,5 -5,-5Z"/>`:`<circle class="signal-point" cx="${x(p.index)}" cy="${y(p.value)}" r="4.5"/>`}</g>`;}).join('');
   trend.innerHTML=`<header class="signal-plot-head"><span>${t('Sequenza delle richieste','Request sequence')}</span><small>${unit} · ${t('scala adattiva','adaptive scale')}</small></header><svg viewBox="0 0 710 274" role="group" aria-label="${esc(names[key])} · ${data.points.length} ${t('osservazioni','observations')}">${grid}${median}<path d="${trace(data.points,x,y)}" class="signal-trace-shadow"/><path d="${trace(data.points,x,y)}" class="signal-trace"/>${marks}<text x="60" y="258">${t('Richiesta','Request')} 1</text><text x="670" y="258" text-anchor="end">${t('Richiesta','Request')} ${series.length}</text></svg>`;
  }
  const valid=results.filter(r=>{const s=r.summary?.[key];return s&&[s.min,s.max,s.median].every(finite)&&s.min<=s.median&&s.median<=s.max;});
  if(!valid.length)comparison.innerHTML=`<div class="signal-empty"><strong>${t('Il confronto apparirà qui','The comparison will appear here')}</strong><span>${t('Servono profili con misure completate.','Completed profile measurements are required.')}</span></div>`;
  else{
   const max=Math.max(...valid.map(r=>r.summary[key].max))*1.08||1,x=v=>20+v/max*400;
   comparison.innerHTML=`<header class="signal-plot-head"><span>${t('Mediana e variabilità','Median and variability')}</span><small>${unit} · ${t('scala comune','shared scale')}</small></header><div class="signal-profile-list">${valid.map((r,i)=>{const s=r.summary[key],label=r.label||r.variant||t('Profilo','Profile');return `<article class="signal-profile"><div class="signal-profile-heading"><span>${esc(label)}</span><strong>${fmt(s.median)}<small>${unit}</small></strong></div><svg viewBox="0 0 440 48" role="img" tabindex="0" aria-label="${esc(label)}: ${t('mediana','median')} ${fmt(s.median)}; min ${fmt(s.min)}; max ${fmt(s.max)} ${unit}"><title>${t('Minimo','Minimum')} ${fmt(s.min)} · ${t('Mediana','Median')} ${fmt(s.median)} · ${t('Massimo','Maximum')} ${fmt(s.max)} ${unit}</title><path d="M20 24H420" class="signal-channel"/>${[0,.25,.5,.75,1].map(f=>`<path d="M${20+400*f} 16v16" class="signal-ruler"/>`).join('')}<path d="M${x(s.min)} 24H${x(s.max)}" class="signal-range"/><path d="M${x(s.min)} 17v14M${x(s.max)} 17v14" class="signal-range-cap"/><path d="M${x(s.median)} 16l8,8 -8,8 -8,-8Z" class="signal-diamond"/></svg><div class="signal-range-labels"><span>min ${fmt(s.min)}</span><span>max ${fmt(s.max)}</span></div></article>`;}).join('')}</div><div class="signal-scale"><span>0</span><span>${fmt(max)} ${unit}</span></div>`;
  }
  document.getElementById('lab-chart-note').textContent=(['wall_s','generation_ms'].includes(key)?t('Un tempo minore è migliore.','Lower time is better.'):t('Una velocità maggiore è migliore.','Higher speed is better.'))+' '+t('Diamante: mediana. Capsula: minimo–massimo osservati, non intervallo di confidenza.','Diamond: median. Capsule: observed minimum–maximum, not a confidence interval.');
  let details=section.querySelector('.signal-data');if(!details){details=document.createElement('details');details.className='signal-data';section.append(details);}
  details.innerHTML=`<summary>${t('Consulta i campioni','Inspect samples')} · ${data.points.length}</summary><div class="signal-table-scroll"><table><thead><tr><th>${t('Richiesta','Request')}</th><th>${t('Fase','Phase')}</th><th>${esc(names[key])} · ${unit}</th></tr></thead><tbody>${series.map((r,i)=>`<tr><td>${i+1}</td><td>${r.warmup===true?t('Riscaldamento','Warmup'):r.warmup===false?t('Misura valida','Measured sample'):'—'}</td><td>${fmt(r[key])}</td></tr>`).join('')||`<tr><td colspan="3">${t('Nessun campione disponibile','No samples available')}</td></tr>`}</tbody></table></div>`;
 }
 root.StrataBenchmarkSignals={render,describe,trace};if(typeof module!=='undefined')module.exports={describe,trace};
})(typeof window==='undefined'?globalThis:window);

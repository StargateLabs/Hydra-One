/* Measured request chronicle. Adaptive scale is explicit; gaps are never zeros. */
((root)=>{
 const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const number=(v,en)=>v.toLocaleString(en?'en-US':'it-IT',{maximumFractionDigits:1});
 const observations=new Map();
 function observationRows(series){
  return series.flatMap(item=>(item.data?.points||[]).map(point=>({label:item.label,position:point.index+1,value:point.value,unit:item.unit,source:item.source})));
 }
 function promptMetric(requests,history=[]){
  const rate=requests.map(r=>r.prefill_tok_s??(r.prompt_read>0&&r.prompt_ms>0?r.prompt_read/(r.prompt_ms/1000):null));
  if(rate.some(v=>Number.isFinite(v)&&v>0))return {kind:'rate',values:rate,unit:'token/s',source:'requests'};
  if(history.some(v=>Number.isFinite(v)&&v>0))return {kind:'rate',values:history.map(v=>v>0?v:null),unit:'token/s',source:'readings'};
  return {kind:'tokens',values:requests.map(r=>typeof r.prompt_tokens==='number'?r.prompt_tokens:null),unit:'token',source:'requests'};
 }
 function chart(values,{unit='token/s',english=false,source='requests',id='chart'}={}){
  const window=(values||[]).slice(-40);
  const points=window.map((value,index)=>({value,index})).filter(p=>typeof p.value==='number'&&Number.isFinite(p.value)&&p.value>=0);
  if(!points.length)return {count:0,points,markup:`<text x="320" y="120" text-anchor="middle" class="generation-chart-empty">${english?'No separate measurement available':'Nessuna misura separata disponibile'}</text>`};
  const sorted=points.map(p=>p.value).sort((a,b)=>a-b),count=sorted.length;
  const median=count%2?sorted[(count-1)/2]:(sorted[count/2-1]+sorted[count/2])/2;
  const min=sorted[0],max=sorted.at(-1),spread=Math.max(max-min,max*.12,1);
  const low=Math.max(0,min-spread*.28),high=max+spread*.32;
  const x=i=>window.length===1?320:52+i/(window.length-1)*538,y=v=>192-(v-low)/(high-low)*150;
  const positions=points.map(p=>({...p,x:x(p.index),y:y(p.value)}));
  const path=positions.map((p,i)=>(i&&p.index===positions[i-1].index+1?'L':'M')+p.x.toFixed(2)+','+p.y.toFixed(2)).join(' ');
  const segments=[];
  positions.forEach((p,i)=>{if(!i||p.index!==positions[i-1].index+1)segments.push([]);segments.at(-1).push(p);});
  const area=segments.filter(segment=>segment.length>1).map(segment=>segment.map((p,i)=>(i?'L':'M')+p.x.toFixed(2)+','+p.y.toFixed(2)).join(' ')+` L${segment.at(-1).x.toFixed(2)},192 L${segment[0].x.toFixed(2)},192 Z`).join(' ');
  const gradient='trace-'+id.replace(/[^a-zA-Z0-9_-]/g,'');
  let markup=`<defs><linearGradient id="${gradient}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="currentColor" stop-opacity=".28"/><stop offset="100%" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>`;
  for(const f of [0,.5,1]){const v=low+(high-low)*f;markup+=`<line x1="52" x2="590" y1="${y(v)}" y2="${y(v)}" class="generation-chart-grid"/><text x="42" y="${y(v)+4}" text-anchor="end">${number(v,english)}</text>`;}
  markup+=`<rect x="52" y="${y(max)}" width="538" height="${Math.max(1,y(min)-y(max))}" class="chart-range-band"/><line x1="52" x2="590" y1="${y(median)}" y2="${y(median)}" class="chart-median"/>`;
  if(count>1)markup+=`<path d="${area}" fill="url(#${gradient})"/><path d="${path}" class="chart-trace-halo"/><path d="${path}" class="chart-trace"/>`;
  positions.forEach((p,i)=>{
   const label=`${source==='readings'?(english?'Sample':'Campione'):(english?'Request':'Richiesta')} ${p.index+1}: ${number(p.value,english)} ${unit}`;
   markup+=`<g class="chart-observation" tabindex="0" role="img" data-point="${i}" aria-label="${escape(label)}"><title>${escape(label)}</title><line x1="${p.x}" x2="${p.x}" y1="32" y2="196" class="chart-crosshair"/><circle cx="${p.x}" cy="${p.y}" r="${i===count-1?12:9}" class="chart-point-aura"/><circle cx="${p.x}" cy="${p.y}" r="${i===count-1?5:3.5}" class="chart-point"/></g>`;
  });
  markup+=`<text x="52" y="224">${english?'Earlier':'Prima'}</text><text x="590" y="224" text-anchor="end">${source==='readings'?(english?'Latest sample':'Ultimo campione'):(english?'Latest request':'Ultima richiesta')}</text>`;
  return {count,median,min,max,latest:points.at(-1).value,positions,points,markup};
 }
 function render(svg,values,options){
  const signature=JSON.stringify([values,options]);if(svg.dataset.chartSignature===signature)return;
  svg.dataset.chartSignature=signature;
  const data=chart(values,{...options,id:svg.id}),en=options.english;
  observations.set(svg.id,{label:options.label,unit:options.unit,source:options.source,data});
  svg.dataset.i18nIgnore='true';svg.setAttribute('viewBox','0 0 640 240');svg.setAttribute('preserveAspectRatio','xMidYMid meet');svg.setAttribute('role','group');
  svg.setAttribute('aria-label',options.label+' · '+data.count+(en?' measured observations':' misure disponibili'));
  let panel=svg.closest('.generation-viz');
  if(!panel){panel=document.createElement('div');panel.className='generation-viz';panel.dataset.i18nIgnore='true';svg.before(panel);panel.append(svg);const detail=document.createElement('div');detail.className='generation-viz-detail';detail.setAttribute('role','status');panel.append(detail);const stats=document.createElement('div');stats.className='generation-viz-stats';panel.append(stats);}
  svg.innerHTML=data.markup;
  const detail=panel.querySelector('.generation-viz-detail'),stats=panel.querySelector('.generation-viz-stats');
  const pointLabel=options.source==='readings'?(en?'Sample ':'Campione '):(en?'Request ':'Richiesta ');
  const idle=()=>{detail.textContent=data.count?(options.source==='readings'?(en?'Explore telemetry samples':'Esplora i campioni rilevati'):(en?'Explore each request':'Esplora le singole richieste'))+' · '+data.count+' '+(en?'observations':'misure'):en?'No measured values':'Nessun valore misurato';};idle();
  stats.innerHTML=data.count?[[en?'Median':'Mediana',data.median],[en?'Minimum':'Minimo',data.min],[en?'Peak':'Picco',data.max]].map(([label,value])=>`<div><span>${label}</span><strong>${number(value,en)}<small>${escape(options.unit)}</small></strong></div>`).join(''):'';
  for(const point of svg.querySelectorAll('[data-point]')){
   const show=()=>{const p=data.points[Number(point.dataset.point)];detail.textContent=pointLabel+(p.index+1)+' · '+number(p.value,en)+' '+options.unit;};
   point.onpointerenter=point.onfocus=show;point.onpointerleave=point.onblur=idle;
  }
  panel.dataset.scope=options.source;
  panel.dataset.empty=String(data.count===0);
  panel.title=en?'Adaptive scale; measured observations in chronological order':'Scala adattiva; misure reali in ordine cronologico';
 }
 function details(phase){
  const speed=document.getElementById('sp-speed')?.closest('.dm');
  const prompt=document.getElementById('sp-prefill')?.closest('.dm');
  if(!speed||!prompt)return;
  const en=document.documentElement.lang.startsWith('en'),card=speed.closest('.dash-card--inf');
  let console=card.querySelector('.generation-unified');
  if(!console){
   console=document.createElement('section');console.className='generation-unified';console.setAttribute('aria-label',en?'Generation measurements':'Misure della generazione');speed.before(console);
   const plots=document.createElement('div');plots.className='generation-unified-plots';console.append(plots);plots.append(speed,prompt);
   speed.classList.add('generation-signal','generation-signal--decode');prompt.classList.add('generation-signal','generation-signal--prompt');
   const rail=document.createElement('div');rail.className='generation-unified-metrics';console.append(rail);
   const footer=document.createElement('div');footer.className='generation-unified-footer';
   const disclosure=document.createElement('details');disclosure.className='generation-observations';
   disclosure.innerHTML='<summary></summary><div class="generation-observations-body"></div>';footer.append(disclosure);
   const download=document.createElement('button');download.type='button';download.className='generation-data-export';footer.append(download);console.append(footer);
  }
  const rail=console.querySelector('.generation-unified-metrics');
  console.setAttribute('aria-label',en?'Generation measurements':'Misure della generazione');
  for(const [id,kind] of [['mv-state','generation-state-footer'],['ctx-fill','generation-context-footer'],['mv-experts','generation-cache-footer'],['mv-hit','generation-hit-footer'],['mv-draft','generation-draft-footer']]){
   const tile=document.getElementById(id)?.closest('.dm');
   if(tile){tile.classList.add('generation-inline-metric',kind);if(tile.parentElement!==rail)rail.append(tile);if(id==='mv-state')tile.dataset.phase=phase||'unknown';}
  }
  const series=['sp-speed','sp-prefill'].map(id=>observations.get(id)).filter(Boolean),rows=observationRows(series);
  console.querySelector('summary').textContent=(en?'Data and sources':'Dati e provenienza')+' · '+rows.length+' '+(en?'values':'valori');
  const body=console.querySelector('.generation-observations-body'),signature=JSON.stringify([rows,en]);
  if(body.dataset.signature!==signature){
   body.dataset.signature=signature;
   const source=value=>value==='requests'?(en?'Completed requests':'Richieste completate'):(en?'Telemetry samples':'Campioni della telemetria');
   body.innerHTML=rows.length?`<p>${en?'Up to 40 observations per series, in sequence order. Units and sources remain separate.':'Fino a 40 osservazioni per serie, in ordine di rilevazione. Ogni serie mantiene la propria unità e origine.'}</p><div class="generation-observations-scroll"><table><thead><tr>${(en?['Series','Position','Value','Unit','Source']:['Serie','Posizione','Valore','Unità','Origine']).map(text=>'<th scope="col">'+text+'</th>').join('')}</tr></thead><tbody>${rows.map(row=>`<tr><td>${escape(row.label)}</td><td>${row.position}</td><td>${row.value.toLocaleString(en?'en-US':'it-IT',{maximumFractionDigits:3})}</td><td>${escape(row.unit)}</td><td>${source(row.source)}</td></tr>`).join('')}</tbody></table></div>`:`<p>${en?'Measured observations will appear here after a request.':'Le osservazioni effettive compariranno qui dopo una richiesta.'}</p>`;
  }
  const download=console.querySelector('.generation-data-export');download.textContent=en?'Export chart data':'Esporta dati dei grafici';download.disabled=!rows.length;
  download.onclick=()=>{
   const payload={schema:'stargatelab.generation-observations.v1',exported_at:new Date().toISOString(),model:document.getElementById('ms-model')?.textContent||null,source_context:document.getElementById('view-monitor').dataset.monitorSource||'unknown',source_label:document.getElementById('monitor-source-label')?.textContent||null,positions_are_window_relative:true,rows};
   const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'})),link=document.createElement('a');link.href=url;link.download='stargatelab-generation-observations.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
 }

 root.StrataGenerationChart={chart,render,promptMetric,details,observationRows};
 if(typeof module!=='undefined')module.exports={chart,promptMetric,observationRows};
})(typeof window==='undefined'?globalThis:window);

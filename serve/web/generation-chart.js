/* Measured observations, never zero-filled gaps or fabricated time axes. */
((root)=>{
 const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function chart(values,{unit='token/s',english=false,source='requests'}={}){
  const points=(values||[]).slice(-40).map((value,index)=>({value,index})).filter(p=>typeof p.value==='number'&&Number.isFinite(p.value)&&p.value>=0);
  if(!points.length)return {count:0,markup:`<text x="310" y="82" text-anchor="middle" class="generation-chart-empty">${english?'Waiting for a measured request':'In attesa di una richiesta misurata'}</text>`};
  const sorted=points.map(p=>p.value).sort((a,b)=>a-b),count=sorted.length;
  const median=count%2?sorted[(count-1)/2]:(sorted[count/2-1]+sorted[count/2])/2;
  const max=Math.max(sorted.at(-1),1),top=max*1.15;
  const x=i=>48+(i+.5)*540/count,y=v=>137-v/top*86;
  const number=v=>v.toLocaleString(english?'en-US':'it-IT',{maximumFractionDigits:1});
  const measure=english?'Median':'Mediana',range=english?'Range':'Intervallo';
  let markup=`<text x="32" y="20" class="chart-summary">${measure} ${number(median)} <tspan class="chart-muted">${escape(unit)}</tspan></text><text x="594" y="20" text-anchor="end" class="chart-muted">${range} ${number(sorted[0])}–${number(sorted.at(-1))}</text>`;
  for(const fraction of [0,.5,1]){const value=max*fraction;markup+=`<line x1="48" x2="588" y1="${y(value)}" y2="${y(value)}" class="generation-chart-grid"/><text x="39" y="${y(value)+4}" text-anchor="end">${number(value)}</text>`;}
  markup+=`<line x1="48" x2="588" y1="${y(median)}" y2="${y(median)}" class="chart-median"/>`;
  const width=Math.max(3,Math.min(38,540/count*.6));
  points.forEach((p,i)=>{
   const label=`${english?'Observation':'Misura'} ${p.index+1}: ${number(p.value)} ${unit}`;
   markup+=`<g class="chart-observation" tabindex="0" role="img" aria-label="${escape(label)}"><title>${escape(label)}</title><rect x="${x(i)-width/2}" y="${y(p.value)}" width="${width}" height="${Math.max(2,137-y(p.value))}" rx="${Math.min(4,width/2)}" class="chart-column"/><circle cx="${x(i)}" cy="${y(p.value)}" r="${i===count-1?4.5:3}" class="chart-point"/></g>`;
  });
  const scope=source==='requests'?(english?'completed requests · chronological order':'richieste concluse · ordine cronologico'):(english?'valid readings · gaps omitted':'rilevamenti validi · intervalli mancanti omessi');
  markup+=`<text x="48" y="168">${count} ${scope}</text><text x="588" y="168" text-anchor="end">${english?'Latest':'Ultima'} ${number(points.at(-1).value)}</text>`;
  return {count,median,min:sorted[0],max:sorted.at(-1),markup};
 }
 root.StrataGenerationChart={chart};
 if(typeof module!=='undefined')module.exports={chart};
})(typeof window==='undefined'?globalThis:window);

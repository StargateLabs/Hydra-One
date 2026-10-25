((root)=>{
 function identity(metrics,nativeState,source='operational'){
  const eng=metrics?.engine||{},observed=metrics?.hydra_native;
  const state=typeof observed?.enabled==='boolean'?observed:source==='operational'?nativeState:null;
  const hydra=state?.enabled===true&&['hip','strata'].includes(String(eng.backend).toLowerCase())||metrics?.optional_backend?.engine_addon==='hydra-one';
  return {hydra,label:hydra?'HYDRA ONE':eng.backend||'HIP',runtime:eng.backend||null};
 }
 function graphSummary(metrics,english=false){
  const optional=metrics?.optional_backend;
  const graph=optional?.status==='ready'&&optional?.engine_addon==='hydra-one'?optional.graph_inference:metrics?.hydra_native?.graph_inference;
  if(!graph||typeof graph.enabled!=='boolean')return null;
  if(!graph.enabled)return {label:english?'Graph disabled':'Grafo disattivato',detail:english?'Graph context is disabled for this source.':'Il contesto dal grafo è disattivato per questa sorgente.'};
  const last=graph.last||{},used=last.strategy==='graph_context',number=v=>Number.isFinite(v)&&v>=0;
  const label=last.reason==='awaiting_request'?(english?'Graph ready':'Grafo pronto'):used&&number(last.nodes_retrieved)?(english?`Graph · ${last.nodes_retrieved} nodes`:`Grafo · ${last.nodes_retrieved} nodi`):(english?'Standard context':'Contesto standard');
  const parts=[english?'Last preparation':'Ultima preparazione'];
  if(number(last.tokens_before)&&number(last.tokens_after))parts.push(`${last.tokens_before} → ${last.tokens_after} token`);
  if(number(last.preparation_s))parts.push(`${Math.round(last.preparation_s*1000)} ms`);
  const reasons={awaiting_request:english?'waiting for a compatible request':'in attesa di una richiesta compatibile',token_budget:english?'context budget exceeded':'budget del contesto superato',preparation_error:english?'retrieval unavailable':'recupero non disponibile',no_verified_sources:english?'no verified sources':'nessuna fonte verificata',preparation_busy:english?'preparation already busy':'preparazione già occupata',retrieval_cost_not_justified:english?'simple request':'richiesta semplice',source_special_tokens:english?'protected source content':'contenuto della fonte protetto'};
  if(!used)parts.push(reasons[last.reason]||(english?'original context preserved':'contesto originale conservato'));
  if(number(last.observed_at_unix_s))parts.push(new Date(last.observed_at_unix_s*1000).toLocaleTimeString(english?'en-GB':'it-IT'));
  return {label,detail:parts.join(' · ')};
 }
 root.StrataMonitorIdentity={identity,graphSummary};if(typeof module!=='undefined')module.exports={identity,graphSummary};
})(typeof window==='undefined'?globalThis:window);

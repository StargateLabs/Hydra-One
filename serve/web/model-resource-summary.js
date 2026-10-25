/* Shared selection summary. Estimates are never shown as measured memory. */
((root)=>{
 function summary(model,plan,context,english=false){
  if(model?.remote)return {size:english?'Server-managed':'Gestiti dal server',need:english?'Server-managed':'Gestite dal server',note:
   (english?'Selected model: ':'Modello selezionato: ')+(model.name||(english?'not selected':'non selezionato'))+'. '+
   (english?'Memory is managed by the connected server.':'La memoria è gestita dal server collegato.')};
  const finite=v=>Number.isFinite(v)&&v>=0;
  const row=plan?.options?.find(r=>r.context===Number(context));
  const ram=row?.ram_required_gib,gpu=plan?.device==='cpu'?0:row?.gpu_required_gib;
  const need=finite(ram)&&finite(gpu)?'~ '+ram.toFixed(1)+' + '+gpu.toFixed(1)+' GiB':null;
  return {size:finite(model?.bytes)?(model.bytes/2**30).toFixed(2)+' GiB':(english?'Unavailable':'Non disponibile'),need:need||(english?'To verify':'Da verificare'),
   note:(english?'Selected model: ':'Modello selezionato: ')+(model?.name||(english?'not selected':'non selezionato'))+'. '+
    (need?(english?'Estimated RAM + VRAM including margins; rechecked at loading.':'RAM + VRAM stimate con margini; verificate nuovamente al caricamento.'):
          (english?'Memory requirements unavailable until resource analysis.':'Requisiti di memoria non disponibili fino all’analisi delle risorse.'))};
 }
 function nativeSummary(prepared,local,documented,english=false){
  const key=String(prepared?.key||'').toUpperCase(),quant=String(prepared?.quant||'').toUpperCase();
  const documentedFamily=/qwen3[.]8[- ]flash[- ]next/i.test([prepared?.display_label,prepared?.label,local?.name].join(' '));
  const reference=documented[key]?key:documentedFamily&&documented[quant]?quant:null,info=documented[reference]||{};
  const name=prepared?.display_label||prepared?.label||local?.name||prepared?.key||(english?'not selected':'non selezionato');
  return {size:Number.isFinite(local?.bytes)&&local.bytes>=0?(local.bytes/2**30).toFixed(2)+' GiB':info.dl||(english?'Unavailable':'Non disponibile'),
   need:info.need||(english?'To verify':'Da verificare'),
   note:(english?'Selected model: ':'Modello selezionato: ')+name+'. '+(info.need?
    (english?'Published requirements for ':'Requisiti documentati per ')+reference+': '+info.need+'. '+(english?'Actual allocation is checked at loading.':'L’allocazione effettiva viene verificata al caricamento.'):
    (english?'No published memory requirement for this profile.':'Requisiti di memoria non documentati per questo profilo.'))};
 }
 root.StrataModelResourceSummary={summary,nativeSummary};if(typeof module!=='undefined')module.exports={summary,nativeSummary};
})(typeof window==='undefined'?globalThis:window);

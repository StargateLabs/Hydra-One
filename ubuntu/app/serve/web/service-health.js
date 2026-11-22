/* Service diagnostics use read-only endpoints and never start an engine. */
((root)=>{
 function facts(health,status,backend){
  const active=['ready','loading'].includes(backend?.status);
  return {reachable:health?.status==='ok',model:active?backend.model:health?.model,
   runtime:active?backend.backend:health?.service,loaded:active?backend.status==='ready':health?.loaded,
   context:active?backend.context:health?.max_context,images:active?backend.vision:health?.images,
   busy:active?backend.busy:status?.busy,queued:active?backend.queued:status?.queued,backend:active?backend.status:null};
 }
 if(typeof module!=='undefined'&&module.exports){module.exports={facts};return;}
 let dialog,returnFocus,controller;
 const en=()=>document.documentElement.lang.startsWith('en'),t=(it,english)=>en()?english:it;
 function init(){
  if(dialog)return;
  dialog=document.createElement('dialog');dialog.id='service-health-dialog';dialog.dataset.i18nIgnore='';
  dialog.setAttribute('aria-labelledby','service-health-title');
  dialog.innerHTML='<header><div class="service-health-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M3 12h4l3-7 4 14 3-7h4"/></svg></div><div><p class="service-health-eyebrow"></p><h2 id="service-health-title"></h2></div><button type="button" class="service-health-close" aria-label="Close">×</button></header><div class="service-health-body" aria-live="polite"></div><footer><span class="service-health-time"></span><button type="button" class="st-btn st-btn--secondary service-health-refresh"></button></footer>';
  document.body.append(dialog);
  dialog.querySelector('.service-health-close').onclick=()=>dialog.close();
  dialog.querySelector('.service-health-refresh').onclick=refresh;
  dialog.addEventListener('close',()=>{controller?.abort();returnFocus?.focus();});
 }
 function add(container,label,value){
  const item=document.createElement('div'),key=document.createElement('dt'),val=document.createElement('dd');
  key.textContent=label;val.textContent=value==null?t('Non disponibile','Unavailable'):String(value);item.append(key,val);container.append(item);
 }
 async function refresh(){
  controller?.abort();const request=new AbortController();controller=request;
  const body=dialog.querySelector('.service-health-body'),button=dialog.querySelector('.service-health-refresh');
  dialog.dataset.state='checking';button.disabled=true;button.textContent=t('Verifica…','Checking…');
  dialog.querySelector('.service-health-eyebrow').textContent=t('Stato del servizio','Service status');
  dialog.querySelector('h2').textContent=t('Controllo in corso','Checking service');
  dialog.querySelector('.service-health-close').setAttribute('aria-label',t('Chiudi stato del servizio','Close service status'));
  body.textContent=t('Verifica della connessione e dei motori…','Checking connection and engines…');
  const started=performance.now();
  try{
   const results=await Promise.allSettled(['health','status','inference-backends','metrics'].map(async path=>{
    const response=await fetch(path,{headers:typeof headers==='function'?headers():{},cache:'no-store',signal:AbortSignal.any([request.signal,AbortSignal.timeout(8000)])});
    if(!response.ok)throw Error(path+': HTTP '+response.status);return response.json();
   }));
   if(request.signal.aborted||controller!==request)return;
   const values=results.map(result=>result.status==='fulfilled'?result.value:null),[health,status,backend,metrics]=values;
   const state=facts(health,status,backend),ok=state.reachable;
   dialog.dataset.state=ok?'ok':'error';dialog.querySelector('h2').textContent=ok?t('Il servizio risponde','Service is responding'):t('Servizio non raggiungibile','Service unavailable');
   body.replaceChildren();
   const summary=document.createElement('p');summary.className='service-health-summary';
   summary.textContent=ok?(state.backend==='loading'?t('Il modello si sta caricando.','The model is loading.'):state.loaded===true?t('Modello caricato e disponibile.','Model loaded and available.'):state.loaded===false?t('Servizio disponibile. Il modello è scaricato dalla memoria.','Service available. The model is unloaded from memory.'):t('Stato del modello non disponibile.','Model state unavailable.')):t('La verifica della connessione non è riuscita. Nessun motore è stato avviato o riavviato.','Connection check failed. No engine was started or restarted.');body.append(summary);
   const identity=document.createElement('div');identity.className='service-health-model';const label=document.createElement('small'),name=document.createElement('strong');label.textContent=t('Modello effettivo','Actual model');name.textContent=state.model||t('Non rilevato','Not detected');identity.append(label,name);body.append(identity);
   const list=document.createElement('dl');list.className='service-health-facts';
   const bool=value=>typeof value==='boolean'?(value?t('Sì','Yes'):t('No','No')):null;
   add(list,t('Motore','Engine'),state.runtime);add(list,t('Modello in memoria','Model in memory'),bool(state.loaded));
   add(list,t('Contesto configurato','Configured context'),Number.isFinite(state.context)?state.context.toLocaleString(en()?'en-US':'it-IT')+' token':null);
   add(list,t('Supporto immagini','Image support'),bool(state.images));add(list,t('Richiesta in corso','Request in progress'),bool(state.busy));add(list,t('Richieste in coda','Queued requests'),state.queued);
   body.append(list);
   const hardware=metrics?.hardware;
   if(hardware){const details=document.createElement('details'),title=document.createElement('summary'),resources=document.createElement('dl');title.textContent=t('Risorse e diagnostica','Resources and diagnostics');resources.className='service-health-facts';
    add(resources,t('Temperatura GPU','GPU temperature'),Number.isFinite(hardware.gpu_temp)?hardware.gpu_temp+' °C':null);
    add(resources,t('Utilizzo CPU','CPU utilization'),Number.isFinite(hardware.cpu)?hardware.cpu+'%':null);
    add(resources,t('VRAM del sistema usata','System VRAM used'),Number.isFinite(hardware.gpu_mem_used)&&Number.isFinite(hardware.gpu_mem_total)?(hardware.gpu_mem_used/2**30).toFixed(1)+' / '+(hardware.gpu_mem_total/2**30).toFixed(1)+' GiB':null);
    add(resources,t('RAM del sistema usata','System RAM used'),Number.isFinite(hardware.ram_used)&&Number.isFinite(hardware.ram_total)?(hardware.ram_used/1e9).toFixed(1)+' / '+(hardware.ram_total/1e9).toFixed(1)+' GB':null);
    add(resources,t('Endpoint API','API endpoint'),location.origin+'/v1');details.append(title,resources);body.append(details);
   }
   const missing=results.map((r,i)=>r.status==='rejected'?['health','status','inference-backends','metrics'][i]:null).filter(Boolean);
   if(missing.length){const note=document.createElement('p');note.className='service-health-note';note.textContent=t('Dati non disponibili: ','Unavailable data: ')+missing.join(', ');body.append(note);}
   dialog.querySelector('.service-health-time').textContent=t('Verificato alle ','Checked at ')+new Date().toLocaleTimeString(en()?'en-US':'it-IT')+' · '+Math.round(performance.now()-started)+' ms '+t('per il controllo','for the check');
  }finally{if(controller===request){button.disabled=false;button.textContent=t('Aggiorna stato','Refresh status');}}
 }
 root.StrataServiceHealth={open:()=>{init();if(!dialog.open){returnFocus=document.activeElement;dialog.showModal();}refresh();}};
})(globalThis);

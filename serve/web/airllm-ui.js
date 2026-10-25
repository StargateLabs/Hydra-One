(()=>{
 const t=(it,en)=>document.documentElement.lang==='en'?en:it;
 let timer;
 function mount(box){
  if(box.querySelector('.airllm-runtime'))return;
  box.innerHTML='<section class="airllm-runtime up-update-action"><h3><img class="engine-brand-logo" src="web/brand-airllm.png" alt="" width="44" height="44">AirLLM</h3><p class="airllm-copy"></p><p class="airllm-state" role="status"></p><button type="button" class="st-btn st-btn--primary"></button><p class="airllm-help"></p><a href="https://github.com/lyogavin/airllm" target="_blank" rel="noopener noreferrer"></a></section>';
  box.querySelector('button').onclick=async()=>{const b=box.querySelector('button');b.disabled=true;try{const r=await fetch('airllm/prepare',{method:'POST',headers:headers(true),body:'{}'});const data=await r.json();if(!r.ok)throw Error(data.error?.message||r.status);paint(box,data);poll();}catch(e){box.querySelector('.airllm-state').textContent=e.message;b.disabled=false;}};
 }
 function paint(box,data){
  mount(box);const active=data.job?.state==='preparing';
  box.querySelector('.airllm-copy').textContent=t('Carica un livello alla volta dal disco. Pensato per ridurre la memoria occupata dai pesi; la velocità dipende da modello, disco e CPU.','Loads one layer at a time from disk. Designed to reduce resident weight memory; speed depends on model, disk and CPU.');
  box.querySelector('.airllm-state').textContent=data.job?.error||(active?t('Preparazione dell’ambiente CPU separato…','Preparing separate CPU environment…'):data.installed?'AirLLM '+data.version+' · '+t('dipendenze verificate','dependencies checked'):t('Ambiente AirLLM da preparare','AirLLM environment needs preparation'));
  const b=box.querySelector('button');b.textContent=data.installed?t('Prepara aggiornamento AirLLM','Prepare AirLLM update'):t('Prepara AirLLM · CPU','Prepare AirLLM · CPU');b.disabled=active||data.can_prepare===false;
  box.querySelector('.airllm-help').textContent=t('Nella scheda Modello scegli Safetensors; in Gestione risorse apri Calcolo e loader e scegli AirLLM. Prima conversione: serve spazio per una copia dei livelli. Gli originali vengono conservati. GPU, compressione e modelli con codice remoto non sono abilitati in questa integrazione.','Choose Safetensors in the Model card; open Compute and loader in Resources and select AirLLM. First conversion needs space for a layer copy. Originals are retained. GPU, compression and remote-code models are not enabled in this integration.');
  let restore=box.querySelector('.airllm-rollback');if(!restore){restore=document.createElement('button');restore.type='button';restore.className='st-btn st-btn--secondary airllm-rollback';restore.onclick=async()=>{restore.disabled=true;try{const r=await fetch('airllm/rollback',{method:'POST',headers:headers(true),body:'{}'});const result=await r.json();if(!r.ok)throw Error(result.error?.message||r.status);paint(box,result);}catch(error){box.querySelector('.airllm-state').textContent=error.message;}};box.querySelector('.airllm-help').before(restore);}restore.textContent=t('Ripristina AirLLM precedente','Restore previous AirLLM');restore.hidden=!data.can_rollback;restore.disabled=active||data.can_prepare===false;
  box.querySelector('a').textContent=t('Documentazione ufficiale ↗','Official documentation ↗');
 }
 async function refresh(){try{const r=await fetch('airllm',{headers:headers(),cache:'no-store'});if(!r.ok)return;const data=await r.json();document.querySelectorAll('[data-airllm-runtime]').forEach(box=>paint(box,data));if(data.job?.state==='preparing'){if(!timer)timer=setInterval(refresh,2500);}else{clearInterval(timer);timer=null;}}catch(e){document.querySelectorAll('.airllm-state').forEach(box=>box.textContent=e.message);}}
 function poll(){if(!timer)timer=setInterval(refresh,2500);refresh();}
 window.StrataAirLLMUI={render(box){box.dataset.airllmRuntime='';mount(box);refresh();}};
 const loader=document.getElementById('backend-python-loader');if(loader){const box=document.createElement('div');box.dataset.airllmRuntime='';loader.closest('label').after(box);const update=()=>{box.hidden=loader.value!=='airllm';if(!box.hidden){mount(box);refresh();}};loader.addEventListener('change',update);update();}
 window.addEventListener('strata:languagechange',refresh);window.addEventListener('pagehide',()=>clearInterval(timer));
})();

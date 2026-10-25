/* Opening an installed audio engine's configuration prepares that engine once. */
(()=>{
 const el=id=>document.getElementById(id),panel=el('local-audio-panel');if(!panel)return;
 const flights=new Map();
 window.StrataConfiguration={waitForMediaPreparation:()=>flights.get('generation')};
 async function activate(tool){
  if(flights.has(tool))return flights.get(tool);
  const config=tool==='asr'?{endpoint:'local-audio',model:'audio-model',state:'audio-state'}:
   tool==='tts'?{endpoint:'local-speech',model:'speech-model',state:'speech-state'}:null;
  if(!config){
   if(!['image','video','music','voice_conversion'].includes(tool))return;
   if(flights.has('generation'))return flights.get('generation');
   const preparation=(async()=>{try{
    const states=await Promise.all(['local-audio','local-speech'].map(async endpoint=>{
     const response=await fetch(endpoint,{headers:headers(),cache:'no-store'});
     const state=await response.json();if(!response.ok)throw Error(state.error?.message||response.status);
     return {endpoint,state};
    }));
    if(states.some(({state})=>state.busy||state.status==='loading'))return;
    for(const {endpoint,state}of states)if(state.status==='ready'){
     const stopped=await fetch(endpoint+'/stop',{method:'POST',headers:headers(true),body:JSON.stringify({automatic_idle:true})});
     const result=await stopped.json();if(!stopped.ok)throw Error(result.error?.message||stopped.status);
    }
   }catch(error){el('generation-status').textContent=error.message;}})();
   flights.set('generation',preparation);try{await preparation;}finally{flights.delete('generation');}return;
  }
  const flight=(async()=>{try{
   const response=await fetch(config.endpoint,{headers:headers(),cache:'no-store'});
   const state=await response.json();if(!response.ok)throw Error(state.error?.message||response.status);
   if(!state.installed||state.busy||!['idle','error'].includes(state.status))return;
   const model=el(config.model)?.value||state.models?.[0]?.path;if(!model)return;
   const payload={model_path:model};
   if(tool==='asr')payload.threads=Number(el('audio-threads').value);
   else payload.reference_path=el('speech-reference')?.value.trim()||undefined;
   el(config.state).textContent=document.documentElement.lang.startsWith('en')?'Starting configured engine…':'Avvio del motore configurato…';
   const started=await fetch(config.endpoint+'/start',{method:'POST',headers:headers(true),body:JSON.stringify(payload)});
   const result=await started.json();if(!started.ok)throw Error(result.error?.message||started.status);
  }catch(error){el(config.state).textContent=error.message;}})();
  flights.set(tool,flight);try{await flight;}finally{flights.delete(tool);}
 }
 document.addEventListener('click',event=>{const button=event.target.closest('.media-tool');if(button&&button.getAttribute?.('aria-pressed')!=='false')activate(button.dataset.tool);});
 el('media-tool-choice')?.addEventListener('change',event=>activate(event.target.value));
 panel.addEventListener('toggle',()=>{if(panel.open){const tool=document.querySelector?.('.media-tool[aria-pressed="true"]')?.dataset.tool||'asr';activate(tool);}});
})();

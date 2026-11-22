/* Release managed services after leaving their UI; active jobs keep running. */
(()=>{
 const timers=new Map(),delay=30000;
 function cancel(key){clearTimeout(timers.get(key));timers.delete(key);}
 function schedule(key,config){cancel(key);timers.set(key,setTimeout(async()=>{
  timers.delete(key);if(config.inUse?.())return;
  try{const response=await fetch(config.status,{headers:headers(true),cache:'no-store'});if(!response.ok)return;const state=await response.json();
   // The configuration can reopen while the status request is in flight.
   if(config.inUse?.())return;
   if(!config.rendererOnly&&(state.busy||['running','generating','loading','starting'].includes(state.status))){schedule(key,config);return;}
   if(state.status==='idle'||state.status==='stopped'||state.installed===false)return;
   const stopped=await fetch(config.stop,{method:'POST',headers:headers(true),body:'{"automatic_idle":true}'});
   if(!stopped.ok||(await stopped.json()).busy)schedule(key,config);
  }catch{schedule(key,config);}
 },delay));}
 window.StrataIdleRelease={schedule,cancel};
 const el=id=>document.getElementById(id),panel=el('local-audio-panel'),control=el('view-control');
 const media=[['audio',{status:'local-audio',stop:'local-audio/stop',tool:'asr'}],['speech',{status:'local-speech',stop:'local-speech/stop',tool:'tts'}],['voicestudio',{status:'voicestudio',stop:'voicestudio/stop',tool:'voicestudio'}]];
 function update(){const active=el('media-tool-choice')?.value;for(const[key,config]of media){config.inUse=()=>panel?.open&&!control?.hidden&&el('media-tool-choice')?.value===config.tool;const used=panel?.open&&!control?.hidden&&active===config.tool;if(used)cancel(key);else if(!timers.has(key))schedule(key,config);}}
 panel?.addEventListener('toggle',update);el('media-tool-choice')?.addEventListener('change',update);
 document.addEventListener('click',event=>{if(event.target.closest('.media-tool'))update();});
 if(control)new MutationObserver(update).observe(control,{attributes:true,attributeFilter:['hidden']});
 window.addEventListener('pagehide',()=>{for(const[,config]of media){try{fetch(config.stop,{method:'POST',headers:headers(true),body:'{"automatic_idle":true}',keepalive:true}).catch(()=>{});}catch{}}for(const timer of timers.values())clearTimeout(timer);timers.clear();});
})();

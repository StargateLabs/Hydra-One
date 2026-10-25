/* Select the native adapter without creating a second process or scheduler. */
(()=>{
 let chain=Promise.resolve(),replay=false;
 const selected=()=>window.StrataUnifiedEngine?.selected?.()==='hydra-strata';
 async function apply(){
  const enabled=selected();
  const response=await fetch('hydra/native',{method:'POST',headers:headers(true),body:JSON.stringify({enabled})});
  const result=await response.json();
  if(!response.ok)throw Error(result.error?.message||'Selezione HYDRA non riuscita');
  window.StrataNativeHydraState=result;
  return result;
 }
 function report(error){const notice=document.getElementById('unified-engine-notice');if(notice)notice.textContent=error.message;}
 document.addEventListener('strata:engine-selected',()=>{
  chain=chain.catch(()=>{}).then(apply);chain.catch(report);
 });
 // Await successful binding before the existing native load/switch handlers.
 for(const id of ['ctrl-load','ctrl-switch'])document.getElementById(id)?.addEventListener('click',async event=>{
  if(replay)return;
  event.preventDefault();event.stopImmediatePropagation();const button=event.currentTarget;
  try{await chain;await apply();replay=true;button.click();}
  catch(error){report(error);}
  finally{replay=false;}
 },true);
 // Reloading a page must not silently disable an active native adapter.
 fetch('hydra/native',{headers:headers(),cache:'no-store'}).then(response=>{
  if(!response.ok)throw Error('Stato HYDRA nativo non disponibile');return response.json();
 }).then(state=>{window.StrataNativeHydraState=state;if(state.enabled)window.StrataUnifiedEngine?.select('hydra-strata');else if(selected()){chain=chain.catch(()=>{}).then(apply);chain.catch(report);}}).catch(report);
})();

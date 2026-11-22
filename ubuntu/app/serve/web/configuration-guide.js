/* Guides belong to the configuration fields, never to the main menus. */
(()=>{
 const t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it;
 const rows=[['backend-mode','Il motore viene riconosciuto dal modello; la scelta manuale resta disponibile.','The engine is identified from the model; manual selection remains available.'],['backend-local-model','Scegli il modello per primo. Il formato determina il motore e le configurazioni compatibili.','Choose the model first. Its format determines the engine and compatible settings.']];
 let pending=false;
 function ensure(){pending=false;document.querySelectorAll('.config-section-number').forEach(element=>element.remove());document.querySelectorAll('details > .config-section-guide').forEach(element=>element.remove());for(const[id,it,en]of rows){const field=document.getElementById(id),label=field?.closest('label');if(!label)continue;let guide=label.querySelector('.config-field-guide');if(!guide){guide=document.createElement('small');guide.className='config-field-guide';guide.dataset.i18nIgnore='';label.append(guide);}const copy=t(it,en);if(guide.textContent!==copy)guide.textContent=copy;}}
 function schedule(){if(!pending){pending=true;requestAnimationFrame(ensure);}}
 function initialize(){ensure();const form=document.getElementById('backend-form');if(form)new MutationObserver(schedule).observe(form,{childList:true,subtree:true});new MutationObserver(schedule).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initialize,{once:true});else initialize();
})();

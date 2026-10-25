/* Present existing native controls; their IDs, validation and save handlers stay intact. */
(()=>{
 const dialog=document.getElementById('backend-config-dialog');if(!dialog)return;
 const el=id=>document.getElementById(id),t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it;
 const strip=document.createElement('div');strip.className='backend-config-status-strip';strip.setAttribute('role','status');strip.setAttribute('aria-live','polite');dialog.querySelector('.catalogue-dialog-head').after(strip);
 const chips={};for(const key of ['engine','device','context','detail','save']){const chip=document.createElement('span'),label=document.createElement('small'),value=document.createElement('strong');chip.className='backend-config-chip';chip.dataset.kind=key;chip.append(label,value);strip.append(chip);chips[key]={label,value};}
 const note=document.createElement('p');note.className='backend-config-support-note';dialog.querySelector('.backend-guide-copy').append(note);
 const put=(node,value)=>{if(node.textContent!==value)node.textContent=value;};let scheduled=false;
 function update(){scheduled=false;const mode=el('backend-mode')?.value,external=mode==='api',context=Number(el('backend-context')?.value),gpu=el('backend-gpu')?.checked;
  const values={engine:[t('Motore','Engine'),({gguf:'llama.cpp · GGUF',safetensors:'Python · Safetensors',api:t('API configurata','Configured API')})[mode]||t('Motore selezionato','Selected engine')],device:[t('Esecuzione','Execution'),external?t('Gestita dal servizio','Managed by service'):gpu?'GPU':'CPU'],context:[t('Contesto scelto','Selected context'),external?t('Gestito dal servizio','Managed by service'):Number.isFinite(context)&&context>0?context.toLocaleString(document.documentElement.lang)+' token':'—'],detail:[t('Vista','View'),dialog.dataset.detail==='advanced'?t('Tutti i parametri','All parameters'):t('Essenziali','Essentials')],save:[t('Applicazione','Application'),t('Al prossimo caricamento','On next load')]};
  for(const [key,pair]of Object.entries(values)){put(chips[key].label,pair[0]);put(chips[key].value,pair[1]);}
  put(note,t('I campi seguono il motore selezionato. Stime di memoria e valori caricati sono distinti.','Fields follow the selected engine. Memory estimates and loaded values are distinct.'));
  strip.setAttribute('aria-label',t('Riepilogo delle scelte del modello','Model settings summary'));
 }
 function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(update);}}
 dialog.addEventListener('input',schedule);dialog.addEventListener('change',schedule);dialog.addEventListener('click',schedule);
 new MutationObserver(schedule).observe(dialog,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['open','hidden','disabled','data-section','data-detail']});
 new MutationObserver(schedule).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});update();
})();

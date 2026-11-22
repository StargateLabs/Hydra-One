/* One existing Control menu owns all media views; original controllers remain intact. */

(()=>{

 const el=id=>document.getElementById(id),panel=el('local-audio-panel'),tabs=el('audio-mode-tabs'),generation=el('generation-panel');if(!panel||!tabs||!generation)return;

 const t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it;

 const workspace=panel.querySelector('.training-workspace'),intro=workspace.querySelector('.training-intro'),voiceStudio=el('voicestudio-panel');

 const baseViews=[el('audio-form')?.closest('.training-layout'),el('speech-form')?.closest('.training-layout'),el('audio-separation-view')].filter(Boolean);

 const library=workspace.querySelector('.speech-library'),libraryPage=document.createElement('section');libraryPage.id='studio-library-page';libraryPage.hidden=true;libraryPage.dataset.i18nIgnore='true';if(library)libraryPage.append(library);workspace.append(libraryPage);if(voiceStudio)voiceStudio.hidden=true;

 const visionPage=document.createElement('section');visionPage.id='studio-vision-page';visionPage.hidden=true;visionPage.dataset.i18nIgnore='true';workspace.append(visionPage);const visionCopy=document.createElement('p');visionCopy.id='studio-vision-help';const visionSteps=document.createElement('ol');visionSteps.className='studio-vision-steps';for(const id of ['studio-vision-model','studio-vision-attach','studio-vision-ask']){const item=document.createElement('li');item.id=id;visionSteps.append(item);}const visionActions=document.createElement('div');visionActions.className='training-profile-actions';visionPage.append(visionCopy,visionSteps,visionActions);

 const originalButtons=[...tabs.querySelectorAll('button')];

 function hideExtras(){current=null;generation.hidden=true;libraryPage.hidden=true;visionPage.hidden=true;if(voiceStudio)voiceStudio.hidden=true;intro.hidden=false;for(const button of tabs.querySelectorAll('[data-studio-view]'))button.setAttribute('aria-pressed','false');}

 for(const button of originalButtons){const previous=button.onclick;button.onclick=event=>{hideExtras();previous?.call(button,event);};}

 const definitions=[['image','Immagini','Images'],['video','Video','Video'],['music','Musica','Music'],['effects','Suoni · AudioGen','Sounds · AudioGen'],['style','MusicGen Style','MusicGen Style'],['jasco','JASCO','JASCO'],['codec','Codec · EnCodec','Codec · EnCodec'],['magnet','MAGNeT · Meta','MAGNeT · Meta'],['watermark','AudioSeal · watermark','AudioSeal · watermark'],['mbd','MultiBand Diffusion','MultiBand Diffusion'],['voice_conversion','Conversione voce','Voice conversion'],['voicestudio','VoiceStudio','VoiceStudio'],['library','Libreria','Library'],['vision','Analisi immagini','Image analysis']];

 let current=null;

 for(const[name,it,en]of definitions){const button=document.createElement('button');button.type='button';button.dataset.studioView=name;button.id='studio-mode-'+name;button.setAttribute('aria-pressed','false');button.textContent=t(it,en);tabs.append(button);

  button.onclick=()=>{

   const task=el('generation-task');task.closest('label').hidden=true;if(['image','video','music','effects','codec','magnet','watermark','mbd','style','jasco','voice_conversion'].includes(name)&&task.disabled&&task.value!==name){el('generation-status').textContent=t('Attendi o annulla l’operazione prima di cambiare tipo.','Wait or cancel the operation before changing type.');return;}

   originalButtons[0].onclick();for(const view of baseViews)view.hidden=true;intro.hidden=true;current=name;

   for(const other of tabs.querySelectorAll('button'))other.setAttribute('aria-pressed',String(other===button));

   if(name==='voicestudio'){if(voiceStudio)voiceStudio.hidden=false;window.StrataVoiceStudio?.openConfiguration();}

   else if(name==='vision'){visionPage.hidden=false;}

   else if(name==='library'){libraryPage.hidden=false;if(library)library.open=true;}

   else{generation.hidden=false;task.value=name;task.dispatchEvent(new Event('change'));el('generation-refresh').click();}

  };

 }

 // Vision inference belongs to the selected model. Link to its existing controls

 // instead of duplicating or detaching them from the original loading form.

 const vision=document.createElement('button');vision.type='button';vision.id='studio-open-vision';vision.className='st-btn st-btn--secondary';vision.dataset.i18nIgnore='true';vision.onclick=()=>{const engine=window.StrataUnifiedEngine?.selected()||el('backend-mode')?.value;let target=engine==='strata'?el('ctrl-vision'):engine==='gguf'?el('backend-vision'):engine==='api'?el('backend-id'):el('backend-file');for(let parent=target?.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;if(!target?.getClientRects().length)target=el('unified-engine')?.closest('label');target?.scrollIntoView({block:'center',behavior:'auto'});target?.focus();};visionActions.append(vision);const visionChat=document.createElement('button');visionChat.type='button';visionChat.id='studio-vision-chat';visionChat.className='st-btn st-btn--primary';visionChat.onclick=()=>{el('tab-btn-chat').click();el('attach-btn').focus();};visionActions.append(visionChat);

 const translate=()=>{visionCopy.textContent=t('L’analisi usa il modello di chat, non il generatore di immagini. Serve un modello con capacità visive confermate dal motore. Per GGUF, configura anche il proiettore corrispondente quando richiesto.','Analysis uses the chat model, not the image generator. A model with engine-confirmed vision capabilities is required. For GGUF, configure the matching projector when needed.');el('studio-vision-model').textContent=t('Scegli e configura un modello che comprende immagini.','Choose and configure a model that understands images.');el('studio-vision-attach').textContent=t('Apri la chat e allega l’immagine con il pulsante degli allegati.','Open chat and attach the image using the attachment button.');el('studio-vision-ask').textContent=t('Scrivi cosa vuoi analizzare: contenuti, dettagli o testo nell’immagine.','Describe what to analyse: contents, details or text in the image.');visionChat.textContent=t('Apri chat per analizzare','Open chat to analyse');for(const[name,it,en]of definitions)el('studio-mode-'+name).textContent=t(it,en);vision.textContent=t('Analisi delle immagini · configura il modello','Image analysis · configure the model');if(current&&['image','video','music','voice_conversion'].includes(current))intro.hidden=true;};

 new MutationObserver(translate).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});translate();

})();


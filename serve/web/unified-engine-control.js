/* Rehome the existing controllers and DOM. Never duplicate their controls. */
(()=>{
 const el=id=>document.getElementById(id),t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it;
 const form=el('backend-form'),grid=document.querySelector('#view-control .dash4');if(!form||!grid)return;
 const cards={model:grid.querySelector('.dash-card--model'),run:grid.querySelector('.dash-card--run'),resources:grid.querySelector('.dash-card--res'),monitor:grid.querySelector('.dash-card--pm')};
 const original={},optional={};for(const[key,card]of Object.entries(cards)){original[key]=[...card.children].filter(node=>!node.classList.contains('dash-head'));const slot=document.createElement('div');slot.className='dash-body unified-engine-extra';slot.dataset.engineSection=key;optional[key]=slot;card.append(slot);}
 const resourceTiles=el('ctrl-dl-size').closest('.dm--full'),modelHint=el('hint-ctrl-model');
 const sharedModelSummary=document.createElement('div');sharedModelSummary.className='dash-body unified-engine-extra shared-model-summary';sharedModelSummary.dataset.i18nIgnore='';sharedModelSummary.append(resourceTiles,modelHint);cards.model.append(sharedModelSummary);
 const leftovers=[...form.children];form.classList.add('dash4','unified-engine-control');grid.replaceWith(form);form.replaceChildren(cards.model,cards.resources,cards.monitor,cards.run);
 for(const field of document.querySelectorAll('input[id^="backend-"]:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="file"]),select[id^="backend-"],textarea[id^="backend-"]'))field.classList.add('st-input');
 for(const button of form.querySelectorAll('button'))button.type='button';
 const move=(node,key)=>{if(node)optional[key].append(node);};
 for(const node of leftovers)move(node,node.id==='backend-choose-step'?'model':node.classList.contains('backend-actions')||['backend-load-progress','backend-error'].includes(node.id)?'run':'resources');
 for(const field of form.querySelectorAll('input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="file"]),select,textarea'))field.classList.add('st-input');
 const adapterNote=el('backend-native-note');if(adapterNote)el('backend-manual').append(adapterNote);
 const manual=el('backend-manual'),manualFields=document.createElement('div');manualFields.className='unified-manual-fields';for(const node of [...manual.children])if(node.tagName!=='SUMMARY')manualFields.append(node);manual.append(manualFields);
 const facts=el('backend-model-facts'),factsDetails=document.createElement('details');factsDetails.className='unified-model-details';const factsSummary=document.createElement('summary');factsSummary.textContent=t('Informazioni e compatibilità del modello','Model information and compatibility');facts.replaceWith(factsDetails);factsDetails.append(factsSummary,facts);
 const shared=(node,key)=>{const slot=document.createElement('div');slot.className='unified-engine-shared dm dm--full';slot.append(node);cards[key].append(slot);};
 const intro=el('backend-model').closest('.backend-intro');move(factsDetails,'model');const inference=document.querySelector('#view-monitor .dash-card--inf .dash-body'),system=document.querySelector('#view-monitor .dash-card--cpu .dash-body');const activity=intro.querySelector('.backend-timeline'),liveResources=intro.querySelector('.backend-live');activity.classList.add('engine-monitor-section');liveResources.classList.add('engine-monitor-section');inference.append(activity);system.append(liveResources);const monitorVisibility=()=>{const state=typeof lastMetrics==='undefined'?null:lastMetrics?.optional_backend,active=['ready','loading'].includes(state?.status);activity.hidden=!active;liveResources.hidden=!active;};window.addEventListener('strata:metrics',monitorVisibility);monitorVisibility();move(intro,'run');
 shared(el('backend-endpoint').closest('.backend-api-access'),'run');cards.run.querySelector('.dash-head').append(el('backend-state'));cards.model.querySelector('.dash-head').append(el('backend-count-badge'));
 const mode=el('backend-mode'),modeLabel=mode.closest('label');modeLabel.hidden=true;
 const label=document.createElement('label');label.className='dm dm--full unified-engine-picker';label.dataset.i18nIgnore='';const caption=document.createElement('span');caption.className='dm__label';const select=document.createElement('select');select.id='unified-engine';select.append(new Option('Hydra One','strata'));const hydraOption=new Option('HYDRA ONE™ (HYBRID By StargateLab™)','hydra-strata');select.append(hydraOption);for(const option of mode.options)if(!option.value.startsWith('hydra-'))select.append(new Option(option.textContent,option.value));select.append(new Option('Colibri','colibri'));label.append(caption,select);cards.model.querySelector('.dash-body').prepend(label);
 const browse=document.querySelector('.local-model-browse');if(browse){const common=document.createElement('div');common.className='dm dm--full unified-model-browser';common.hidden=true;common.append(browse,el('backend-manage-local'));label.before(common);}const catalogue=el('optional-catalogue-open');catalogue.classList.add('model-catalogue-access');catalogue.setAttribute('aria-haspopup','dialog');catalogue.setAttribute('aria-controls','optional-catalogue-dialog');cards.model.querySelector('.dash-head').append(catalogue);
 const visionOptions=document.querySelector('.model-vision-options');if(visionOptions)move(visionOptions,'resources');
 const resourceNotice=document.createElement('p');resourceNotice.className='unified-resource-notice';resourceNotice.setAttribute('role','status');optional.resources.prepend(resourceNotice);
 const computeGroup=el('backend-config-group-compute')?.closest('fieldset'),computePage=el('backend-config-page-compute'),configDialog=el('backend-config-dialog');
 const computeDetails=document.createElement('details'),computeSummary=document.createElement('summary');computeDetails.className='unified-model-details unified-compute-portal';computeDetails.dataset.i18nIgnore='';computeDetails.append(computeSummary);optional.resources.append(computeDetails);
 function placeCompute(){if(!computeGroup)return;const target=configDialog.open&&configDialog.dataset.section==='compute'?computePage:computeDetails;if(computeGroup.parentElement!==target)target.append(computeGroup);}
 new MutationObserver(placeCompute).observe(configDialog,{attributes:true,attributeFilter:['open','data-section']});placeCompute();
 const activeNotice=document.createElement('div');activeNotice.className='unified-engine-shared dm dm--full';const activeCopy=document.createElement('p');activeCopy.className='dm__sub';activeNotice.append(activeCopy);cards.run.append(activeNotice);const actions=el('backend-start').parentElement;
 // Pair the existing controls without cloning fields or leaving their owner panels.
 const modelBody=cards.model.querySelector('.dash-body'),nativeModelPicker=el('ctrl-model').closest('.dm');
 const localModelPicker=el('backend-local-model').closest('label'),apiModelPicker=el('backend-id').closest('label');
 const selectorRows=new Map();
 function placeModelSelectors(){
  const hydra=selected.startsWith('hydra-'),colibri=selected==='colibri';
  const picker=hydra?document.querySelector('#hydra-model-library .hydra-library-picker'):colibri?document.querySelector('.colibri-compatible-picker'):selected==='strata'?nativeModelPicker:selected==='api'?apiModelPicker:localModelPicker;
  if(!picker)return; // Colibri and Hydra create their own fields later in page setup.
  const host=hydra?el('hydra-model-library'):colibri||selected==='strata'?modelBody:selected==='api'?el('backend-api-fields'):el('backend-gguf-fields');
  let row=selectorRows.get(host);
  if(!row){row=document.createElement('div');row.className='unified-model-selectors';selectorRows.set(host,row);if(hydra)picker.before(row);else host.prepend(row);}
  for(const item of selectorRows.values()){item.hidden=item!==row;for(const child of item.children)if(child!==label)child.hidden=child!==picker;}
  if(label.parentElement!==row)row.prepend(label);
  if(picker.parentElement!==row)row.append(picker);
  row.hidden=false;picker.hidden=false;label.hidden=false;
 }
 const runRows=new Map(),endpointPanel=el('backend-endpoint').closest('.unified-engine-shared');
 const optionalRunCommand=document.createElement('div');optionalRunCommand.className='unified-run-command';intro.before(optionalRunCommand);optionalRunCommand.append(intro,actions);
 function placeRunToolbar(){
  const native=['strata','hydra-strata'].includes(selected);
  const command=native?el('ctrl-load').closest('.dm'):selected==='colibri'?el('colibri-engine-stop')?.closest('.colibri-controls'):optionalRunCommand;
  if(!command)return;
  const host=native?cards.run.querySelector('.dash-body'):optional.run;
  let row=runRows.get(host);
  if(!row){row=document.createElement('div');row.className='unified-run-toolbar';runRows.set(host,row);command.before(row);}
  for(const item of runRows.values()){item.hidden=item!==row;for(const child of item.children)if(child!==endpointPanel)child.hidden=child!==command;}
  if(command.parentElement!==row)row.prepend(command);
  if(endpointPanel.parentElement!==row)row.append(endpointPanel);
  row.hidden=false;command.hidden=false;
 }
 const notice=document.createElement('p');notice.id='unified-engine-notice';notice.className='dm__sub';notice.setAttribute('role','status');label.append(notice);
 let savedEngine=null;try{savedEngine=localStorage.getItem('strata-unified-engine');}catch{}
 const initialBackend=window.StrataOptional?.state?.();let selected=([...select.options].some(option=>option.value===savedEngine)||window.StrataHydraChoice.routes.includes(savedEngine))?savedEngine:initialBackend?.status==='ready'?(initialBackend.publisher==='colibri'?'colibri':(initialBackend.engine_addon==='hydra-one'?'hydra-'+initialBackend.mode:initialBackend.mode)||mode.value):'strata';if(selected.startsWith('hydra-'))hydraOption.value=selected;select.value=selected;
 const hydraRunContext=document.createElement('p');hydraRunContext.className='dm__sub unified-engine-shared';hydraRunContext.dataset.i18nIgnore='';hydraRunContext.setAttribute('role','status');cards.run.querySelector('.dash-head').after(hydraRunContext);
 const thermalContext=document.createElement('p');thermalContext.className='dm__sub unified-engine-shared';thermalContext.dataset.i18nIgnore='';thermalContext.setAttribute('role','status');cards.monitor.querySelector('.dash-head').after(thermalContext);
 // Native power controls cannot govern optional backends; physical sensors remain shared.
 const nativeThermalGroups=[...new Set(['ctrl-power-mode','ctrl-temp-limit','ctrl-power-limit','ctrl-apply-power','ms-ctrl-power-state'].map(id=>el(id)?.closest('.dm')).filter(Boolean))];
 const drafts=new Map();let switching=false;
 const power=document.createElement('button');power.id='engine-power-toggle';power.type='button';power.className='st-btn engine-power-toggle';power.dataset.i18nIgnore='';
 power.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v8M6.3 5.8a9 9 0 1 0 11.4 0"/></svg><span></span>';
 let nativeLoaded=null,nativeBusy=false,powerPending=null;
 function renderPower(){
  const native=['strata','hydra-strata'].includes(selected),active=window.StrataOptional?.state?.()||{};
  const colibri=window.StrataColibriControls?.data?.()?.workspace||window.StrataColibri?.state?.()||{};
  const targetParent=native?el('ctrl-load').parentElement:selected==='colibri'&&el('colibri-engine-stop')?el('colibri-engine-stop').parentElement:actions;
  if(power.parentElement!==targetParent)targetParent.prepend(power);
  const state=window.StrataEnginePower.powerState({route:selected,nativeLoaded,nativeBusy,optional:active,colibri,pending:powerPending,
   startDisabled:native?!el('ctrl-load').onclick:selected==='colibri'?!el('colibri-start')||el('colibri-start').disabled:el('backend-start').disabled,
   stopDisabled:el('backend-stop').disabled,colibriStopDisabled:!el('colibri-engine-stop')||el('colibri-engine-stop').disabled,english:document.documentElement.lang.startsWith('en')});
  power.dataset.tone=state.tone;power.dataset.target=state.target;power.disabled=state.disabled;power.setAttribute('aria-busy',String(state.tone==='pending'));power.querySelector('span').textContent=state.label;
  power.title=state.target==='backend-stop'&&active.mode==='api'?t('Disconnette il modello dalla chat; il server collegato gestisce il proprio processo.','Disconnects the model from chat; the connected server owns its process.'):state.disabled&&nativeBusy?t('Attendi la fine della richiesta attiva.','Wait for the active request to finish.'):state.label;
 }
 async function refreshPowerHealth(){try{const response=await fetch('health');if(response.ok){const data=await response.json();nativeLoaded=!!data.loaded;}}catch{}renderPower();}
 power.onclick=async()=>{
  if(power.disabled)return;const target=power.dataset.target;
  if(target==='backend-start'){form.requestSubmit();renderPower();return;}
  powerPending=target.endsWith('stop')||target==='ctrl-unload'?'stop':'start';renderPower();
  try{if(target==='backend-stop')await window.StrataOptional.stop();else{await el(target).onclick.call(el(target));if(target==='colibri-start'){await window.StrataColibri.refresh();if(window.StrataColibri.state().status==='ready')await window.StrataColibri.connect();}}}
  finally{powerPending=null;await refreshPowerHealth();}
 };
 document.addEventListener('strata:controlstate',event=>{const state=event.detail.state;if(typeof state==='string'){nativeLoaded=state!=='unloaded';nativeBusy=['reading','generating'].includes(state);}renderPower();});
 function snapshot(){return [...document.querySelectorAll('[id^="backend-"]')].filter(field=>field.matches('input,select,textarea')&&field!==mode).map(field=>[field.id,field.type==='checkbox'?field.checked:field.value]);}
 function restore(value){for(const[id,saved]of drafts.get(value)||[]){const field=el(id);if(field.type==='checkbox')field.checked=saved;else field.value=saved;}}
 function choose(value){if(switching||!['strata','hydra-strata','colibri'].includes(value)&&![...mode.options].some(option=>option.value===value))return;const changed=value!==selected;if(changed)drafts.set(selected,snapshot());selected=value;if(value.startsWith('hydra-'))hydraOption.value=value;select.value=value;try{localStorage.setItem('strata-unified-engine',value);}catch{}switching=true;try{const backendMode=value==='colibri'?'api':value;if(!['strata','hydra-strata'].includes(value)&&mode.value!==backendMode){mode.value=backendMode;mode.dispatchEvent(new Event('change',{bubbles:true}));}if(changed)restore(value);if(!['strata','hydra-strata'].includes(value))window.StrataOptional?.refreshConfiguration();}finally{switching=false;}render();document.dispatchEvent(new CustomEvent('strata:engine-selected',{detail:{engine:value}}));}
 function render(){const native=['strata','hydra-strata'].includes(selected),api=['api','colibri'].includes(selected);form.dataset.engine=selected;for(const key of Object.keys(cards)){if(key!=='monitor')for(const node of original[key])node.hidden=!native;optional[key].hidden=native;}
  sharedModelSummary.hidden=false;resourceTiles.hidden=false;modelHint.hidden=false;
  if(!native){
   const model=api?{name:el('backend-id').value,remote:true}:window.StrataOptional?.localModels().find(row=>row.path===el('backend-file').value)||{name:el('backend-file').value.split(/[\\/]/).pop()};
   const data=window.StrataModelResourceSummary.summary(model,window.StrataOptional?.resourcePreview?.(),el('backend-context').value,document.documentElement.lang.startsWith('en'));
   el('ctrl-dl-size').textContent=data.size;el('ctrl-dl-size').nextElementSibling.textContent=t('Pesi locali','Local weights');el('ctrl-ram-req').textContent=data.need;
   const hardware=typeof lastMetrics==='undefined'?{}:lastMetrics?.hardware||{};
   el('ctrl-vram-req').textContent=[hardware.ram_total,hardware.gpu_mem_total].map(value=>Number.isFinite(value)?(value/2**30).toFixed(0):'—').join(' + ')+' GiB';
   modelHint.replaceChildren();const heading=document.createElement('b'),copy=document.createElement('span');heading.textContent=t('Risorse del modello','Model resources');copy.textContent=data.note;modelHint.append(heading,copy);
  }else{el('ctrl-dl-size').nextElementSibling.textContent=t('Pesi locali','Local weights');window.StrataNativeResources?.refresh();}
  for(const group of nativeThermalGroups)group.hidden=!native;for(const id of ['ctrl-pm-stat','ctrl-pm-eff']){const node=el(id);if(node)(id==='ctrl-pm-eff'?node.parentElement:node).hidden=!native;}el('ctrl-power-status').hidden=!native;el('hint-ctrl-power').hidden=!native;thermalContext.hidden=native;
  thermalContext.textContent=t('Sensori del PC · temperatura e potenza osservate. I profili termici del backend nativo non controllano questo percorso.','PC sensors · observed temperature and power. Native backend thermal profiles do not control this path.');
  const hydra=selected.startsWith('hydra-');hydraRunContext.hidden=!hydra;hydraRunContext.textContent=native?t('Configura le risorse del modello selezionato e gestisci il motore HYDRA ONE.','Configure resources for the selected model and manage the HYDRA ONE engine.'):selected==='hydra-gguf'?t('Configura contesto, accelerazione GPU e memoria per il modello GGUF selezionato.','Configure context, GPU acceleration and memory for the selected GGUF model.'):t('Configura caricamento, risorse e contesto per il modello Safetensors selezionato.','Configure loading, resources and context for the selected Safetensors model.');
  const load=el('ctrl-load');load.dataset.i18nIgnore='';const loadText=t(hydra?'Avvia HYDRA ONE':'Avvia Hydra One',hydra?'Start HYDRA ONE':'Start Hydra One');const loadLabel=[...load.childNodes].find(node=>node.nodeType===3&&node.textContent.trim());if(loadLabel)loadLabel.textContent=' '+loadText;else{let copy=load.querySelector('[data-engine-action-label]');if(!copy){copy=document.createElement('span');copy.dataset.engineActionLabel='';load.append(copy);}copy.textContent=loadText;}
  el('ctrl-status').hidden=!native;el('ctrl-resources-status').hidden=!native;el('cat-summary').hidden=!native;el('backend-state').hidden=native;el('backend-count-badge').hidden=native||api;
  const active=window.StrataOptional?.state?.();activeNotice.hidden=!(native&&['ready','loading'].includes(active?.status));activeCopy.textContent=t('Un altro motore è già attivo. Arrestalo prima di caricare questo modello.','Another engine is already active. Stop it before loading this model.');const stopParent=activeNotice.hidden?actions:activeNotice;if(el('backend-stop').parentElement!==stopParent)stopParent.append(el('backend-stop'));
  label.hidden=false;modelBody.hidden=false;const common=browse?.closest('.unified-model-browser');if(common)common.hidden=false;
  // Preserve the native layout while hiding only its model-specific controls.
  if(!native){for(const node of modelBody.children)if(node!==label&&node!==common&&node.id!=='hydra-model-library'&&!node.classList.contains('unified-model-selectors'))node.hidden=true;}
  else{for(const node of modelBody.children)node.hidden=false;}
  // Polling also calls render: keep the Hydra library scoped to its selected engine.
  const hydraLibrary=el('hydra-model-library');if(hydraLibrary)hydraLibrary.hidden=!hydra;
  const hasModel=native||(api?!!el('backend-id').value.trim():!!el('backend-file').value.trim());factsDetails.hidden=native||!hasModel;optional.resources.hidden=native;resourceNotice.hidden=native;resourceNotice.textContent=api?t('La memoria e il calcolo sono gestiti dall’app collegata. Generazione e strumenti appartengono alle impostazioni della chat; il monitor mostra sempre le risorse del PC.','Memory and compute are managed by the connected app. Generation and tools belong to chat settings; the monitor always shows PC resources.'):hasModel?t('Impostazioni del modello selezionato. Il controllo di compatibilità precede ogni caricamento.','Settings for the selected model. Compatibility is checked before each load.'):t('Scegli prima un modello nella scheda Modello. Le impostazioni compatibili restano disponibili qui, senza caricare il motore.','Choose a model in the Model card first. Compatible settings remain available here without loading the engine.');
  computeDetails.hidden=native||api;computeSummary.textContent=t('2. Calcolo e loader del motore','2. Engine compute and loader');placeCompute();
  el('backend-resource-step').hidden=api;for(const page of ['resources','compute'])el('backend-config-tab-'+page).hidden=api;if(api&&['resources','compute'].includes(el('backend-config-dialog').dataset.section))el('backend-config-tab-generation').click();
  for(const[id,brand]of [['backend-manage-local',hydra?'hydra':'strata'],['optional-catalogue-open','huggingface']]){const button=el(id);if(button){const image=button.querySelector('.engine-brand-logo');if(image&&image.dataset.brand!==brand)image.remove();if(!button.querySelector('.engine-brand-logo'))button.insertAdjacentHTML('afterbegin',window.StrataBrands?.markup(brand)||'');}}
  select.options[0].textContent='Hydra One';caption.textContent=t('Motore del modello','Model engine');notice.textContent=selected.startsWith('hydra-')?t('HYDRA ONE: GGUF, Safetensors/LoRA e pack nativi supportati. Compatibilità legata ad architettura, backend e memoria disponibili. Un unico motore: il percorso compatibile viene selezionato dal formato del modello.','HYDRA ONE: GGUF, Safetensors/LoRA and supported native packs. Compatibility depends on architecture, backend and available memory. One engine: the compatible path follows the model format.'):native?t('Configurazione nativa Hydra One. Scegli un modello preparato o sfoglia tutta la libreria.','Native Hydra One configuration. Choose a prepared model or browse the entire library.'):t('Il modello determina le opzioni disponibili. La selezione non arresta il motore già attivo.','The model determines available options. Selection does not stop the active engine.');
  const guide=form.querySelector(':scope > .configuration-assistant');if(guide)optional.resources.prepend(guide);
  renderPower();
  el('backend-api-fields').hidden=selected==='colibri'||!api;el('backend-choose-step').hidden=selected==='colibri';const colibriPanel=el('colibri-workspace');if(colibriPanel)colibriPanel.hidden=selected!=='colibri';const compatiblePicker=document.querySelector('.colibri-compatible-picker');if(compatiblePicker)compatiblePicker.hidden=selected!=='colibri';modeLabel.hidden=true;placeModelSelectors();placeRunToolbar();
 }
 select.addEventListener('change',()=>choose(select.value.startsWith('hydra-')?window.StrataHydraChoice.routeFor(selected):select.value));mode.addEventListener('change',()=>{if(selected==='colibri'){mode.value='api';window.StrataOptional?.refreshConfiguration();return;}choose(selected.startsWith('hydra-')&&['gguf','safetensors','hydra-gguf','hydra-safetensors'].includes(mode.value)?window.StrataHydraChoice.routeFor(mode.value):mode.value);},true);el('ctrl-model').addEventListener('change',()=>{if(!['colibri','hydra-strata'].includes(selected))choose('strata');});el('backend-local-model').addEventListener('change',()=>{if(selected==='colibri')return;const row=window.StrataOptional?.localModels().find(row=>row.path===el('backend-local-model').value);if(row?.required_engine==='strata'){choose(selected.startsWith('hydra-')?'hydra-strata':'strata');window.StrataModelRouting?.show(row);}else choose(selected.startsWith('hydra-')?window.StrataHydraChoice.routeFor(mode.value,row):mode.value);});el('backend-file').addEventListener('change',()=>{if(selected!=='colibri')choose(selected.startsWith('hydra-')?window.StrataHydraChoice.routeFor(mode.value,{path:el('backend-file').value}):mode.value);});el('backend-id').addEventListener('change',render);
 form.addEventListener('submit',event=>{if(['strata','hydra-strata'].includes(selected)){event.preventDefault();event.stopImmediatePropagation();}},true);
 window.StrataUnifiedEngine={select:choose,selected:()=>selected,refresh:render,refreshPower:renderPower};
 new MutationObserver(()=>render()).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
 el('backend-panel').hidden=true;el('backend-panel').open=true;
 choose(selected);document.addEventListener('DOMContentLoaded',render,{once:true});
 refreshPowerHealth();
})();


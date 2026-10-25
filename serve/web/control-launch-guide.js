/* Navigate existing controls. Visiting a step never applies settings or starts a model. */
(()=>{
 const el=id=>document.getElementById(id),form=el('backend-form');
 if(!form||!window.StrataLaunchState)return;
 const t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it;
 const steps=[
  {key:'model',card:form.querySelector('.dash-card--model'),it:'Modello',en:'Model'},
  {key:'resources',card:form.querySelector('.dash-card--res'),it:'Gestione risorse',en:'Resources'},
  {key:'thermal',card:form.querySelector('.dash-card--pm'),it:'Monitor termico',en:'Thermal monitor'},
  {key:'run',card:form.querySelector('.dash-card--run'),it:'Avvio nel modello',en:'Start in Model'}
 ];
 if(steps.some(step=>!step.card))return;
 form.dataset.launchGuide='active';
 const create=(tag,className)=>{const node=document.createElement(tag);if(className)node.className=className;return node;};
 const put=(node,value)=>{if(node.textContent!==String(value))node.textContent=value;};
 const guide=create('section','control-launch-guide');guide.id='control-launch-guide';guide.dataset.i18nIgnore='';guide.setAttribute('aria-labelledby','control-launch-title');
 const head=create('header','control-launch-head'),intro=create('div'),eyebrow=create('span','control-launch-eyebrow'),title=create('h2');title.id='control-launch-title';
 intro.append(eyebrow,title);const identity=create('div','control-launch-identity'),brand=create('span','control-launch-brand'),engineName=create('strong'),phase=create('span','control-launch-phase');phase.setAttribute('role','status');identity.append(brand,engineName,phase);head.append(intro,identity);
 const rail=create('ol','control-launch-rail');rail.setAttribute('aria-label',t('Ordine per avviare un modello','Model startup order'));
 const detail=create('div','control-launch-detail'),dial=create('span','control-launch-dial');dial.setAttribute('aria-hidden','true');
 dial.innerHTML='<svg viewBox="0 0 52 52" fill="none"><circle cx="26" cy="26" r="23"/><path d="M26 3a23 23 0 0 1 23 23"/></svg><b></b>';
 const detailCopy=create('div','control-launch-copy'),detailTitle=create('strong'),detailText=create('p');detailText.id='control-launch-description';detailCopy.append(detailTitle,detailText);
 const actions=create('div','control-launch-actions'),open=create('button','st-btn st-btn--secondary'),next=create('button','st-btn st-btn--primary');open.type=next.type='button';actions.append(open,next);detail.append(dial,detailCopy,actions);guide.append(head,rail,detail);form.before(guide);
 let current=0,nativeLive=null,scheduled=false,lastBrand='';const fieldPositions=new Map();
 const dock=create('nav','control-guide-dock');dock.dataset.i18nIgnore='';dock.setAttribute('aria-label',t('Continua la configurazione','Continue setup'));const dockBack=create('button','st-btn st-btn--secondary'),dockCopy=create('div'),dockTitle=create('strong'),dockNote=create('small'),dockNext=create('button','st-btn st-btn--primary');dockBack.type=dockNext.type='button';dockCopy.append(dockTitle,dockNote);dock.append(dockBack,dockCopy,dockNext);form.after(dock);dockBack.onclick=()=>select(Math.max(0,current-1),true);dockNext.onclick=()=>{if(current<3)select(current+1,true);else if(snapshot().ready)el('tab-btn-chat').click();};
 function dockVisibility(){const box=steps[current].card.getBoundingClientRect();dock.hidden=!form.getClientRects().length||box.bottom<130||box.top>innerHeight-80;}
 window.addEventListener('scroll',dockVisibility,true);window.addEventListener('resize',dockVisibility);

 for(const[index,step]of steps.entries()){
  step.card.id='control-card-'+step.key;step.card.dataset.launchStep=String(index+1);
  const heading=step.card.querySelector('.dash-head');heading.id='control-card-'+step.key+'-title';heading.setAttribute('role','heading');heading.setAttribute('aria-level','3');heading.tabIndex=-1;
  step.card.setAttribute('role','group');step.card.setAttribute('aria-labelledby',heading.id);
  const number=create('span','control-step-number');number.textContent=String(index+1);heading.prepend(number);
  const hint=create('div','control-step-hint'),hintCopy=create('span'),localActions=create('div','control-step-actions'),localBack=create('button','st-btn st-btn--icon control-step-back'),localNext=create('button','st-btn st-btn--secondary control-step-next');hint.dataset.i18nIgnore='';hint.hidden=true;localNext.type=localBack.type='button';localBack.innerHTML='<svg class="st-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="m14 6-6 6 6 6"/></svg>';localActions.append(localBack,localNext);hint.append(hintCopy,localActions);heading.after(hint);Object.assign(step,{hint,hintCopy,localNext,localBack});
  localBack.onclick=()=>moveField(-1);
  localNext.onclick=()=>moveField(1);
  const item=create('li'),button=create('button','control-launch-stop'),counter=create('span','control-launch-number'),copy=create('span','control-launch-stop-copy'),name=create('strong'),summary=create('small');
  button.type='button';button.dataset.step=step.key;button.setAttribute('aria-controls',step.card.id);counter.textContent=String(index+1);copy.append(name,summary);button.append(counter,copy);item.append(button);rail.append(item);Object.assign(step,{button,name,summary});
  button.onclick=()=>select(index,true);
 }
 function nativePhase(){
  if(nativeLive?.state)return nativeLive.state;
  const text=el('ctrl-stat-state')?.textContent.trim().toLowerCase()||'';
  if(['scaricato','unloaded'].includes(text))return 'unloaded';
  if(['pronto','ready'].includes(text))return 'idle';
  if(['lettura','reading'].includes(text))return 'reading';
  if(['generazione','generating'].includes(text))return 'generating';
  return 'unknown';
 }
 function snapshot(){
  const displayEngine=el('unified-engine')?.value||'strata',engine=({'hydra-strata':'strata','hydra-gguf':'gguf','hydra-safetensors':'safetensors'})[displayEngine]||displayEngine,optional=window.StrataOptional?.state?.()||{};
  const model=engine==='strata'?(el('ctrl-model')?.value||''):engine==='colibri'?(optional.model||window.StrataColibri?.state()?.model_id||''):engine==='api'?(el('backend-id')?.value.trim()||''):(el('backend-file')?.value.trim()||'');
  let resourceSummary=engine==='strata'?el('ctrl-ctx-out')?.textContent:el('backend-context-mode')?.value==='auto'?t('Adattamento automatico','Automatic fit'):el('backend-context')?.value;
  if(/^\d+$/.test(resourceSummary||''))resourceSummary=new Intl.NumberFormat(document.documentElement.lang||'it').format(Number(resourceSummary))+t(' token',' tokens');
  return window.StrataLaunchState({engine:displayEngine,model,phase:engine==='strata'?nativePhase():optional.status,
   activeEngine:optional.mode,otherActive:['ready','loading'].includes(optional.status),resourceSummary,
   thermalSummary:el('ctrl-pm-mode-view')?.textContent.trim()});
 }
 function explanation(index,state){
  const copy={
   model:state.engine==='strata'?
    ['Scegli un modello preparato o apri il catalogo. Premi «Usa questo modello» per confermare e passare a Gestione risorse.','Choose a prepared model or open the catalogue. Press “Use this model” to confirm and continue to Resources.']:
    state.engine==='colibri'?['Scegli o prepara un modello dal catalogo Colibri. Avvio e collegamento alla chat restano sotto il tuo controllo.','Choose or prepare a model from the Colibri catalogue. Starting and connecting Chat remain under your control.']:
    state.engine==='gguf'?['Scegli un file GGUF compatibile. Per comprendere immagini, configura anche il proiettore corrispondente quando richiesto.','Choose a compatible GGUF file. To understand images, configure its matching projector when required.']:
    state.engine==='safetensors'?['Scegli la cartella Safetensors. L’adapter LoRA è facoltativo; formato e architettura determinano i loader disponibili.','Choose the Safetensors folder. A LoRA adapter is optional; format and architecture determine available loaders.']:
    ['Collega l’API locale, rileva i modelli e scegli l’ID esatto. Il caricamento rimane gestito dall’app collegata.','Connect the local API, detect models and choose the exact ID. The connected app manages loading.'],
   resources:state.engine==='colibri'?
    ['Usa Memoria per contesto, RAM, VRAM e profilo; Esecuzione per cache, sessioni KV e coda; Risposta per la generazione. «Applica e riavvia» applica memoria ed esecuzione. I valori della risposta valgono dalla prossima richiesta.','Use Memory for context, RAM, VRAM and policy; Execution for cache, KV slots and queue; Response for generation. “Apply and restart” applies memory and execution. Response settings apply to the next request.']:
    state.resourceOwner==='external'?
    ['L’app collegata gestisce memoria e calcolo. Verifica il modello e l’indirizzo nella prima scheda; qui trovi le informazioni sulle risorse.','The connected app manages memory and compute. Check the model and address in the first card; resource information remains here.']:
    state.engine==='strata'?['Controlla riserva VRAM, cache KV e contesto. Le modifiche si applicano con il pulsante della scheda; osserva i margini prima dell’avvio.','Check the VRAM reserve, KV cache and context. Apply changes using the card’s button; review available headroom before starting.']:
    ['Adatta memoria e contesto al modello. «Calcolo e loader» raccoglie i parametri del motore; il controllo di compatibilità precede il caricamento.','Fit memory and context to the model. “Compute and loader” contains engine parameters; compatibility is checked before loading.'],
   thermal:state.thermalOwner==='engine'?
    ['Controlla temperatura e potenza, poi scegli il profilo. «Applica» aggiorna i limiti del motore; il monitor distingue misure attuali e soglie.','Check temperature and power, then choose a profile. “Apply” updates engine limits; the monitor distinguishes current measurements from thresholds.']:
    ['Osserva le risorse e la temperatura del PC durante il lavoro. Queste misure includono le altre app; il profilo Hydra One non controlla il servizio esterno.','Watch PC resources and temperature during work. These measurements include other apps; the Hydra One profile does not control an external service.'],
   run:state.active?
    ['Segui lo stato in Avvio / Arresto, dentro Modello: il motore sta caricando o elaborando una richiesta. La Chat del motore attivo resta raggiungibile quando pronta.','Follow Start / Stop inside Model: the engine is loading or processing a request. The active engine’s Chat remains accessible when ready.']:
    state.ready?['Il motore è attivo. Apri la Chat per usarlo; lo stato e i comandi di arresto restano in Avvio / Arresto, dentro Modello.','The engine is active. Open Chat to use it; status and stop controls remain in Start / Stop, inside Model.']:
    state.engine==='colibri'?['Usa «Avvia Colibri» o «Collega alla chat» in Avvio / Arresto, dentro Modello. Arresta e Riavvia gestiscono il motore; le richieste attive impediscono le modifiche.','Use “Start Colibri” or “Connect to Chat” in Start / Stop, inside Model. Stop and Restart manage the engine; active requests block changes.']:
    state.engine==='api'?['Usa il comando di collegamento in Avvio / Arresto, dentro Modello. La connessione e il modello vengono controllati prima di usare la Chat.','Use the connection action in Start / Stop, inside Model. Connection and model are checked before using Chat.']:
    ['Dopo modello e configurazione, usa il pulsante Avvia di Avvio / Arresto, dentro Modello. Il caricamento parte da quell’azione e lo stato mostra quando puoi entrare in Chat.','After choosing model and settings, use Start in Start / Stop, inside Model. That action starts loading, and status shows when Chat is ready.']
  };
  return t(...copy[steps[index].key]);
 }
 function fieldGroups(step){return [...step.card.querySelectorAll('.dash-body .dm')].filter(group=>group.closest('.dash-card')===step.card&&group.getClientRects().length&&[...group.querySelectorAll('input,select,textarea,button')].some(input=>!input.disabled&&input.type!=='hidden'&&input.getClientRects().length));}
 function fieldState(step){const groups=fieldGroups(step);let position=fieldPositions.get(step.key)||0;position=Math.min(position,Math.max(0,groups.length-1));fieldPositions.set(step.key,position);return {groups,position,field:groups[position]};}
 function fieldName(group){const label=group?.querySelector('.dm__label,label,legend');if(!label)return t('Configura la sezione','Configure this section');const copy=label.cloneNode(true);copy.querySelectorAll('output,.dm__sub').forEach(node=>node.remove());return copy.textContent.trim();}
 function moveField(direction){const step=steps[current],state=fieldState(step),position=state.position+direction;if(position>=0&&position<state.groups.length){fieldPositions.set(step.key,position);render();const field=state.groups[position],input=[...field.querySelectorAll('input,select,textarea,button')].find(input=>!input.disabled&&input.type!=='hidden'&&input.getClientRects().length);field.scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});input?.focus({preventScroll:true});return;}if(direction<0&&current>0){const previous=steps[current-1];fieldPositions.set(previous.key,Math.max(0,fieldGroups(previous).length-1));select(current-1,true);}else if(direction>0&&current<3)select(current+1,true);else if(direction>0&&snapshot().ready)el('tab-btn-chat').click();}
 function render(){
  scheduled=false;const state=snapshot();try{const pending=JSON.parse(sessionStorage.getItem('strata:launch-guide-next')||'null');if(pending&&Date.now()-pending.at<600000&&state.engine==='strata'&&state.model===pending.model){sessionStorage.removeItem('strata:launch-guide-next');current=1;requestAnimationFrame(()=>navigate(1));}else if(pending&&Date.now()-pending.at>=600000)sessionStorage.removeItem('strata:launch-guide-next');}catch{}const selected=steps[current];put(dockTitle,(current+1)+' / 4 · '+t(steps[current].it,steps[current].en));put(dockNote,t('Navigazione guidata · i valori si applicano con i comandi della scheda','Guided navigation · apply values using the card actions'));put(dockBack,t('Indietro','Back'));dockBack.disabled=current===0;put(dockNext,current===3?t('Apri Chat','Open Chat'):t('Continua: ','Continue: ')+(current+2)+'. '+t(steps[current+1].it,steps[current+1].en));dockNext.disabled=current===0&&!state.modelChosen||current===3&&!state.ready;dockVisibility();guide.dataset.step=String(current+1);guide.dataset.phase=state.active?'active':state.ready?'ready':'stopped';
  put(eyebrow,t('PERCORSO DI AVVIO','STARTUP PATH'));put(title,t('Dal modello alla tua prima richiesta.','From model to your first request.'));
  const names={strata:'Hydra One',gguf:'llama.cpp · Unsloth',safetensors:'Safetensors · Python',api:t('API locale','Local API'),colibri:'Colibri'};put(engineName,state.displayEngine?.startsWith('hydra-')?'HYDRA ONE · '+(state.engine==='strata'?t('Motore ibrido','Hybrid engine'):names[state.engine]):names[state.engine]);
  const mark=state.displayEngine?.startsWith('hydra-')?'hydra':{strata:'strata',gguf:'llama.cpp',safetensors:'huggingface',api:'openai',colibri:'colibri'}[state.engine];if(mark!==lastBrand){brand.innerHTML=window.StrataBrands?.markup(mark)||'';lastBrand=mark;}
  const labels={loading:t('Caricamento…','Loading…'),reading:t('Lettura del prompt','Reading prompt'),generating:t('Generazione','Generating'),error:t('Controlla lo stato','Check status'),unknown:t('Verifica stato…','Checking status…')};
  put(phase,!state.matches?t('Altro motore attivo','Another engine active'):labels[state.phase]||(state.ready?t('Motore attivo','Engine active'):['api','colibri'].includes(state.engine)?t('Da collegare','Disconnected'):t('Non caricato','Unloaded')));
  const summaries=[state.modelChosen?t('Modello selezionato','Model selected'):t('Scegli un modello','Choose a model'),state.engine==='colibri'?t('Memoria, esecuzione e risposta','Memory, execution and response'):state.resourceOwner==='external'?t('Gestite dall’app collegata','Managed by connected app'):state.resourceSummary?t('Contesto: ','Context: ')+state.resourceSummary:t('Controlla i margini','Check available headroom'),state.thermalSummary&&state.thermalSummary!=='—'?state.thermalSummary:t('Misure del PC','PC measurements'),phase.textContent];
  for(const[index,step]of steps.entries()){
   put(step.name,t(step.it,step.en));put(step.summary,summaries[index]);step.button.setAttribute('aria-current',index===current?'step':'false');step.button.title=explanation(index,state);
   step.card.classList.toggle('control-step-current',index===current);step.hint.hidden=index!==current;put(step.hintCopy,explanation(index,state));
   const fields=fieldState(step);for(const group of step.card.querySelectorAll('.control-field-current'))group.classList.remove('control-field-current');if(index===current&&fields.field)fields.field.classList.add('control-field-current');const internalNext=fields.position+1<fields.groups.length;
   if(index===current&&fields.field)put(step.hintCopy,(index+1)+'.'+(fields.position+1)+' / '+fields.groups.length+' · '+fieldName(fields.field)+' — '+explanation(index,state));
   put(step.localNext,internalNext?t('Avanti','Next'):index===3?t('Apri Chat','Open Chat'):(index+2)+'. '+t(steps[index+1].it,steps[index+1].en));const disabled=!internalNext&&(index===0&&!state.modelChosen||index===3&&!state.ready);if(step.localNext.disabled!==disabled)step.localNext.disabled=disabled;
   step.localNext.setAttribute('aria-label',internalNext?t('Campo successivo: ','Next field: ')+fieldName(fields.groups[fields.position+1]):step.localNext.textContent);step.localNext.title=step.localNext.getAttribute('aria-label');step.localBack.hidden=index===0&&fields.position===0;if(fields.position>0){step.localBack.setAttribute('aria-label',t('Campo precedente','Previous field'));step.localBack.title=t('Campo precedente','Previous field');}if(index>0&&fields.position===0){const back=t('Torna a ','Back to ')+index+'. '+t(steps[index-1].it,steps[index-1].en);step.localBack.setAttribute('aria-label',back);step.localBack.title=back;}
  }
  rail.setAttribute('aria-label',t('Ordine per avviare un modello','Model startup order'));put(detailTitle,(current+1)+'. '+t(selected.it,selected.en));put(detailText,explanation(current,state));put(dial.querySelector('b'),String(current+1));
  const actionsCopy=[['Vai al modello','Go to model'],['Vai alle risorse','Go to resources'],['Vai al monitor','Go to monitor'],['Vai ad Avvio','Go to Start']];put(open,t(...actionsCopy[current]));open.setAttribute('aria-label',t('Apri la scheda ','Open card ')+(current+1)+': '+t(selected.it,selected.en));
  const selectedFields=fieldState(selected),hasNextField=selectedFields.position+1<selectedFields.groups.length;put(next,hasNextField?t('Successivo: ','Next: ')+fieldName(selectedFields.groups[selectedFields.position+1]):current===3?t('Apri Chat','Open Chat'):(current+2)+'. '+t(steps[current+1].it,steps[current+1].en));next.disabled=!hasNextField&&(current===0&&!state.modelChosen||current===3&&!state.ready);next.title=next.disabled?(current===0?t('Scegli un modello nella prima scheda.','Choose a model in the first card.'):t('Avvia il motore in Avvio / Arresto, dentro Modello.','Start the engine in Start / Stop, inside Model.')):'';
 }
 function target(index){
  const state=snapshot();
  if(index===0&&state.engine==='colibri')return el('colibri-model');if(index===0)return el(state.engine==='strata'?'ctrl-model':['api','colibri'].includes(state.engine)?'backend-id':'backend-local-model');
  if(index===1&&state.engine==='colibri')return el('colibri-context');if(index===1)return state.resourceOwner==='external'?steps[index].card.querySelector('.dash-head'):el(state.engine==='strata'?'ctrl-vram-reserve':'backend-fit-mode');
  if(index===2)return state.thermalOwner==='engine'?el('ctrl-power-mode'):steps[index].card.querySelector('.dash-head');
  return el(state.engine==='strata'?'ctrl-load':'backend-start');
 }
 function navigate(index){
  let field=target(index);for(let parent=field?.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
  if(!field?.getClientRects().length||field.disabled)field=steps[index].card.querySelector('.dash-head');
  const visible=field.parentElement?.querySelector('[role="combobox"]');if(visible?.getClientRects().length&&field.tagName==='SELECT')field=visible;
  steps[index].card.scrollIntoView({block:'start',behavior:'auto'});field.focus({preventScroll:true});
 }
 function select(index,navigateNow=false){current=index;render();guide.classList.remove('control-launch-transit');void guide.offsetWidth;guide.classList.add('control-launch-transit');if(navigateNow)navigate(index);}
 // Editing a different section moves the guide's light to that section too.
 const followSection=event=>{const card=event.target.closest?.('[data-launch-step]');const index=steps.findIndex(step=>step.card===card);if(index>=0){const group=event.target.closest?.('.dm'),groups=fieldGroups(steps[index]),position=groups.indexOf(group);if(position>=0)fieldPositions.set(steps[index].key,position);if(index!==current)select(index);else render();}};
 form.addEventListener('pointerdown',followSection);
 form.addEventListener('focusin',followSection);
 open.onclick=()=>navigate(current);next.onclick=()=>moveField(1);
 rail.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const index=event.key==='Home'?0:event.key==='End'?3:(current+(event.key==='ArrowRight'?1:3))%4;select(index);steps[index].button.focus();});
 const schedule=()=>{if(!scheduled){scheduled=true;requestAnimationFrame(render);}};
 document.addEventListener('strata:model-confirmed',event=>{if(event.detail?.engine==='strata'&&event.detail.model===el('ctrl-model')?.value){fieldPositions.set('resources',0);select(1,true);}});
 document.addEventListener('strata:controlstate',event=>{nativeLive=event.detail;schedule();});
 el('tab-btn-control')?.addEventListener('click',schedule);form.addEventListener('input',schedule);form.addEventListener('change',event=>{if(event.target.id==='unified-engine')current=0;schedule();});
 new MutationObserver(schedule).observe(form,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['data-engine','disabled']});
 new MutationObserver(schedule).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
 render();
})();

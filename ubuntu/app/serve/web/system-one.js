/* System One uses Colibri's scoring endpoint; never substitutes chat generation. */
(()=>{
 const parseCriteria=(type,text)=>{
  const lines=text.split('\n').map(x=>x.trim()).filter(Boolean);
  if(!lines.length||lines.length>255)throw Error('Inserisci da 1 a 255 criteri.');
  if(type==='score')return lines;
  const entries=lines.map(line=>{const split=line.indexOf('|');return split<0?[line,null]:[line.slice(0,split).trim(),line.slice(split+1).trim()||null];});
  if(entries.some(([label])=>!label)||new Set(entries.map(([label])=>label)).size!==entries.length)throw Error('Ogni opzione deve avere un nome distinto.');
  return Object.fromEntries(entries);
 };
 if(typeof module!=='undefined')module.exports={parseCriteria};
 if(typeof document==='undefined')return;
 const el=id=>document.getElementById(id),host=el('colibri-system-one'),form=el('colibri-decision-form');if(!host||!form)return;
 let current=null,controller=null,result=null,open=false,serial=0,revision=0,resultRevision=-1,submitted=null;
 host.querySelector('h3').remove();
 host.removeAttribute('data-i18n-ignore');
 const header=document.createElement('header');header.className='so-header';
 header.innerHTML='<div class="so-identity">'+(window.StrataBrands?.markup('colibri')||'')+'<div><h2>System One</h2><p>Valuta alternative, probabilità e punteggi sullo stesso documento.</p></div></div><button type="button" class="st-btn st-btn--secondary" id="system-one-back">Torna alla chat</button>';
 host.prepend(header);
 form.innerHTML=`<div class="so-runtime"><span class="so-status-dot" aria-hidden="true"></span><strong id="system-one-runtime">Verifica del motore…</strong><span id="system-one-model"></span></div>
 <div class="so-columns"><section class="so-source" aria-labelledby="so-source-title"><div class="so-section-heading"><h3 id="so-source-title">Contesto</h3><output id="so-context-count" data-i18n-ignore>0 / 200.000 caratteri</output></div><p class="so-help">Inserisci il documento da analizzare. Scrivi le domande e le risposte ammesse nel pannello accanto.</p><label for="colibri-decision-context">Documento o contesto</label><textarea class="st-input" id="colibri-decision-context" rows="10" maxlength="200000" placeholder="Incolla il testo, i dati o la situazione da valutare…" required></textarea><label class="so-import">Importa testo<input type="file" id="colibri-decision-file" accept=".txt,.md,.csv,.json,text/plain"></label><p class="so-help" id="so-import-note">TXT, Markdown, CSV e JSON · massimo 200 kB. Il file originale resta invariato.</p>
 <div class="so-native"><div class="so-section-heading"><h3>Impostazioni del motore</h3></div><div class="so-options"><label>Normalizzazione<select class="st-input" id="so-normalize"><option value="sum">Somma · predefinita</option><option value="mean">Media per token</option></select><small>La media riduce l’effetto della lunghezza delle opzioni.</small></label><label>Cache del contesto<select class="st-input" id="so-pin"><option value="">Automatica</option><option value="true">Mantieni il contesto</option><option value="false">Rileggi a ogni richiesta</option></select><small>Automatica segue la gestione nativa del motore.</small></label><label>Sessione KV<select class="st-input" id="so-cache"><option value="">Automatica dal contesto</option></select></label></div><label>Istruzioni persistenti<textarea class="st-input" id="so-prefix" rows="3" maxlength="20000" placeholder="Regole comuni alle valutazioni · facoltative"></textarea></label><p class="so-help" id="so-prefix-help">Il prefisso può essere riutilizzato dal modello linguistico. I motori decisionali dedicati possono non supportarlo.</p></div></section>
 <section class="so-questions" aria-labelledby="so-questions-title"><div class="so-section-heading"><h3 id="so-questions-title">Domande</h3><output id="so-question-count" data-i18n-ignore>1 / 64</output></div><p class="so-help">Scelta tra alternative, probabilità di Sì oppure punteggio atteso su una scala.</p><div id="colibri-decision-questions"></div><button type="button" class="st-btn st-btn--secondary" id="colibri-decision-add">Aggiungi domanda</button></section></div>
 <div class="so-action-bar"><p role="status" id="colibri-decision-state">Prepara il contesto e almeno una domanda.</p><div><button type="button" class="st-btn st-btn--secondary" id="colibri-decision-cancel" disabled>Interrompi</button><button type="submit" class="st-btn st-btn--primary" id="colibri-decision-run" disabled>Valuta opzioni</button></div></div>
 <section class="so-results" aria-labelledby="so-results-title"><div class="so-section-heading"><div><h3 id="so-results-title">Risultati</h3><p class="so-help" id="so-result-summary">Le probabilità riguardano le alternative fornite e non garantiscono la correttezza della decisione.</p></div><button type="button" class="st-btn st-btn--secondary" id="colibri-decision-export" disabled>Esporta JSON</button></div><div id="colibri-decision-result"><p class="so-empty">Le valutazioni appariranno qui, con probabilità e riferimenti alle domande.</p></div></section>`;
 const native=form.querySelector('.so-native');form.querySelector('.so-action-bar').before(native);native.setAttribute('aria-label','Configurazione nativa System One');
 const trigger=document.createElement('button');trigger.id='system-one-open';trigger.type='button';trigger.className='st-btn st-btn--secondary';trigger.textContent='System One';trigger.setAttribute('aria-controls',host.id);trigger.setAttribute('aria-pressed','false');
 document.querySelector('.chat-workspace-actions').prepend(trigger);
 const chatNodes=['chat-scroll','composer','chat-find-input'].map(id=>el(id)?.closest(id==='composer'?'.composer-wrap':id==='chat-find-input'?'.chat-find':'#chat-scroll')).filter(Boolean);
 const previousHidden=new Map();
 function show(value){
  open=value;host.hidden=!value;trigger.setAttribute('aria-pressed',String(value));el('view-chat').classList.toggle('system-one-mode',value);
  for(const node of chatNodes){if(value){if(!previousHidden.has(node))previousHidden.set(node,node.hidden);node.hidden=true;}else if(previousHidden.has(node)){node.hidden=previousHidden.get(node);previousHidden.delete(node);}}
  if(value){el('colibri-decision-context').focus();window.StrataColibriControls?.refresh(true);}else trigger.focus();
 }
 trigger.onclick=()=>show(!open);el('system-one-back').onclick=()=>show(false);host.hidden=true;
 function available(){return current?.workspace?.status==='ready'&&(current.health?.capabilities||[]).includes('systemone');}
 function updateButtons(){el('colibri-decision-run').disabled=!available()||!!controller;el('colibri-decision-cancel').disabled=!controller;el('colibri-decision-add').disabled=!!controller||el('colibri-decision-questions').children.length>=64;}
 function setState(data){
  if(!data)return;current=data;const enabled=available();el('system-one-runtime').textContent=enabled?'Motore pronto':data.workspace?.status!=='ready'?'Avvia Colibri in Lab™ Ai':'System One non disponibile per questo modello';el('system-one-model').textContent=data.workspace?.native?.setup?.model?.name||data.workspace?.model_id||'';host.dataset.ready=String(enabled);
  const count=Number.isInteger(data.health?.kv_slots)?data.health.kv_slots:1,select=el('so-cache');
  if(select.dataset.count!==String(count)){const previous=select.value;select.replaceChildren(new Option('Automatica dal contesto',''),...Array.from({length:Math.min(count,1024)},(_,i)=>new Option('Sessione '+(i+1),String(i))));if([...select.options].some(o=>o.value===previous))select.value=previous;select.dataset.count=String(count);}
  const engineSelected=window.StrataUnifiedEngine?.selected()==='colibri';trigger.hidden=!engineSelected;if(!engineSelected&&open)show(false);updateButtons();
 }
 function changed(){revision++;el('so-context-count').textContent=new Intl.NumberFormat(document.documentElement.lang==='en'?'en-US':'it-IT').format(el('colibri-decision-context').value.length)+(document.documentElement.lang==='en'?' / 200,000 characters':' / 200.000 caratteri');if(result&&revision!==resultRevision)el('so-result-summary').textContent='Risultati della valutazione precedente. Le modifiche non sono ancora state valutate.';}
 form.addEventListener('input',changed);form.addEventListener('change',changed);
 function renumber(){[...el('colibri-decision-questions').children].forEach((field,i)=>field.querySelector('legend').textContent='Domanda '+(i+1));el('so-question-count').textContent=el('colibri-decision-questions').children.length+' / 64';updateButtons();}
 function addQuestion(){
  if(el('colibri-decision-questions').children.length>=64)return;
  const field=document.createElement('fieldset');field.className='so-question';field.dataset.key='q'+(++serial);
  field.innerHTML='<legend>Domanda</legend><div class="so-question-toolbar"><label>Tipo di valutazione<select class="st-input" data-type><option value="choice">Scelta tra alternative</option><option value="noul">Sì / No · probabilità</option><option value="score">Punteggio su scala</option></select></label><button type="button" class="st-btn st-btn--secondary so-remove">Rimuovi</button></div><label>Domanda<textarea class="st-input" data-question rows="2" maxlength="2000" placeholder="Che cosa vuoi valutare?" required></textarea></label><label><span data-options-caption>Alternative · una per riga</span><textarea class="st-input" data-options rows="4" placeholder="Opzione | descrizione facoltativa"></textarea></label><p class="so-help" data-options-help>Una risposta per riga. Aggiungi | e una descrizione per distinguere meglio le alternative.</p><div class="so-binary" hidden><label>Quando Sì<textarea class="st-input" data-yes rows="2" maxlength="2000" placeholder="Criterio facoltativo"></textarea></label><label>Quando No<textarea class="st-input" data-no rows="2" maxlength="2000" placeholder="Criterio facoltativo"></textarea></label></div>';
  const type=field.querySelector('[data-type]'),options=field.querySelector('[data-options]');options.value='Sì\nNo';
  const chooser=document.createElement('div');chooser.className='so-type-chooser';chooser.setAttribute('role','group');chooser.setAttribute('aria-label','Tipo di valutazione');for(const [value,title,description]of [['choice','Alternative','Scegli tra risposte definite'],['noul','Sì / No','Misura la probabilità di Sì'],['score','Scala','Calcola un punteggio atteso']]){const button=document.createElement('button');button.type='button';button.className='so-type-option';button.dataset.value=value;button.setAttribute('aria-pressed',String(value===type.value));button.append(textNode('strong',title),textNode('small',description));button.onclick=()=>{type.value=value;type.dispatchEvent(new Event('change',{bubbles:true}));};chooser.append(button);}type.closest('label').classList.add('so-type-native');field.querySelector('.so-question-toolbar').after(chooser);
  type.onchange=()=>{for(const button of chooser.children)button.setAttribute('aria-pressed',String(button.dataset.value===type.value));const binary=type.value==='noul';options.closest('label').hidden=binary;field.querySelector('.so-binary').hidden=!binary;field.querySelector('[data-options-caption]').textContent=type.value==='score'?'Livelli in ordine crescente · uno per riga':'Alternative · una per riga';field.querySelector('[data-options-help]').textContent=binary?'I criteri sono facoltativi. Il risultato è la probabilità di Sì.':type.value==='score'?'Il primo livello vale 0, il secondo 1 e così via. Il risultato è il punteggio atteso.':'Una risposta per riga. Aggiungi | e una descrizione per distinguere le alternative.';};
  field.querySelector('.so-remove').onclick=()=>{field.remove();changed();renumber();};el('colibri-decision-questions').append(field);renumber();
 }
 el('colibri-decision-add').onclick=()=>{addQuestion();changed();};addQuestion();
 el('colibri-decision-file').onchange=async event=>{
  const file=event.target.files[0];if(!file)return;
  try{if(file.size>200000)throw Error('Il file deve restare entro 200 kB.');const text=await file.text();if(text.includes('\0'))throw Error('Scegli un documento di testo.');el('colibri-decision-context').value=text;el('so-import-note').textContent=file.name+' · '+new Intl.NumberFormat('it-IT').format(file.size)+' byte · testo caricato';changed();}
  catch(error){el('colibri-decision-state').textContent=error.message;}
 };
 const number=value=>Number.isFinite(value)?new Intl.NumberFormat('it-IT',{maximumFractionDigits:3}).format(value):'Non disponibile';
 const percent=value=>Number.isFinite(value)?new Intl.NumberFormat('it-IT',{style:'percent',maximumFractionDigits:2}).format(value):'Non disponibile';
 function textNode(tag,text,className){const node=document.createElement(tag);node.textContent=text;if(className)node.className=className;return node;}
 function renderResults(value,questions){
  const target=el('colibri-decision-result');target.replaceChildren();
  for(const [key,answer]of Object.entries(value.answers||{})){
   const block=document.createElement('article');block.className='so-answer';const question=questions[key];
   block.append(textNode('h4',question?.instructions||key));
   const headline=answer.type==='noul'?'Probabilità di Sì: '+percent(answer.noul):answer.type==='score'?'Punteggio atteso: '+number(answer.score):'Scelta: '+(answer.choice??'Non disponibile');block.append(textNode('p',headline,'so-answer-headline'));
   if(Number.isFinite(answer.confidence))block.append(textNode('p','Concentrazione della scelta: '+percent(answer.confidence),'so-help'));
   const probabilities=answer.type==='noul'?{'Sì':answer.noul,'No':Number.isFinite(answer.noul)?1-answer.noul:null}:answer.probabilities||{};
   const entries=Object.entries(probabilities);if(answer.type!=='score')entries.sort((a,b)=>b[1]-a[1]);
   const list=document.createElement('div');list.className='so-probabilities';
   for(const [choice,p]of entries){const row=document.createElement('div');row.className='so-probability';row.dataset.i18nIgnore='true';row.append(textNode('span',answer.legend?.[choice]!=null?choice+' · '+answer.legend[choice]:choice),textNode('strong',percent(p)));const meter=document.createElement('meter');meter.min=0;meter.max=1;meter.value=Number.isFinite(p)?Math.max(0,Math.min(1,p)):0;meter.setAttribute('aria-label','Probabilità '+(answer.legend?.[choice]??choice));row.append(meter);list.append(row);}block.append(list);
   const positive=Object.values(probabilities).filter(p=>Number.isFinite(p)&&p>0);if(entries.length>1){const entropy=-positive.reduce((sum,p)=>sum+p*Math.log(p),0)/Math.log(entries.length);block.append(textNode('p','Incertezza della distribuzione: '+percent(entropy),'so-help'));}
   target.append(block);
  }
 }
 el('colibri-decision-cancel').onclick=()=>{if(controller){el('colibri-decision-state').textContent='Interruzione richiesta al motore…';controller.abort();}};
 form.onsubmit=async event=>{
  event.preventDefault();if(controller||!available())return;
  const questions={};
  try{
   if(!el('colibri-decision-context').value.trim())throw Error('Inserisci il documento o il contesto.');
   for(const field of el('colibri-decision-questions').children){const type=field.querySelector('[data-type]').value,instructions=field.querySelector('[data-question]').value.trim();if(!instructions)throw Error('Completa il testo di ogni domanda.');const question={type,instructions};
    if(type==='noul'){const yes=field.querySelector('[data-yes]').value.trim(),no=field.querySelector('[data-no]').value.trim();if(yes||no)question.criteria={true:yes||null,false:no||null};}else question.criteria=parseCriteria(type,field.querySelector('[data-options]').value);questions[field.dataset.key]=question;
   }
   if(!Object.keys(questions).length)throw Error('Aggiungi almeno una domanda.');
  }catch(error){el('colibri-decision-state').textContent=error.message;return;}
  const payload={state:el('colibri-decision-context').value,questions,normalize:el('so-normalize').value};if(el('so-prefix').value.trim())payload.prefix=el('so-prefix').value;if(el('so-pin').value)payload.pin_state=el('so-pin').value==='true';if(el('so-cache').value!=='')payload.cache_slot=Number(el('so-cache').value);
  controller=new AbortController();const started=performance.now(),sentRevision=revision;
  const editable=[...form.querySelectorAll('input,textarea,select,.so-remove,.so-type-option')];editable.forEach(node=>node.disabled=true);updateButtons();host.setAttribute('aria-busy','true');el('colibri-decision-state').textContent='Valutazione in corso · '+Object.keys(questions).length+' domande sullo stesso contesto…';
  try{
   const key=el('api-key')?.value||sessionStorage.getItem('strata-api-key'),response=await fetch('colibri/decide',{method:'POST',headers:{'Content-Type':'application/json',...(key?{Authorization:'Bearer '+key}:{})},body:JSON.stringify(payload),signal:controller.signal}),value=await response.json();if(!response.ok)throw Error(value.error?.message||response.status);
   if(!value.answers||Object.keys(value.answers).length!==Object.keys(questions).length)throw Error('Il motore ha restituito un risultato incompleto.');
   result=value;submitted=structuredClone(payload);resultRevision=sentRevision;renderResults(value,questions);el('colibri-decision-export').disabled=false;el('so-result-summary').textContent='Probabilità relative alle alternative fornite. La concentrazione misura quanto la scelta prevale sulle altre; non è una verifica di correttezza.';el('colibri-decision-state').textContent='Completata in '+number((performance.now()-started)/1000)+' s · '+number(value.usage?.input_tokens)+' token in ingresso · '+number(value.usage?.output_tokens)+' token delle opzioni';window.StrataColibriControls?.refresh();
  }catch(error){el('colibri-decision-state').textContent=error.name==='AbortError'?'Richiesta interrotta dal client. Attendi che il motore risulti libero prima di riavviarlo.':error.message;}
  finally{controller=null;editable.forEach(node=>node.disabled=false);host.removeAttribute('aria-busy');updateButtons();}
 };
 el('colibri-decision-export').onclick=()=>{if(!result)return;const url=URL.createObjectURL(new Blob([JSON.stringify({request:submitted,response:result},null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='colibri-system-one.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
 window.StrataSystemOne={setState,show,parseCriteria,setError(message){el('system-one-runtime').textContent='Stato del motore non disponibile';el('system-one-model').textContent=message;current=null;host.dataset.ready='false';updateButtons();}};setState(window.StrataColibriControls?.data());document.addEventListener('strata:engine-selected',()=>setState(current));
})();

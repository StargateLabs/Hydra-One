const HYBRID_REPO='shefowl/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-Hybrid-GGUF';
let catalogueOpen=false,catalogueEntries=[],catalogueVersion=0,catalogueSearching=false,catTimer=null,cataloguePendingKey=null,catalogueJob={},cataloguePreparedMarkup='';
async function catPost(path,payload){
 const response=await fetch(path,{method:'POST',headers:headers(true),body:JSON.stringify(payload)});
 const data=await response.json();if(!response.ok)throw Error(data.error?.message||`HTTP ${response.status}`);return data;
}
function catStato(text,error=false){$('cat-state').textContent=text;$('cat-state').dataset.error=String(!!error);}
function catalogueIdentity(e){
 const known={
  'ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF':['Qwen3.8 Flash Next','Originale GSQ-RCO','Modello completo nelle quantizzazioni GSQ-RCO.'],
  'ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF':['Qwen3.8 Flash Next Coder','Coder','Variante per programmazione con esperti ridotti.'],
  'ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF':['Swift 1.5 Flash Next','Fine-tune','Ragionamento più breve; velocità per token da misurare.'],
  [HYBRID_REPO]:['Qwen3.8 Flash Next Hybrid','Hybrid IQ3/Q2','Parti dense IQ3_XXS ed esperti Q2_0. Qualità e velocità locali da verificare.']
 };
 const item=known[e.repo]||[e.repo.split('/')[1].replace(/-/g,' '),'Pubblicazione della community','Compatibilità strutturale verificata; prestazioni locali da misurare.'];
 return {name:item[0],edition:item[1],description:item[2],author:e.author||e.repo.split('/')[0]};
}
function catalogueMetadata(e){
 const rows=[['Architettura',e.architecture],['Livelli',e.layers],['Esperti per livello',e.experts],['File dei pesi',e.files?.length]];
 const facts=rows.filter(([,value])=>value!==undefined&&value!==null).map(([name,value])=>`<div><dt>${esc(name)}</dt><dd>${esc(value)}</dd></div>`).join('');
 const files=(e.file_metadata||[]).map(file=>`<li><strong>${esc(file.path)}</strong><span>${fmt(file.bytes/2**30,2)} GiB</span><code>${esc(file.sha256||'SHA-256 non dichiarato dalla fonte')}</code></li>`).join('');
 return `<dl class="catalogue-metadata">${facts}</dl>${files?`<ul class="catalogue-file-list" aria-label="File e integrità">${files}</ul>`:''}`;
}
function renderCatalogue(entries){
 catalogueEntries=entries;
 const releases=new Set(entries.map(e=>e.repo));
 $('cat-results').innerHTML=entries.length?entries.map(e=>{
  const identity=catalogueIdentity(e),quant=e.repo===HYBRID_REPO?'IQ3 / Q2_0':e.quant;
  const busy=cataloguePendingKey===e.key||(['starting','downloading','verifying','packing','registering'].includes(catalogueJob.state)&&catalogueJob.key===e.key);
  return `<article class="catalogue-entry catalogue-entry--variant" data-model-key="${esc(e.key)}"><header class="catalogue-heading"><div class="catalogue-mark" aria-hidden="true">${window.StrataModelBrands?.modelMarkup({repo:e.repo,name:identity.name})||window.StrataBrands?.markup('huggingface')||''}</div><div class="catalogue-identity"><h3 title="${esc(identity.name)}">${esc(identity.name)}</h3><div class="catalogue-byline"><span>Pubblicato da</span><a href="https://huggingface.co/${esc(e.repo.split('/')[0])}" target="_blank" rel="noopener noreferrer">${esc(identity.author)}</a><span class="catalogue-edition">${esc(identity.edition)}</span></div></div></header><div class="catalogue-tags"><span class="cat-tag cat-tag--format">GGUF · Hydra One</span><span class="cat-tag cat-tag--architecture">${esc(e.architecture||'Architettura non dichiarata')}</span><span class="cat-tag ${e.on_disk?'cat-tag--ready':'cat-tag--compatible'}">${e.on_disk?'Preparato sul PC':'Compatibile con questo PC'}</span></div><p class="catalogue-description" title="${esc(identity.description)}">${esc(identity.description)}</p><div class="catalogue-variants"><div class="catalogue-variant"><div class="catalogue-format"><span>Quantizzazione</span><strong>${esc(quant)}</strong><small>${esc(e.experts)} esperti per livello</small></div><dl class="catalogue-specs"><div><dt>Download</dt><dd>${fmt(e.download_gib,2)} <small>GiB</small></dd></div><div><dt>RAM minima</dt><dd>${fmt(e.fit.ram_gb)} <small>GiB</small></dd></div></dl><div class="catalogue-action"><span class="catalogue-availability${e.on_disk?' is-ready':''}">${e.on_disk?'Preparato':'Adatto a questo PC'}</span><button class="st-btn ${e.on_disk?'st-btn--secondary':'st-btn--primary'}" data-cat-action="${e.on_disk?'use':'fetch'}" data-cat-key="${esc(e.key)}" ${busy?'disabled aria-busy="true"':''} aria-label="${esc((e.on_disk?'Usa modello':'Scarica e prepara')+' '+identity.name+' '+e.quant)}">${e.on_disk?'Usa modello':'Scarica e prepara'}</button></div></div></div><footer class="catalogue-footer"><a href="https://huggingface.co/${esc(e.repo)}" target="_blank" rel="noopener noreferrer">Scheda e provenienza ↗</a><details><summary>Versione e preparazione</summary><div><a href="https://huggingface.co/${esc(e.repo)}" target="_blank" rel="noopener noreferrer" class="catalogue-source-repo">${esc(e.repo)}</a><span>Revisione verificata</span><code>${esc(e.revision||'—')}</code>${catalogueMetadata(e)}<p>La compatibilità del formato non certifica qualità o velocità. I nuovi modelli sono preparati senza ereditare il draft MTP dell’originale.</p><a href="https://huggingface.co/${esc(e.repo)}/tree/${esc(e.revision||'main')}" target="_blank" rel="noopener noreferrer">File della revisione ↗</a></div></details></footer></article>`;
 }).join(''):'<div class="catalogue-empty">Nessun modello verificato per questa ricerca.<small>Hydra One richiede architettura qwen4exp, formato HIP supportato e risorse sufficienti.</small></div>';
 $('cat-summary').textContent=`${releases.size} pubblicazioni · ${entries.length} varianti · ${entries.filter(e=>e.on_disk).length} preparate`;
}

async function catCerca(){
 if(catalogueSearching)return;
 catApri(true,false);catalogueSearching=true;const version=++catalogueVersion;$('cat-search').disabled=true;$('cat-query').disabled=true;
 catStato('Ricerca su Hugging Face e verifica della compatibilità…');
 try{
  const data=await catPost('catalogue-search',{query:$('cat-query').value});
  if(version!==catalogueVersion)return;
  if(['','qwen3.8-flash-next','qwen3.8'].includes($('cat-query').value.trim().toLowerCase())&&!data.results.some(e=>e.repo===HYBRID_REPO)){
   try{const featured=await catPost('catalogue-inspect',{repo:HYBRID_REPO,quant:'Q2_0'});data.results.push(featured);data.checked_repositories+=1;}catch(error){console.info('Hybrid non disponibile per questo host:',error.message);}
  }
  if(version!==catalogueVersion)return;
  renderCatalogue(data.results.filter(e=>e.compatible===true&&e.verified===true));
  catStato(`${data.checked_repositories} repository controllati. Mostrati solo i modelli compatibili con Hydra One e questo PC.`);
 }catch(error){if(version===catalogueVersion){renderCatalogue([]);catStato('Ricerca non completata: '+error.message,true);}}
 finally{catalogueSearching=false;$('cat-search').disabled=false;$('cat-query').disabled=false;}
}
function ensureCatalogueDialog(){
 if($('catalogue-dialog')){const logo=$('catalogue-dialog').querySelector('[data-catalogue-service-brand]');if(logo)logo.innerHTML=window.StrataBrands?.markup(window.StrataBrands.selectedEngine())||'';return $('catalogue-dialog');}
 const dialog=document.createElement('dialog');dialog.id='catalogue-dialog';dialog.className='catalogue-dialog';dialog.setAttribute('aria-labelledby','catalogue-dialog-title');
 dialog.innerHTML=`<header class="catalogue-dialog-head"><div class="catalogue-title-block"><div class="catalogue-title-brands"><span data-catalogue-service-brand>${window.StrataBrands?.markup(window.StrataBrands.selectedEngine())||''}</span>${window.StrataBrands?.markup('huggingface')||''}</div><div><h2 id="catalogue-dialog-title">Modelli e catalogo</h2><p>Confronta le varianti compatibili, controlla le risorse e prepara il tuo modello.</p></div></div><button type="button" id="catalogue-close" aria-label="Chiudi catalogo">×</button></header><div class="catalogue-dialog-tabs" role="tablist" aria-label="Gestione modelli"><button id="catalogue-tab-discover" role="tab" aria-selected="true" aria-controls="cat-block" data-cat-tab="discover">Catalogo Hugging Face</button><button id="catalogue-tab-prepared" role="tab" aria-selected="false" aria-controls="catalogue-prepared" data-cat-tab="prepared">Modelli preparati</button></div><div class="catalogue-dialog-scroll"><div id="catalogue-progress" class="catalogue-progress" hidden aria-live="polite"></div><section id="catalogue-prepared" hidden role="tabpanel" aria-labelledby="catalogue-tab-prepared"><div id="catalogue-installed"></div></section></div>`;
 document.body.append(dialog);const panel=$('cat-block');panel.className='catalogue-panel';panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby','catalogue-tab-discover');$ ('catalogue-progress').after(panel);
 $('catalogue-close').onclick=()=>catApri(false);
 dialog.addEventListener('close',()=>{catalogueOpen=false;panel.hidden=true;$('cat-toggle').textContent='Mostra catalogo';$('cat-toggle').setAttribute('aria-expanded','false');document.body.classList.remove('catalogue-modal-open');$('cat-toggle').focus();});
 dialog.addEventListener('click',event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)catApri(false);}});
 for(const button of dialog.querySelectorAll('[data-cat-tab]'))button.onclick=()=>{const prepared=button.dataset.catTab==='prepared';panel.hidden=prepared;$('catalogue-prepared').hidden=!prepared;for(const b of dialog.querySelectorAll('[data-cat-tab]')){b.setAttribute('aria-selected',String(b===button));b.tabIndex=b===button?0:-1;}};
 for(const [i,button] of [...dialog.querySelectorAll('[data-cat-tab]')].entries()){button.tabIndex=i===0?0:-1;button.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const tabs=[...dialog.querySelectorAll('[data-cat-tab]')];const target=event.key==='Home'?tabs[0]:event.key==='End'?tabs[1]:tabs[(i+1)%2];target.click();target.focus();}});}
 $('catalogue-installed').onclick=event=>{const button=event.target.closest('[data-prepared-key]');if(button)catUsa(button.dataset.preparedKey);};
 return dialog;
}
function renderPreparedCatalogue(models){
 ensureCatalogueDialog();const ready=models.filter(m=>m.ready);
 const markup=ready.length?ready.map(m=>{const entry=catalogueEntries.find(e=>e.key===m.key);const identity=entry?catalogueIdentity(entry):{name:m.display_label||m.label||m.key,author:m.author||'—'};return `<article class="catalogue-installed-entry"><div class="catalogue-prepared-identity"><div class="catalogue-mark" aria-hidden="true">${window.StrataModelBrands?.modelMarkup({name:identity.name,author:identity.author})||''}</div><div><h3>${esc(identity.name)}</h3><p>${entry?esc(identity.author)+' · '+esc(entry.quant):esc(m.key)}</p><span>File e pack verificati</span></div></div><button class="st-btn st-btn--secondary" data-prepared-key="${esc(m.key)}">Usa modello</button></article>`;}).join(''):'<p class="catalogue-empty">Nessun modello preparato. Scegli una variante nel catalogo.</p>';
 if(markup!==cataloguePreparedMarkup){$('catalogue-installed').innerHTML=markup;cataloguePreparedMarkup=markup;}
}
function catApri(open,search=true){
 const dialog=ensureCatalogueDialog();catalogueOpen=open===undefined?!dialog.open:!!open;
 $('cat-toggle').textContent=catalogueOpen?'Nascondi catalogo':'Mostra catalogo';$('cat-toggle').setAttribute('aria-expanded',String(catalogueOpen));
 if(catalogueOpen){$('cat-block').hidden=false;$('catalogue-prepared').hidden=true;for(const b of dialog.querySelectorAll('[data-cat-tab]')){b.setAttribute('aria-selected',String(b.dataset.catTab==='discover'));b.tabIndex=b.dataset.catTab==='discover'?0:-1;}if(!dialog.open)dialog.showModal();document.body.classList.add('catalogue-modal-open');catSegui();if(search&&!catalogueEntries.length&&!catalogueSearching)catCerca();}
 else if(dialog.open)dialog.close();
}

function renderCatalogueProgress(job){
 const target=$('catalogue-progress');target.dataset.state=job.state||'';target.hidden=!job.state;if(!job.state){target.innerHTML='';return;}
 const phases={starting:'Avvio della preparazione',downloading:'Download dei pesi',verifying:'Verifica dei pesi',packing:'Preparazione del pack',registering:'Registrazione del modello',done:'Modello pronto',failed:'Preparazione fallita'};
 const p=job.progress||{},total=Number(p.total_bytes||job.download_bytes||0),received=Number(p.received_bytes??(job.state==='done'?total:0));
 const percent=total>0?Math.min(100,Math.max(0,received/total*100)):null;
 const rate=Number.isFinite(p.network_bytes_per_second)?fmt(p.network_bytes_per_second/1e6,1)+' MB/s':job.state==='done'?'Completato':'Rilevamento in corso';
 const remaining=job.state==='done'?'Terminato':Number.isFinite(p.eta_seconds)&&job.state==='downloading'?fmt(Math.ceil(p.eta_seconds/60))+' min':job.state==='downloading'?'Calcolo in corso':'Elaborazione';
 const order=['downloading','verifying','packing','registering'];
 target.innerHTML=`<div class="catalogue-transfer-heading"><div><strong>${esc(phases[job.state]||job.state)}</strong><span>${esc(job.repo||'')}</span></div><b>${percent==null?'':fmt(percent,1)+'%'}</b></div><progress max="100" ${percent==null?'':`value="${percent}"`} aria-label="Avanzamento del download"></progress><dl class="catalogue-transfer-stats"><div><dt>Modello ricevuto</dt><dd>${total>0?fmt(Math.min(received,total)/2**30,2)+' / '+fmt(total/2**30,2)+' GiB':'Verifica dei metadati'}</dd></div><div><dt>Velocità rete</dt><dd>${esc(rate)}</dd></div><div><dt>Tempo residuo</dt><dd>${esc(remaining)}</dd></div></dl><ol aria-label="Fasi della preparazione">${order.map((phase,i)=>`<li class="${job.state===phase?'is-current':job.state==='done'||order.indexOf(job.state)>i?'is-complete':''}">${esc(['Download','Verifica','Pack','Registrazione'][i])}</li>`).join('')}</ol>${job.state==='verifying'?`<small>SHA256: ${esc(job.verification?.verified_files??0)} / ${esc(job.verification?.files_total??0)} file verificati</small>`:''}`;
 if(job.state==='done'){const details=document.createElement('details'),summary=document.createElement('summary');details.className='catalogue-transfer-complete';summary.append(target.firstElementChild);details.append(summary);while(target.firstChild)details.append(target.firstChild);target.append(details);}
}

async function catSegui(){
 if(catTimer)clearTimeout(catTimer);
 try{
  const response=await fetch('catalogue',{headers:headers(),cache:'no-store'});if(!response.ok)throw Error(`HTTP ${response.status}`);
  const data=await response.json(),h=data.host||{},job=data.job||{};
  renderPreparedCatalogue(data.prepared||[]);
  if(typeof aggiornaMenuModelli==='function')aggiornaMenuModelli({prepared:data.prepared||[]},health.model);
  renderCatalogueProgress(job);
  catalogueJob=job;if(['done','failed'].includes(job.state))cataloguePendingKey=null;
  if(data.entries?.length){
   for(const entry of catalogueEntries.filter(e=>e.repo===HYBRID_REPO))if(!data.entries.some(e=>e.key===entry.key))data.entries.push(entry);
   for(const entry of data.entries)if((data.prepared||[]).some(m=>m.key===entry.key&&m.ready))entry.on_disk=true;
  }
  $('cat-disk').innerHTML=[['RAM',h.ram_total_gib,'ram'],['VRAM',h.vram_total_gib,'vram'],['Disco libero',h.free_gib,'disk']].map(([name,value,kind])=>`<div class="catalogue-resource catalogue-resource--${kind}"><span>${name}</span><strong>${esc(value??'—')} <small>GiB</small></strong></div>`).join('');
  if(!catalogueSearching&&data.entries?.length)renderCatalogue(data.entries);
  else if(!catalogueEntries.length)$('cat-summary').textContent=`${(data.prepared||[]).filter(m=>m.ready).length} modelli installati · ricerca Hugging Face verificata`;
  if(job.state&&job.state!=='done')catStato(job.state==='failed'?'Preparazione fallita: '+job.error:`Preparazione: ${job.state} · ${job.repo||''}`,job.state==='failed');
  if(job.state==='done')catStato('Modello preparato e aggiunto al selettore della dashboard.');
  if(['starting','downloading','verifying','packing','registering'].includes(job.state))catTimer=setTimeout(catSegui,3000);
 }catch(error){if(catalogueOpen)catStato('Catalogo non aggiornato: '+error.message,true);}
}
async function catUsa(key){
 try{
  catStato('Seleziono il modello…');const result=await catPost('switch-model',{model:key});
  if(result.status==='already_active'){catStato('Modello confermato. Continua con Gestione risorse.');catApri(false);document.dispatchEvent(new CustomEvent('strata:model-confirmed',{detail:{engine:'strata',model:key}}));return;}
  catStato('Cambio modello in corso. La pagina si riconnette alla configurazione selezionata.');
  for(let i=0;i<60;i++){
   await new Promise(resolve=>setTimeout(resolve,2000));
   try{const response=await fetch('health',{headers:headers()});if(response.ok){const health=await response.json();if(health.model===result.target_model){sessionStorage.setItem('strata:launch-guide-next',JSON.stringify({model:result.target_model,at:Date.now()}));location.reload();return;}}}catch(error){}
  }
  catStato('Il nuovo server non risponde ancora. Consulta lo stato in Control.',true);
 }catch(error){catStato('Cambio non avviato: '+error.message,true);}
}
window.addEventListener('DOMContentLoaded',()=>{
ensureCatalogueDialog();catSegui();
$('cat-toggle').onclick=()=>catApri();$('cat-search').onclick=catCerca;
$('cat-query').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();catCerca();}};
$('cat-results').onclick=async event=>{
 const button=event.target.closest('[data-cat-action]');if(!button)return;
 const entry=catalogueEntries.find(e=>e.key===button.dataset.catKey);if(!entry)return;
 if(button.dataset.catAction==='use'){catUsa(entry.key);return;}
 button.disabled=true;cataloguePendingKey=entry.key;
 try{await catPost('catalogue-fetch',{repo:entry.repo,quant:entry.quant});catStato('Preparazione avviata sulla revisione verificata.');catSegui();}
 catch(error){cataloguePendingKey=null;catStato('Preparazione non avviata: '+error.message,true);button.disabled=false;}
};
});

window.addEventListener('strata:languagechange',()=>{if(catalogueEntries.length)renderCatalogue(catalogueEntries);});

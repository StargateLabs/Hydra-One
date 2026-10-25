/* HYDRA's single library delegates selection to the existing controllers. */
((root)=>{
 function libraryStatus(row,backend={},native={},english=false){
  const ready=english?'Engine active · model ready':'Motore attivo · modello pronto';
  if(row?.kind==='pack')return native.loaded&&native.profile===row.profile?ready:null;
  if(row?.path&&backend.model_path===row.path){
   if(backend.status==='ready')return ready;
   if(backend.status==='loading')return english?'Model starting…':'Avvio del modello in corso…';
  }
  return null;
 }
 function componentDescription(row,rows,english=false){
  if(row.file_role==='controlvector')return english?'Experimental control vector · optional, off by default. Changes model responses; it is not a speed optimization.':'Vettore di controllo sperimentale · opzionale, disattivato per default. Modifica le risposte; non è un’accelerazione.';
  if(row.file_role==='projector'){
   const owners=rows.filter(r=>!r.component&&(r.paired_projectors||[]).includes(row.path)).map(r=>r.name);
   return owners.length?(english?'Paired with ':'Associato a ')+owners.join(', ')+(english?' · used when Vision is enabled.':' · utilizzato quando Visione è attiva.'):(english?'No compatible model detected for automatic pairing.':'Nessun modello compatibile rilevato per l’associazione automatica.');
  }
  return english?'Draft · requires a compatible main model and speculative runtime.':'Draft · richiede modello principale e runtime speculativo compatibili.';
 }
 function componentsForModel(model,rows){
  if(!model)return [];
  return rows.filter(row=>row.component&&row.file_role==='projector'&&(model.paired_projectors||[]).includes(row.path));
 }
 function visibleLibraryRows(rows,query='',format='all'){
  return rows.filter(row=>(format==='all'||row.kind===format)&&[row.name,row.repo,row.path].join(' ').toLowerCase().includes(query.toLowerCase()));
 }
 function componentLabel(row,english=false){
  return ({projector:english?'Vision projector':'Proiettore visivo',controlvector:english?'Control vector':'Vettore di controllo',draft:english?'Draft component':'Componente draft'})[row.file_role]||'';
 }
 function projectorState(projector,model,backend={}){
  if(backend.status==='ready'&&backend.model_path===model.path&&backend.vision_requested===true&&backend.vision_device==='gpu'&&backend.mmproj_path===projector.path)return 'active';
  return ['loading','ready'].includes(backend.status)?'stop_required':'configure';
 }
 function libraryRows(local,native){
  const rows=[],seen=new Set();
  for(const row of local){
   if(!row.path||seen.has(row.path))continue;
   seen.add(row.path);
   const format=String(row.format||'').toLowerCase(),pack=row.required_engine==='strata';
   const route=pack?'hydra-strata':format==='gguf'?'hydra-gguf':format==='safetensors'?'hydra-safetensors':null;
   const profile=pack?native.find(p=>[row.strata_key,row.strata_configuration].includes(p.value)):null;
   const reason=row.runtime_supported===false?(row.runtime_error||'Runtime incompatibile'):!route?'Formato non riconosciuto':pack&&(!row.strata_ready||!profile)?'Configurazione del pack non disponibile':null;
   const filename=String(row.path).split(/[\\/]/).pop();
   const role=/^Qwen3[.]8-Flash-Next-experimental-speed-projection[.]gguf$/i.test(filename)?'controlvector':row.file_role||(/(?:^|[-_.])mmproj(?:[-_.]|$)/i.test(filename)?'projector':/(?:^|[-_.])(?:DSpark|DFLASH|projection)(?:[-_.]|$)/i.test(filename)?'draft':'model');
   rows.push({...row,file_role:role,key:row.path,route,profile:profile?.value,available:!reason,reason,kind:pack?'pack':format,component:['draft','projector','controlvector'].includes(role)});
  }
  for(const p of native){
   if(!p.value||rows.some(row=>row.profile===p.value))continue;
   rows.push({key:'profile:'+p.value,name:p.label,route:'hydra-strata',profile:p.value,kind:'pack',available:!p.disabled,reason:p.disabled?'Configurazione non disponibile':null});
  }
  return rows;
 }
 if(typeof module!=='undefined'&&module.exports){module.exports={libraryRows,libraryStatus,componentDescription,componentsForModel,projectorState,visibleLibraryRows,componentLabel};return;}
 const el=id=>document.getElementById(id),card=el('control-card-model')||document.querySelector('#backend-form .dash-card--model');if(!card||!root.StrataUnifiedEngine)return;
 const t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it;
 const panel=document.createElement('section');panel.id='hydra-model-library';panel.dataset.i18nIgnore='';panel.hidden=true;
 panel.innerHTML='<header><div><small>HYDRA ONE™</small><div class="hydra-library-identity"><img src="web/hydra-one.png" alt="HYDRA ONE" width="60" height="60"><h3></h3></div></div><span class="hydra-library-count"></span></header><div class="hydra-library-tools"><label><span></span><input type="search" id="hydra-library-search" autocomplete="off"></label><label><span id="hydra-library-format-label"></span><select id="hydra-library-filter"><option value="all"></option><option value="gguf">GGUF</option><option value="safetensors">Safetensors</option><option value="pack"></option></select></label></div><label class="hydra-library-picker"><span id="hydra-library-model-label"></span><select id="hydra-library-model"></select></label><div class="hydra-library-plan" role="status" aria-live="polite"></div><p class="hydra-library-help"></p><details class="hydra-library-unavailable"><summary></summary><p></p></details>';
 card.querySelector('.dash-body').append(panel);
 // Reuse the live controls: preserve listeners, IDs and their original homes.
 const nativeActions=document.createElement('div');nativeActions.className='hydra-library-native-actions';nativeActions.hidden=true;panel.append(nativeActions);
 const nativeControls=['ms-ctrl-model-info','ctrl-switch'].map(id=>{const node=el(id),home=document.createComment(id+' original position');node.before(home);return {node,home};});
 function placeNativeActions(inside){nativeActions.hidden=!inside;for(const {node,home} of nativeControls){if(inside){if(node.parentNode!==nativeActions)nativeActions.append(node);}else if(node.previousSibling!==home)home.after(node);}}

 const search=el('hydra-library-search'),filter=el('hydra-library-filter'),picker=el('hydra-library-model'),plan=panel.querySelector('.hydra-library-plan');
 panel.querySelector('.hydra-library-tools').remove();
 search.value='';filter.value='all';
 let rows=[],signature='',selection='',applying=false,controlMessage='';
 function render(){
  if(applying)return;
  const engine=root.StrataUnifiedEngine.selected(),active=engine.startsWith('hydra-');panel.hidden=!active;placeNativeActions(engine==='hydra-strata');if(!active)return;
  const native=[...el('ctrl-model').options].map(o=>({value:o.value,label:o.textContent,disabled:o.disabled}));
  rows=libraryRows(root.StrataOptional?.localModels()||[],native);
  const route=root.StrataUnifiedEngine.selected(),current=rows.find(r=>r.route===route&&(r.kind==='pack'?r.profile===el('ctrl-model').value:r.path===el('backend-file').value));if(current)selection=current.key;
  const query=search.value.trim().toLowerCase(),shown=visibleLibraryRows(rows,query,filter.value);
  panel.querySelector('h3').textContent=t('Scegli cosa eseguire con HYDRA ONE','Choose what to run with HYDRA ONE');
  const components=rows.filter(r=>r.component).length;
  panel.querySelector('.hydra-library-count').textContent=(rows.length-components)+' '+t('modelli rilevati','models detected')+(components?' · '+components+' '+t('componenti ausiliari','auxiliary components'):'');
  search.previousElementSibling.textContent=t('Cerca nella libreria','Search your library');search.placeholder=t('Nome, autore o percorso','Name, publisher or path');
  el('hydra-library-model-label').textContent=t('Modello','Model');
  const next=JSON.stringify([shown,query,filter.value,document.documentElement.lang]);
  if(next!==signature){signature=next;picker.replaceChildren(new Option(shown.length?t('Scegli un modello','Choose a model'):t('Nessun risultato: cambia ricerca o formato','No results: change search or format'),''));for(const row of shown){const size=Number.isFinite(row.bytes)?' · '+(row.bytes/2**30).toFixed(2)+' GiB':'';const option=new Option(row.component?row.name+' · '+componentLabel(row,document.documentElement.lang.startsWith('en')):row.name+' · '+(row.kind==='pack'?t('pack preparato','prepared pack'):row.format)+size+(row.available?'':' · '+t('non disponibile','unavailable')),row.key);option.disabled=!row.available;option.title=row.component?componentDescription(row,rows,document.documentElement.lang.startsWith('en')):row.reason||'';picker.add(option);}}picker.value=shown.some(r=>r.key===selection)?selection:'';
  const row=rows.find(r=>r.key===picker.value);
  plan.replaceChildren();
  if(row){const title=document.createElement('strong'),detail=document.createElement('span');title.textContent=row.available?t('Percorso predisposto','Path prepared'):t('Modello non disponibile','Model unavailable');detail.textContent=row.reason||({pack:t('Pack preparato · risorse gestite dal backend','Prepared pack · backend-managed resources'),gguf:'GGUF · CPU / GPU',safetensors:t('Safetensors · loader CPU / GPU configurabile','Safetensors · configurable CPU / GPU loader')}[row.kind]);plan.append(title,detail);}
  else plan.textContent=t('Scegli un modello: HYDRA prepara il percorso adatto.','Choose a model: HYDRA prepares the matching path.');
  const activeProfile=typeof ctrlState==='undefined'?null:(ctrlState.config?.prepared||[]).find(p=>p.label===ctrlState.model)?.key;
  const observed=typeof lastMetrics==='undefined'?null:(lastMetrics?.native_metrics||lastMetrics)?.live?.state;
  const actual=libraryStatus(row,root.StrataOptional?.state?.(),{profile:activeProfile,loaded:['idle','reading','generating'].includes(observed)},document.documentElement.lang.startsWith('en'));
  if(actual||controlMessage)plan.textContent=actual||controlMessage;
  const blocked=rows.filter(r=>!r.available&&!r.component),auxiliary=rows.filter(r=>r.component),details=panel.querySelector('.hydra-library-unavailable');details.hidden=!blocked.length&&!auxiliary.length;details.querySelector('summary').textContent=[blocked.length?blocked.length+' '+t('modelli da configurare','models requiring setup'):null,auxiliary.length?auxiliary.length+' '+t('componenti ausiliari','auxiliary components'):null].filter(Boolean).join(' · ');const componentList=details.querySelector('p');componentList.replaceChildren();for(const item of [...blocked,...auxiliary]){const line=document.createElement('span');line.style.display='block';line.style.marginBlock='8px';const name=document.createElement('strong'),copy=document.createElement('span');name.textContent=item.name;copy.textContent=': '+(item.component?componentDescription(item,rows,document.documentElement.lang.startsWith('en')):item.reason);line.append(name,copy);if(item.file_role==='projector'){const owner=rows.find(model=>model.available&&!model.component&&(model.paired_projectors||[]).includes(item.path));if(owner){const componentState=projectorState(item,owner,root.StrataOptional?.state?.()||{});if(componentState!=='configure'){const status=document.createElement('span');status.className='hydra-component-status';status.textContent=componentState==='active'?t(' · Visione GPU attiva',' · GPU vision active'):t(' · Ferma il motore attivo per configurare Visione GPU.',' · Stop the active engine to configure GPU vision.');line.append(status);componentList.append(line);continue;}const action=document.createElement('button');action.type='button';action.className='st-btn st-btn--secondary';action.textContent=t('Configura Visione GPU','Configure GPU vision');action.style.marginInlineStart='10px';action.disabled=['loading','ready'].includes(root.StrataOptional?.state?.().status);action.onclick=async()=>{action.disabled=true;selection=owner.key;picker.value=owner.key;const applied=await applySelection();if(applied&&el('backend-file').value===owner.path){el('backend-gpu').checked=true;if(root.StrataVision?.prepare(item.path,'gpu')){for(const id of ['backend-threads','backend-threads-batch'])if(el(id))el(id).value='2';el('backend-file').dispatchEvent(new Event('input'));controlMessage=t('Visione GPU predisposta per ','GPU vision prepared for ')+owner.name;render();}}};line.append(action);}}componentList.append(line);}
  panel.querySelector('.hydra-library-help').hidden=true;
 }
 async function applySelection(){
  selection=picker.value;const row=rows.find(r=>r.key===selection);if(!row?.available){render();return;}
  const initialEngine=root.StrataUnifiedEngine.selected();picker.disabled=true;
  controlMessage=t('Verifica del percorso sul server…','Checking the server-side path…');render();
  try{
   const response=await fetch('/hydra/model-plan',{method:'POST',headers:typeof headers==='function'?headers(true):{'Content-Type':'application/json'},body:JSON.stringify({model_path:row.path,profile:row.profile,mode:'auto',inspect_only:true}),signal:AbortSignal.timeout(10000)});
   const resolved=await response.json();if(!response.ok||!resolved.available)throw Error(resolved.reason||resolved.error?.message||'HYDRA model resolution failed');
   if(root.StrataUnifiedEngine.selected()!==initialEngine)return;
   if(resolved.route==='hydra-strata'&&![...el('ctrl-model').options].some(o=>o.value===resolved.profile))throw Error(t('Profilo preparato non presente nella libreria','Prepared profile missing from the library'));
   applying=true;
   try{
    root.StrataUnifiedEngine.select(resolved.route);
    if(resolved.route==='hydra-strata'){el('ctrl-model').value=resolved.profile;el('ctrl-model').dispatchEvent(new Event('change',{bubbles:true}));}
    else{el('backend-file').value=resolved.model_path;el('backend-local-model').value=resolved.model_path;el('backend-local-model').dispatchEvent(new Event('change',{bubbles:true}));el('backend-file').dispatchEvent(new Event('change',{bubbles:true}));}
    controlMessage=t('Selezionato · motore non avviato','Selected · engine not started');return true;
   }finally{applying=false;}
  }catch(error){controlMessage=t('Modello non applicato: ','Model not applied: ')+error.message;return false;}
  finally{picker.disabled=false;render();}
 }
 picker.addEventListener('change',applySelection);
 search.addEventListener('input',render);filter.addEventListener('change',render);
 document.addEventListener('strata:engine-selected',render);window.addEventListener('strata:metrics',render);
 new MutationObserver(render).observe(el('backend-local-model'),{childList:true});
 new MutationObserver(render).observe(el('ctrl-model'),{childList:true});
 new MutationObserver(render).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
 render();
})(globalThis);




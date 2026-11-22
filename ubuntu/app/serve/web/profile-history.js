/* Model profiles are data only; recovering a version never starts a runtime. */
(()=>{
 function record(history,key,previous,next,at){const versions=[...(Array.isArray(history[key])?history[key]:[])];if(!versions.length&&previous)versions.push({at:null,profile:structuredClone(previous)});if(!versions.length||JSON.stringify(versions.at(-1).profile)!==JSON.stringify(next))versions.push({at,profile:structuredClone(next)});return {...history,[key]:versions.slice(-20)};}
 if(typeof module!=='undefined')module.exports={record};if(typeof document==='undefined')return;
 const storage='strata.model_profile_versions';let refresh=()=>{};
 function read(){try{const data=JSON.parse(localStorage.getItem(storage)||'{}');return data&&typeof data==='object'&&!Array.isArray(data)?data:{};}catch{return {};}}
 window.StrataProfileHistory={record,save(key,previous,next){const data=record(read(),key,previous,next,new Date().toISOString());localStorage.setItem(storage,JSON.stringify(data));refresh();},mount({key,restore,canEdit}){
 const anchor=document.getElementById('backend-profile-save'),row=document.createElement('div');row.className='profile-version-control';row.dataset.i18nIgnore='';const label=document.createElement('label'),caption=document.createElement('span'),select=document.createElement('select'),button=document.createElement('button');select.className='st-input';button.className='st-btn st-btn--secondary';button.type='button';label.append(caption,select);row.append(label,button);anchor.parentElement.before(row);
 refresh=()=>{const en=document.documentElement.lang==='en';caption.textContent=en?'Saved profile versions':'Versioni del profilo salvate';button.textContent=en?'Recover settings':'Recupera impostazioni';const versions=read()[key()]||[];select.replaceChildren(new Option(en?'Choose a version':'Scegli una versione',''),...versions.map((v,i)=>new Option((i+1)+' · '+(v.at?new Date(v.at).toLocaleString(en?'en-GB':'it-IT'):en?'Previous profile':'Profilo precedente'),String(i))));row.hidden=!versions.length;button.disabled=!canEdit();};
 button.onclick=()=>{const v=(read()[key()]||[])[Number(select.value)];if(select.value===''||!v||!canEdit())return;restore(structuredClone(v.profile));};
 document.addEventListener('strata:engine-selected',refresh);window.addEventListener('strata:languagechange',refresh);document.getElementById('backend-config-dialog').addEventListener('toggle',refresh);new MutationObserver(refresh).observe(anchor,{attributes:true,attributeFilter:['disabled']});refresh();
 }};
})();

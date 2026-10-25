/* Colibri candidates come only from its official resolver. No automatic downloads. */
(()=>{
 const t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it;
 const headers=()=>{const key=document.getElementById('api-key')?.value||sessionStorage.getItem('strata-api-key');return key?{Authorization:'Bearer '+key}:{};};
 for(const id of ['catalogue-dialog','optional-catalogue-dialog']){
  const dialog=document.getElementById(id);if(!dialog)continue;
  const nav=dialog.querySelector('.catalogue-dialog-tabs')||dialog.querySelector('header');if(!nav)continue;
  const button=document.createElement('button');button.type='button';button.className='st-btn st-btn--secondary';button.dataset.catalogueEngine='colibri';button.innerHTML=(window.StrataBrands?.markup('colibri')||'')+'<span>Colibri</span>';nav.append(button);
  const panel=document.createElement('section');panel.className='colibri-catalogue';panel.hidden=true;panel.dataset.i18nIgnore='true';dialog.append(panel);
  let original=[];
  function close(){panel.hidden=true;for(const[node,hidden]of original)node.hidden=hidden;original=[];}
  dialog.addEventListener('close',close);
  button.onclick=async()=>{
   if(!panel.hidden){close();return;}
   original=[...dialog.children].filter(node=>node!==panel&&node!==nav&&node.tagName!=='HEADER'&&!node.contains(nav)).map(node=>[node,node.hidden]);for(const[node]of original)node.hidden=true;panel.hidden=false;panel.replaceChildren();
   const back=document.createElement('button');back.type='button';back.className='st-btn st-btn--secondary';back.textContent=t('Torna al catalogo','Back to catalogue');back.onclick=close;const heading=document.createElement('h3');heading.textContent=t('Modelli compatibili con Colibri','Colibri compatible models');const state=document.createElement('p');state.setAttribute('role','status');state.textContent=t('Lettura del catalogo ufficiale…','Reading official catalogue…');panel.append(back,heading,state);
   try{const response=await fetch('colibri/catalogue',{headers:headers()}),rows=await response.json();if(!response.ok)throw Error(rows.error?.message||response.status);state.textContent=t('Compatibilità dichiarata dal resolver ufficiale. La preparazione richiede una conferma separata del download.','Compatibility declared by the official resolver. Preparation requires separate download confirmation.');for(const row of rows){const card=document.createElement('article');card.className='colibri-catalogue-card';const title=document.createElement('h4');title.innerHTML=window.StrataModelBrands?.modelMarkup({name:row.name,repo:row.repo})||'';title.append(document.createTextNode(row.name));const facts=document.createElement('p');facts.textContent=row.download_gb+' GB · RAM '+row.ram_min_gb+' GB · '+(row.kind==='image'?t('Immagini','Images'):t('Testo','Text'));const note=document.createElement('p');note.textContent=[row.fits?t('Compatibile con le risorse rilevate.','Compatible with detected resources.'):t('Non utilizzabile con le risorse attualmente rilevate.','Not usable with currently detected resources.'),row.license_note].filter(Boolean).join(' ');const action=document.createElement('button');action.type='button';action.className='st-btn st-btn--primary';action.textContent=row.kind==='image'?t('Generazione immagini da collegare','Image generation integration pending'):row.fits?t('Scegli per Colibri','Choose for Colibri'):t('Risorse insufficienti','Insufficient resources');action.disabled=!row.fits||row.kind==='image';action.onclick=async()=>{action.disabled=true;try{await window.StrataColibri.chooseModel(row.id);dialog.close();document.getElementById('colibri-model').scrollIntoView({block:'center'});}catch(error){state.textContent=error.message;}finally{action.disabled=!row.fits||row.kind==='image';}};card.append(title,facts,note,action);panel.append(card);}}
   catch(error){state.textContent=error.message;}
  };
 }
})();

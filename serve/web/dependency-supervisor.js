/* Dependency recovery shares the existing authenticated, validated update flow. */
(()=>{
 const parent=document.querySelector('.update-center');if(!parent)return;
 const t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it;
 const node=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n;};
 const box=node('section'),title=node('h3',t('Controllo e recupero componenti','Component checks and recovery')),status=node('p',t('Controllo dipendenze in preparazione…','Preparing dependency checks…')),details=node('details'),list=node('ul');
 box.className='dependency-health-hub';box.style.padding='20px';box.dataset.i18nIgnore='';status.setAttribute('role','status');
 details.append(node('summary',t('Dettaglio dipendenze e risorse','Dependency and resource details')),list);
 const scan=node('button',t('Controlla tutto','Check everything')),repair=node('button',t('Recupera pacchetti mancanti','Recover missing packages'));
 for(const b of [scan,repair]){b.type='button';b.className='st-btn st-btn--secondary';}
 box.append(title,status,scan,repair,details);parent.querySelector('summary').after(box);
 let pending=false,latest={},autoChecked=false;
 function draw(data){
  latest=data.dependency_health||latest;list.replaceChildren();
  const rows=latest.checks||[],missing=rows.filter(r=>r.state==='missing');
  status.textContent=latest.checking?t('Controllo in corso…','Checking…'):latest.error||(!latest.checked_at?t('Controllo non ancora eseguito','Not checked yet'):`${rows.length} ${t('controlli','checks')} · ${t('elementi da ripristinare','items to recover')}: ${missing.length}`);
  for(const row of rows){const item=node('li',`${row.name}: ${row.state==='ready'?t('presente','present'):t('da ripristinare','needs recovery')}`);if(row.missing?.length){const info=node('details');info.append(node('summary',t('Risorse mancanti','Missing resources')),node('pre',row.missing.join('\n')));item.append(info);}list.append(item);}
  scan.disabled=pending||!!latest.checking;repair.disabled=pending||!!latest.checking||!latest.checked_at||latest.state==='error';
 }
 async function action(name){pending=true;draw({});try{const response=await fetch('updates/'+name,{method:'POST',headers:headers(true),body:'{}'}),data=await response.json();if(!response.ok)throw Error(data.error?.message||response.status);if(name==='repair-missing')status.textContent=t('Recupero affidato al Centro aggiornamenti: verifica, installazione e test dei componenti compatibili.','Recovery handed to the Update Centre: verification, installation and testing of compatible components.');else draw(data);}catch(error){status.textContent=error.message;}finally{pending=false;scan.disabled=false;repair.disabled=!!latest.checking||!latest.checked_at;}}
 scan.onclick=()=>action('health-check');repair.onclick=()=>action('repair-missing');
 async function refresh(){
  if(!parent.open||pending)return;
  try{const response=await fetch('updates/health',{headers:headers(false)});if(!response.ok)throw Error(response.status);const health=await response.json();draw({dependency_health:health});if(!autoChecked&&!health.checking&&!health.checked_at){autoChecked=true;await action('health-check');}}
  catch(error){status.textContent=error.message;}
 }
 const timer=setInterval(refresh,3000);window.addEventListener('pagehide',()=>clearInterval(timer));
 new MutationObserver(refresh).observe(parent,{attributes:true,attributeFilter:['open']});
 refresh();
 window.addEventListener('strata:updateschange',event=>{draw(event.detail||{});if(!autoChecked&&!pending&&!latest.checking&&!latest.checked_at){autoChecked=true;action('health-check');}});
})();

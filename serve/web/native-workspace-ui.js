/* Full native UIs live inside LocalAI's desktop container, never detached windows. */
(()=>{
 const t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it,pending=new Map();
 async function request(path,body){const response=await fetch('native-workspace'+path,{method:body===undefined?'GET':'POST',headers:headers(body!==undefined),body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});const data=await response.json();if(!response.ok)throw Error(data.error?.message||response.status);return data;}
 async function open(kind,box){
  if(pending.has(kind))return pending.get(kind);
  const task=(async()=>{const button=box.querySelector('[data-native-open]'),state=box.querySelector('[data-native-state]');button.disabled=true;
   try{state.textContent=t('Avvio dell’interfaccia originale dentro LocalAI…','Starting original interface inside LocalAI…');await request('/open',{kind});
    for(let attempt=0;attempt<90;attempt++){
     const status=await request('');const view=status.windows?.[kind];
     if(view?.embedded&&view.visible){state.textContent=t('Interfaccia originale attiva nella vista interna di LocalAI.','Original interface active in LocalAI’s internal view.');return;}
     if(status.error)throw Error(status.error);
     await new Promise(resolve=>setTimeout(resolve,500));
    }
    throw Error(t('Avvio ancora in corso. Verifica lo stato del contenitore.','Startup still in progress. Check workspace status.'));
   }catch(error){state.textContent=error.message;}finally{button.disabled=false;}
  })();pending.set(kind,task);try{await task;}finally{pending.delete(kind);}
 }
 function render(box,status,kind){
  const name=kind==='claude'?'Claude Desktop':'Antigravity';
  if(!box.querySelector('.native-workspace-app')){
   box.replaceChildren();const section=document.createElement('section');section.className='claude-official native-workspace-app';
   const title=document.createElement('h2'),copy=document.createElement('p'),button=document.createElement('button'),message=document.createElement('p');
   title.textContent=name;if(window.StrataBrands)title.insertAdjacentHTML('afterbegin',window.StrataBrands.markup(kind==='claude'?'claude-desktop':kind));copy.dataset.nativeCopy='';button.type='button';button.className='st-btn st-btn--primary';button.dataset.nativeOpen='';
   message.dataset.nativeState='';message.setAttribute('role','status');message.setAttribute('aria-live','polite');section.append(title,copy,button,message);box.append(section);button.onclick=()=>open(kind,box);
   if(kind==='claude'){
    const details=document.createElement('details'),summary=document.createElement('summary'),tools=document.createElement('div');
    summary.dataset.nativeToolsTitle='';details.append(summary,tools);section.append(details);details.addEventListener('toggle',()=>{if(details.open)window.StrataClaudeCodeUI?.render(tools,box._nativeStatus);});
   }
  }
  box._nativeStatus=status;
  box.querySelector('[data-native-copy]').textContent=t('Dashboard, Claude e Antigravity condividono la stessa finestra LocalAI. Configurazioni e sessioni restano quelle delle app originali.','Dashboard, Claude and Antigravity share one LocalAI window. Original app settings and sessions are preserved.');
  box.querySelector('[data-native-open]').textContent=t('Apri ','Open ')+name+t(' dentro LocalAI',' inside LocalAI');
  box.querySelector('[data-native-open]').disabled=pending.has(kind)||status?.desktop?.installed===false;
  const tools=box.querySelector('[data-native-tools-title]');if(tools)tools.textContent=t('Claude Code · controlli locali','Claude Code · local controls');
  document.getElementById('chat-harness-status').textContent=name+' · '+t('vista nativa integrata','embedded native view');
 }
 window.StrataNativeWorkspaceUI={render,open};
 window.StrataClaudeUI={render:(box,status)=>render(box,status,'claude')};
 window.StrataAntigravityUI={render:(box,status)=>render(box,status,'antigravity')};
})();

/* The installed native application owns its interface, sessions and windows. */
(()=>{
 const t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it;
 const pending=new Map();
 async function open(kind,box){
  if(pending.has(kind))return pending.get(kind);
  const button=box.querySelector('[data-native-open]'),message=box.querySelector('[data-native-state]');
  const operation=(async()=>{button.disabled=true;try{
   message.textContent=t('Apertura dell’app originale…','Opening original app…');
   const response=await fetch('harness/'+kind+'/desktop',{method:'POST',headers:headers(true),body:'{}'});
   const result=await response.json();if(!response.ok)throw Error(result.error?.message||response.status);
   message.textContent=t('Interfaccia originale collegata al Harness interno.','Original interface connected to the embedded Harness.');
  }catch(error){message.textContent=error.message;}finally{button.disabled=false;}})();
  pending.set(kind,operation);try{await operation;}finally{pending.delete(kind);}
 }
 window.StrataNativeDesktopUI={render(box,status,kind){
  const desktop=status?.desktop||{},name=kind==='claude'?'Claude Desktop':'Antigravity';
  if(!box.querySelector('.native-desktop-app')){
   box.replaceChildren();const section=document.createElement('section');section.className='claude-official native-desktop-app';
   const title=document.createElement('h2'),copy=document.createElement('p'),button=document.createElement('button'),message=document.createElement('p');
   title.textContent=name;button.type='button';button.className='st-btn st-btn--primary';button.dataset.nativeOpen='';
   message.dataset.nativeState='';message.setAttribute('role','status');copy.dataset.nativeDescription='';
   section.append(title,copy,button,message);box.append(section);button.onclick=()=>open(kind,box);
   if(kind==='claude'){
    const details=document.createElement('details'),summary=document.createElement('summary'),tools=document.createElement('div');
    summary.textContent=t('Claude Code · controlli locali','Claude Code · local controls');tools.className='native-code-tools';details.append(summary,tools);section.append(details);
    details.addEventListener('toggle',()=>{if(details.open)window.StrataClaudeCodeUI?.render(tools,box._nativeStatus);});
   }
  }
  box._nativeStatus=status;
  box.querySelector('[data-native-description]').textContent=t('Usa l’interfaccia originale dentro Harness, con le funzioni disponibili e le sessioni esistenti.','Use the original interface inside Harness, with available functions and existing sessions.');
  box.querySelector('[data-native-open]').textContent=t('Apri ','Open ')+name;
  box.querySelector('[data-native-open]').disabled=!desktop.installed||pending.has(kind);
  document.getElementById('chat-harness-status').textContent=name+' · '+t('interfaccia nativa','native interface');
 },open};
})();

(()=>{
 const wrap=document.querySelector('.st-composer__bar');if(!wrap)return;
 const panel=document.createElement('details');panel.className='chat-context';panel.dataset.i18nIgnore='';
 panel.innerHTML='<summary><span class="chat-context__label"></span><span class="chat-context__numbers"></span><span class="chat-context__track"><i></i></span><span class="chat-context__remaining"></span></summary><p></p>';
 wrap.insertBefore(panel,wrap.querySelector('.spacer'));
 const controls=document.createElement('div');controls.className='chat-context-tools';
 wrap.insertBefore(controls,panel);
 const actions=document.createElement('div');actions.className='chat-context-actions';actions.setAttribute('role','group');actions.setAttribute('aria-label','Chat actions');
 for(const id of ['attach-btn','new-btn','chat-delete-current','export-btn','sampling-btn','chat-mcp-trigger']){const button=document.getElementById(id);if(button)actions.append(button);}
 const remove=document.getElementById('chat-delete-current');if(remove){remove.dataset.i18nIgnore='';remove.className='st-btn st-btn--icon';remove.innerHTML='<svg class="st-icon" aria-hidden="true"><use href="web/sprite.svg#i-trash"/></svg>';}
 controls.append(actions,panel);
 const navigation=document.getElementById('chat-navigator');if(navigation)controls.append(navigation);
 const t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it;
 let previous='';
 function render(){
  const data=window.StrataChatContext?.snapshot();if(!data)return;
  const model=window.StrataOptional?.context();const capacity=model?.capacity||data.capacity;
  const last=data.messages.at(-1),usage=last&&last.model===data.model?last.usage:null;
  const measured=!data.busy&&!data.draft&&Number.isInteger(usage?.prompt_tokens)&&Number.isInteger(usage?.completion_tokens);
  const characters=(data.payloadCharacters??data.messages.reduce((n,m)=>n+m.text.length,0))+data.draft.length;
  const used=measured?usage.prompt_tokens+usage.completion_tokens:Math.ceil(characters/4)+data.messages.length*8;
  const ratio=capacity?Math.min(100,used/capacity*100):0;
  const signature=JSON.stringify([used,capacity,measured,model?.declared,document.documentElement.lang]);if(signature===previous)return;previous=signature;
  const f=n=>new Intl.NumberFormat(document.documentElement.lang).format(n);
  panel.querySelector('.chat-context__label').textContent=t('Contesto','Context');
  const compact=n=>n>=1000000?f(Math.round(n/10000)/100)+'M':n>=1000?f(Math.round(n/100)/10)+'k':f(n);
  panel.querySelector('.chat-context__numbers').textContent=(measured?'':'≈ ')+compact(used)+' / '+(capacity?compact(capacity):'—');
  panel.style.setProperty('--context-fill',ratio+'%');panel.dataset.level=ratio>=95?'critical':ratio>=80?'warning':'normal';
  panel.querySelector('.chat-context__remaining').textContent=capacity?(measured?'':'≈ ')+f(Math.max(0,capacity-used))+' '+t('liberi','remaining'):'—';
  panel.querySelector('summary').title=t('Mostra l’utilizzo del contesto','Show context usage');
  panel.querySelector('p').textContent=f(used)+' '+t('token usati','tokens used')+' · '+(capacity?f(Math.max(0,capacity-used))+' '+t('liberi','remaining'):'—')+'. '+(measured?t('Token misurati dal motore nell’ultima richiesta, inclusa la risposta.','Tokens measured by the engine in the last request, including its response.'):t('Stima del testo della conversazione e della bozza: il conteggio esatto arriva dal motore dopo la risposta. Template, allegati e strumenti possono richiedere altri token.','Estimated conversation and draft text: the exact count comes from the engine after its reply. Templates, attachments and tools can require additional tokens.'))+' '+t('Contesto caricato: ','Loaded context: ')+(capacity?f(capacity):'—')+'. '+t('Limite dichiarato dal modello: ','Declared model limit: ')+(model?.declared?f(model.declared):model?'—':capacity?f(capacity):'—')+'.';
 }
 document.getElementById('input').addEventListener('input',render);window.addEventListener('strata:languagechange',render);render();setInterval(()=>{if(!document.hidden)render();},1000);
})();

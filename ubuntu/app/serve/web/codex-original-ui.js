/* Render the actual Codex TUI. Opening this tab never starts an agent. */
(()=>{
 const t=(it,en)=>document.documentElement.lang==='en'?en:it;
 async function api(path,payload){const r=await fetch('harness/codex/'+path,{method:payload===undefined?'GET':'POST',headers:headers(true),body:payload===undefined?undefined:JSON.stringify(payload)});const d=await r.json();if(!r.ok)throw Error(d.error?.message||r.status);return d;}
 window.StrataCodexUI={render(box,status){
  if(box.dataset.originalHarness==='codex'){if(box._codexStatus)box._codexStatus(status);return;}
  box.replaceChildren();box.dataset.originalHarness='codex';
  const note=document.createElement('p'),start=document.createElement('button'),host=document.createElement('div');
  note.className='original-harness-status';note.setAttribute('role','status');host.className='original-claude-terminal';
  start.className='st-btn st-btn--primary';start.textContent=t('Apri Codex originale','Open original Codex');
  note.textContent=t('Sessione nella cartella ARA. Modello, autenticazione e conferme restano nativi.','Session in ARA workspace. Native model, authentication and approvals.');box.append(note,start,host);
  let term,fit,observer,cursor=0,running=false,writing=Promise.resolve();
  const visible=()=>!document.hidden&&!box.closest('[hidden]')&&box.getClientRects().length>0;
  const fail=e=>{note.textContent=e.message;};
  function resize(){if(!term||!visible())return;fit.fit();if(running)api('terminal/input',{action:'resize',cols:Math.max(10,Math.min(400,term.cols)),rows:Math.max(10,Math.min(400,term.rows))}).catch(fail);}
  function mount(){if(term)return;term=new Terminal({cursorBlink:false,scrollback:3000,fontSize:14,theme:{background:'#121416',foreground:'#e8e8e8'}});fit=new FitAddon.FitAddon();term.loadAddon(fit);term.open(host);observer=new ResizeObserver(resize);observer.observe(host);term.onData(data=>{if(!running)return;for(let i=0;i<data.length;i+=8192){const chunk=data.slice(i,i+8192);writing=writing.then(()=>api('terminal/input',{action:'input',data:chunk})).catch(fail);}});resize();}
  box._codexStatus=s=>{if(s?.ready&&!running){mount();running=true;start.hidden=true;resize();}else if(s?.installed===false){start.disabled=true;note.textContent=t('Codex.exe non disponibile nel PATH di Hydra.','Codex.exe not available in Hydra PATH.');}else start.disabled=false;};
  start.onclick=async()=>{start.disabled=true;try{mount();await api('terminal/start',{});term.reset();cursor=0;running=true;start.hidden=true;note.textContent=t('Codex originale · usa /quit per uscire. Chiudere il pannello conserva il compito.','Original Codex · use /quit to exit. Closing the panel preserves the task.');resize();term.focus();}catch(e){fail(e);}finally{start.disabled=false;}};
  let delay=250;
  async function poll(){if(!box.isConnected){observer?.disconnect();term?.dispose();return;}if(visible()&&running){try{const s=await api('terminal?after='+cursor);if(s.reset){term.reset();note.textContent=t('Output precedente ridotto al buffer disponibile.','Earlier output limited to the available buffer.');}for(const chunk of s.chunks||[])term.write(chunk);cursor=s.cursor;running=s.ready;start.hidden=running;if(!running)note.textContent=s.error||t('Sessione terminata.','Session ended.');delay=250;}catch(e){fail(e);delay=Math.min(5000,delay*2);}}setTimeout(poll,visible()?delay:1500);}
  box._codexStatus(status);poll();
 }};
})();

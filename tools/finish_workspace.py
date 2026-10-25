from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'serve/web/index.html'
s=p.read_text(encoding='utf-8');s=s.replace('<link rel="stylesheet" href="web/about.css', '<link rel="stylesheet" href="web/chat-workspace.css?v=20261009-1">\n<link rel="stylesheet" href="web/about.css');p.write_text(s,encoding='utf-8')
p=ROOT/'serve/web/chat-workspace.css';s=p.read_text();s=s.replace('--st-border','--st-line').replace('--st-text','--st-ink').replace('--st-muted','--st-ink-muted').replace('font:600 18px inherit','font:600 18px var(--st-font)');p.write_text(s)
p=ROOT/'serve/web/app.js';s=p.read_text(encoding='utf-8')
s=s.replace('if(!Array.isArray(chatArchives))chatArchives=[];',"if(!Array.isArray(chatArchives))chatArchives=[];\nchatArchives=chatArchives.filter(c=>c&&typeof c.id==='string'&&Array.isArray(c.messages));\nif(!Array.isArray(messages))messages=[];")
s=s.replace('meta.textContent = `You · ${timeStr(m.time)}`;', '''meta.textContent = `Tu · ${timeStr(m.time)}`;
    const edit=document.createElement('button');edit.className='chat-edit';edit.type='button';edit.textContent='Modifica';edit.dataset.chatEdit=i;meta.appendChild(edit);''')
s=s.replace('  $("input").value = "";\n  autosize();', '  $("input").value = "";\n  store.set("chat_draft", "");\n  autosize();')
s=s.replace('$("input").addEventListener("input", autosize);', '''$("input").addEventListener("input",()=>{autosize();store.set('chat_draft',$('input').value);});
$('input').value=store.get('chat_draft','');autosize();
function toggleChatHistory(open){$('chat-history-panel').hidden=!open;$('chat-history-btn').setAttribute('aria-expanded',String(open));if(open){updateChatWorkspace();$('chat-history-search').focus();}else $('chat-history-btn').focus();}
$('chat-history-btn').onclick=()=>toggleChatHistory($('chat-history-panel').hidden);
$('chat-history-close').onclick=()=>toggleChatHistory(false);
$('chat-history-search').oninput=updateChatWorkspace;
$('chat-find-input').oninput=updateChatWorkspace;
$('chat-title').onchange=()=>{chatTitle=$('chat-title').value.trim().slice(0,80);saveChat();};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('chat-history-panel').hidden)toggleChatHistory(false);});
$('chat-archive-list').onclick=e=>{
 const open=e.target.closest('[data-chat-open]'),del=e.target.closest('[data-chat-delete]');
 if(open){if(busy){toast('warn','Risposta in corso','Arresta la risposta prima di cambiare conversazione.');return;}const record=chatArchives.find(c=>c.id===open.dataset.chatOpen);if(!record||!archiveConversation())return;messages=structuredClone(record.messages);chatIdentity=record.id;chatTitle=record.title;attachments=[];renderAttachments();saveChat();renderChat();toggleChatHistory(false);}
 if(del){const backup=chatArchives;const next=chatArchives.filter(c=>c.id!==del.dataset.chatDelete);try{localStorage.setItem('strata.conversations',JSON.stringify(next));chatArchives=next;updateChatWorkspace();toast('info','Conversazione eliminata','',6000,{label:'Annulla',run:()=>{chatArchives=backup;store.set('conversations',backup);updateChatWorkspace();}});}catch(error){toast('error','Archivio non aggiornato',error.message);}}
};
function downloadChatJSON(){const record={id:chatIdentity,title:chatTitle||'Conversazione',model:health.model,updated_at:Date.now(),messages:persistentMessages()};const data={schema_version:1,exported_at:new Date().toISOString(),current:record,conversations:chatArchives,attachments:'Nomi conservati; contenuti da riallegare'};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='strata-conversazioni.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('chat-backup').onclick=downloadChatJSON;
for(const button of document.querySelectorAll('[data-chat-starter]'))button.onclick=()=>{$('input').value=button.dataset.chatStarter.replace(/\\\\n/g,'\\n');store.set('chat_draft',$('input').value);autosize();$('input').focus();};
function branchChat(index,regenerate=false){
 if(busy)return;const user=messages[index];if(user?.role!=='user')return;
 if((user.images||[]).some(i=>!i.url)||(user.files||[]).some(f=>typeof f.text!=='string')){toast('warn','Riallega i file','Il contenuto degli allegati non è conservato nell’archivio.');return;}
 if(!archiveConversation())return;
 messages=messages.slice(0,index);chatIdentity=crypto.randomUUID();attachments=[...(user.images||[]),...(user.files||[]).map(f=>({...f,kind:'file'}))];$('input').value=user.text;store.set('chat_draft',user.text);renderAttachments();saveChat();renderChat();autosize();$('input').focus();if(regenerate)send();
}
$('chat').addEventListener('click',e=>{const button=e.target.closest('[data-chat-edit]');if(button)branchChat(Number(button.dataset.chatEdit));});
$('chat-regenerate').onclick=()=>{if(busy||messages.at(-1)?.role!=='assistant')return;let index=messages.length-2;while(index>=0&&messages[index].role!=='user')index--;branchChat(index,true);};''')
start=s.index('    $("ctrl-switch").onclick = async () => {');end=s.index('    for (const [id, out, unit]',start)
s=s[:start]+"    $('ctrl-switch').onclick=()=>catUsa($('ctrl-model').value);\n"+s[end:]
s=s.replace('aria-label="Copy the answer" title="Copy"','aria-label="Copia la risposta" title="Copia"').replace('"The request failed"','"Richiesta non riuscita"').replace('"Still writing", "Stop the answer first."','"Risposta in corso", "Arresta la risposta prima."').replace('"Nothing to save yet"','"Nessun messaggio da esportare"')
s=s.replace("evidence.latest_kind === 'pcie55'", "['pcie20','pcie55'].includes(evidence.latest_kind)")
s=s.replace('Consulta il registro in Potenziamenti.','Consulta il registro in Prestazioni.')
s=s.replace('  return labels[Object.keys(labels)', '''  Object.assign(labels,{"iq3-memory-pcie20-b1":"PCIe 20% · variante B1","iq3-memory-pcie20-b2":"PCIe 20% · conferma B2"});
  return labels[Object.keys(labels)''')
p.write_text(s,encoding='utf-8')
p=ROOT/'serve/server.py';s=p.read_text(encoding='utf-8');s=s.replace('if not aiuto.exists():\n            raise ValueError', 'if not aiuto.exists():\n            self.switch_in_progress=False\n            raise ValueError');s=s.replace('except OSError as e:\n            raise ValueError(f"non riesco ad avviare il cambio:', 'except OSError as e:\n            self.switch_in_progress=False\n            raise ValueError(f"non riesco ad avviare il cambio:');s=s.replace("            if self.loaded():self.engine.unload()\n        finally:self.fifo.release()", "            if self.loaded():self.engine.unload()\n        except BaseException:\n            self.switch_in_progress=False\n            raise\n        finally:self.fifo.release()");p.write_text(s,encoding='utf-8')

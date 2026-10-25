/* Manual extractive prompt overlay; saved/rendered conversation remains complete. */
(()=>{
 let active=null,candidate=null,pending=false;
 const t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it;
 window.StrataContextCompaction={transform(rows,chatId){
  if(!active||active.chatId!==chatId)return rows;
  // Fail back to complete history if a source message is edited or regenerated.
  if(active.changes.some(c=>JSON.stringify(rows[c.index])!==JSON.stringify(c.original))){active=null;return rows;}
  const output=rows.slice();for(const c of active.changes)output[c.index]=c.replacement;return output;
 }};
  const container=document.querySelector('.chat-context-tools');
  // The button belongs to the icon group, not to the grid container it sits in: appended
  // to the grid it is stretched across a whole column and reads as a wide slab.
  const group=document.querySelector('.chat-context-actions')||container;if(!group)return;
  const button=document.createElement('button');button.type='button';
  button.className='st-btn chat-compact-btn';button.dataset.i18nIgnore='';
  button.setAttribute('aria-label','Compatta contesto');group.append(button);
 const dialog=document.createElement('dialog');dialog.className='st-card';dialog.style.cssText='max-width:min(680px,90vw);max-height:85vh;overflow:auto;color:var(--text);background:var(--surface,#17191e)';dialog.innerHTML='<h3></h3><p data-disclosure></p><p data-metrics></p><pre style="white-space:pre-wrap;max-height:40vh;overflow:auto"></pre><button type="button" data-apply class="st-btn st-btn--primary"></button> <button type="button" data-cancel class="st-btn st-btn--secondary"></button>';document.body.append(dialog);
 const invalidate=()=>window.StrataChatContext?.invalidate();
  function label(){
    const activeLabel=active?t('Ripristina contesto completo','Restore full context'):t('Compatta contesto','Compact context');
    // icon only, exactly like its neighbours in the group: the full wording lives in the
    // tooltip and the accessible name, so nothing is lost and the toolbar does not grow
    button.innerHTML='<svg class="st-icon" aria-hidden="true"><use href="web/sprite.svg#i-layers"/></svg>';
    button.setAttribute('aria-label',activeLabel);
    button.title=activeLabel+' — '+t('Prepara estratti dei messaggi vecchi; mostra l’anteprima prima di applicarli.','Prepare excerpts of old messages; preview before applying.');
    button.dataset.active=String(!!active);
  }
 button.onclick=async()=>{
  if(active){active=null;invalidate();label();return;}
  if(pending||window.StrataChatContext?.snapshot().busy)return;
  const input=window.StrataChatContext?.rawPayload();if(!input)return;
  pending=true;button.disabled=true;
  try{
   const response=await fetch('chat/context/compact',{method:'POST',headers:headers(true),body:JSON.stringify({messages:input.messages,keep_recent_turns:4,max_summary_chars:6000})});
   const result=await response.json();if(!response.ok)throw Error(result.error?.message||response.status);
   candidate={...result,chatId:input.chatId};
   dialog.querySelector('h3').textContent=t('Anteprima contesto compatto','Compact context preview');
   dialog.querySelector('[data-disclosure]').textContent=t('Estratti iniziali e finali, non riassunto semantico. Il testo centrale non entrerà nei prossimi prompt. La cronologia completa resta visibile ed esportabile; ultimi 4 turni, istruzioni e scambi con strumenti restano completi.','Beginning and ending excerpts, not a semantic summary. Middle text is omitted from subsequent prompts. Full history stays visible and exportable; last 4 turns, instructions and tool exchanges stay complete.');
   dialog.querySelector('[data-metrics]').textContent=result.before_characters+' → '+result.after_characters+' '+t('caratteri nel prompt; ','prompt characters; ')+result.changes.length+' '+t('messaggi abbreviati.','shortened messages.');
   if(result.context_analysis)dialog.querySelector('[data-metrics]').textContent+=' Open WebUI · ~'+result.context_analysis.estimated_tokens+' '+t('token stimati prima della compattazione.','estimated tokens before compaction.');
   dialog.querySelector('pre').textContent=result.changes.map(c=>c.original.role+':\n'+c.replacement.content).join('\n\n');
   const apply=dialog.querySelector('[data-apply]');apply.textContent=t('Applica ai prossimi prompt','Apply to subsequent prompts');apply.disabled=!result.changes.length;
   dialog.querySelector('[data-cancel]').textContent=t('Annulla','Cancel');dialog.showModal();
  }catch(error){toast('error',t('Contesto','Context'),error.message);}finally{pending=false;button.disabled=false;}
 };
 dialog.querySelector('[data-apply]').onclick=()=>{if(window.StrataChatContext?.snapshot().busy)return;const now=window.StrataChatContext?.rawPayload();if(!candidate||now.chatId!==candidate.chatId||candidate.changes.some(c=>JSON.stringify(now.messages[c.index])!==JSON.stringify(c.original))){dialog.close();candidate=null;return;}active=candidate;candidate=null;invalidate();dialog.close();label();};
 dialog.querySelector('[data-cancel]').onclick=()=>{candidate=null;dialog.close();};
 window.addEventListener('strata:languagechange',label);label();
})();

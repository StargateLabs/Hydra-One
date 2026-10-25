/* Ordered spotlight over existing fields. Navigation never applies settings or starts work. */
(()=>{
 const t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it;
 function mount(root,anchor,scope){if(!root||!anchor||!scope)return;
  const bar=document.createElement('section');bar.className='workspace-step-guide';bar.dataset.i18nIgnore='';bar.setAttribute('aria-label',t('Guida alla configurazione','Configuration guide'));bar.innerHTML='<span class="workspace-step-count"></span><div><strong></strong><p></p></div><div class="workspace-step-actions"><button type="button" class="st-btn st-btn--secondary"></button><button type="button" class="st-btn st-btn--primary"></button></div>';anchor.after(bar);
  const count=bar.querySelector('span'),title=bar.querySelector('strong'),hint=bar.querySelector('p'),[back,next]=bar.querySelectorAll('button');let fields=[],current=null,scheduled=false;root.dataset.workspaceGuide='active';
  // Keep original validation and its action available without a second competing guide.
  const validations=Array.from(scope.querySelectorAll('.configuration-assistant')).map(assistant=>{const details=document.createElement('details'),summary=document.createElement('summary');details.className='workspace-guide-validation';assistant.before(details);details.append(summary,assistant);return summary;});
  const put=(node,text)=>{if(node.textContent!==text)node.textContent=text;};
  function visible(e){return !e.closest('[hidden]')&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';}
  function eligible(label){return visible(label)&&Array.from(label.querySelectorAll('input:not([type=hidden]),select,textarea')).some(e=>!e.disabled&&!e.readOnly);}
  function name(label){const caption=label.querySelector(':scope>span:not(.st-select),:scope>strong');if(caption)return caption.textContent.trim();const copy=label.cloneNode(true);copy.querySelectorAll('input,select,textarea,button,small,output,.st-select').forEach(e=>e.remove());return copy.textContent.trim().replace(/\s+/g,' ').slice(0,110)||t('Configurazione','Configuration');}
  function group(label){const selector='.generation-grid,.training-fields,.training-dataset-pair';let candidate=label.closest(selector);if(!candidate||!scope.contains(candidate))return label;let parent=candidate.parentElement?.closest(selector);while(parent&&scope.contains(parent)){candidate=parent;parent=candidate.parentElement?.closest(selector);}return candidate;}
  function render(){scheduled=false;fields=Array.from(scope.querySelectorAll('label')).filter(eligible).filter(label=>!label.closest('.workspace-step-guide'));
   if(!fields.includes(current))current=fields[0]||null;
   const activeGroup=current?group(current):null,groups=new Set(fields.map(group));
   for(const node of scope.querySelectorAll('.workspace-guide-field')){if(!fields.includes(node))node.classList.remove('workspace-guide-field','workspace-guide-field-current');}
   for(const node of scope.querySelectorAll('.workspace-guide-section')){if(!groups.has(node))node.classList.remove('workspace-guide-section','workspace-guide-section-current');}
   for(const field of fields){field.classList.add('workspace-guide-field');field.classList.toggle('workspace-guide-field-current',field===current);}
   for(const section of groups){section.classList.add('workspace-guide-section');section.classList.toggle('workspace-guide-section-current',section===activeGroup);}
   bar.hidden=!current;validations.forEach(summary=>put(summary,t('Completezza dei campi richiesti','Required field completeness')));const index=fields.indexOf(current);put(count,`${index+1} / ${fields.length}`);put(title,current?name(current):'');const control=current?.querySelector('input,select,textarea'),described=(control?.getAttribute('aria-describedby')||'').split(/\s+/).map(id=>document.getElementById(id)?.textContent?.trim()).filter(Boolean).join(' '),help=described||current?.querySelector('small,[class*=help]')?.textContent?.trim()||control?.title;put(hint,help||t('Configura questo campo, poi passa al successivo. Le scelte si applicano soltanto con i comandi originali.','Configure this field, then continue. Settings apply only through the original actions.'));put(back,t('Precedente','Previous'));put(next,index===fields.length-1?t('Ultimo campo','Last field'):t('Successivo','Next'));back.disabled=index<=0;next.disabled=index<0||index===fields.length-1;
  }
  function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(render);}}
  function move(delta){render();const index=fields.indexOf(current),target=fields[index+delta];if(!target)return;current=target;render();target.scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth'});const control=target.querySelector('.premium-select-button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled])');control?.focus({preventScroll:true});}
  back.onclick=()=>move(-1);next.onclick=()=>move(1);
  function select(event){const label=event.target.closest('label');if(label&&fields.includes(label)&&current!==label){current=label;render();}}
  scope.addEventListener('focusin',select);scope.addEventListener('pointerdown',select);
  root.addEventListener('click',schedule);root.addEventListener('change',schedule);root.addEventListener('toggle',schedule,true);window.addEventListener('resize',schedule);
  new MutationObserver(schedule).observe(scope,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden','disabled','aria-pressed']});new MutationObserver(schedule).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});render();
 }
 const training=document.getElementById('local-training-panel');mount(training,training?.querySelector('.training-function-guide'),training?.querySelector('.training-editor'));
 const media=document.getElementById('local-audio-panel');mount(media,media?.querySelector('.media-function-head'),document.getElementById('media-function-body'));
})();


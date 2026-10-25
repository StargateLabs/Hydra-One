/* Guide actual missing values; configured defaults need no manual confirmation. */
(()=>{
 const t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it;
 const setText=(element,copy)=>{if(element.textContent!==copy)element.textContent=copy;};
 function controls(form){return [...form.querySelectorAll('input,select,textarea')].filter(input=>!input.disabled&&!['hidden','submit','button','checkbox'].includes(input.type)&&!input.closest('[hidden]')&&input.closest('label')&&input.closest('label').getClientRects().length);}
 function complete(input){
  if(['backend-local-model','backend-file'].includes(input.id)&&document.getElementById('backend-mode')?.value!=='api')return !!(document.getElementById('backend-local-model')?.value||document.getElementById('backend-file')?.value.trim());
  return input.validity.valid&&(!input.required||!!input.value.trim());
 }
 for(const id of ['backend-form','generation-form','training-form','audio-form','speech-form','separation-form']){
  const form=document.getElementById(id);if(!form)continue;const guide=document.createElement('section');guide.className='configuration-assistant';guide.dataset.i18nIgnore='true';guide.innerHTML='<div><strong></strong><p role="status"></p></div><button type="button" class="st-btn st-btn--secondary"></button>';form.prepend(guide);let current=null,scheduled=false,attempted=false,guideStep=0;
  let path=null;const steps=[['Modello','Model'],['Motore','Engine'],['Risorse','Resources'],['Calcolo','Compute'],['Generazione','Generation'],['Strumenti','Tools']];
  function modelChosen(){return document.getElementById('backend-mode')?.value==='api'?!!document.getElementById('backend-id')?.value.trim():!!(document.getElementById('backend-local-model')?.value||document.getElementById('backend-file')?.value.trim());}
  function go(step){
   if(document.getElementById('backend-mode')?.value==='api'&&[3,4].includes(step))step=5;
   if(step===1&&document.getElementById('backend-mode')?.value==='api'){document.getElementById('backend-id').focus();guideStep=1;schedule();return;}
   if(step===2){const field=document.getElementById('unified-engine')||document.getElementById('backend-mode');field.closest('label').scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});field.focus();guideStep=2;schedule();return;}
   if(step===1||!modelChosen()){guideStep=1;schedule();const picker=form.querySelector('.local-model-browse');if(picker&&!picker.disabled)picker.click();return;}
   guideStep=step;schedule();if(step===3){document.getElementById('backend-resource-step').scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});return;}
   document.getElementById('backend-configuration').open=true;document.getElementById('backend-config-tab-'+({4:'compute',5:'generation',6:'tools'}[step])).click();
  }
  if(id==='backend-form'){path=document.createElement('nav');path.className='backend-guide-path';path.ariaLabel=t('Ordine della configurazione','Configuration order');for(let step=1;step<=6;step++){const button=document.createElement('button');button.type='button';button.dataset.step=String(step);button.innerHTML='<span></span><strong></strong>';button.querySelector('span').textContent=String(step);button.onclick=()=>go(step);path.append(button);}guide.append(path);}
  function update(){scheduled=false;const list=controls(form),labels=[...new Set(list.map(input=>input.closest('label')))];
   for(const label of form.querySelectorAll('[data-config-state]')){delete label.dataset.configState;delete label.dataset.configCurrent;}
   labels.forEach((label,index)=>{label.dataset.configState=list.filter(input=>input.closest('label')===label).every(complete)?'complete':attempted?'invalid':'incomplete';if(id!=='backend-form'){const title=label.querySelector(':scope > span,:scope > strong');if(title){let number=title.querySelector('.configuration-field-number');if(!number){number=document.createElement('span');number.className='configuration-field-number';number.ariaHidden='true';title.prepend(number);}setText(number,(index+1)+'. ');}}});
   const remaining=list.filter(input=>!complete(input));current=remaining[0]||null;if(current)current.closest('label').dataset.configCurrent='true';
   setText(guide.querySelector('strong'),t('Configurazione guidata','Guided setup')+' · '+(list.length-remaining.length)+' / '+list.length);
   const caption=current?.closest('label').querySelector(':scope > span,:scope > strong')?.textContent||current?.name||current?.id;
   setText(guide.querySelector('p'),current?t('Da completare: ','To complete: ')+caption:t('Campi compilati. La compatibilità viene verificata prima dell’avvio.','Fields completed. Compatibility is checked before startup.'));
   setText(guide.querySelector('button'),current?t('Vai al campo da completare','Go to missing field'):t('Rivedi la configurazione','Review settings'));
   guide.dataset.guideState=current?'needs-input':'ready';
   if(path){const step=guideStep||(!modelChosen()?1:document.getElementById('backend-mode')?.value==='api'?5:3);guide.dataset.activeStep=String(step);setText(guide.querySelector('strong'),t('Configura il motore','Configure the engine')+' · '+t('passaggio ','step ')+step+' / 6');setText(guide.querySelector('p'),!modelChosen()?t('Scegli il modello: formato e motore determinano quali configurazioni puoi usare.','Choose a model: its format and engine determine the available settings.'):t('Segui i passaggi in ordine. Le impostazioni già compilate restano conservate; la compatibilità viene verificata prima dell’avvio.','Follow the steps in order. Existing settings are preserved; compatibility is checked before startup.'));setText(guide.querySelector(':scope > button'),!modelChosen()&&step!==2?t('1. Scegli il modello','1. Choose model'):t('Apri il passaggio '+step,'Open step '+step));for(const button of path.children){const number=Number(button.dataset.step);button.setAttribute('aria-current',number===step?'step':'false');button.hidden=document.getElementById('backend-mode')?.value==='api'&&[3,4].includes(number);button.dataset.completed=String(number<step);setText(button.querySelector('strong'),t(...steps[number-1]));}}
  }
  function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(update);}}
  guide.querySelector('button').onclick=()=>{if(path){go(Number(guide.dataset.activeStep));return;}update();const input=current||controls(form)[0];if(!input)return;for(let parent=input.parentElement;parent&&parent!==form;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;input.closest('label').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'});input.focus({preventScroll:true});};
  function changed(event){if(['backend-mode','backend-local-model','backend-file'].includes(event.target.id))guideStep=0;schedule();}form.addEventListener('input',changed);form.addEventListener('change',changed);form.addEventListener('strata:configuration-choice',changed);form.addEventListener('invalid',()=>{attempted=true;schedule();},true);
  new MutationObserver(schedule).observe(document.body,{subtree:true,childList:false,attributes:true,attributeFilter:['hidden','disabled','required','open']});new MutationObserver(schedule).observe(form,{childList:true,subtree:true});new MutationObserver(schedule).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});update();
 }
})();



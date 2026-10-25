/* Catalogue context follows the selected engine; opening never changes it. */
(()=>{
 const t=(it,en)=>document.documentElement.lang.startsWith('en')?en:it;
 function update(dialog){
  const selected=window.StrataUnifiedEngine?.selected?.()||'strata',hydra=selected.startsWith('hydra-');
  const brand=hydra?'hydra':selected==='colibri'?'colibri':selected==='strata'?'strata':selected==='gguf'?'llama.cpp':selected==='safetensors'?'transformers':'openai';
  const name=hydra?'HYDRA ONE™ (HYBRID By StargateLab™)':selected==='colibri'?'Colibri':selected==='strata'?'Hydra One':document.querySelector('#unified-engine')?.selectedOptions[0]?.textContent||selected;
  let context=dialog.querySelector('.catalogue-engine-context');
  if(!context){context=document.createElement('div');context.className='catalogue-engine-context';context.dataset.i18nIgnore='';context.setAttribute('role','status');dialog.querySelector('header')?.append(context);}
  context.replaceChildren();
  if(window.StrataBrands)context.insertAdjacentHTML('beforeend',window.StrataBrands.markup(brand));
  const copy=document.createElement('div'),label=document.createElement('small'),title=document.createElement('strong');label.textContent=t('Catalogo per il motore selezionato','Catalogue for the selected engine');title.textContent=name;copy.append(label,title);context.append(copy);
  dialog.dataset.selectedEngine=selected;
  const colibri=dialog.querySelector('[data-catalogue-engine="colibri"]');
  if(colibri){
   if(selected!=='colibri'&&dialog.querySelector('.colibri-catalogue')?.hidden===false)colibri.click();
   colibri.hidden=selected!=='colibri';
   if(selected==='colibri'&&dialog.open&&dialog.querySelector('.colibri-catalogue')?.hidden===true)colibri.click();
  }
 }
 function mount(){for(const id of ['catalogue-dialog','optional-catalogue-dialog']){const dialog=document.getElementById(id);if(!dialog)continue;new MutationObserver(()=>{if(dialog.open)update(dialog);}).observe(dialog,{attributes:true,attributeFilter:['open']});document.addEventListener('strata:engine-selected',()=>{if(dialog.open)update(dialog);});document.addEventListener('strata:languagechange',()=>{if(dialog.open)update(dialog);});}}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();

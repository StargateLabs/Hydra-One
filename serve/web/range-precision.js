/* Exact input for numeric ranges. Existing apply actions remain the only writes. */
((root)=>{
 function valid(value,min,max,step){return Number.isFinite(value)&&value>=min&&value<=max&&(step==='any'||Math.abs((value-min)/step-Math.round((value-min)/step))<1e-6);}
 function presets(id,min,max){
  const sizes=id==='ctrl-vram-reserve'?[0,256,512,768,1024,1536,2048,3072,4096,6144,8192,12288,16384]:['ctrl-kv-resident','ctrl-max-ctx','colibri-context','backend-context-range'].includes(id)?[1024,2048,4096,8192,16384,20480,24576,32768,49152,65536,98304,131072,196608,262144,524288,1048576]:['pm-temp','ctrl-temp-limit'].includes(id)?[50,55,60,65,70,75,80,85,90,95]:['pm-power','ctrl-power-limit'].includes(id)?[50,75,100,125,150,175,200,225,250,275,300,325,350]:id==='s-temp'?[0,.1,.2,.3,.4,.5,.6,.7,.8,.9,1,1.2,1.5]:id==='s-topp'?[.05,.1,.2,.3,.4,.5,.6,.7,.8,.9,.95,1]:id==='s-topk'?[1,5,10,15,20,25,32,40,48,56,64]:id==='colibri-runtime-ram'?[0,4,8,12,16,24,32,48,64,96,128]:id==='colibri-runtime-vram'?[0,2,4,6,8,10,12,16,20,24]:[];
  return sizes.filter(value=>value>=min&&value<=max);
 }
 function attach(range){
  if(range.dataset.precision||range.id==='colibri-runtime-policy')return;
  range.dataset.precision='true';
  const box=document.createElement('div');box.className='range-precise';box.dataset.i18nIgnore='true';box.setAttribute('role','group');
  const caption=document.createElement('span');caption.textContent=document.documentElement.lang.startsWith('en')?'Custom value':'Valore personalizzato';
  const input=document.createElement('input');input.type='number';input.className='st-input';input.id=range.id?range.id+'-exact':'';input.inputMode='decimal';
  const name=range.getAttribute('aria-label')||range.closest('.dm')?.querySelector('.dm__label')?.firstChild?.textContent||range.id;
  input.setAttribute('aria-label',name+' · '+caption.textContent);
  const customStep=()=>['s-temp','s-topp'].includes(range.id)?'any':['ctrl-vram-reserve','ctrl-kv-resident','ctrl-max-ctx'].includes(range.id)?1:range.step||1;
  const sync=()=>{input.title=(document.documentElement.lang.startsWith('en')?'Supported range: ':'Intervallo supportato: ')+range.min+' – '+range.max+' · '+(document.documentElement.lang.startsWith('en')?'step ':'passo ')+customStep();input.min=range.min;input.max=range.max;input.step=customStep();input.disabled=range.disabled;if(document.activeElement!==input){input.value=range.value;input.setCustomValidity('');}};
  range.addEventListener('input',sync);range.addEventListener('change',sync);input.addEventListener('focus',sync);
  input.addEventListener('input',()=>{const value=input.valueAsNumber,step=customStep();if(!valid(value,+range.min,+range.max,step==='any'?'any':+step)){input.setCustomValidity(document.documentElement.lang.startsWith('en')?'Use a value within the supported range.':'Usa un valore entro i limiti supportati.');return;}input.setCustomValidity('');range.step=String(step);range.value=String(value);range.dispatchEvent(new Event('input',{bubbles:true}));});
  input.addEventListener('change',()=>{if(!input.validity.valid){input.reportValidity();return;}range.dispatchEvent(new Event('change',{bubbles:true}));});
  input.addEventListener('keydown',event=>{if(event.key==='Enter')event.preventDefault();});
  box.append(caption,input);const host=range.closest('.dash-controls,.slider-row');if(host){const scale=host.nextElementSibling;((scale?.classList.contains('range-scale'))?scale:host).after(box);}else{const scale=range.nextElementSibling;(scale?.classList.contains('range-scale')?scale:range).after(box);}
  sync();new MutationObserver(sync).observe(range,{attributes:true,attributeFilter:['min','max','step','disabled']});
 }
 function scan(){document.querySelectorAll('input[type=range]').forEach(attach);}
 root.StrataRangePrecision={valid,scan,presets};if(typeof module!=='undefined')module.exports={valid,presets};
 if(typeof document!=='undefined'){scan();new MutationObserver(records=>{if(records.some(r=>[...r.addedNodes].some(n=>n.nodeType===1&&(!n.classList.contains('range-precise'))&&(n.matches('input[type=range]')||n.querySelector('input[type=range]')))))scan();}).observe(document.body,{childList:true,subtree:true});document.addEventListener('strata:languagechange',()=>{document.querySelectorAll('.range-precise>span').forEach(el=>el.textContent=document.documentElement.lang.startsWith('en')?'Custom value':'Valore personalizzato');});}
})(typeof window==='undefined'?globalThis:window);

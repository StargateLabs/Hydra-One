(function(){
 'use strict';
 function node(tag,text,className){const element=document.createElement(tag);if(text!==undefined)element.textContent=text;if(className)element.className=className;return element;}
 window.renderPytorchIntegration=function(row,options={}){
  const target=options.target||document.getElementById('pytorch-integration');if(!target)return;
  const english=(document.documentElement.lang||'it').startsWith('en');const text=(it,en)=>english?en:it;
  target.replaceChildren();const heading=node('h3','PyTorch');
  if(window.StrataBrands)heading.insertAdjacentHTML('afterbegin',window.StrataBrands.markup('pytorch'));
  target.append(heading,node('p',text('Framework tensoriale usato dai loader Python e dall’addestramento. Versione e build GPU restano separate per ambiente.','Tensor framework used by Python loaders and training. Version and GPU build remain separate for each environment.')));
  const facts=node('div',undefined,'up-facts');
  for(const [label,value]of[[text('PyTorch dell’ambiente Unsloth','Unsloth environment PyTorch'),row.installed_version||'—'],[text('Ultima release pubblicata · PyPI','Latest published release · PyPI'),row.version||'—'],[text('Python richiesto dalla release','Release Python requirement'),row.requires_python||'—']]){const box=node('div');box.append(node('small',label),node('strong',value));facts.append(box);}target.append(facts);
  const guide=node('ol',undefined,'config-order-guide');for(const line of [text('1. Scegli l’ambiente dell’app che vuoi aggiornare.','1. Choose the environment used by your app.'),text('2. Prepara il piano: confronta dipendenze e build CPU/GPU.','2. Prepare the plan: compare dependencies and CPU/GPU builds.'),text('3. Verifica la copia candidata prima di selezionarla.','3. Verify the candidate copy before selecting it.')])guide.append(node('li',line.replace(/^\d\. /,'')));target.append(guide);
  for(const environment of row.installed_environments||[]){const box=node('div',undefined,'up-update-action');box.append(node('strong',environment.environment+' · torch '+environment.version),node('p',text('Tipo di build: ','Build type: ')+({unknown:text('Da verificare','Needs verification'),cpu:'CPU',cuda:'CUDA',rocm:'ROCm · AMD'}[environment.flavor]||environment.flavor)+(environment.build_suffix?' · '+environment.build_suffix:'')));
   box.append(node('p',environment.flavor==='rocm'?text('Preservare wheel e canale ROCm AMD/PyTorch. La release PyPI non certifica compatibilità con questa build.','Preserve the AMD/PyTorch ROCm wheel and channel. The PyPI release does not certify compatibility with this build.'):text('Il tipo di build deriva dai metadati, non da una prova sulla GPU.','Build type comes from metadata, not a GPU runtime test.')));
   if(options.onManage){const manage=node('button',text('2. Prepara piano · ','2. Prepare plan · ')+environment.environment,'st-btn st-btn--primary');manage.type='button';manage.onclick=()=>options.onManage(environment.environment);box.append(manage);}target.append(box);
  }
  target.append(node('p',text('Aggiornamenti in un candidato isolato: nessuna sostituzione automatica dell’ambiente funzionante.','Updates use an isolated candidate: no automatic replacement of a working environment.')));
  for(const [label,url]of[['PyTorch','https://pytorch.org/'],['GitHub','https://github.com/pytorch/pytorch'],['PyPI',row.release_url||'https://pypi.org/project/torch/']]){const link=node('a',label+' ↗');link.href=url;link.target='_blank';link.rel='noopener noreferrer';target.append(link,node('br'));}
 };
})();

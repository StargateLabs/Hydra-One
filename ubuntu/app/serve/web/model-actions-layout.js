/* Reparent existing controls; retain IDs, listeners, values and live ownership. */
((root)=>{
 function mount(document){
  const form=document.getElementById('backend-form');
  const model=form?.querySelector('.dash-card--model');
  const run=form?.querySelector('.dash-card--run');
  if(!model||!run)return false;
  if(run.parentElement!==model)model.append(run);
  run.classList.add('model-actions-embedded');
  form.dataset.modelActions='embedded';
  return true;
 }
 if(typeof module!=='undefined')module.exports={mount};
 if(root.document)mount(root.document);
})(typeof window==='undefined'?globalThis:window);

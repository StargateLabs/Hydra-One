/* One visible engine; existing route identities remain internal contracts. */
((root)=>{
 const routes=['hydra-strata','hydra-gguf','hydra-safetensors'];
 function routeFor(mode,row){
  if(row?.required_engine==='strata')return 'hydra-strata';
  const format=String(row?.format||'').toLowerCase();
  if(format==='gguf'||/\.gguf$/i.test(row?.path||''))return 'hydra-gguf';
  if(['safetensors','lora'].includes(format))return 'hydra-safetensors';
  if(routes.includes(mode))return mode;
  if(['gguf','safetensors'].includes(mode))return 'hydra-'+mode;
  return 'hydra-strata';
 }
 const api={routes,routeFor};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
 else root.StrataHydraChoice=api;
})(globalThis);

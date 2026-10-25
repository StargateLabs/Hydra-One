/* A selected field is not proof of a validated or running model. */
(function(root,factory){const describe=factory();if(typeof module==='object'&&module.exports)module.exports=describe;if(root)root.StrataLaunchState=describe;})(typeof window==='object'?window:null,()=>{
 return input=>{
  const displayEngine=input.engine,requested=({'hydra-strata':'strata','hydra-gguf':'gguf','hydra-safetensors':'safetensors'})[input.engine]||input.engine;
  const engine=['strata','gguf','safetensors','api','colibri'].includes(requested)?requested:'strata';
  const phase=input.phase||'unknown',matches=engine==='strata'?!input.otherActive:!input.activeEngine||input.activeEngine===(engine==='colibri'?'api':engine);
  const ready=matches&&(engine==='strata'?['idle','reading','generating'].includes(phase):phase==='ready');
  return {engine,displayEngine,phase,ready,matches,active:matches&&['loading','reading','generating'].includes(phase),
   modelChosen:!!input.model,resourceOwner:['api','colibri'].includes(engine)?'external':'local',
   thermalOwner:engine==='strata'?'engine':'pc',model:input.model||'',
   resourceSummary:input.resourceSummary||'',thermalSummary:input.thermalSummary||''};
 };
});

/* One control, driven by observed engine state. Existing actions own lifecycle. */
((root)=>{
 function powerState(input){
  const {route,nativeLoaded,nativeBusy=false,optional={},colibri={},startDisabled=false,stopDisabled=false,colibriStopDisabled=false,pending,english=false}=input;
  const native=['strata','hydra-strata'].includes(route),active=['ready','loading'].includes(optional.status);
  const selectedName=route.startsWith('hydra-')?'HYDRA ONE':({strata:'Hydra One',gguf:'llama.cpp',safetensors:'Python',api:'API',colibri:'Colibri'}[route]||'motore');
  const activeName=active?(optional.engine_addon==='hydra-one'?'HYDRA ONE':optional.publisher==='colibri'?'Colibri':optional.mode==='api'?'API':optional.backend||'motore'):nativeLoaded?(native?selectedName:'Hydra One'):selectedName;
  const colibriActive=(route==='colibri'||optional.publisher==='colibri')&&['ready','loading'].includes(colibri.status);
  const stopping=active||colibriActive||nativeLoaded===true;
  const target=colibriActive?'colibri-engine-stop':active?'backend-stop':nativeLoaded===true?'ctrl-unload':native?'ctrl-load':route==='colibri'?'colibri-start':'backend-start';
  if(pending)return {target,tone:'pending',disabled:true,label:pending==='stop'?(english?'Stopping…':'Arresto…'):(english?'Starting…':'Avvio…')};
  if(native&&nativeLoaded===null&&!active)return {target,tone:'pending',disabled:true,label:english?'Checking state…':'Verifica stato…'};
  return {target,tone:stopping?'stop':'start',disabled:stopping?(colibriActive?colibriStopDisabled:active?stopDisabled:nativeBusy):startDisabled,
   label:(stopping?(english?'Stop ':'Ferma '):(english?'Start ':'Avvia '))+(colibriActive?'Colibri':activeName)};
 }
 root.StrataEnginePower={powerState};if(typeof module!=='undefined')module.exports={powerState};
})(typeof window==='undefined'?globalThis:window);

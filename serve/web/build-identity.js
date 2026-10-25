/* Presentation only: retain the build metadata supplied by the existing API. */
((root)=>{
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function render(engine,active=[],english=false,identity={}){
  const t=(it,en)=>english?en:it,unknown=t('Non disponibile','Unavailable');
  const amd=String(engine.backend||'').toLowerCase()==='hip';
  const mark=(file,alt,cls='')=>`<img class="build-mark ${cls}" src="web/${file}" alt="${alt}" width="78" height="22">`;
  const icon=id=>`<span class="build-symbol build-symbol--${id==='i-layers'?'layers':'cpu'}" aria-hidden="true"></span>`;
  const tile=(id,label,value,tone,art,note)=>`<div class="build-tile build-tile--${id}" data-tone="${tone}"><dt><span>${label}</span>${id==='library'?art:''}</dt><dd><span class="build-value">${escape(value)}</span>${id!=='library'?`<span class="build-card-art">${art}</span>`:''}<small>${note}</small></dd></div>`;
  const tags=Array.isArray(engine.archs)?engine.archs:[],inUse=new Set(active||[]);
  return tile('engine',identity.hydra?t('Motore del servizio','Service engine'):t('Versione del motore','Engine version'),identity.hydra?'HYDRA ONE':engine.version?'v'+engine.version:unknown,'mint',identity.hydra?mark('hydra-one.png','HYDRA ONE','build-mark--hydra'):mark('brand-strata.svg','Hydra One','build-mark--symbol'),identity.hydra?escape(t('Runtime nativo · build ','Native runtime · build ')+(engine.version||unknown)):t('Identità della build','Build identity'))+
   tile('backend','Backend',engine.backend?String(engine.backend).toUpperCase():unknown,'rose',amd?mark('brand-amd-official.svg','AMD'):icon('i-code'),t('Percorso di calcolo','Compute backend'))+
   tile('runtime','Runtime',engine.rocm?'ROCm '+engine.rocm:'—','blue',amd?mark('brand-amd-official.svg','AMD'):icon('i-layers'),t('Versione dichiarata dalla build','Version reported by the build'))+
   tile('platform',t('Piattaforma','Platform'),engine.platform||'—','violet',/^windows/i.test(engine.platform||'')?mark('brand-microsoft-official.png','Microsoft','build-mark--microsoft'):icon('i-cpu'),t('Destinazione del binario','Binary target'))+
   `<div class="build-tile build-tile--architectures" data-tone="mint"><dt>${icon('i-cpu')}<span>${t('Architetture GPU incluse','Included GPU architectures')}</span></dt><dd><div class="build-architecture-list">${tags.length?tags.map(a=>`<span data-family="${escape(String(a).slice(0,5))}" class="build-arch${inUse.has(a)?' is-active':''}"><span>${escape(a)}</span>${inUse.has(a)?`<b>${t('In uso','In use')}</b>`:''}</span>`).join(''):'<span class="build-value">—</span>'}</div><small>${t('Incluse nel binario · la GPU determina il percorso utilizzato.','Included in the binary · your GPU determines the path used.')}</small></dd></div>`+
   tile('library','hipBLASLt',engine.hipblaslt?String(engine.hipblaslt):'—','amber',icon('i-layers'),t('Libreria di calcolo · versione build','Compute library · build version'));
 }
 if(typeof module!=='undefined'&&module.exports)module.exports={render};else root.StrataBuildIdentity={render};
})(globalThis);

(()=>{
 const t=(it,en)=>document.documentElement.lang==='en'?en:it;
 window.StrataAntigravityPreviewUI={render(box,status){
  if(!box.querySelector('.antigravity-official')){
   box.innerHTML='<section class="claude-official antigravity-official"><h2><img class="engine-brand-logo" src="web/brand-antigravity.ico" alt="" width="36" height="36"> Antigravity</h2><p class="antigravity-copy"></p><button type="button" class="st-btn st-btn--primary"></button><p role="status"></p><iframe title="Antigravity · interfaccia originale" hidden style="width:100%;height:72vh;min-height:520px;border:0;border-radius:12px"></iframe></section>';
   box.querySelector('button').onclick=async()=>{const b=box.querySelector('button');b.disabled=true;try{const r=await fetch('harness/antigravity/web/start',{method:'POST',headers:headers(true),body:'{}'});const data=await r.json();if(!r.ok)throw Error(data.error?.message||r.status);const url=new URL(data.url);if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||url.port!=='18196')throw Error(t('Indirizzo interfaccia non valido','Invalid interface address'));const frame=box.querySelector('iframe');if(frame.src!==url.href)frame.src=url.href;frame.hidden=false;box.querySelector('[role="status"]').textContent=t('Anteprima originale locale: connessione Google e inferenza disabilitate.','Original local preview: Google connection and inference disabled.');}catch(e){box.querySelector('[role="status"]').textContent=e.message;}finally{b.disabled=false;}};
  }
  box.querySelector('.antigravity-copy').textContent=t('Interfaccia web originale servita dal programma Google installato. Questa anteprima non espone un provider Hydra One e non include le funzioni native Electron.','Original web interface served by the installed Google program. This preview exposes no Hydra One provider and excludes native Electron features.');
  box.querySelector('button').textContent=t('Apri interfaccia qui','Open interface here');box.querySelector('button').disabled=!status?.desktop?.original_web_renderer_available;
  if(status?.desktop?.original_web_renderer_available&&!box.querySelector('iframe').src&&!box.dataset.autoStarting){box.dataset.autoStarting='true';box.querySelector('button').onclick().finally(()=>{delete box.dataset.autoStarting;});}
  document.getElementById('chat-harness-status').textContent=t('Interfaccia originale · anteprima locale','Original interface · local preview');
 }};
})();

window.StrataAntigravityUI={render(box,status){window.StrataAntigravityPreviewUI.render(box,status);}};


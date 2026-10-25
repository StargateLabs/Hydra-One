from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=root/'serve/web/app.js';source=path.read_text(encoding='utf-8')
start=source.index('// Catalogo dei modelli compatibili (HuggingFace).')
end=source.index('async function loadControl()',start)
source=source[:start]+source[end:]
start=source.index('function aggiornaMenuModelli(');end=source.index('// ---------------------------------------------------------------------------------------------',start)
source=source[:start]+'''function aggiornaMenuModelli(config,corrente){
 const select=$('ctrl-model'),selected=select.value,ready=(config.prepared||[]).filter(m=>m.ready);
 select.innerHTML=ready.map(m=>`<option value="${esc(m.key)}">${esc(m.label||m.key)} · installato</option>`).join('');
 const current=ready.find(m=>(m.label||'')===corrente);
 if(current)select.value=current.key;else if(ready.some(m=>m.key===selected))select.value=selected;
 $('ctrl-switch').disabled=!ready.length;
 $('ctrl-download').textContent='Cerca altri modelli';$('ctrl-download').onclick=()=>catApri(true);
 $('ms-ctrl-model-info').textContent=`${ready.length} configurazioni con file verificati · in servizio: ${corrente||'—'}`;
}

'''+source[end:]
path.write_text(source,encoding='utf-8')
path=root/'serve/web/index.html';source=path.read_text(encoding='utf-8')
source=source.replace('<div class="dm dm--full" id="cat-block" style="display:none">','<div class="dm dm--full catalogue-panel" id="cat-block" hidden>')
start=source.index('            <label class="dm__sub"',source.index('id="cat-block"'))
end=source.index('            <div class="dm__sub" id="cat-disk"',start)
source=source[:start]+source[end:]
source=source.replace('<div class="dm__sub" id="cat-disk">','<div class="catalogue-resources" id="cat-disk">')
source=source.replace('<button class="st-btn st-btn--secondary" id="cat-toggle">','<button class="st-btn st-btn--secondary" id="cat-toggle" aria-controls="cat-block" aria-expanded="false">')
source=source.replace('<div class="dash-controls">\n              <input id="cat-query"','<div class="catalogue-search">\n              <input id="cat-query"')
source=source.replace('<link rel="stylesheet" href="web/about.css', '<link rel="stylesheet" href="web/catalogue.css?v=20261009-verified-1">\n<link rel="stylesheet" href="web/about.css')
source=source.replace('</body>','<script src="web/catalogue.js?v=20261009-verified-1"></script>\n</body>')
path.write_text(source,encoding='utf-8')

from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'serve/web/index.html';s=p.read_text(encoding='utf-8');anchor='<div data-performance-pane-content="results">'
s=s.replace(anchor,anchor+'''<section class="perf-panel perf-record-panel"><div class="perf-section-head"><div><p class="perf-kicker">BANCO LOCALE / AGGIORNAMENTO AUTOMATICO</p><h2>Migliore mediana osservata</h2></div><label class="perf-record-selector">Protocollo<select class="st-input" id="perf-record-protocol" aria-label="Protocollo del miglior risultato"></select></label></div><div id="perf-record-result" class="perf-evidence">Caricamento dei test completati…</div></section>''',1)
s=s.replace('Profilo appreso raccolto e verificato: nessun vantaggio decode nel primo ABBA. Prossima priorità: ripartizione GPU/CPU e costo delle attese sul PCIe.','Cache appresa senza vantaggio decode. Quota PCIe 20%: +3,15% nel primo ABBA; qualità appaiata e stabilità vengono valutate separatamente. Quota 55% non adottata.')
s=s.replace('class="st-btn st-btn--primary" href="#control">Apri Control ↗','class="st-btn st-btn--primary" href="#control">Apri Control ↗')
s=s.replace('web/app.js?v=20261009-workspace-4','web/app.js?v=20261009-workspace-6').replace('web/chat-workspace.css?v=20261009-1','web/chat-workspace.css?v=20261009-3')
p.write_text(s,encoding='utf-8')
p=ROOT/'serve/web/app.js';s=p.read_text(encoding='utf-8');anchor='async function loadBenchmarks() {'
code='''let performanceRecordGroups=[];
function renderPerformanceRecord(){
 const select=$('perf-record-protocol'),target=$('perf-record-result'),group=performanceRecordGroups.find(g=>g.id===select.value);
 if(!group){target.innerHTML='<p class="perf-copy">Nessun test completo e valido per questo modello. I risultati compariranno automaticamente dopo il completamento nel Benchmark.</p>';return;}
 const winner=group.winner,s=winner.summary,p=group.protocol;
 target.innerHTML=`<div class="perf-evidence-head"><div><h3>${esc(winner.label)}</h3><p>${new Date(winner.finished_at*1000).toLocaleString('it-IT')} · ${esc(group.tested_profiles)} profili completati nelle stesse condizioni di prova</p></div><span class="perf-state">Miglior test · esplorativo</span></div><div class="perf-evidence-stats">${[['decode_tok_s','Decode','t/s'],['prefill_tok_s','Prefill','t/s'],['wall_s','Durata totale','s']].map(([key,title,unit])=>`<article class="perf-evidence-stat"><span>${title}</span><div class="perf-evidence-value"><strong>${fmt(s[key],key==='wall_s'?2:1)} <small>${unit}</small></strong></div></article>`).join('')}</div><div class="perf-evidence-foot"><span>${p.runs} misure + 5 riscaldamenti · ${p.tokens} output · ${p.paragraphs} paragrafi${winner.quality?` · qualità ${winner.quality.correct}/${winner.quality.total}`:''}</span><span>Si aggiorna dopo un test completo migliore. Confronto tra mediane osservate; conferma ABBA e stabilità richieste.</span></div>`;
 target.dataset.recordJob=winner.job_id;target.dataset.recordDecode=String(s.decode_tok_s);
}
$('perf-record-protocol').onchange=renderPerformanceRecord;
function updatePerformanceRecords(groups){
 const select=$('perf-record-protocol'),old=select.value;performanceRecordGroups=groups||[];
 select.innerHTML=performanceRecordGroups.map(g=>`<option value="${esc(g.id)}">${g.protocol.tokens} token · ${g.protocol.paragraphs} paragrafi · ${g.protocol.runs} misure · ${esc(g.winner.label)}</option>`).join('')||'<option value="">Nessun protocollo completato</option>';
 if(performanceRecordGroups.some(g=>g.id===old))select.value=old;
 select.disabled=!performanceRecordGroups.length;renderPerformanceRecord();
}

'''
s=s.replace(anchor,code+anchor,1)
s=s.replace('    performanceReports = d.reports || [];','    performanceReports = d.reports || [];\n    updatePerformanceRecords(d.best_groups);')
s=s.replace('    $("perf-report-count").textContent = "Dati non disponibili";','    $("perf-report-count").textContent = "Dati non disponibili";\n    updatePerformanceRecords([]);delete $("perf-record-result").dataset.recordJob;delete $("perf-record-result").dataset.recordDecode;$("perf-record-result").textContent="Risultato migliore non aggiornato: "+e.message;')
p.write_text(s,encoding='utf-8')

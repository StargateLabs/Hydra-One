from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'serve/web/index.html';s=p.read_text(encoding='utf-8')
a=s.index('<section class="perf-evidence" data-performance-evidence');b=s.index('</section>',a)+len('</section>')
s=s[:a]+'<details class="perf-disclosure"><summary><span>Ultimo confronto ABBA verificato <small>Controllo, variante e qualità</small></span><span class="perf-disclosure-action">Confronto</span></summary><div class="perf-disclosure-body">'+s[a:b]+'</div></details>'+s[b:]
s=s.replace('quota PCIe 20%: +3,15%','quota PCIe 20%: +3,15%')
s=s.replace('Quota PCIe 20%: +3,15% nel primo ABBA; qualità appaiata e stabilità vengono valutate separatamente.','Quota PCIe 20%: +3,15% nel primo ABBA e 8/12 → 9/12 compiti senza regressioni osservate. Stabilità prolungata da verificare.')
s=s.replace('class="muted small">the\n      vettore','class="muted small">Il\n      vettore')
p.write_text(s,encoding='utf-8')
p=ROOT/'serve/web/app.js';s=p.read_text(encoding='utf-8');s=s.replace("if(!group){target.innerHTML=", "if(!group){delete target.dataset.recordJob;delete target.dataset.recordDecode;target.innerHTML=")
p.write_text(s,encoding='utf-8')

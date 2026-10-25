from pathlib import Path
p=Path(__file__).resolve().parents[1]/'serve/web/index.html';s=p.read_text(encoding='utf-8')
for title,ico,detail in [('Spiega','thinking','Concetti chiari, esempi e passaggi'),('Analizza','layers','Punti critici e miglioramenti'),('Scrivi codice','tool','Soluzioni, scelte e casi limite'),('Rivedi testo','refresh','Chiarezza, precisione e stile')]:
    s=s.replace('>'+title+'</button>',f'><svg class="st-icon" aria-hidden="true"><use href="web/sprite.svg#i-{ico}"/></svg><span><b>{title}</b><small>{detail}</small></span><span aria-hidden="true" class="chat-starter-arrow">↗</span></button>')
s=s.replace('class="chat-empty__title">Chat locale','class="chat-empty__title">Da dove iniziamo?')
p.write_text(s,encoding='utf-8')

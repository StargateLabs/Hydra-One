from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'serve/web/index.html';s=p.read_text(encoding='utf-8')
s=s.replace('<link rel="stylesheet" href="web/premium.css?v=20261009-chat-about-1">','<link rel="stylesheet" href="web/premium.css?v=20261009-chat-about-1">\n<link rel="stylesheet" href="web/workspace-layout.css?v=20261009-width-1">')
start=s.index('<section class="view view--control"');end=s.index('</section>',start)
part=s[start:end];opening=part.index('>')+1
part=part[:opening]+'\n    <div class="control-shell">'+part[opening:]+'    </div>\n  '
s=s[:start]+part+s[end:];p.write_text(s,encoding='utf-8')
p=ROOT/'serve/web/control.css';s=p.read_text(encoding='utf-8').replace('#view-control>.dash4','#view-control>.control-shell>.dash4');p.write_text(s,encoding='utf-8')

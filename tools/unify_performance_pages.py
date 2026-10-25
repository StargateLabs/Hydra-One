from html.parser import HTMLParser
from pathlib import Path
import re

root=Path(__file__).resolve().parents[1];path=root/'serve/web/index.html';source=path.read_text(encoding='utf-8')
start=source.index('  <section class="view view--tuning"');middle=source.index('  <section class="view view--confronti"',start);end=source.index('  <section class="view view--about"',middle)
def contents(text):return text[re.search(r'<div class="[^"]*\bperf-suite\b[^"]*">',text).end():text.rfind('</div>')]
class Blocks(HTMLParser):
    def __init__(self,text):
        super().__init__();self.text=text;self.lines=[0];self.depth=0;self.blocks=[]
        for i,c in enumerate(text):
            if c=='\n':self.lines.append(i+1)
        self.feed(text)
    def char_pos(self):line,col=self.getpos();return self.lines[line-1]+col
    def handle_starttag(self,tag,attrs):
        if tag in ('input','img','br','hr','meta','link','use'):return
        if self.depth==0:self.begin=self.char_pos()
        self.depth+=1
    def handle_endtag(self,tag):
        if tag=='use':return
        self.depth-=1
        if self.depth==0:self.blocks.append(self.text[self.begin:self.char_pos()+len('</'+tag+'>')])
t=Blocks(contents(source[start:middle])).blocks;c=Blocks(contents(source[middle:end])).blocks
assert len(t)==7 and len(c)==6,(len(t),len(c))
header=t[0].replace('<h1>Potenziamenti</h1>','<h1>Prestazioni</h1>').replace('Risultati, priorità e prossime verifiche del motore IQ3_XXS.','Misure, confronti e piano di sviluppo del motore IQ3_XXS.').replace('href="#confronti">Confronti ↗','href="#benchmark">Benchmark ↗')
nav='<div class="perf-subnav" aria-label="Sezioni delle prestazioni"><button type="button" data-performance-pane="results" aria-pressed="true">Risultati e confronti</button><button type="button" data-performance-pane="plan" aria-pressed="false">Piano e configurazione</button><button type="button" data-performance-pane="archive" aria-pressed="false">Rapporti e fonti</button></div>'
def pane(name,blocks):return f'<div data-performance-pane-content="{name}"'+(' hidden' if name!='results' else '')+'>'+''.join(blocks)+'</div>'
merged='  <section class="view view--tuning" id="view-tuning" role="tabpanel" aria-labelledby="tab-btn-tuning" hidden><div class="perf-suite perf-compact">'+header+nav+pane('results',[t[1],t[2],c[3]])+pane('plan',[t[3],t[4]])+pane('archive',[t[5],t[6],c[4],c[5]])+'</div></section>\n\n'
source=source[:start]+merged+source[end:]
nav_start=source.index('    <button class="st-tab" role="tab" id="tab-btn-confronti"');nav_end=source.index('</button>',nav_start)+len('</button>')
source=source[:nav_start]+source[nav_end:]
source=source.replace('sprite.svg#i-bolt"/></svg>Potenziamenti</button>','sprite.svg#i-bolt"/></svg>Prestazioni</button>')
path.write_text(source,encoding='utf-8')

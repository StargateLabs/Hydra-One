from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'serve/web/index.html';s=p.read_text(encoding='utf-8')
s=s.replace('<div class="chat-scroll" id="chat-scroll">','<div class="chat-scroll" id="chat-scroll" tabindex="0" role="region" aria-label="Messaggi della conversazione">')
anchor='    <div class="composer-wrap">'
s=s.replace(anchor,'''    <nav class="chat-navigator" id="chat-navigator" aria-label="Navigazione della conversazione" hidden>
      <button type="button" id="chat-nav-top" aria-label="Vai all’inizio della chat" title="Inizio della chat">↑</button>
      <button type="button" id="chat-nav-prev" aria-label="Richiesta precedente" title="Richiesta precedente">‹</button>
      <span class="chat-nav-position" id="chat-nav-position">1 / 1</span>
      <button type="button" id="chat-nav-next" aria-label="Richiesta successiva" title="Richiesta successiva">›</button>
      <button type="button" id="chat-nav-bottom" class="chat-nav-latest" aria-label="Vai all’ultima risposta" title="Ultima risposta"><svg viewBox="0 0 36 36" aria-hidden="true"><circle class="chat-nav-ring-track" cx="18" cy="18" r="14"/><circle id="chat-nav-ring" cx="18" cy="18" r="14"/></svg><span aria-hidden="true">↓</span></button>
      <span class="chat-nav-update" id="chat-nav-update" hidden>Risposta in corso</span>
    </nav>
''' +anchor,1)
p.write_text(s,encoding='utf-8')
p=ROOT/'serve/web/app.js';s=p.read_text(encoding='utf-8');s=s.replace('function scrollDown(force) { const s = $("chat-scroll"); if (force || nearBottom()) s.scrollTop = s.scrollHeight; }','function scrollDown(force) { const s = $("chat-scroll"); if (force || nearBottom()) s.scrollTop = s.scrollHeight; updateChatNavigation(); }')
anchor='// pictures and text files:'
code='''// Wheel, touch and keyboard retain native scrolling; the navigator only selects a position.
let chatNavFrame=0;
function chatNavRequests(){return [...document.querySelectorAll('#chat .st-msg--user')].filter(el=>!el.hidden);}
function chatNavOffset(el){const scroll=$('chat-scroll');return el.getBoundingClientRect().top-scroll.getBoundingClientRect().top+scroll.scrollTop;}
function updateChatNavigation(){
 const scroll=$('chat-scroll'),nav=$('chat-navigator');if(!nav)return;
 const span=Math.max(0,scroll.scrollHeight-scroll.clientHeight);nav.hidden=span<24||!messages.length;
 const progress=span?Math.min(1,Math.max(0,scroll.scrollTop/span)):1;
 $('chat-nav-ring').style.strokeDashoffset=String(87.965*(1-progress));
 const requests=chatNavRequests();let index=0;requests.forEach((el,i)=>{if(chatNavOffset(el)<=scroll.scrollTop+90)index=i;});
 $('chat-nav-position').textContent=requests.length?`${index+1} / ${requests.length}`:'Chat';
 $('chat-nav-position').title=`Richiesta ${index+1} di ${requests.length} · ${Math.round(progress*100)}% della conversazione`;
 $('chat-nav-prev').disabled=!requests.length||scroll.scrollTop<=chatNavOffset(requests[0])+8;
 $('chat-nav-next').disabled=!requests.some(el=>chatNavOffset(el)>scroll.scrollTop+90);
 $('chat-nav-top').disabled=scroll.scrollTop<8;
 $('chat-nav-bottom').disabled=progress>.995;
 $('chat-nav-update').hidden=!busy||nearBottom();
 $('view-chat').style.setProperty('--chat-composer-height',$('view-chat').querySelector('.composer-wrap').offsetHeight+'px');
}
function moveChatTo(top){const scroll=$('chat-scroll');scroll.scrollTo({top,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}
$('chat-nav-top').onclick=()=>moveChatTo(0);
$('chat-nav-bottom').onclick=()=>moveChatTo($('chat-scroll').scrollHeight);
$('chat-nav-prev').onclick=()=>{const list=chatNavRequests().filter(el=>chatNavOffset(el)<$('chat-scroll').scrollTop-8);moveChatTo(list.length?chatNavOffset(list.at(-1)):0);};
$('chat-nav-next').onclick=()=>{const el=chatNavRequests().find(el=>chatNavOffset(el)>$('chat-scroll').scrollTop+90);if(el)moveChatTo(chatNavOffset(el));};
$('chat-scroll').addEventListener('scroll',()=>{if(!chatNavFrame)chatNavFrame=requestAnimationFrame(()=>{chatNavFrame=0;updateChatNavigation();});},{passive:true});
new ResizeObserver(updateChatNavigation).observe($('chat'));
new ResizeObserver(updateChatNavigation).observe($('view-chat').querySelector('.composer-wrap'));
window.addEventListener('resize',updateChatNavigation);

'''
s=s.replace(anchor,code+anchor,1);p.write_text(s,encoding='utf-8')

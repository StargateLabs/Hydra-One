/* Harness tabs: OpenCode and DeepSeek Harness beside Hydra One.

   Hydra One stays the model and the GPU; each tab shows the harness that orchestrates on top,
   managed entirely from this interface: state, model binding and MCP tools. Nothing runs
   until the tab is opened. Another program's interface is never embedded or opened here.
   Strings follow the app's it/en switch. */
(function () {
  const HARNNESSES = [
    {kind:'antigravity',title:'Antigravity',sub:{it:'interfaccia originale dentro Harness',en:'original interface inside Harness'}},
    {kind:'claude',title:'Claude Code',sub:{it:'runtime originale · sessioni e MCP',en:'original runtime · sessions and MCP'}},
    { kind: 'opencode', title: 'OpenCode', sub: { it: 'agente su Hydra One', en: 'agent on Hydra One' } },
    {kind:'hermes',title:'Hermes Agent',sub:{it:'agente su Hydra One',en:'agent on Hydra One'}},
    { kind:'trueforge',title:'TrueForge',sub:{it:'agente su Hydra One',en:'agent on Hydra One'}},
    { kind: 'dsh', title: 'DeepSeek Harness', sub: { it: 'agente su Hydra One', en: 'agent on Hydra One' } },
  ];
  const el = (id) => document.getElementById(id);
  const t = (it, en) => (document.documentElement.lang === 'en' ? en : it);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const state = {};      // kind -> last status
  let selected = 'opencode';
  let polling = null;
  const rendered = {};
  const pending = new Set();

  function brand(){const box=el('harness-current-brand');if(!box)return;const cfg=HARNNESSES.find(h=>h.kind===selected),dark=document.documentElement.dataset.theme==='dark';box.replaceChildren();const img=document.createElement('img');img.src='web/harness-logo-'+selected+((selected==='dsh'||selected==='trueforge'||selected==='hermes')&&dark?'-dark':'')+'.svg';if(selected==='claude')img.src='web/harness-logo-claude.png';if(selected==='antigravity')img.src='web/brand-antigravity.ico';img.alt=cfg.title;if(selected==='claude'){img.onerror=()=>img.remove();}img.width=36;img.height=36;const name=document.createElement('strong');name.textContent=cfg.title;box.append(img,name);const binding=state[selected]?.binding;if(binding){const badge=document.createElement('small');badge.className='harness-auto-model';badge.textContent=binding.model;badge.title=t('Modello rilevato automaticamente · contesto: ','Automatically detected model · context: ')+binding.context;box.append(badge);}}
  function panel(kind) { return el(`harness-panel-${kind}`); }

  function render(kind, cfg) {
    const box = panel(kind);
    if (!box) return;
    const status = state[kind];
    if(kind==='antigravity'){window.StrataAntigravityUI?.render(box,status);return;}
    if(kind==='claude'){window.StrataClaudeUI?.render(box,status);return;}
    if (!status) { box.innerHTML = `<p class="harness-note">${esc(t('Verifica dello stato…', 'Checking status…'))}</p>`; return; }
    const signature=JSON.stringify([status.status,status.error,status.installed,status.pid,status.tools,status.binding,document.documentElement.lang]);
    if(rendered[kind]===signature)return;
    rendered[kind]=signature;
    const st = status.status || 'idle';
    const label = {
      idle: t('Fermo', 'Stopped'), starting: t('Avvio…', 'Starting…'),
      ready: t('In esecuzione', 'Running'), error: t('Errore', 'Error'),
    }[st] || st;

    const head = `<header class="harness-head">
      <div class="harness-id"><b>${esc(cfg.title)}</b><small>${esc(cfg.sub[document.documentElement.lang === 'en' ? 'en' : 'it'])}</small></div>
      <span class="harness-state" data-state="${esc(st)}">${esc(label)}</span>
    </header>`;

    const facts = `<details class="harness-runtime"><summary>${esc(t('Dettagli di connessione','Connection details'))}</summary><dl class="harness-facts">
      <div><dt>${esc(t('Modello', 'Model'))}</dt><dd><code>${esc(status.binding?.model||'—')}</code></dd></div>
      <div><dt>${esc(t('Server MCP configurati', 'Configured MCP servers'))}</dt><dd>${esc(status.tools)} ${esc(t('server', 'servers'))}</dd></div>
      <div><dt>${esc(t('Binario', 'Binary'))}</dt><dd>${status.installed ? esc(t('installato', 'installed')) : esc(t('assente', 'missing'))}</dd></div>
      <div><dt>${esc(t('Indirizzo', 'Address'))}</dt><dd><code>${esc(status.url ? new URL(status.url).origin : '—')}</code></dd></div>
    </dl></details>`;

    const controls = `<div class="harness-actions">${st==='ready'?'':`<button type="button" class="st-btn st-btn--primary" data-harness="${kind}" data-act="start"${status.installed?'':' disabled'}>${esc(t('Avvia','Start'))}</button>`}</div>`;

    const error = status.error ? `<p class="harness-error">${esc(status.error)}</p>` : '';
    // only claim a missing binary when the server actually answered; an unreachable or
    // older server reports an error and must not be described as "binary not found"
    const missing = (!status.installed && st !== 'error')
      ? `<p class="harness-note">${esc(t('Runtime non disponibile. Preparalo dal Centro aggiornamenti.',
                                          'Runtime unavailable. Prepare it from the Update Center.'))}</p>`
      : '';

    // The harness's own chat, framed when it runs. OpenCode gates its API behind basic
    // auth: the panel shows the credential to type once in its own tab, after which the
    // browser caches it and the frame loads too.
    const frame = st === 'ready'
      ? `<div class="harness-frame"><iframe id="harness-frame-${kind}" title="${esc(cfg.title)}"
             referrerpolicy="no-referrer" allow="clipboard-read; clipboard-write; fullscreen" sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-downloads allow-modals"></iframe></div>`
      : '';

    const previous=el(`harness-frame-${kind}`),sameProcess=previous&&previous.dataset.pid===String(status.pid);
    box.classList.toggle('is-running',st==='ready');
    if(st==='ready'&&sameProcess){
      // Metadata and language changes must not detach a live original renderer.
      const holder=document.createElement('div');holder.innerHTML=facts;
      const next=holder.firstElementChild,current=box.querySelector('.harness-runtime');
      if(current){next.open=current.open;current.replaceWith(next);}else previous.before(next);
      if(kind===selected)el('chat-harness-status').textContent=label;
      return;
    }
    box.innerHTML = (st==='ready'?'':head) + controls + error + missing + facts + frame;
    if(st==='ready'){el(`harness-frame-${kind}`).dataset.pid=String(status.pid);connect(kind);}
    if(kind===selected)el('chat-harness-status').textContent=label;
  }

  async function connect(kind){
    const expectedPid=state[kind]?.pid;
    try{const r=await fetch(`harness/${kind}/connect`,{method:'POST',headers:typeof headers==='function'?headers(true):{'Content-Type':'application/json'},body:'{}'});const body=await r.json();if(!r.ok)throw Error(body.error?.message||`HTTP ${r.status}`);if(state[kind]?.pid!==expectedPid||state[kind]?.status!=='ready')return;const frame=el(`harness-frame-${kind}`);if(frame)frame.src=body.url;
    }catch(error){if(state[kind]?.pid!==expectedPid||state[kind]?.status!=='ready')return;const box=panel(kind);if(box){const note=document.createElement('p');note.className='harness-error';note.textContent=t('Collegamento interrotto. Riapri l’interfaccia: ','Connection interrupted. Reopen the interface: ')+error.message;const retry=document.createElement('button');retry.type='button';retry.className='st-btn st-btn--secondary';retry.textContent=t('Ricollega UI','Reconnect UI');retry.onclick=()=>{note.remove();connect(kind);};note.append(retry);box.append(note);}}
  }

  async function refresh(kind) {
    try {
      const r = await fetch(`harness/${kind}/status`, { headers: typeof headers === 'function' ? headers() : {} });
      state[kind] = r.ok ? await r.json() : { status: 'error', error: `HTTP ${r.status}`, tools: 0, installed: false };
    } catch (e) {
      state[kind] = { status: 'error', error: e.message, tools: 0, installed: false };
    }
    render(kind, HARNNESSES.find((h) => h.kind === kind));
    if(kind===selected)brand();
  }

  async function act(kind, action) {
    if (action === 'open') { await connect(kind); return; }
    if(pending.has(kind))return;pending.add(kind);
    const btn = document.querySelector(`[data-harness="${kind}"][data-act="${action}"]`);
    if (btn) btn.disabled = true;
    try {
      const r = await fetch(`harness/${kind}/${action}`, {
        method: 'POST', headers: typeof headers === 'function' ? headers(true) : { 'Content-Type': 'application/json' }, body: '{}',
      });
      const body = await r.json().catch(() => ({}));
      if(r.ok)state[kind]=body;
      if (!r.ok) state[kind] = { ...(state[kind] || {}), status: 'error', error: (body.error && body.error.message) || `HTTP ${r.status}` };
    } catch (e) {
      state[kind] = { ...(state[kind] || {}), status: 'error', error: e.message };
    }
    render(kind, HARNNESSES.find((h) => h.kind === kind));
    pending.delete(kind);
    await refresh(kind);
  }

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-harness][data-act]');
    if (btn) act(btn.dataset.harness, btn.dataset.act);
  });

  async function selectHarness(kind) {
    if(selected!==kind)releaseHarness(selected);
    window.StrataIdleRelease?.cancel('harness-'+kind);
    selected = kind;brand();
    for (const h of HARNNESSES) {
      const p = panel(h.kind);
      if (p) p.hidden = h.kind !== kind;
    }
    document.querySelectorAll('[data-harness-switch]').forEach((b) => {
      b.setAttribute('aria-selected', String(b.dataset.harnessSwitch === kind));
    });
    await refresh(kind);
    window.dispatchEvent(new CustomEvent('strata:harness-opened',{detail:{kind}}));
    if(kind==='antigravity'){
      /* Native workspace is no longer opened automatically. */
      return;
    }
    if(state[kind]?.status==='idle'&&state[kind]?.installed&&!pending.has(kind))act(kind,'start');
  }

  document.addEventListener('click', (e) => {
    const sw = e.target.closest('[data-harness-switch]');
    if (sw) selectHarness(sw.dataset.harnessSwitch);
    const close = e.target.closest('#chat-harness-close');
    if (close) setOpen(false);
  });

  function setOpen(open){
    const box=el('chat-harness'),view=el('view-chat');if(!box||!view)return;
    box.hidden=!open;brand();view.classList.toggle('harness-open',open);el('chat-harness-trigger')?.setAttribute('aria-expanded',String(open));
    if(open){selectHarness(selected);if(!polling)polling=setInterval(()=>{if(!document.hidden&&!view.hidden)refresh(selected);},4000);}
    else{clearInterval(polling);polling=null;releaseHarness(selected);}
  }
  function releaseHarness(kind){if(['antigravity','claude'].includes(kind)){window.StrataIdleRelease?.schedule('harness-'+kind,{rendererOnly:kind==='antigravity',status:'harness/'+kind+(kind==='antigravity'?'/original':'/terminal'),stop:'harness/'+kind+(kind==='antigravity'?'/original/stop':'/terminal/stop'),inUse:()=>selected===kind&&!el('chat-harness')?.hidden&&!el('view-chat')?.hidden});return;}window.StrataIdleRelease?.schedule('harness-'+kind,{status:'harness/'+kind+'/status',stop:'harness/'+kind+'/stop',inUse:()=>!el('chat-harness')?.hidden&&selected===kind&&!el('view-chat')?.hidden});}
  new MutationObserver(()=>{if(el('view-chat').hidden)releaseHarness(selected);else if(!el('chat-harness')?.hidden)selectHarness(selected);}).observe(el('view-chat'),{attributes:true,attributeFilter:['hidden']});
  window.addEventListener('strata:languagechange',()=>{rendered[selected]=null;refresh(selected);});
  function boot() {
    const box=el('chat-harness'),view=el('view-chat'),trigger=el('chat-harness-trigger');if(!box||!view||!trigger||box.dataset.inlineInitialized)return;box.dataset.inlineInitialized='true';box.removeAttribute('popover');box.classList.add('harness-inline');box.hidden=true;trigger.removeAttribute('popovertarget');view.querySelector('.chat-workspace-bar').after(box);trigger.addEventListener('click',()=>setOpen(box.hidden));
    const identity=document.createElement('div');identity.id='harness-current-brand';identity.className='harness-current-brand';view.querySelector('.chat-workspace-bar').prepend(identity);brand();new MutationObserver(brand).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
    if(trigger)trigger.title=t('Apri Claude Code, Antigravity, OpenCode, DeepSeek Harness, TrueForge e Hermes Agent','Open Claude Code, Antigravity, OpenCode, DeepSeek Harness, TrueForge and Hermes Agent');
    if (new URLSearchParams(location.search).get('harness')) selectHarness(selected);
  }
  document.addEventListener('DOMContentLoaded', boot);
  if (document.readyState !== 'loading') boot();
})();




// serve/web/app.js - the Hydra One web app: Chat, Monitor, About. No framework, no network beyond this server.
// The Monitor tab rebuilds PR #22's dashboard idea (code-martin) on the server's own /metrics.
"use strict";

const $ = (id) => document.getElementById(id);
const SPRITE = "web/sprite.svg";
const icon = (name, cls = "st-icon") => `<svg class="${cls}" aria-hidden="true"><use href="${SPRITE}#i-${name}"/></svg>`;
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const fmt = (n, d = 0) => (n == null || Number.isNaN(n) ? "–" : Number(n).toLocaleString(undefined, {maximumFractionDigits: d, minimumFractionDigits: d}));
const kfmt = (n) => (n == null ? "–" : n >= 1000 ? `${fmt(n / 1000, n >= 10000 ? 0 : 1)}k` : fmt(n));
// a context size: 32768 -> "32K" (powers of two), else like kfmt
const ctxfmt = (n) => (n && n % 1024 === 0 ? `${fmt(n / 1024)}K` : kfmt(n));
const gb = (b, d = 1) => (b == null ? "–" : fmt(b / 1073741824, d));   // memory: binary GB, as Windows shows it

const store = {
  get(k, d) { try { const v = localStorage.getItem("strata." + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("strata." + k, JSON.stringify(v)); } catch (e) { /* private mode: in memory only */ } },
};

// ------------------------------------------------------------------ toasts
function toast(kind, title, text = "", ms = 3500, action = null) {
  const names = {info: "info", success: "check", warn: "warning", error: "error"};
  const el = document.createElement("div");
  el.className = `st-toast st-toast--${kind}`;
  el.innerHTML = `${icon(names[kind] || "info")}<div><div class="st-toast__title"></div><div class="t-text"></div></div>`;
  el.querySelector(".st-toast__title").textContent = title;
  el.querySelector(".t-text").textContent = text;
  if (action) {
    const b = document.createElement("button");
    b.className = "st-btn st-btn--secondary";
    b.style.height = "32px";
    b.style.marginLeft = "auto";
    b.textContent = action.label;
    b.onclick = () => { action.run(); el.remove(); };
    el.appendChild(b);
  }
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), ms);
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {                                   // http on another host: no async clipboard
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  if (btn) {
    const use = btn.querySelector("use");
    use.setAttribute("href", `${SPRITE}#i-check`);
    setTimeout(() => use.setAttribute("href", `${SPRITE}#i-copy`), 1500);
  }
  toast("success", "Copiato negli appunti", "", 1800);
}

// ------------------------------------------------------------------ theme and tabs
// the system's theme until the user picks one (only a click is saved)
function setTheme(t, save) {
  document.documentElement.dataset.theme = t;
  if (save) try { localStorage.setItem("strata.theme", t); } catch (e) { /* ignore */ }
  $("theme-icon").setAttribute("href", `${SPRITE}#i-${t === "dark" ? "sun" : "moon"}`);
  $("dark-toggle").setAttribute("aria-checked", String(t === "dark"));
}
const flipTheme = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
$("theme-btn").onclick = flipTheme;
$("dark-toggle").onclick = flipTheme;
setTheme(document.documentElement.dataset.theme || "light", false);
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
  let saved = null;
  try { saved = localStorage.getItem("strata.theme"); } catch (err) { /* ignore */ }
  if (!saved) setTheme(e.matches ? "dark" : "light", false);
});

let tab = "chat";
function showTab(name) {
  tab = ["chat", "monitor", "about", "control", "tuning", "confronti"].includes(name) ? name : "chat";
  for (const b of document.querySelectorAll(".st-tab")) {
    b.setAttribute("aria-selected", String(b.dataset.tab === tab));
    b.tabIndex = b.dataset.tab === tab ? 0 : -1;
  }
  for (const v of ["chat", "monitor", "about", "control", "tuning", "confronti"]) $(`view-${v}`).hidden = v !== tab;
  if (location.hash.slice(1) !== tab) history.replaceState(null, "", tab === "chat" ? location.pathname : `#${tab}`);
  if (tab === "chat") $("input").focus();
  if (tab === "monitor") loadMcp();
  if (tab === "control") loadControl();
  if (tab === "tuning") loadBenchmarks();
  if (tab === "confronti") loadBenchmarks();
  if (tab === "about") loadAboutBenchmarks();
  if (lastMetrics) render(lastMetrics);
}
for (const b of document.querySelectorAll(".st-tab")) b.onclick = () => showTab(b.dataset.tab);
document.querySelector(".st-tabs").addEventListener("keydown", e => {
  const tabs = [...document.querySelectorAll(".st-tab")];
  const i = tabs.indexOf(document.activeElement);
  if (i < 0 || !["ArrowLeft","ArrowRight","Home","End"].includes(e.key)) return;
  e.preventDefault();
  const next = e.key === "Home" ? 0 : e.key === "End" ? tabs.length-1 : (i+(e.key === "ArrowRight" ? 1 : -1)+tabs.length)%tabs.length;
  showTab(tabs[next].dataset.tab); tabs[next].focus(); tabs[next].scrollIntoView({block:"nearest",inline:"nearest"});
});
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));

// ------------------------------------------------------------------ server access
function headers(json = false) {
  const h = {};
  const key = store.get("apikey", "");
  if (key) h.Authorization = "Bearer " + key;
  if (json) h["Content-Type"] = "application/json";
  return h;
}
$("api-key").value = store.get("apikey", "");
$("api-key").onchange = () => { store.set("apikey", $("api-key").value.trim()); toast("success", "Chiave API salvata", "Conservata soltanto in questo browser."); };

let health = {model: "strata", images: false, max_context: 0};
async function loadHealth() {
  try {
    health = await (await fetch("health")).json();
    $("attach-btn").title = health.images ? "Allega un file di testo o un’immagine, oppure trascinali qui"
                                          : "Allega un file di testo o trascinalo qui";
    $("chat-empty-sub").textContent = `${health.model} elabora le richieste su questo PC. Gli strumenti esterni, se configurati, possono usare la rete.`;
  } catch (e) {
    setTimeout(loadHealth, 2000);
  }
}

// ------------------------------------------------------------------ Monitor
// the Monitor's cards live in index.html (Hydra One Lab premium dashboard); renderMonitor fills them

function spark(id, values, max) {
  const svg = $(id);
  if (!svg) return;                                  // a card without that sparkline must not break the panel
  const v = values || [], valid = v.filter(Number.isFinite);
  if (valid.length < 2) { svg.querySelector(".line").setAttribute("d", ""); svg.querySelector(".area").setAttribute("d", ""); return; }
  const top = Math.max(max || 0, ...valid, 1e-9);
  // a series that does not move (idle temperature) must not be pinned to the top edge: it reads
  // as a broken graph. A flat line belongs on the middle of its box.
  const lo = Math.min(...valid), flat = (top - lo) <= 0.02 * top;
  let connected = false;
  const line = v.map((x,i) => {
    if (!Number.isFinite(x)) { connected = false; return ""; }
    const command = connected ? "L" : "M"; connected = true;
    return `${command}${((i / (v.length - 1)) * 100).toFixed(2)},${(flat ? 15 : 30 - (x / top) * 26).toFixed(2)}`;
  }).join("");
  svg.querySelector(".line").setAttribute("d", line);
  svg.querySelector(".area").setAttribute("d", valid.length === v.length ? `${line}L100,32L0,32Z` : "");
}
const meanOf = (a) => { const v = (a || []).filter((x) => x != null); return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null; };
const peakOf = (a) => { const v = (a || []).filter((x) => x != null); return v.length ? Math.max(...v) : null; };
function setMetric(key, value, unit, sub) {
  const v = $(`mv-${key}`);
  if (v) v.innerHTML = value == null ? "–" : `${esc(value)}${unit ? `<small>${esc(unit)}</small>` : ""}`;
  const s = $(`ms-${key}`);
  if (s) s.textContent = value == null ? "Dato non disponibile" : sub || "";
}

let lastMetrics = null, metricsFailures = 0, keyWarned = false, mcpTick = 0, benchmarkTick = 0, aboutBenchBusy = false;
let performanceReports = [], performanceBusy = false;
let reqShowAll = false;   // the Monitor's request table: the last 12, or every one the server keeps (issue #35)
async function poll() {
  try {
    const r = await fetch(reqShowAll ? "metrics?requests=all" : "metrics", {headers: headers(),cache:"no-store",signal:AbortSignal.timeout(8000)});
    if (r.status === 401) {
      setPill("error", "API key needed");
      if (!keyWarned) { keyWarned = true; toast("warn", "API key needed", "This server needs a key: add it under About > Settings.", 6000); }
    } else if (r.ok) {
      const firstMetrics = lastMetrics === null;
      lastMetrics = await r.json();
      metricsFailures = 0;
      if ($("monitor-freshness")) $("monitor-freshness").textContent = `Aggiornato alle ${new Date().toLocaleTimeString("it-IT")}`;
      if ($("monitor-feed")) $("monitor-feed").dataset.stale = "false";
      render(lastMetrics);
      if (firstMetrics && tab === "about") loadAboutBenchmarks();
      if (firstMetrics && ["tuning","confronti"].includes(tab)) loadBenchmarks();
    } else {
      throw new Error(`HTTP ${r.status}`);
    }
  } catch (e) {
    if (++metricsFailures >= 3) { setPill("error", "Server non raggiungibile"); const state = $("about-live-state"); if (state) state.textContent = "Server non raggiungibile · dati precedenti"; if ($("monitor-feed")) $("monitor-feed").dataset.stale = "true"; if ($("monitor-freshness")) $("monitor-freshness").textContent = "Server non raggiungibile · dati precedenti"; }
  }
  if (tab === "monitor" && ++mcpTick % 10 === 0) loadMcp();       // server states change rarely: every 10 s
  if (tab === "tuning" && ++benchmarkTick % 5 === 0) loadBenchmarks();
  if (tab === "confronti" && ++benchmarkTick % 5 === 0) loadBenchmarks();
  if (tab === "about" && ++benchmarkTick % 5 === 0) loadAboutBenchmarks();
  setTimeout(poll, document.hidden ? 5000 : 2000);                  // 2 s visible, 5 s in a background tab
}

function setPill(state, text) {
  $("pill").dataset.state = state === "error" ? "queued" : state;
  $("pill-text").textContent = text;
}

function render(m) {
  if (document.hidden && !lastMetrics) { lastMetrics = m; return; }   // a background tab costs nothing
  if (tab === 'monitor') {
    const source = $('monitor-source')?.value || 'auto';
    const bench = m.benchmark;
    const selected = bench && (source === 'benchmark' || source === 'auto' && bench.active);
    $('monitor-source-label').textContent = selected
      ? `${bench.active ? 'Test in corso' : 'Ultimo test · dati conservati'} · ${bench.label}`
      : source === 'benchmark' ? 'Nessun test disponibile' : 'Servizio operativo · porta 8088';
    if (selected) {
      m = bench.metrics;
      if (!bench.active) m = {...m, live:{...m.live, state:'idle', queued:0}};
      $('monitor-feed').dataset.stale = String(bench.stale);
      $('monitor-freshness').textContent = `${bench.active ? 'Aggiornato' : 'Terminato'} alle ${new Date(bench.updated_at*1000).toLocaleTimeString('it-IT')}`;
    }
  }
  const live = m.live || {}, hw = m.hardware || {}, st = m.hardware_static || {}, eng = m.engine || {}, h = m.history || {};
  const last = (m.requests || [])[0];
  // the header pill
  if (live.state === "reading") {
    const pct = live.prompt_total ? Math.round((100 * live.prompt_read) / live.prompt_total) : null;
    setPill("reading", pct != null ? `Lettura del prompt · ${pct}%` : "Lettura del prompt");
  } else if (live.state === "generating") {
    setPill("generating", `Generazione · ${fmt(live.tok_s, 1)} tok/s`);
  } else {
    setPill("idle", live.state === "unloaded" ? "Motore spento" : "Pronto");
  }
  if (live.queued > 0) setPill("queued", `${live.queued} queued`);
  if (tab === "monitor") renderMonitor(live, hw, st, eng, h, last, m.requests || [], m.totals, m.requests_kept, m.efficiency_sample);
  if (tab === "monitor") renderPower(m.power, m);
  if (tab === "control") renderControlLive();
  if (tab === "about") renderAbout(eng, hw, st);
  if (tab === "tuning") renderTuning(eng, hw, h, st, last);
  if (tab === "confronti") renderConfronti(eng);
}

function renderTotals(t) {
  if (!t || !t.requests) return "";
  const since = new Date(t.since * 1000).toLocaleString([], {weekday: "short", hour: "2-digit", minute: "2-digit"});
  const read = t.prompt_tokens - t.reused;
  const pSpeed = t.prompt_ms > 0 && read > 0 ? ` at ${fmt(read / (t.prompt_ms / 1000))} tok/s` : "";
  const oSpeed = t.decode_ms > 0 && t.output_tokens > 0 ? ` at ${fmt(t.output_tokens / (t.decode_ms / 1000), 1)} tok/s` : "";
  return `Since ${since}: ${fmt(t.requests)} requests · ${fmt(read)} prompt tokens read${pSpeed} (${fmt(t.reused)} reused) · ` +
         `${fmt(t.output_tokens)} written${oSpeed}`;
}
function bar(id, pct, tone) {
  const el = $(id);
  if (!el) return;
  el.style.width = `${Math.min(100, Math.max(0, pct || 0))}%`;
  if (tone) el.dataset.tone = tone; else delete el.dataset.tone;
}
// a recommendation banner with no text is a 46px empty box: it must not be on screen
function syncHints() {
  document.querySelectorAll(".dash-hint").forEach((h) => { h.hidden = !h.textContent.trim(); });
}

function renderMonitor(live, hw, st, eng, h, last, requests, totals, kept, efficiencySample) {
  // ---- model state
  const on = live.queued > 0 ? "queued" : live.state;
  for (const b of document.querySelectorAll("#state-badges .st-badge")) b.classList.toggle("on", b.dataset.s === on || b.dataset.s === live.state);
  const prog = $("state-progress");
  let label = "In attesa di una richiesta", detail = "", pct = 0;
  if (live.state === "reading") {
    label = "Lettura del prompt";
    prog.dataset.tone = "info";
    if (live.prompt_total) {
      pct = (100 * live.prompt_read) / live.prompt_total;
      detail = `${fmt(live.prompt_read)} / ${fmt(live.prompt_total)} tokens · ${fmt(pct)}%`;
    } else {
      detail = `${fmt(live.prompt_tokens)} tokens`;
    }
  } else if (live.state === "generating") {
    const PHASE_IT = {answering: "Risposta", thinking: "Ragionamento", decoding: "Decodifica", draft: "Bozza", verify: "Verifica", prefill: "Prefill"};
    const ph = live.phase ? (PHASE_IT[live.phase.toLowerCase()] || live.phase[0].toUpperCase() + live.phase.slice(1)) : null;
    label = ph || "Generazione";
    delete prog.dataset.tone;
    pct = live.max_tokens ? Math.min(100, (100 * live.generated) / live.max_tokens) : 0;
    // progress of the request itself: the rate lives in the inference card
    detail = live.max_tokens
      ? `${fmt(live.generated)} di ${fmt(live.max_tokens)} token (${Math.round(pct)}%)`
      : `${fmt(live.generated)} token generati`;
  } else if (live.state === "unloaded") {
    delete prog.dataset.tone;
    label = "Motore scaricato";
    detail = "Si caricherà alla prossima richiesta. Le misure precedenti non descrivono un motore attivo.";
  } else if (live.state === "error") {
    prog.dataset.tone = "danger";
    label = "Errore del motore";
    detail = "Consulta la diagnosi del sistema prima di riprovare.";
  } else if (last) {
    delete prog.dataset.tone;
    detail = `ultima richiesta: ${fmt(last.output_tokens)} token in ${fmt(last.duration_s, 1)} s`
           + (last.finish === "length" ? " · limite raggiunto" : last.finish === "error" ? " · fallita" : ["cancel", "disconnect"].includes(last.finish) ? " · annullata" : " · terminata");
  } else {
    detail = "il motore è pronto";
  }
  $("state-label").textContent = label;
  $("state-detail").textContent = detail;
  $("state-bar").style.width = `${pct}%`;
  // the strip's own line: what the request is doing, the first token, the queue, the totals
  const bus = live.state === "reading" ? "info" : null;
  if (bus) prog.dataset.tone = "info"; else if (live.state === "generating") delete prog.dataset.tone;
  $("state-pct").textContent = `${Math.round(pct)}%`;
  $("state-phase").textContent = live.state === "reading" ? "lettura del prompt"
                               : live.state === "generating" ? "generazione"
                               : live.state === "queued" ? "in coda" : "avanzamento richiesta";
  const ttft = last && last.prompt_ms != null ? last.prompt_ms : null;
  $("state-bar-sub").textContent = live.state === "reading"
    ? (live.prefill_tok_s_mean ? `prompt letto a ${fmt(live.prefill_tok_s_mean)} tok/s` : "lettura del prompt in corso")
    : live.state === "generating"
      ? "Generazione in corso · il tempo di lettura indicato appartiene all'ultima richiesta conclusa"
      : (ttft != null ? `ultima richiesta: prompt letto in ${fmt(ttft / 1000, 2)} s` : "nessuna richiesta in corso");
  $("st-ttft").textContent = ttft != null ? `${fmt(ttft / 1000, 2)} s` : (live.state === "reading" ? "in corso" : "—");
  $("st-reqs").textContent = totals && totals.requests != null ? fmt(totals.requests) : "—";
  $("st-tokens").textContent = totals && totals.output_tokens != null ? fmt(totals.output_tokens) : "—";
  $("st-queue").textContent = live.queued != null ? fmt(live.queued) : "—";
  const stq = $("st-queue"); if (stq) stq.dataset.tone = live.queued > 0 ? "hot" : "";
  $("st-engine").textContent = [eng.version ? `motore ${eng.version}` : null, "HIP",
    eng.kv ? `KV ${eng.kv}` : null, eng.mtp_max ? `draft ${eng.mtp_max}` : null,
    eng.pool_workers ? `${eng.pool_workers} worker pool` : null,
    eng.images ? "immagini sì" : "immagini no"].filter(Boolean).join("  ·  ");
  const warn = $("st-warn");
  if (warn) {
    const low = eng.vram_free_mib != null && eng.vram_free_mib < 256;
    warn.hidden = !low;
    if (low) warn.textContent = `solo ${eng.vram_free_mib} MiB di VRAM liberi — le richieste possono rallentare`;
  }

  const multi = (hw.gpus || []).length > 1;
  const per = (f) => (hw.gpus || []).map((g) => `GPU ${g.index} ${f(g)}`).join(" · ");

  // ============ 1. GPU & Power ============
  setMetric("gpu", hw.gpu_util == null ? null : fmt(hw.gpu_util), "%",
            multi ? per((g) => (g.util == null ? "–" : `${fmt(g.util)}%`))
                  : `media ${fmt(meanOf(h.gpu_util))}% · picco ${fmt(peakOf(h.gpu_util))}%`);
  spark("sp-gpu", h.gpu_util, 100);
  setMetric("vram", hw.gpu_mem_used == null ? null : gb(hw.gpu_mem_used, 1), "GB",
            hw.gpu_mem_total ? `of ${gb(hw.gpu_mem_total, 0)} GB` : "");
  bar("bar-vram", hw.gpu_mem_total ? (100 * hw.gpu_mem_used) / hw.gpu_mem_total : 0,
      hw.gpu_mem_total && hw.gpu_mem_used / hw.gpu_mem_total > 0.95 ? "warn" : "");
  setMetric("temp", hw.gpu_temp == null ? null : fmt(hw.gpu_temp), "°C",
            multi ? per((g) => (g.temp == null ? "–" : `${fmt(g.temp)}°`))
                  : `media ${fmt(meanOf(h.gpu_temp))}° · picco ${fmt(peakOf(h.gpu_temp))}°`);
  spark("sp-temp", h.gpu_temp, 90);
  setMetric("hotspot", hw.gpu_temp_hotspot == null ? null : fmt(hw.gpu_temp_hotspot), "°C",
            hw.gpu_temp != null && hw.gpu_temp_hotspot != null ? `+${fmt(hw.gpu_temp_hotspot - hw.gpu_temp)}° over edge` : "");
  spark("sp-hotspot", h.gpu_temp_hotspot, 90);
  setMetric("power", hw.gpu_power == null ? null : fmt(hw.gpu_power), "W",
            hw.gpu_power_limit ? `di ${fmt(hw.gpu_power_limit)} W · picco ${fmt(peakOf(h.gpu_power))} W`
                               : `media ${fmt(meanOf(h.gpu_power))} W · picco ${fmt(peakOf(h.gpu_power))} W`);
  spark("sp-power", h.gpu_power, hw.gpu_power_limit || 350);
  setMetric("vramtemp", hw.gpu_vram_temp == null ? null : fmt(hw.gpu_vram_temp), "°C", "VRAM modules");
  spark("sp-vramtemp", h.gpu_vram_temp, 100);
  const gen = hw.gpu_pcie_gen;
  const probe = eng.pcie_probe_gbs;
  setMetric("pcie", gen ? `Gen${gen}` : probe != null ? fmt(probe, 1) : null,
            gen ? (hw.gpu_pcie_width ? `x${hw.gpu_pcie_width}` : "") : probe != null ? "GB/s" : "",
            [gen ? `collegamento attuale · x${hw.gpu_pcie_width || "?"}` : null,
             probe != null ? `${fmt(probe, 1)} GB/s RAM → GPU · prova all'avvio` : null,
             hw.gpu_pcie_rx_mb != null ? `RX ${fmt(hw.gpu_pcie_rx_mb, 1)} MB/s` : null,
            ].filter(Boolean).join(" · ") || "Lettura PCIe non disponibile");
  const speedNow = live.state === "generating" ? live.tok_s : last ? last.decode_tok_s : null;
  // efficiency is never a dash: live while generating, else the last measured one, with the best seen so far
  const effHist = (h.eff || []).filter((v) => v > 0);
  const effLast = efficiencySample?.value > 0 ? efficiencySample.value : effHist.length ? effHist[effHist.length - 1] : null;
  const effPeak = effHist.length ? Math.max(...effHist) : null;
  const effLive = live.state === "generating" && speedNow > 0 && hw.gpu_power > 0 ? speedNow / hw.gpu_power : null;
  const effShow = effLive != null ? effLive : effLast;
  setMetric("eff", effShow == null ? null : fmt(effShow, 2), "t/s/W",
            effLive != null ? `live · picco ${fmt(effPeak, 2)}`
              : effLast != null ? `Ultimo campione${efficiencySample?.time ? ' · '+new Date(efficiencySample.time*1000).toLocaleTimeString('it-IT') : ''}` : "In attesa di una misura durante la generazione");
  if (effShow == null) $('ms-eff').textContent = hw.gpu_power == null ? 'Manca la lettura della potenza GPU' : 'In attesa di una misura durante la generazione';
  spark("sp-eff", (h.eff || []).map(v => v > 0 ? v : null), effPeak);
  setMetric("volt", hw.gpu_volt == null ? null : fmt(hw.gpu_volt, 3), "V",
            hw.gpu_volt != null ? 'Tensione GPU rilevata' : '');
  $("ms-gpu-name").textContent = st.gpu_name || "";
  // a reading that runs hot takes the warning colour in its own tile
  const hot = (key, v, warn, danger) => {
    const el = $(`mv-${key}`);
    const dm = el && el.closest(".dm");
    if (dm) dm.dataset.hot = v == null ? "" : v >= danger ? "2" : v >= warn ? "1" : "";
  };
  hot("temp", hw.gpu_temp, 70, 80); hot("hotspot", hw.gpu_temp_hotspot, 80, 90);
  hot("vramtemp", hw.gpu_vram_temp, 85, 95); hot("cpu_temp", hw.cpu_temp, 75, 85);

  // ============ 2. CPU & System ============
  setMetric("cpu", hw.cpu == null ? null : fmt(hw.cpu), "%",
            `media ${fmt(meanOf(h.cpu))}% · ${st.threads || "?"} thread del pool`);
  spark("sp-cpu", h.cpu, 100);
  setMetric("cpu_temp", hw.cpu_temp == null ? null : fmt(hw.cpu_temp), "°C",
            `media ${fmt(meanOf(h.cpu_temp))}° · picco ${fmt(peakOf(h.cpu_temp))}°`);
  spark("sp-cpu_temp", h.cpu_temp, 95);
  setMetric("cpu_power", hw.cpu_power == null ? null : fmt(hw.cpu_power), "W",
            `media ${fmt(meanOf(h.cpu_power))} W · picco ${fmt(peakOf(h.cpu_power))} W`);
  spark("sp-cpu_power", h.cpu_power, 200);
  $("ms-cores").textContent = st.cores ? `${st.cores} cores · ${st.threads} threads` : "";
  setMetric("ram", hw.ram_total ? `${gb(hw.ram_used, 1)} / ${gb(hw.ram_total, 0)}` : null, "GB",
            hw.ram_total ? `${fmt((100 * hw.ram_used) / hw.ram_total)}% used` : "");
  bar("bar-ram", hw.ram_total ? (100 * hw.ram_used) / hw.ram_total : 0,
      hw.ram_total && hw.ram_used / hw.ram_total > 0.92 ? "danger" : "");
  if (hw.disk_read_mb == null) {
    setMetric("disk", null, "", st.psutil ? "" : "needs psutil (setup installs it)");
  } else {
    const big = hw.disk_read_mb >= 1000;
    setMetric("disk", big ? fmt(hw.disk_read_mb / 1024, 2) : fmt(hw.disk_read_mb, hw.disk_read_mb < 10 ? 1 : 0),
              big ? "GB/s" : "MB/s", hw.disk_write_mb == null ? "" : `write ${fmt(hw.disk_write_mb, 1)} MB/s`);
  }
  setMetric("board", hw.cpu_temp != null || hw.cpu_power != null ? `${fmt(hw.cpu_temp)}° / ${fmt(hw.cpu_power)} W` : null, "",
            hw.cpu_temp != null ? "CPU package (AIDA64)" : "");
  setMetric("corecount", st.cores ? `${st.cores} / ${st.threads}` : null, "", "fisici / logici");
  const upS = totals && totals.since ? Math.max(0, Date.now() / 1000 - totals.since) : null;
  const hm = (s) => s == null ? null : (s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m` : `${Math.floor(s / 60)}m ${Math.floor(s % 60)}s`);
  setMetric("uptime", hm(upS), "", totals && totals.requests ? `${fmt(totals.requests)} richieste · ${fmt(totals.output_tokens)} token scritti` : "nessuna richiesta ancora");

  // ============ 3. Inference ============
  const speed = live.state === "generating" ? live.tok_s : last ? last.decode_tok_s : null;
  setMetric("speed", speed == null ? null : fmt(speed, 1), "t/s",
            live.state === "generating" ? "in corso ora" : last ? "ultima richiesta"
              : "in attesa della prima richiesta");
  spark("sp-speed", (h.tok_s || []).map(v => v > 0 ? v : null));
  const prefill = ["reading", "generating"].includes(live.state) ? live.prefill_tok_s_mean
    : last && last.prompt_ms > 0 ? Math.max(0, last.prompt_tokens - (last.reused || 0)) / (last.prompt_ms / 1000) : null;
  setMetric("prefill", prefill == null ? null : fmt(prefill), "t/s",
            live.state === "reading" ? "legge il prompt ora" : live.state === "generating" ? "questa richiesta"
              : last ? "ultima richiesta" : "in attesa della prima richiesta");
  spark("sp-prefill", (h.prefill_tok_s_mean || []).map(v => v > 0 ? v : null));
  const ctx = eng.max_context || 0;
  let used = 0;
  if (live.state !== "idle") used = (live.prompt_tokens || 0) + (live.generated || 0);
  else if (last) used = (last.prompt_tokens || 0) + (last.output_tokens || 0);
  const frac = ctx ? Math.min(1, used / ctx) : 0;
  $("ctx-fill").setAttribute("stroke-dasharray", `${(235.6 * frac).toFixed(1)} 314.2`);
  $("ctx-fill").style.opacity = 235.6 * frac >= 3 ? "1" : "0";
  $("ctx-pct").textContent = `${Math.round(frac * 100)}%`;
  $("ctx-sub").textContent = ctx ? `${kfmt(used)} / ${ctxfmt(ctx)}` : "–";
  const cacheBytes = (eng.expert_cache_mib || 0) * 1048576;
  setMetric("experts", live.state !== 'unloaded' && eng.expert_slots ? fmt(eng.expert_slots) : null, "",
            eng.expert_slots ? `${gb(cacheBytes)} GB in VRAM` : "");
  bar("bar-experts", live.state !== 'unloaded' && hw.gpu_mem_total ? (100 * cacheBytes) / hw.gpu_mem_total : 0, "");
  setMetric("state", ({unloaded:"Scaricato",idle:"Pronto",reading:"Lettura",generating:"Generazione",error:"Errore",queued:"In coda"})[live.state] || live.state || null, "",
            live.state === "generating" ? `${fmt(live.generated)} token scritti`
              : live.state === "reading" ? "legge il prompt" : "in attesa di una richiesta");
  $("ms-model").textContent = eng.model || "";
  // ---- one recommendation line per card: what the machine does vs what it should
  const hint = (id, ok, text) => {
    const el = $(id);
    if (!el) return;
    el.dataset.tone = ok ? "" : "warn";
    el.innerHTML = `<b>${ok ? "Stato" : "Avviso"}</b><span>${esc(text)}</span>`;
    el.hidden = false;
    el.title = text;                                  // the full line on hover, the box stays fixed
  };
  const vramPct = hw.gpu_mem_total && hw.gpu_mem_used != null ? Math.round((100 * hw.gpu_mem_used) / hw.gpu_mem_total) : null;
  hint("hint-gpu", !(hw.gpu_temp >= 80 || vramPct >= 95),
       `VRAM ${vramPct == null ? 'non disponibile' : vramPct+'% in uso'}${hw.gpu_temp == null || hw.gpu_power == null ? ' · sensori temperatura/potenza GPU non disponibili' : ' · sensori GPU disponibili'}`);
  const ramPct2 = hw.ram_total ? Math.round((100 * hw.ram_used) / hw.ram_total) : null;
  hint("hint-cpu", ramPct2 == null || ramPct2 < 92,
       `RAM ${ramPct2 == null ? 'non disponibile' : ramPct2+'% in uso'} · ${eng.pool_workers ? eng.pool_workers+' worker configurati' : 'pool non rilevato'}`);
  const hr = last && last.hit_rate != null ? Math.round(last.hit_rate * 100) : null;
  const dr = totals && totals.drafts_offered ? Math.round((100 * totals.drafts_accepted) / totals.drafts_offered) : null;
  hint("hint-inf", true,
       live.state === 'unloaded' ? 'Motore scaricato · invia una richiesta o seleziona i dati di un test'
       : `Ultima richiesta · cache ${hr == null ? 'non disponibile' : hr+'%'} · draft accettati ${dr == null ? 'non disponibili' : dr+'%'}`);
  hint("hint-pm", !(lastMetrics && lastMetrics.power && lastMetrics.power.throttling),
       "Soglie di avviso software · nessuna modifica ai limiti del driver");
  // the Control tab's own lines
  hint("hint-ctrl-run", true, "Lascia che carichi alla prima richiesta; “Ferma” libera la VRAM senza perdere la configurazione.");
  hint("hint-ctrl-res", true, "Su questa macchina: VRAM riservata 1536 MiB · KV 32768 · contesto 131072. Applica e riavvia per attivarli.");
  hint("hint-ctrl-power", true, "Balanced segnala oltre 80°C o 250 W. Eco usa soglie inferiori; nessun profilo modifica il driver.");
  setMetric("hit", last && last.hit_rate != null ? (last.hit_rate * 100).toFixed(1) : null, "%",
            last && last.hit_rate != null ? "esperti in VRAM · ultima richiesta" : "in attesa di una richiesta");
  const d = totals || {};
  setMetric("draft", d.drafts_offered ? Math.round((100 * d.drafts_accepted) / d.drafts_offered) : null, "%",
            d.drafts_offered ? `${fmt(d.drafts_accepted)} / ${fmt(d.drafts_offered)} draft MTP` : "nessun draft ancora");
  if (live.state === 'reading') {
    if (!last) $('ms-speed').textContent = 'In attesa della generazione';
    if (!last?.hit_rate) $('ms-hit').textContent = 'Disponibile al termine della richiesta';
    if (!d.drafts_offered) $('ms-draft').textContent = 'In attesa della generazione';
    if (effShow == null) $('ms-eff').textContent = 'Disponibile durante la generazione';
  }

  // ============ 4. Power Manager ============   (filled by render() from metrics.power)

  // ---- recent requests
  const body = $("req-body");
  if (!requests.length) {
    body.innerHTML = `<tr><td colspan="8" class="muted">Nessuna richiesta registrata</td></tr>`;
  } else {
    const badge = {stop: ["", "Done"], length: ["", "Max tokens"], cancel: ["st-badge--queued", "Stopped"],
                   disconnect: ["st-badge--queued", "Closed"], error: ["st-badge--error", "Error"]};
    body.innerHTML = requests.slice(0, reqShowAll ? requests.length : 12).map((r) => {
      const [cls, text] = badge[r.finish] || ["", r.finish || "–"];
      const t = new Date(r.time * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
      const proj = r.projection == null ? "" : ` <span class="st-badge${r.projection ? " st-badge--reading" : ""}" title="experimental speed projection ${r.projection ? "on" : "off"}">${r.projection ? "ESP" : "stock"}</span>`;
      const hit = r.hit_rate == null ? "–" : `${(r.hit_rate * 100).toFixed(1)}%`;
      return `<tr><td>${esc(t)}</td><td><span class="st-badge ${cls}">${esc(text)}</span>${proj}</td><td class="num">${fmt(r.prompt_tokens)}</td>
        <td class="num">${fmt(r.reused)}</td><td class="num">${fmt(r.output_tokens)}</td><td class="num">${fmt(r.decode_tok_s, 1)}</td>
        <td class="num">${hit}</td><td class="num">${fmt(r.duration_s, 1)} s</td></tr>`;
    }).join("");
  }
  const all = $("req-all");
  kept = kept == null ? requests.length : kept;
  all.hidden = kept <= 12;
  all.textContent = reqShowAll ? "Mostra meno" : `Mostra tutte (${kept})`;
  $("req-wrap").classList.toggle("all", reqShowAll);
  $("req-totals").textContent = renderTotals(totals);
  syncHints();                                      // no empty banner box on the Monitor either
}

// the Power Manager card: mode, limits, live status (from GET /metrics' "power")
function renderPower(pm, metrics = lastMetrics) {
  if (!pm) return;
  const st = $("pm-status");
  if (st) { st.textContent = pm.throttling ? "Soglia superata" : "Monitoraggio"; $("pm-stat-status").dataset.tone = pm.throttling ? "warn" : "ok"; }
  if ($("pm-eff")) {
    const hist = (metrics?.history?.eff || []).filter((v) => v > 0);
    const fallback = metrics?.efficiency_sample?.value > 0 ? metrics.efficiency_sample.value : hist.length ? hist[hist.length - 1] : null;
    $("pm-eff").textContent = pm.efficiency > 0 ? fmt(pm.efficiency, 2) : fallback != null ? fmt(fallback, 2) : "–";
  }
  if ($("pm-tlim")) $("pm-tlim").textContent = `${pm.temp_limit}°C`;
  if ($("pm-plim")) $("pm-plim").textContent = `${pm.power_limit}W`;
  if ($("ms-pm-mode")) $("ms-pm-mode").textContent = pm.mode || "";
  const modeEl = $("pm-mode");
  if (modeEl && pm.mode && document.activeElement !== modeEl && modeEl.value !== pm.mode) modeEl.value = pm.mode;
  const tEl = $("pm-temp"), pEl = $("pm-power");
  if (tEl && document.activeElement !== tEl && pm.temp_limit != null && +tEl.value !== pm.temp_limit) {
    tEl.value = pm.temp_limit; $("pm-temp-out").textContent = `${pm.temp_limit}°C`;
  }
  if (pEl && document.activeElement !== pEl && pm.power_limit != null && +pEl.value !== pm.power_limit) {
    pEl.value = pm.power_limit; $("pm-power-out").textContent = `${pm.power_limit}W`;
  }
  // the two limit sliders show what the machine is doing against the limit
  const tnow = lastMetrics && lastMetrics.hardware ? lastMetrics.hardware.gpu_temp : null;
  const pnow = lastMetrics && lastMetrics.hardware ? lastMetrics.hardware.gpu_power : null;
  const sub = (id, text) => { const el = $(id); if (el) el.textContent = text; };
  const barS = (id, pct) => { const el = $(id); if (el) el.style.width = `${Math.min(100, Math.max(0, pct || 0))}%`; };
  if (tnow != null && pm.temp_limit) {
    sub("ms-pm-temp", `${fmt(tnow)}°C ora · ${fmt(pm.temp_limit - tnow)}° di margine`);
    barS("bar-pm-temp", (100 * tnow) / pm.temp_limit);
  }
  if (pnow != null && pm.power_limit) {
    sub("ms-pm-power", `${fmt(pnow)} W ora · ${fmt(pm.power_limit - pnow)} W di margine`);
    barS("bar-pm-power", (100 * pnow) / pm.power_limit);
  }
  const thr = $("pm-throttle");
  if (thr) { thr.hidden = !pm.throttling; if (pm.throttling) thr.textContent = `Avviso: ${pm.throttle_reason} · valido per ${pm.cooldown_s}s · nessun intervento sul driver`; }
}

// ---- Power Manager controls (wired once)
(function () {
  const tEl = $("pm-temp"), pEl = $("pm-power");
  if (tEl) tEl.oninput = () => { $("pm-temp-out").textContent = `${tEl.value}°C`; };
  if (pEl) pEl.oninput = () => { $("pm-power-out").textContent = `${pEl.value}W`; };
  const send = async (body, ok) => {
    try {
      const r = await fetch("power", {method: "POST", headers: headers(true), body: JSON.stringify(body)});
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      if (ok) toast("success", "Power Manager", ok);
    } catch (e) { toast("error", "Power Manager", e.message); }
  };
  if ($("pm-apply")) $("pm-apply").onclick = () => send({mode: $("pm-mode").value, temp_limit: +tEl.value, power_limit: +pEl.value},
                                                        `${$("pm-mode").value} · ${tEl.value}°C · ${pEl.value}W`);
  if ($("pm-reset")) $("pm-reset").onclick = () => send({reset: true}, "Avviso azzerato");
})();

function facts(el, rows) {
  el.innerHTML = rows.filter((r) => r[1] != null && r[1] !== "").map(([k, v, copy]) =>
    `<dt>${esc(k)}</dt><dd>${copy ? `<code>${esc(v)}</code><button class="st-btn st-btn--icon" data-copy="${esc(v)}" aria-label="Copy">${icon("copy")}</button>` : esc(v)}</dd>`).join("");
}
$("export-diagnostics").addEventListener("click", async () => {
  try {
    const r = await fetch("metrics", {headers: headers(), cache: "no-store"});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const m = await r.json();
    const report = {schema_version: 1, exported_at: new Date().toISOString(), diagnostics: m.diagnostics,
      engine: m.engine, live: m.live, hardware: m.hardware, hardware_static: m.hardware_static, totals: m.totals};
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type:"application/json"}));
    const a = document.createElement("a"); a.href = url; a.download = "strata-diagnosi.json"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) { toast("error", "Diagnosi", e.message); }
});
// INFO cvec=project:4-44[:singleL] | add:A-B | 0
function projectionText(c) {
  if (!c || c === "0" || c === 0) return null;
  const [mode, range, single] = String(c).split(":");
  const [a, b] = (range || "").split("-");
  return `${mode === "project" ? "Projection" : "Additive"} control vector on layers ${a}–${b}` +
         `${single ? ` (layer ${single.replace("single", "")}'s direction)` : ""}. Per chat in Sampling. Its package ` +
         "describes the vector as a refusal-direction projection; measure the speed yourself";
}
function renderAbout(eng, hw, st) {
  const kv = {int8: "8-bit", q4_0: "4-bit (Hadamard)", fp16: "16-bit"}[eng.kv] || eng.kv;
  const m = lastMetrics || {};
  const last = (m.requests || []).find(r => r.decode_tok_s != null && !["error","disconnect"].includes(r.finish)) || {};
  const arch = (eng.archs || []).join(" · ");
  const state = $("about-live-state");
  if (state) { state.textContent = ({idle:"Motore pronto",unloaded:"Motore scaricato · caricamento a richiesta",reading:"Lettura del prompt",generating:"Generazione in corso"})[m.live?.state] || "Stato non disponibile"; state.dataset.state = m.live?.state || "unknown"; }
  if ($("about-updated")) $("about-updated").textContent = m.time ? `Dati aggiornati alle ${new Date(m.time*1000).toLocaleTimeString("it-IT")}` : "Aggiornamento non disponibile";
  if ($("about-model-title")) $("about-model-title").textContent = eng.model || "Modello non disponibile";
  if ($("about-model-sub")) $("about-model-sub").textContent = `${eng.max_context ? fmt(eng.max_context)+" token di contesto" : "Contesto non disponibile"} · ${eng.images ? "immagini abilitate" : "immagini spente"}`;
  if ($("about-backend-badge")) $("about-backend-badge").textContent = eng.backend ? eng.backend.toUpperCase() : "—";
  if ($("about-amd-mark")) $("about-amd-mark").hidden = eng.backend !== "hip";

  // --- the identity plate: what this build IS, in one glance
  const spec = [["Motore", eng.version ? `v${eng.version}` : "Non disponibile"],
                ["Backend", eng.backend ? eng.backend.toUpperCase() : "Non disponibile"],
                ["Runtime", eng.rocm ? `ROCm ${eng.rocm}` : "—"],
                ["hipBLASLt", eng.hipblaslt ? String(eng.hipblaslt) : "—"],
                ["Target compilati", arch || "—"],
                ["Piattaforma", eng.platform || "—"]];
  const specEl = $("about-spec");
  if (specEl) specEl.innerHTML = spec.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("");

  // These rows are the card's shape: a value that is momentarily missing shows "—" instead of
  // dropping the row, or the card shrinks and stops matching the one beside it.
  const dash = (v) => (v == null || v === "" ? "—" : v);
  facts($("facts-engine"), [
    ["Modello", dash(eng.model)],
    ["Contesto", eng.max_context ? `${fmt(eng.max_context)} token` : "—"],
    ["KV cache", kv ? `${kv}${eng.kv_resident ? ` · ${fmt(eng.kv_resident)} celle/layer in VRAM` : " · tutto in VRAM"}` : "—"],
    ["Esperti in VRAM", eng.expert_slots ? `${fmt(eng.expert_slots)} (${gb((eng.expert_cache_mib || 0) * 1048576)} GiB)` : "—"],
    ["Speculazione", eng.mtp_max ? `fino a ${eng.mtp_max} draft per passo${eng.lookup ? " · lookup prompt" : ""}` : "—"],
    ["Pool CPU", eng.pool_workers ? `${eng.pool_workers} worker` : "—"],
    ["Arena", eng.arena_mib != null ? `${fmt(eng.arena_mib)} MiB` : "—"],
    ["Immagini", eng.images ? "encoder attivo" : "encoder spento · attivazione in Control"],
  ]);

  facts($("facts-hw"), [
    ["GPU", dash(st.gpu_name || "non leggibile")],
    ["VRAM", hw.gpu_mem_total ? `${gb(hw.gpu_mem_total, 0)} GiB` : "—"],
    ["CPU", dash(st.cpu_name)],
    ["Core", st.cores ? `${st.cores} fisici / ${st.threads} thread` : "—"],
    ["RAM", hw.ram_total ? `${gb(hw.ram_total, 0)} GiB` : "—"],
    ["RAM in uso", hw.ram_used ? `${gb(hw.ram_used, 0)} / ${gb(hw.ram_total, 0)} GiB` : "—"],
    ["PCIe / probe avvio", [hw.gpu_pcie_gen ? `Gen${hw.gpu_pcie_gen} x${hw.gpu_pcie_width || "—"}` : null, eng.pcie_probe_gbs ? `${fmt(eng.pcie_probe_gbs, 1)} GB/s al caricamento` : null].filter(Boolean).join(" · ") || "—"],
    ["Temp. e potenza", hw.gpu_temp != null || hw.gpu_power != null
      ? `${hw.gpu_temp != null ? `${hw.gpu_temp} \u00b0C` : "—"}${hw.gpu_power != null ? ` \u00b7 ${Math.round(hw.gpu_power)} W` : ""}` : "—"],
  ]);

  // --- the numbers this machine really produces, against the documented reference
  const read = last.prompt_read ?? (last.prompt_tokens != null && last.reused != null ? Math.max(0, last.prompt_tokens - last.reused) : null);
  const pf = last.prompt_ms > 0 && read != null ? read / (last.prompt_ms / 1000) : null;
  const cells = $("about-stats") ? $("about-stats").querySelectorAll(".about-stat") : [];
  const row = [
    [last.decode_tok_s ? `${fmt(last.decode_tok_s, 1)}` : "—", "t/s", last.decode_tok_s ? "" : null],
    [pf ? `${fmt(pf, 0)}` : "—", "t/s", ""],
    [last.duration_s != null ? `${fmt(last.duration_s, 2)}` : "—", "s", ""],
    [last.hit_rate != null ? `${fmt(last.hit_rate * 100, 0)}` : "—", "%", ""],
  ];
  cells.forEach((c, i) => {
    c.querySelector("b").textContent = row[i][0];
    c.classList.remove("about-stat--win", "about-stat--low");
  });

  // no request yet on this boot: show WHY the slot is empty instead of four dashes
  const statsEl = $("about-stats");
  const hasData = last.decode_tok_s != null || last.prompt_ms != null;
  if (statsEl) statsEl.hidden = !hasData;
  const emptyEl = $("about-empty");
  if (emptyEl) emptyEl.hidden = hasData;

  const refEl = $("about-ref");
  if (refEl) refEl.hidden = true;
  const noteEl = $("about-note");
  if (noteEl) noteEl.hidden = !hasData;                  // the method line only means something with numbers
  if (noteEl && hasData) noteEl.textContent = `Singola richiesta: ${fmt(last.prompt_tokens)} token di prompt, ${fmt(last.output_tokens)} in uscita. `
    + "Decode dal protocollo DONE; prefill sui soli token letti. Il tempo totale include il prefill. "
    + "Per confrontare configurazioni usa il banco riproducibile: questi valori non sono una mediana.";

  const limEl = $("about-limits");
  if (limEl) {
    const limits = [
      ["Immagini", eng.images ? "Encoder abilitato. Cambiare modalità prepara il prossimo avvio del motore; il cambio è rifiutato durante una richiesta in corso." : "Encoder spento. Attivalo in Control quando serve: il motore viene scaricato e si ricarica con il supporto immagini alla prossima richiesta."],
      ["Speculazione", eng.mtp_max != null ? `Finestra attiva: fino a ${eng.mtp_max} draft; soglia min-p ${eng.spec_min_p ?? "non disponibile"}. Le prove alternative non hanno dimostrato un vantaggio stabile del motore completo.` : "Parametri non ancora riportati dal motore. Consulta Control e i rapporti salvati."],
      ["Memoria", "Gli esperti vengono conservati in VRAM e letti dai file mappati quando necessario. La telemetria e la diagnosi mostrano il margine effettivo; i budget si applicano al successivo avvio."],
      ["Una richiesta alla volta", "Il server serializza l'inferenza. Le richieste concorrenti attendono in coda; l'annullamento del client interrompe la generazione."],
      ["Monitor termico", "Balanced, Eco e Custom impostano avvisi. Non modificano clock o potenza del driver. Un dato mancante non viene interpretato come una lettura zero."],
      ["Output strutturato", "JSON e schemi JSON vengono richiesti al modello e validati prima della consegna. Non è una decodifica vincolata da grammatica: una risposta non conforme può essere rifiutata."],
    ];
    limEl.innerHTML = limits.map(([k, v]) => `<li><b>${esc(k)}.</b> ${esc(v)}</li>`).join("");
  }
  const diag = $("diagnostics-checks");
  if (diag) diag.innerHTML = ((m.diagnostics || {}).checks || []).map(c =>
    `<li data-state="${esc(c.state)}"><b>${esc(c.title)}</b><span>${esc(c.detail)}</span><small>${esc({ok:"Verificato",warn:"Da controllare",info:"Informazione",unknown:"Non disponibile"}[c.state] || c.state)}</small></li>`).join("");

  const base = location.origin;
  facts($("facts-api"), [
    ["OpenAI base URL", `${base}/v1`, true],
    ["Anthropic base URL", base, true],
    ["Model name", eng.model, true],
    ["Stato del motore", `${base}/v1/status`, true],
  ]);
}

document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-copy]");
  if (b) copyText(b.dataset.copy, b);
});
$("req-all").addEventListener("click", () => { reqShowAll = !reqShowAll; if (lastMetrics) render(lastMetrics); });

// ------------------------------------------------------------------ MCP servers (GET /mcp)
// Tools from the MCP servers in the run config: the chat offers them to the model (opt-in per request,
// "strata_mcp": true, which only this page sends); the Monitor lists the servers and what they offer.
let mcpInfo = {servers: [], tools: 0}, mcpRetry = null;
async function loadMcp() {
  try {
    const r = await fetch("mcp", {headers: headers()});
    if (!r.ok) return;
    mcpInfo = await r.json();
  } catch (e) { return; /* an older server: no MCP */ }
  renderMcp();
  clearTimeout(mcpRetry);                          // right after the start, servers may still be starting (npx downloads)
  if ((mcpInfo.servers || []).some((s) => s.status === "starting")) mcpRetry = setTimeout(loadMcp, 3000);
}
const MCP_STATE = {ready: ["st-badge--generating", "Connected"], starting: ["st-badge--reading", "Starting"],
                   failed: ["st-badge--error", "Failed"], stopped: ["st-badge--queued", "Stopped"], idle: ["", "Waiting"]};
function renderMcp() {
  const servers = mcpInfo.servers || [];
  $("mcp-card").hidden = !servers.length;
  $("mcp-row").hidden = !servers.length;
  const ready = servers.filter((s) => s.status === "ready" || s.status === "stopped");
  $("mcp-sum").textContent = servers.length ? `${fmt(mcpInfo.tools)} tools · ${ready.length} of ${servers.length} servers connected` : "";
  $("mcp-row-sub").textContent = mcpInfo.tools ? `${fmt(mcpInfo.tools)} tools from ${ready.map((s) => s.name).join(", ")}; the model calls them when it decides to`
                                               : "no server is connected yet (see the Monitor)";
  $("mcp-list").innerHTML = servers.map((s) => {
    const [cls, text] = MCP_STATE[s.status] || ["", s.status];
    const info = s.info && s.info.name ? ` · ${s.info.name}${s.info.version ? ` ${s.info.version}` : ""}` : "";
    return `<div class="mcp-server"><div class="mcp-server__head"><span class="st-badge ${cls}">${esc(text)}</span>` +
      `<strong>${esc(s.name)}</strong><span class="muted small">${esc(s.transport)} · ${fmt(s.tools.length)} tools${esc(info)}</span></div>` +
      (s.error ? `<div class="msg-error">${esc(s.error)}</div>` : "") +
      (s.tools.length ? `<div class="mcp-server__tools">${s.tools.map((t) => `<span class="chip" title="${esc(t.description || "")}">${esc(t.tool)}</span>`).join("")}</div>` : "") +
      `</div>`;
  }).join("");
}

// ------------------------------------------------------------------ Markdown (escaped first, then formatted)
function inline(s) {
  const codes = [];
  s = s.replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = esc(s)
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\n]+)\*(?![*\w])/g, "$1<em>$2</em>")
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code class="inline">${esc(codes[+i])}</code>`);
}
function codeBlock(lang, code) {
  return `<div class="st-code"><div class="st-code__head"><span>${esc(lang || "code")}</span>` +
    `<button class="st-btn st-btn--icon" data-code-copy aria-label="Copy code">${icon("copy")}</button></div>` +
    `<pre><code>${esc(code)}</code></pre></div>`;
}
function blocks(text) {
  const out = [], lines = text.split("\n");
  let para = [], list = null;
  const flushPara = () => { if (para.length) out.push(`<p>${para.map(inline).join("<br>")}</p>`); para = []; };
  const flushList = () => { if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; };
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    let m;
    if (!l.trim()) { flushPara(); flushList(); continue; }
    if ((m = l.match(/^(#{1,6})\s+(.*)$/))) { flushPara(); flushList(); out.push(`<${m[1].length <= 2 ? "h3" : "h4"}>${inline(m[2])}</${m[1].length <= 2 ? "h3" : "h4"}>`); continue; }
    if (/^\s*([-*_])\s*\1\s*\1[\s\1]*$/.test(l)) { flushPara(); flushList(); out.push("<hr>"); continue; }
    if ((m = l.match(/^>\s?(.*)$/))) { flushPara(); flushList(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
    if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(lines[i + 1])) {
      flushPara(); flushList();
      const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
      let html = `<table><thead><tr>${cells(l).map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>`;
      i += 2;
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) html += `<tr>${cells(lines[i++]).map((c) => `<td>${c}</td>`).join("")}</tr>`;
      i--;
      out.push(html + "</tbody></table>");
      continue;
    }
    if ((m = l.match(/^\s*(?:[-*+]|(\d+)[.)])\s+(.*)$/))) {
      flushPara();
      const tag = m[1] ? "ol" : "ul";
      if (!list || list.tag !== tag) { flushList(); list = {tag, items: []}; }
      list.items.push(m[2]);
      continue;
    }
    if (list && /^\s{2,}\S/.test(l)) { list.items[list.items.length - 1] += " " + l.trim(); continue; }
    flushList();
    para.push(l);
  }
  flushPara(); flushList();
  return out.join("");
}
function markdown(text) {
  let html = "", rest = text;
  for (;;) {
    const m = rest.match(/(^|\n)```([^\n`]*)\n/);
    if (!m) { html += blocks(rest); break; }
    html += blocks(rest.slice(0, m.index));
    rest = rest.slice(m.index + m[0].length);
    const end = rest.match(/(^|\n)```[ \t]*(\n|$)/);
    if (!end) { html += codeBlock(m[2].trim(), rest); break; }         // still streaming
    html += codeBlock(m[2].trim(), rest.slice(0, end.index));
    rest = rest.slice(end.index + end[0].length);
  }
  return html;
}

// ------------------------------------------------------------------ Chat
const DEFAULTS = {thinking: "high", temperature: 0.6, top_p: 0.95, top_k: 20, max: "", seed: "", show: true, esp: true, mcp: true};
let settings = {...DEFAULTS, ...store.get("sampling", {})};
let messages = store.get("chat", []);
let attachments = [];                 // {name, url}
let busy = null;                      // {controller, msg}

function saveChat() {
  store.set("chat", messages.map((m) => ({...m, images: (m.images || []).map((i) => ({name: i.name})),
                                           files: (m.files || []).map((f) => ({name: f.name}))})));
}
function timeStr(t) { return new Date(t).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}); }

function msgEl(m, i) {
  const el = document.createElement("div");
  el.className = `st-msg st-msg--${m.role}`;
  el.dataset.i = i;
  if (m.role === "user") {
    if (m.files && m.files.length) {
      const wrap = document.createElement("div");
      wrap.className = "msg-images";
      for (const f of m.files) {
        const c = document.createElement("span");
        c.className = "chip";
        c.innerHTML = icon("attach", "st-icon st-icon--sm");
        c.append(f.name);
        wrap.appendChild(c);
      }
      el.appendChild(wrap);
    }
    if (m.images && m.images.length) {
      const wrap = document.createElement("div");
      wrap.className = "msg-images";
      for (const im of m.images) {
        if (im.url) { const img = document.createElement("img"); img.src = im.url; img.alt = im.name || "image"; wrap.appendChild(img); }
        else { const c = document.createElement("span"); c.className = "chip"; c.innerHTML = icon("image", "st-icon st-icon--sm"); c.append(im.name || "image"); wrap.appendChild(c); }
      }
      el.appendChild(wrap);
    }
    const b = document.createElement("div");
    b.className = "st-bubble";
    b.textContent = m.text;
    el.appendChild(b);
    const meta = document.createElement("div");
    meta.className = "st-msg__meta";
    meta.textContent = `You · ${timeStr(m.time)}`;
    el.appendChild(meta);
  } else {
    el.innerHTML = `<details class="st-collapse think" hidden><summary>${icon("thinking", "st-icon st-icon--sm")}<span class="think-title"></span>` +
      `${icon("chevron", "st-icon st-icon--sm st-chev")}</summary><div class="st-collapse__body thinking"></div></details>` +
      `<div class="st-bubble"></div><div class="st-msg__meta"><span class="meta-text"></span>` +
      `<button class="st-btn st-btn--icon" data-msg-copy aria-label="Copy the answer" title="Copy">${icon("copy")}</button></div>`;
    updateAssistant(el, m, false);
  }
  return el;
}
// One MCP tool call in the answer: a compact block (name, state, a one-line preview) that opens to the arguments and
// the result as the model read it.  Its body is built only while open: a result can be 20,000 characters.
const TOOL_STATE = {writing: ["st-badge--reading", "Writing"], running: ["st-badge--generating", "Running"], done: ["", "Done"],
                    error: ["st-badge--error", "Error"], skipped: ["st-badge--queued", "Not run"]};
function toolHtml(t, k) {
  const [cls, label] = TOOL_STATE[t.state] || ["", t.state];
  const args = t.arguments == null ? "" : JSON.stringify(t.arguments, null, 2);
  const preview = t.result != null ? t.result : args.replace(/\s+/g, " ");
  let body = "";
  if (t.open) {
    body = `<div class="tool-call__label">Arguments</div><pre class="tool-call__pre">${esc(args || "(being written)")}</pre>`;
    if (t.result != null) {
      body += `<div class="tool-call__label">${t.ok ? "Result" : "Error"}${t.chars ? ` · ${fmt(t.chars)} characters` : ""}` +
              `${t.truncated ? ", cut for the model" : ""}</div><pre class="tool-call__pre">${esc(t.result)}</pre>`;
    }
  }
  return `<details class="st-collapse tool-call" data-tool="${k}" data-state="${esc(t.state)}"${t.open ? " open" : ""}>` +
    `<summary>${icon("tool", "st-icon st-icon--sm")}<span class="tool-call__name" title="${esc(t.name || "")}">${esc(t.tool || t.name || "tool")}</span>` +
    (t.server ? `<span class="muted small">${esc(t.server)}</span>` : "") +
    `<span class="tool-call__preview muted">${esc(preview.slice(0, 200))}</span>` +
    `<span class="st-badge ${cls}">${esc(label)}</span>${t.ms != null && t.state !== "skipped" ? `<span class="muted small">${fmt(t.ms / 1000, 1)} s</span>` : ""}` +
    `${icon("chevron", "st-icon st-icon--sm st-chev")}</summary><div class="st-collapse__body">${body}</div></details>`;
}
// the answer's text with the tool blocks where the model called them
function answerHtml(m) {
  if (!m.tools || !m.tools.length) return markdown(m.text || "");
  let html = "", pos = 0;
  m.tools.forEach((t, k) => {
    const at = Math.min(Math.max(t.at || 0, pos), m.text.length);
    if (at > pos) html += markdown(m.text.slice(pos, at));
    pos = at;
    html += toolHtml(t, k);
  });
  return html + markdown(m.text.slice(pos));
}
// a tool event from the stream (the `strata_mcp` field of a chunk)
function onTool(m, x) {
  if (x.event === "limit") { m.limit = x.max_rounds; return; }
  m.tools = m.tools || [];
  let t = m.tools.find((y) => y.id === x.id);
  if (!t) { t = {id: x.id, name: x.name, at: m.text.length, rat: m.reasoning.length, state: "writing"}; m.tools.push(t); }
  if (x.event === "call") {
    Object.assign(t, {name: x.name, server: x.server, tool: x.tool, arguments: x.arguments, round: x.round, state: "running"});
  } else if (x.event === "result") {
    Object.assign(t, {result: x.text, ok: x.ok, chars: x.chars, truncated: x.truncated, ms: x.ms,
                      state: x.skipped ? "skipped" : x.ok ? "done" : "error"});
  }
}
function updateAssistant(el, m, streaming) {
  const det = el.querySelector("details.think");
  if (m.reasoning) {
    det.hidden = false;
    const thinkingNow = streaming && !m.text;
    el.querySelector(".think-title").textContent = thinkingNow ? "Thinking…" :
      m.thinkSecs != null ? `Thought for ${fmt(m.thinkSecs, 1)} s` : "Thoughts";
    const body = el.querySelector(".thinking");
    if (det.open || thinkingNow) body.textContent = m.reasoning;
    else body.dataset.pending = "1";
    // open while it streams (if wanted), closed once the answer starts - unless the user toggled it themselves
    if (thinkingNow && settings.show && !det.dataset.touched && !det.open) { det._auto = true; det.open = true; }
    if (!thinkingNow && det.open && !det.dataset.touched) { det._auto = true; det.open = false; }
  }
  const bubble = el.querySelector(".st-bubble");
  if (m.error) {
    bubble.innerHTML = `<div class="msg-error"></div>`;
    bubble.firstChild.textContent = m.error;
  } else if (!m.text && streaming && !(m.tools && m.tools.length)) {
    bubble.innerHTML = m.reasoning ? `<span class="muted cursor">Writing</span>` : `<span class="cursor"></span>`;
  } else {
    bubble.innerHTML = answerHtml(m);
    if (streaming) bubble.classList.add("cursor"); else bubble.classList.remove("cursor");
  }
  el.querySelector(".meta-text").textContent = m.meta || (streaming ? "" : m.stopped ? "Stopped" : "");
  el.querySelector("[data-msg-copy]").hidden = streaming || !m.text;
}
function renderChat() {
  const chat = $("chat");
  chat.querySelectorAll(".st-msg").forEach((e) => e.remove());
  $("chat-empty").hidden = messages.length > 0;
  messages.forEach((m, i) => chat.appendChild(msgEl(m, i)));
  scrollDown(true);
}
function nearBottom() { const s = $("chat-scroll"); return s.scrollHeight - s.scrollTop - s.clientHeight < 120; }
function scrollDown(force) { const s = $("chat-scroll"); if (force || nearBottom()) s.scrollTop = s.scrollHeight; }

$("chat").addEventListener("click", (e) => {
  const cc = e.target.closest("[data-code-copy]");
  if (cc) { copyText(cc.closest(".st-code").querySelector("pre").textContent, cc); return; }
  const mc = e.target.closest("[data-msg-copy]");
  if (mc) { const i = +mc.closest(".st-msg").dataset.i; copyText(messages[i].text, mc); return; }
  // a tool block: its open state lives in the message (the answer is rebuilt while it streams), so the click sets it
  const sum = e.target.closest(".tool-call > summary");
  if (sum) {
    e.preventDefault();
    const el = sum.closest(".st-msg"), m = messages[+el.dataset.i], t = m && m.tools && m.tools[+sum.parentElement.dataset.tool];
    if (!t) return;
    t.open = !t.open;
    updateAssistant(el, m, !!busy && busy.msg === m);
  }
});
$("chat").addEventListener("toggle", (e) => {
  const d = e.target;
  if (d.tagName !== "DETAILS" || !d.classList.contains("think")) return;
  if (d._auto) { d._auto = false; return; }          // our own open/close, not the user's
  d.dataset.touched = "1";
  const body = d.querySelector(".thinking");
  if (d.open && body.dataset.pending) { body.textContent = messages[+d.closest(".st-msg").dataset.i].reasoning; delete body.dataset.pending; }
}, true);

function apiMessages() {
  const out = [];
  for (const m of messages) {
    if (m.role === "user") {
      const imgs = (m.images || []).filter((i) => i.url);
      const text = userText(m);
      out.push({role: "user", content: imgs.length ? [{type: "text", text},
        ...imgs.map((i) => ({type: "image_url", image_url: {url: i.url}}))] : text});
    } else if (!m.error) {
      out.push(...assistantMessages(m));
    }
  }
  return out;
}
// An answer that used MCP tools goes back as the model wrote it: per round the text before the calls, the calls and
// their results (as the model read them), then the rest - so the next question can build on what the tools found.
function assistantMessages(m) {
  const ran = (m.tools || []).filter((t) => t.round != null && t.result != null && t.state !== "skipped");
  if (!ran.length) return m.text ? [{role: "assistant", content: m.text}] : [];
  const out = [];
  let pos = 0;
  for (const r of [...new Set(ran.map((t) => t.round))]) {
    const calls = ran.filter((t) => t.round === r);
    const at = Math.min(Math.max(pos, calls[0].at || 0), m.text.length);
    out.push({role: "assistant", content: m.text.slice(pos, at).trim(),
              tool_calls: calls.map((t) => ({id: t.id, type: "function", function: {name: t.name, arguments: JSON.stringify(t.arguments || {})}}))});
    for (const t of calls) out.push({role: "tool", tool_call_id: t.id, content: t.result});
    pos = at;
  }
  const rest = m.text.slice(pos).trim();
  if (rest) out.push({role: "assistant", content: rest});
  return out;
}

function setBusy(on) {
  $("stop-btn").hidden = !on;
  $("send-btn").disabled = on;
  $("composer-hint").textContent = on ? "" : "Maiusc+Invio: nuova riga";
}

async function send() {
  const text = $("input").value.trim();
  if ((!text && !attachments.length) || busy) return;
  messages.push({role: "user", text, images: attachments.filter((a) => a.kind !== "file"),
                 files: attachments.filter((a) => a.kind === "file"), time: Date.now()});
  attachments = [];
  renderAttachments();
  $("input").value = "";
  autosize();
  const m = {role: "assistant", text: "", reasoning: "", time: Date.now()};
  messages.push(m);
  renderChat();
  const el = $("chat").lastElementChild;
  const controller = new AbortController();
  busy = {controller, msg: m};
  setBusy(true);

  const body = {model: health.model, messages: apiMessages(), stream: true,
                reasoning_effort: settings.thinking};
  if (settings.temperature > 0) {
    Object.assign(body, {temperature: +settings.temperature, top_p: +settings.top_p, top_k: +settings.top_k});
  } else {
    body.temperature = 0;
  }
  if (settings.seed) body.seed = +settings.seed;
  if (settings.max) body.max_tokens = +settings.max;
  if (projectionLoaded()) body.experimental_speed_projection = !!settings.esp;
  if (settings.mcp !== false && mcpInfo.tools > 0) body.strata_mcp = true;   // this server may run MCP tools for it

  let firstAt = null, thinkStart = null, usage = null, frame = 0;
  const paint = () => { frame = 0; updateAssistant(el, m, true); scrollDown(); };
  try {
    const r = await fetch("v1/chat/completions", {method: "POST", headers: headers(true), body: JSON.stringify(body),
                                                   signal: controller.signal});
    if (!r.ok) {
      let msg = `HTTP ${r.status}`;
      try { msg = (await r.json()).error.message || msg; } catch (e) { /* not json */ }
      if (r.status === 401) msg = "This server needs an API key: add it under About > Settings.";
      throw new Error(msg);
    }
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line.startsWith("data:")) continue;              // ": keep-alive" comments while a long prompt is read
        const data = line.slice(5).trim();
        if (data === "[DONE]") continue;
        let j;
        try { j = JSON.parse(data); } catch (e) { continue; }
        if (j.error) throw new Error(j.error.message || "the engine reported an error");
        if (j.usage) usage = j.usage;
        if (j.strata_mcp) onTool(m, j.strata_mcp);
        const d = (j.choices && j.choices[0] && j.choices[0].delta) || {};
        const lastTool = m.tools && m.tools.length ? m.tools[m.tools.length - 1] : null;   // a new round after a tool
        if (d.reasoning_content) {
          if (!firstAt) firstAt = performance.now();
          if (!thinkStart) thinkStart = performance.now();
          if (lastTool && m.reasoning && lastTool.rat === m.reasoning.length) m.reasoning += "\n\n";
          m.reasoning += d.reasoning_content;
        }
        if (d.content) {
          if (!firstAt) firstAt = performance.now();
          if (thinkStart && m.thinkSecs == null) m.thinkSecs = (performance.now() - thinkStart) / 1000;
          if (lastTool && m.text && lastTool.at === m.text.length) m.text += "\n\n";
          m.text += d.content;
        }
        if (!frame) frame = requestAnimationFrame(paint);
      }
    }
  } catch (e) {
    if (e.name === "AbortError") m.stopped = true;
    else { m.error = e.message || String(e); toast("error", "The request failed", m.error, 6000); }
  }
  if (thinkStart && m.thinkSecs == null) m.thinkSecs = (performance.now() - thinkStart) / 1000;
  const n = usage ? usage.completion_tokens : null;
  if (n && firstAt) {
    const secs = (performance.now() - firstAt) / 1000;
    m.meta = `${fmt(n)} tokens${secs > 0.25 ? ` · ${fmt(n / secs, 1)} tok/s` : ""}${m.stopped ? " · stopped" : ""}` +
             (projectionLoaded() ? (settings.esp ? " · projection on" : " · projection off") : "");
  } else if (m.stopped) {
    m.meta = "Stopped";
  }
  for (const t of m.tools || []) if (t.state === "writing" || t.state === "running") { t.state = "skipped"; t.ms = null; }
  const ran = (m.tools || []).filter((t) => t.state === "done" || t.state === "error").length;
  if (ran) m.meta = `${m.meta ? `${m.meta} · ` : ""}${ran} tool call${ran > 1 ? "s" : ""}`;
  if (m.limit) m.meta = `${m.meta || ""} · stopped at the limit of ${m.limit} tool rounds (mcp.max_rounds)`;
  busy = null;
  setBusy(false);
  if (frame) cancelAnimationFrame(frame);
  updateAssistant(el, m, false);
  saveChat();
  scrollDown();
}

$("composer").onsubmit = (e) => { e.preventDefault(); send(); };
$("stop-btn").onclick = () => { if (busy) busy.controller.abort(); };
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
});
function autosize() { const t = $("input"); t.style.height = "auto"; t.style.height = `${Math.min(t.scrollHeight, innerHeight * 0.4)}px`; }
$("input").addEventListener("input", autosize);

$("new-btn").onclick = () => {
  if (busy) { toast("warn", "Still writing", "Stop the answer first."); return; }
  if (!messages.length) return;
  const backup = messages;
  messages = [];
  saveChat();
  renderChat();
  toast("info", "New chat", "The last one was cleared.", 6000, {label: "Undo", run: () => { messages = backup; saveChat(); renderChat(); }});
};
$("export-btn").onclick = () => {
  if (!messages.length) { toast("info", "Nothing to save yet"); return; }
  const tools = (m) => (m.tools || []).filter((t) => t.result != null).map((t) =>
    `<details><summary>Tool ${t.server ? `${t.server} / ` : ""}${t.tool || t.name}${t.ok ? "" : " (error)"}</summary>\n\n` +
    `\`\`\`json\n${JSON.stringify(t.arguments || {}, null, 2)}\n\`\`\`\n\n\`\`\`\n${t.result}\n\`\`\`\n\n</details>\n\n`).join("");
  const md = messages.map((m) => m.role === "user" ? `## You\n\n${m.text}\n` :
    `## ${health.model}\n\n${m.reasoning ? `<details><summary>Thinking</summary>\n\n${m.reasoning}\n\n</details>\n\n` : ""}${tools(m)}${m.text || m.error || ""}\n`).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([md], {type: "text/markdown"}));
  a.download = `strata-chat-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}.md`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
};

// pictures and text files: the attach button, dropping them on the chat, or pasting a picture (issue #30)
const TEXT_EXT = /\.(txt|md|markdown|rst|tex|py|pyi|ipynb|js|mjs|cjs|ts|tsx|jsx|vue|svelte|json|jsonl|csv|tsv|log|ya?ml|toml|ini|cfg|conf|env|xml|html?|css|scss|less|c|cc|cpp|cxx|h|hh|hpp|cu|cuh|rs|go|java|kt|kts|swift|rb|php|pl|lua|r|jl|scala|sql|sh|bash|zsh|fish|ps1|psm1|bat|cmd|diff|patch|gradle|cmake|mk|dockerfile|gitignore|proto|graphql)$/i;
const MAX_TEXT_FILE = 512 * 1024;
function isTextFile(f) {
  return f.type.startsWith("text/") || /json|xml|javascript|yaml|toml|x-sh|x-python/.test(f.type) ||
         TEXT_EXT.test(f.name) || /(^|[\\/])(makefile|dockerfile|readme|license)$/i.test(f.name);
}
function addFiles(files) {
  for (const f of files) {
    if (f.type.startsWith("image/")) {
      if (!health.images) { toast("warn", "Pictures are off", "This model was set up for text only."); continue; }
      if (f.size > 20e6) { toast("warn", "Picture too large", `${f.name} is over 20 MB.`); continue; }
      const r = new FileReader();
      r.onload = () => { attachments.push({kind: "image", name: f.name || "pasted image", url: r.result}); renderAttachments(); };
      r.readAsDataURL(f);
      continue;
    }
    if (!isTextFile(f)) { toast("warn", "Not a text file", `${f.name}: attach text files (code, notes, logs, data)${health.images ? " or pictures" : ""}.`); continue; }
    if (f.size > MAX_TEXT_FILE) { toast("warn", "File too large", `${f.name} is over 512 KB.`); continue; }
    const r = new FileReader();
    r.onload = () => {
      const text = String(r.result);
      if (text.includes("\u0000")) { toast("warn", "Not a text file", `${f.name} looks like a binary file.`); return; }
      attachments.push({kind: "file", name: f.name, text});
      renderAttachments();
    };
    r.readAsText(f);
  }
}
// a file's text in the message, fenced with more backticks than it contains itself
function fileBlock(f) {
  const longest = Math.max(2, ...(f.text.match(/`+/g) || []).map((s) => s.length));
  const fence = "`".repeat(longest + 1);
  return `File: ${f.name}\n${fence}\n${f.text}\n${fence}`;
}
function userText(m) {
  const files = (m.files || []).filter((f) => f.text != null);
  return [m.text, ...files.map(fileBlock)].filter((s) => s).join("\n\n");
}
function renderAttachments() {
  const box = $("attachments");
  box.hidden = !attachments.length;
  box.innerHTML = "";
  attachments.forEach((a, i) => {
    const c = document.createElement("span");
    c.className = "chip";
    c.innerHTML = icon(a.kind === "file" ? "attach" : "image", "st-icon st-icon--sm");
    c.append(a.name);
    const x = document.createElement("button");
    x.type = "button"; x.className = "st-btn st-btn--icon"; x.setAttribute("aria-label", "Remove");
    x.innerHTML = icon("trash");
    x.onclick = () => { attachments.splice(i, 1); renderAttachments(); };
    c.appendChild(x);
    box.appendChild(c);
  });
}
$("attach-btn").onclick = () => $("file").click();
// drop files on the chat or the message box
for (const id of ["chat", "composer"]) {
  const el = $(id);
  el.addEventListener("dragover", (e) => {
    if (![...(e.dataTransfer || {}).types || []].includes("Files")) return;
    e.preventDefault();
    $("composer").classList.add("dragging");
  });
  el.addEventListener("dragleave", () => $("composer").classList.remove("dragging"));
  el.addEventListener("drop", (e) => {
    $("composer").classList.remove("dragging");
    if (!e.dataTransfer || !e.dataTransfer.files.length) return;
    e.preventDefault();
    addFiles(e.dataTransfer.files);
    $("input").focus();
  });
}
$("file").onchange = () => { addFiles($("file").files); $("file").value = ""; };
$("input").addEventListener("paste", (e) => {
  if (!health.images) return;
  const files = [...(e.clipboardData || {}).files || []].filter((f) => f.type.startsWith("image/"));
  if (files.length) { e.preventDefault(); addFiles(files); }
});

// ------------------------------------------------------------------ the sampling drawer
function openDrawer(open) {
  $("drawer").inert = !open;
  $("drawer").dataset.open = String(open);
  $("drawer").setAttribute("aria-hidden", String(!open));
  $("scrim").hidden = !open;
  if (open) { loadDrawer(); loadShared(); loadMcp(); $("drawer-close").focus(); }
  else $("sampling-btn").focus();
}
function loadDrawer(s = settings) {
  for (const b of $("s-thinking").children) b.setAttribute("aria-checked", String(b.dataset.v === s.thinking));
  $("s-temp").value = s.temperature; $("s-topp").value = s.top_p; $("s-topk").value = s.top_k;
  $("s-max").value = s.max; $("s-seed").value = s.seed;
  $("s-show").setAttribute("aria-checked", String(!!s.show));
  $("s-esp").setAttribute("aria-checked", String(s.esp !== false));
  $("esp-row").hidden = !projectionLoaded();
  $("s-mcp").setAttribute("aria-checked", String(s.mcp !== false));
  $("s-share").setAttribute("aria-checked", String(sharedOn));
  outputs();
}
// "Use for other apps too": the server keeps these settings as every client's defaults (GET/POST /settings)
let sharedOn = false;
async function loadShared() {
  try {
    const r = await fetch("settings", {headers: headers()});
    if (r.ok) sharedOn = !!(await r.json()).shared;
  } catch (e) { /* an older server: the switch just stays off */ }
  $("s-share").setAttribute("aria-checked", String(sharedOn));
}
function sharedDefaults(s) {
  const d = {reasoning_effort: s.thinking, temperature: +s.temperature};
  if (+s.temperature > 0) Object.assign(d, {top_p: +s.top_p, top_k: +s.top_k});
  if (s.seed) d.seed = +s.seed;
  if (s.max) d.max_tokens = +s.max;
  if (projectionLoaded()) d.experimental_speed_projection = s.esp !== false;
  return d;
}
async function saveShared(on, s) {
  const r = await fetch("settings", {method: "POST", headers: headers(true),
                                      body: JSON.stringify({defaults: on ? sharedDefaults(s) : null})});
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { msg = (await r.json()).error.message || msg; } catch (e) { /* not json */ }
    throw new Error(msg);
  }
  sharedOn = !!(await r.json()).shared;
}
// the engine was started with the experimental-speed-projection control vector (INFO cvec=...)
function projectionLoaded() {
  const c = lastMetrics && lastMetrics.engine ? lastMetrics.engine.cvec : 0;
  return !!c && c !== "0";
}
function outputs() {
  const t = +$("s-temp").value;
  $("o-temp").textContent = t === 0 ? "0 · greedy" : t.toFixed(2);
  $("o-topp").textContent = (+$("s-topp").value).toFixed(2);
  $("o-topk").textContent = $("s-topk").value;
  const sel = [...$("s-thinking").children].find((b) => b.getAttribute("aria-checked") === "true");
  $("o-thinking").textContent = sel ? {none: "answers right away", low: "short", medium: "medium", high: "thorough (default)"}[sel.dataset.v] : "";
  for (const id of ["s-topp", "s-topk"]) $(id).disabled = t === 0;
}
for (const b of $("s-thinking").children) b.onclick = () => { for (const x of $("s-thinking").children) x.setAttribute("aria-checked", String(x === b)); outputs(); };
for (const id of ["s-temp", "s-topp", "s-topk"]) $(id).oninput = outputs;
$("s-show").onclick = () => $("s-show").setAttribute("aria-checked", String($("s-show").getAttribute("aria-checked") !== "true"));
$("s-esp").onclick = () => $("s-esp").setAttribute("aria-checked", String($("s-esp").getAttribute("aria-checked") !== "true"));
$("s-mcp").onclick = () => $("s-mcp").setAttribute("aria-checked", String($("s-mcp").getAttribute("aria-checked") !== "true"));
$("s-share").onclick = () => $("s-share").setAttribute("aria-checked", String($("s-share").getAttribute("aria-checked") !== "true"));
$("s-reset").onclick = () => loadDrawer(DEFAULTS);
$("s-apply").onclick = async () => {
  const sel = [...$("s-thinking").children].find((b) => b.getAttribute("aria-checked") === "true");
  settings = {thinking: sel ? sel.dataset.v : "high", temperature: +$("s-temp").value, top_p: +$("s-topp").value,
              top_k: +$("s-topk").value, max: $("s-max").value.trim(), seed: $("s-seed").value.trim(),
              show: $("s-show").getAttribute("aria-checked") === "true",
              esp: $("s-esp").getAttribute("aria-checked") === "true",
              mcp: $("s-mcp").getAttribute("aria-checked") === "true"};
  store.set("sampling", settings);
  const share = $("s-share").getAttribute("aria-checked") === "true";
  openDrawer(false);
  if (share || sharedOn) {
    try {
      await saveShared(share, settings);
      toast("success", "Sampling saved", share ? "Other apps (omp, API clients) use these settings from their next request."
                                               : "Other apps use their own settings again.");
    } catch (e) {
      toast("error", "Saved here, but not for other apps", e.message, 6000);
    }
    return;
  }
  toast("success", "Sampling saved", settings.temperature === 0 ? "Greedy: the same question gives the same answer." : "");
};
$("sampling-btn").onclick = () => openDrawer(true);
$("drawer-close").onclick = () => openDrawer(false);
$("scrim").onclick = () => openDrawer(false);
document.addEventListener("keydown", (e) => {
  const drawer = $("drawer");
  if (drawer.dataset.open !== "true") return;
  if (e.key === "Escape") { openDrawer(false); return; }
  if (e.key !== "Tab") return;
  const controls = [...drawer.querySelectorAll('button,input,select,textarea,a[href],[tabindex="0"]')]
    .filter(el => !el.disabled && el.getClientRects().length);
  const first = controls[0], last = controls[controls.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
});

// ------------------------------------------------------------------ Control tab
let ctrlState = {loaded: false, model: "", power: {}, config: {}, vision: false};
// the images button reflects the server, never a local guess: /health reports `images`
async function refreshVisionState() {
  const b = $("ctrl-vision");
  if (!b) return;
  try {
    const h = await (await fetch("health")).json();
    ctrlState.vision = !!h.images;
    b.textContent = h.images ? "Immagini: on" : "Immagini: off";
    b.dataset.on = h.images ? "1" : "0";
    b.title = h.images ? "Legge le immagini (l'encoder usa RAM o VRAM)" : "Attiva per far leggere le immagini al modello";
  } catch (e) { /* the server may be restarting: leave the last state */ }
}

// Requirements as the project documents them, not estimates of my own:
//   docs/DETAILS.md "Which model?"   -> Download column
//   docs/MODELS.md  "The sizes"      -> RAM+VRAM Requirements column
// "—" means the project publishes no figure for that variant: it stays blank rather than invented.
// the model card's three tiles, filled from ONE place: the requirements documented in
// docs/DETAILS.md + docs/MODELS.md, and the RAM/VRAM this PC actually has
function fillModelTiles(info) {
  const hw = (lastMetrics && lastMetrics.hardware) || {};
  ctrlText("ctrl-dl-size", (info && info.dl) || "—");
  ctrlText("ctrl-ram-req", (info && info.need) || "—");
  ctrlText("ctrl-vram-req", (hw.ram_total ? gb(hw.ram_total, 0) : "—") + " + "
                            + (hw.gpu_mem_total ? gb(hw.gpu_mem_total, 0) : "—") + " GB");
}

const MODEL_INFO = {
  Q2_0:        {dl: "66,4 GB", need: "48 GB (arena 34,0)"},
  IQ2_XS:      {dl: "68,0 GB", need: "48 GB (arena 35,5)"},
  IQ3_XXS:     {dl: "75,8 GB", need: "60 GB (arena 42,9)"},
  IQ3_S:       {dl: "83,6 GB", need: "62 GB (arena 50,3)"},
  IQ1_M:       {dl: "58,4 GB", need: "32 GB (arena 23,4)"},
  UD_Q4_K_XL:  {dl: "111,3 GB", need: "48 GB (arena 77,0)"},
  "UD-Q4_K_XL":{dl: "111,3 GB", need: "48 GB (arena 77,0)"},
};
const ctxOf = (m) => (m && m.engine && m.engine.max_context) || 0;
function ctrlText(id, value) { const el = $(id); if (el && el.textContent !== String(value)) el.textContent = value; }

// what the Control tab shows while it is open: live numbers straight from /metrics
function renderControlLive() {
  const m = lastMetrics;
  if (!m || tab !== "control") return;
  const hw = m.hardware || {}, live = m.live || {}, pm = m.power || {};
  ctrlState.loaded = live.state !== "unloaded";
  ctrlText("ctrl-status", ctrlState.loaded ? "Caricato" : "Scaricato");
  ctrlText("ctrl-stat-state", ({idle:"Pronto",unloaded:"Scaricato",reading:"Lettura",generating:"Generazione"})[live.state] || "—");
  ctrlText("ctrl-stat-vram", hw.gpu_mem_used != null ? `${gb(hw.gpu_mem_used, 1)} GB` : "—");
  const spd = live.state === "generating" ? live.tok_s : null;
  ctrlText("ctrl-stat-speed", spd != null ? `${fmt(spd, 1)} t/s` : "—");
  ctrlText("ctrl-pm-mode-view", pm.mode || "—");
  const effHistC = ((m.history && m.history.eff) || []).filter((v) => v > 0);
  ctrlText("ctrl-pm-eff", pm.efficiency > 0 ? fmt(pm.efficiency, 2)
          : m.efficiency_sample?.value > 0 ? fmt(m.efficiency_sample.value, 2) : effHistC.length ? fmt(effHistC[effHistC.length - 1], 2) : "in attesa di una richiesta");
  ctrlText("ctrl-pm-temp", hw.gpu_temp != null ? `${fmt(hw.gpu_temp)}°C` : "—");
  ctrlText("ctrl-pm-power", hw.gpu_power != null ? `${fmt(hw.gpu_power)} W` : "—");
  // trend of the last samples: a power manager without the trend cannot show when a throttle bit
  // a 0 in these series is a missing sample, not a reading: it would flatten the whole trend
  const histT = ((m.history && m.history.gpu_temp) || []).filter((v) => v != null && v > 10);
  const histP = ((m.history && m.history.gpu_power) || []).filter((v) => v != null && v > 5);
  // scale of the trend = the limit, not the observed band: the graph then shows the headroom
  // (a 33-34 °C band drawn on its own range would sit flat against the top edge and read as broken)
  spark("ct-temp-spark", histT, pm.temp_limit || 80);
  spark("ct-pow-spark", histP, pm.power_limit || 250);
  ctrlText("ctrl-trend-temp", histT.length ? `${fmt(Math.min(...histT))}–${fmt(Math.max(...histT))} °C` : "—");
  ctrlText("ctrl-trend-power", histP.length ? `${Math.round(Math.min(...histP))}–${Math.round(Math.max(...histP))} W` : "—");
  ctrlText("ms-ctrl-power-state",
    `avviso ${pm.throttling ? "ATTIVO" + (pm.throttle_reason ? ` (${pm.throttle_reason})` : "") : "assente"}`
    + ` · cooldown ${fmt(pm.cooldown_s || 0, 0)} s · limiti ${fmt(pm.temp_limit || 0, 0)} °C / ${fmt(pm.power_limit || 0, 0)} W`);
  const s2 = [];
  if (hw.gpu_temp_hotspot != null) s2.push(`hotspot ${hw.gpu_temp_hotspot} °C`);
  if (hw.gpu_vram_temp != null) s2.push(`memorie ${hw.gpu_vram_temp} °C`);
  if (hw.gpu_fan_rpm != null) s2.push(`ventola ${Math.round(hw.gpu_fan_rpm)} rpm`);
  if (hw.gpu_volt != null) s2.push(`${hw.gpu_volt.toFixed(2)} V`);
  ctrlText("ms-ctrl-power-sensors", s2.length ? s2.join(" · ") : "—");
  // one line exactly: this note shares the row with the Avvio card's, and a wrapped note would
  // make the two cards of the row differ by the height of the extra line
  ctrlText("ms-ctrl-model-info", "Scaricato in Hydra One-data · il motore si riconfigura da solo");
  const tlim = +($("ctrl-temp-limit") ? $("ctrl-temp-limit").value : 80);
  const plim = +($("ctrl-power-limit") ? $("ctrl-power-limit").value : 250);
  ctrlText("ms-ctrl-temp", hw.gpu_temp != null ? `${fmt(hw.gpu_temp)}°C ora · ${fmt(tlim - hw.gpu_temp)}° di margine su ${tlim}°C` : "in attesa della telemetria");
  ctrlText("ms-ctrl-power", hw.gpu_power != null ? `${fmt(hw.gpu_power)} W ora · ${fmt(plim - hw.gpu_power)} W di margine su ${plim} W` : "in attesa della telemetria");
  ctrlText("ctrl-power-status", pm.mode || "");
  // the model card keeps its sizes current even if the panel was opened before a reload
  const selM = $("ctrl-model"), infoM = selM ? (MODEL_INFO[selM.value] || {}) : {};
  if (selM) fillModelTiles(infoM);
  // the resource sliders answer with the machine's own numbers, refreshed every poll
  const cfg = ctrlState.config || {};
  const ctxCfg = cfg.max_context || (m.engine && m.engine.max_context) || 0;
  const usedC = live.state && live.state !== "idle" ? (live.prompt_tokens || 0) + (live.generated || 0) : 0;
  ctrlText("ms-ctrl-vram", hw.gpu_mem_total
    ? `${gb(hw.gpu_mem_used, 1)} / ${gb(hw.gpu_mem_total, 0)} GB usati ora · riserva ${cfg.vram_reserve_mib ?? 0} MiB al desktop`
    : "in attesa della telemetria");
  ctrlText("ms-ctrl-kv", ctxCfg
    ? `al contesto attuale la KV in RAM pesa ~${(ctxCfg * 13.7 / 1048576).toFixed(2)} GB (13,7 KB per token)`
    : "in attesa della configurazione");
  ctrlText("ms-ctrl-ctx", ctxCfg
    ? `finestra: ${usedC.toLocaleString()} / ${ctxCfg.toLocaleString()} token usati (${Math.round((100 * usedC) / ctxCfg)}%)`
    : "in attesa della configurazione");
  const note = $("ctrl-pm-note");
  if (note) { note.hidden = !pm.throttling; if (pm.throttling) note.textContent = `Avviso: ${pm.throttle_reason} · valido per ${pm.cooldown_s}s · nessun intervento sul driver`; }
}

// Il menu deve far vedere quali modelli sono GIA' SUL DISCO (configurazione + pack presenti),
// distinguendoli da quelli ancora da scaricare. Vive a livello alto perche' la chiama loadControl().
function aggiornaMenuModelli(config, corrente) {
  const sel = document.getElementById("ctrl-model");
  if (!sel) return;
  const pronti = Array.isArray(config && config.prepared) ? config.prepared : [];
  const chiaveDi = (v) => String(v || "").toLowerCase().replace(/-/g, "_");
  const sulDisco = [];
  for (const o of [...sel.options]) {
    const p = pronti.find((x) => chiaveDi(x.key) === chiaveDi(o.value));
    const base = o.textContent.replace(/ · (sul disco|da scaricare|pack incompleto)$/, "");
    if (p && p.ready) { o.textContent = base + " · sul disco"; sulDisco.push(o.value); }
    else if (p) { o.textContent = base + " · pack incompleto"; }
    else { o.textContent = base + " · da scaricare"; }
  }
  const c = chiaveDi(corrente);
  if (c) for (const o of sel.options) if (c.includes(chiaveDi(o.value))) { sel.value = o.value; break; }
  const info = document.getElementById("ms-ctrl-model-info");
  if (info) {
    const inUso = (corrente || "").replace("qwen3.8-flash-next-", "") || "—";
    info.textContent = "Sul disco: " + (sulDisco.join(", ") || "nessuno")
                     + "  ·  in servizio: " + inUso;
  }
}

// ---------------------------------------------------------------------------------------------
// Catalogo dei modelli compatibili (HuggingFace).  Tutto a livello alto: la pagina ha gia' pagato
// una volta l'errore di definire una funzione dentro un blocco e chiamarla fuori.
// ---------------------------------------------------------------------------------------------
function catChiave(v) { return String(v || "").toLowerCase().replace(/[^a-z0-9_]/g, "_"); }

async function catPost(via, corpo) {
  const r = await fetch(via, {method: "POST", headers: headers(true), body: JSON.stringify(corpo)});
  const v = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(v.error ? v.error.message : ("HTTP " + r.status));
  return v;
}

function catStato(testo, tipo) {
  const el = document.getElementById("cat-state");
  if (el) { el.textContent = testo; el.style.color = tipo === "err" ? "var(--danger, #e5484d)" : ""; }
}

async function catCerca() {
  const q = (document.getElementById("cat-query") || {}).value || "Qwen3.8-Flash-Next";
  catStato("Cerco su HuggingFace…");
  try {
    const d = await catPost("catalogue-search", {query: q});
    const box = document.getElementById("cat-results");
    if (!box) return;
    if (!d.results.length) { box.innerHTML = "<div class='dm__sub'>Nessun risultato.</div>"; catStato("Nessun repository trovato."); return; }
    box.innerHTML = d.results.map((x) =>
      "<div style='display:flex;gap:8px;align-items:center;justify-content:space-between;padding:4px 0'>" +
      "<span class='dm__sub' style='overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>" + x.repo +
      " <span style='opacity:.6'>(" + (x.downloads || 0).toLocaleString("it-IT") + " download)</span></span>" +
      "<button class='st-btn st-btn--secondary' data-cat-probe=\"" + x.repo + "\">Verifica</button></div>").join("");
    catStato("Trovati " + d.results.length + " repository. 'Verifica' legge l'intestazione del primo GGUF (un secondo, nessuno scaricamento).");
  } catch (e) { catStato("Ricerca fallita: " + e.message, "err"); }
}

async function catVerifica(repo) {
  catStato("Leggo l'intestazione di " + repo + "…");
  try {
    const d = await catPost("catalogue-inspect", {repo: repo});
    if (d.error) { catStato(repo + ": " + d.error, "err"); return; }
    const box = document.getElementById("cat-results");
    const riga = document.createElement("div");
    riga.className = "dm__sub";
    riga.style.cssText = "padding:6px 0;border-top:1px solid var(--border)";
    const ok = d.compatible;
    const sp = d.space || {};
    const ciSta = ok && (sp.ok !== false);
    riga.innerHTML = "<b>" + repo + "</b> · " + (d.dir || "?") + " — architettura <b>" + (d.architecture || "?") +
      "</b>, " + (d.experts || "?") + " esperti, " + (d.layers || "?") + " layer, " + (d.download_gib || "?") + " GiB" +
      (sp.needed_gib ? (" · servono " + sp.needed_gib + " GB, liberi " + sp.free_gib + " GB") : "") +
      (ok ? "" : " <span style='color:var(--danger,#e5484d)'>NON compatibile: il motore legge solo qwen4exp</span>") +
      (!ok ? "" : (!ciSta ? " <span style='color:var(--danger,#e5484d)'>spazio insufficiente: libera spazio o sposta Hydra One-data</span>"
                          : " <button class='st-btn st-btn--primary' data-cat-fetch=\"" + repo + "|" + (d.dir || "") + "\">Scarica e prepara</button>"));
    if (!ok) { catStato(repo + ": non compatibile (architettura " + (d.architecture || "?") + "), non lo mostro.", "err"); return; }
    if (!ciSta) { catStato(repo + ": compatibile ma non ci sta qui — servono ~" + sp.needed_gib + " GB e ne restano " + sp.free_gib + ".", "err"); return; }
    if (box) box.appendChild(riga);
    catStato(repo + " è compatibile: " + d.download_gib + " GiB da scaricare, poi il pack e la configurazione.");
  } catch (e) { catStato("Verifica fallita: " + e.message, "err"); }
}

async function catScarica(repo, quant) {
  catStato("Avvio lo scaricamento di " + repo + " " + quant + "…");
  try {
    const mtp = !!(document.getElementById("cat-mtp") || {}).checked;
    const d = await catPost("catalogue-fetch", {repo: repo, quant: quant, mtp: mtp});
    catStato("Scaricamento avviato (" + d.quant + "). È lungo: lo stato si aggiorna qui sotto.");
    catSegui();
  } catch (e) { catStato("Non posso iniziare: " + e.message, "err"); }
}

let catTimer = null;
async function catSegui() {
  if (catTimer) clearTimeout(catTimer);
  try {
    const c = await fetch("catalogue", {headers: headers()}).then((r) => r.json());
    const j = c.job || {};
    const dsk = c.disk || {};
    const hs = c.host || {};
    const elD = document.getElementById("cat-disk");
    if (elD) elD.textContent = "Questa macchina: RAM " + (hs.ram_total_gib || "?") + " GB (liberi " +
      (hs.ram_free_gib || "?") + ") · VRAM " + (hs.vram_total_gib || "?") + " GB · disco libero " +
      (dsk.free_gib || "?") + " GB";
    catElencoUfficiale(c.official || []);
    if (j.state) {
      const min = j.started ? Math.round((Date.now() / 1000) - j.started) : 0;
      catStato("Lavoro in corso: " + j.state + " (fase " + (j.step || "?") + "/3, " + min + "s) · " + (j.repo || "") + " " + (j.quant || "") +
               (j.error ? " · ERRORE: " + j.error : ""));
      if (j.state === "running" || j.state === "downloading" || j.state === "packing" || j.state === "registering" || j.state === "starting") {
        catTimer = setTimeout(catSegui, 5000);
      } else if (j.state === "done") {
        catStato("Fatto: configurazione " + (j.config || "") + ". Ricarico l'elenco dei modelli…");
        setTimeout(() => loadControl(), 1500);
      }
    }
  } catch (e) { /* il server può essere occupato */ }
}

// la delega: un solo ascoltatore per tutti i pulsanti che il catalogo crea
document.addEventListener("click", (e) => {
  const b = e.target && e.target.closest ? e.target.closest("[data-cat-probe],[data-cat-fetch],[id=cat-search]") : null;
  if (!b) return;
  if (b.id === "cat-search") { catCerca(); return; }
  if (b.dataset.catProbe) { catVerifica(b.dataset.catProbe); return; }
  if (b.dataset.catFetch) {
    const [repo, quant] = b.dataset.catFetch.split("|");
    catScarica(repo, quant);
    return;
  }
  if (b.dataset.catUsa) { catUsa(b.dataset.catUsa); }
});

function catEtichetta(livello) {
  const m = {piena: ["eseguibile", "var(--success,#30a46c)"], disco: ["eseguibile dal disco (lento)", "#d97706"],
             no: ["non eseguibile qui", "var(--danger,#e5484d)"], "?": ["da valutare", "var(--muted-foreground)"]};
  const e = m[livello] || m["?"];
  return "<span style='color:" + e[1] + ";font-weight:600'>" + e[0] + "</span>";
}

function catEseguibile(fit) {
  // 'piena' e 'disco' girano su questa macchina; 'no' e '?' no: e quelli NON si mostrano.
  return !!fit && (fit.level === "piena" || fit.level === "disco");
}

// Cosa dice il progetto di ogni quantizzazione (docs/MODELS.md + setup.py): velocità e qualità.
const CAT_NOTE = {
  Q2_0: "il più veloce · qualità buona",
  IQ2_XS: "veloce · qualità migliore (consigliato)",
  IQ3_XXS: "bilanciato · 3 bit",
  IQ3_S: "il più preciso, come il modello intero",
  IQ1_M: "Coder: metà esperti (codice, strumenti, immagini)",
  UD_IQ1_S: "Unsloth Dynamic, 1-2 bit", UD_IQ1_M: "Unsloth Dynamic, ~1,5 bit",
  UD_Q2_K_XL: "Unsloth Dynamic, 2 bit", UD_IQ3_XXS: "Unsloth Dynamic, ~3 bit",
  UD_Q3_K_XL: "Unsloth Dynamic, 3 bit", UD_IQ4_XS: "Unsloth Dynamic, ~4 bit",
  UD_Q4_K_XL: "Unsloth Dynamic, 4 bit", UD_Q5_K_XL: "Unsloth Dynamic, 5 bit",
  UD_Q6_K_XL: "Unsloth Dynamic, 6 bit", Q8_0: "quasi senza perdita (enorme)",
};
function catNota(q) {
  const k = String(q).toUpperCase().replace(/-/g, "_");
  for (const n of Object.keys(CAT_NOTE)) if (k === n || k.startsWith(n)) return CAT_NOTE[n];
  return "";
}

const CAT_TH = "padding:4px 10px 4px 0;font-size:10px;letter-spacing:.08em;text-transform:uppercase;" +
               "opacity:.55;font-weight:600;border-bottom:1px solid var(--border);text-align:left";
const CAT_TD = "padding:5px 10px 5px 0;border-bottom:1px solid var(--border);vertical-align:top";
const CAT_ACT = "padding:5px 0;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap";

function catTabella(righe) {
  const testa = "<tr><th style='" + CAT_TH + "'>Modello</th><th style='" + CAT_TH + "'>Peso</th>" +
    "<th style='" + CAT_TH + "'>Requisiti</th><th style='" + CAT_TH + "'>Stato</th><th style='" + CAT_ACT +
    ";text-align:right'>Azione</th></tr>";
  const corpo = righe.map((q) => {
    const f = q.fit || {};
    const nota = catNota(q.quant);
    const nome = "<b>" + q.quant + "</b>" + (nota ? "<br><span style='opacity:.65;font-size:11px'>" + nota + "</span>" : "");
    const peso = (q.download_gib ? q.download_gib + " GB" : "—");
    const req = f.arena_gb ? ("arena " + f.arena_gb + " GB su " + (f.host ? f.host.ram_total_gib : "?") + " GB di RAM") : "—";
    const stato = q.on_disk
      ? "<span style='color:var(--success,#30a46c);font-weight:600'>sul disco</span>"
      : (f.level === "disco"
          ? "<span style='color:#d97706;font-weight:600'>dal disco (lento)</span>"
          : "<span style='opacity:.8'>da scaricare</span>");
    const azione = q.on_disk
      ? "<button class='st-btn st-btn--secondary' data-cat-usa=\"" + q.key + "\">Usa</button>"
      : "<button class='st-btn st-btn--secondary' data-cat-fetch=\"" + q.repo + "|" + q.quant + "\">Scarica</button>";
    return "<tr><td style='" + CAT_TD + "'>" + nome + "</td><td style='" + CAT_TD + ";white-space:nowrap'>" + peso +
      "</td><td style='" + CAT_TD + ";opacity:.8;font-size:11px'>" + req + "</td><td style='" + CAT_TD + "'>" + stato +
      "</td><td style='" + CAT_ACT + "'>" + azione + "</td></tr>";
  }).join("");
  return "<table style='width:100%;border-collapse:collapse'>" + testa + corpo + "</table>";
}

function catElencoUfficiale(official) {
  const box = document.getElementById("cat-results");
  if (!box || !official.length) return;
  const ordina = (a, b) => (b.on_disk ? 1 : 0) - (a.on_disk ? 1 : 0) || (a.download_gib || 0) - (b.download_gib || 0);
  let nascosti = 0, mostrati = 0;
  const gruppi = official.map((e) => {
    const buoni = e.quants.filter((q) => catEseguibile(q.fit)).sort(ordina);
    nascosti += e.quants.length - buoni.length;
    mostrati += buoni.length;
    if (!buoni.length) return "";
    const pronti = buoni.filter((q) => q.on_disk).length;
    return "<div class='dm__sub' style='padding:10px 0 4px 0;border-top:1px solid var(--border)'>" +
      "<div style='display:flex;justify-content:space-between;align-items:baseline'>" +
      "<b>" + e.title + "</b>" +
      "<span style='opacity:.65;font-size:11px'>" + e.by + " · " + buoni.length + " eseguibili · " +
      pronti + " già pronti</span></div></div>" + catTabella(buoni);
  }).join("");
  box.innerHTML = gruppi;
  catStato(mostrati + " modelli girano su questa macchina" +
           (nascosti ? " · " + nascosti + " nascosti perché qui non girano" : "") +
           " · apri 'Cerca' per altri repository della stessa famiglia");
}

// 'Usa' su un modello già pronto: passa il server a quella configurazione (stessa strada del pulsante in alto)
async function catUsa(chiave) {
  const inUso = (ctrlState.model || "").toLowerCase();
  if (inUso.includes(String(chiave).toLowerCase())) { catStato(chiave + " è già il modello in servizio."); return; }
  catStato("Passo a " + chiave + ": il server si riavvia sulla stessa porta…");
  try {
    await catPost("switch-model", {model: chiave});
  } catch (e) { catStato("Cambio non riuscito: " + e.message, "err"); return; }
  for (let i = 0; i < 90; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    try {
      const h = await fetch("health", {headers: headers()}).then((r) => r.json());
      if (h && h.loaded) { catStato("Modello cambiato: " + h.model + ". Ricarico…"); setTimeout(() => location.reload(), 1200); return; }
    } catch (e) { /* il server sta ripartendo */ }
  }
  catStato("Il server non è tornato: guarda strata-cambio-*.log.", "err");
}

async function loadControl() {
  // wire the buttons once (the markup is static)
  if (!ctrlState.wired) {
    ctrlState.wired = true;
    const post = async (path, body, okTitle, okText) => {
      try {
        const r = await fetch(path, {method: "POST", headers: headers(true), body: JSON.stringify(body)});
        const v = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(v.error ? v.error.message : `HTTP ${r.status}`);
        toast("success", okTitle, okText || "");
        return v;
      } catch (e) { toast("error", okTitle, e.message); return null; }
    };
    $("ctrl-load").onclick = async () => { await post("load", {}, "Avvio", "Il modello si sta caricando…"); setTimeout(loadControl, 3000); };
    $("ctrl-unload").onclick = async () => { await post("unload", {}, "Arresto", "VRAM liberata."); setTimeout(loadControl, 2000); };
    $("ctrl-restart").onclick = async () => {
      const r = await post("unload", {}, "Riavvio", "Scarico il motore…");
      if (r) setTimeout(async () => { await post("load", {}, "Riavvio", "Ricaricamento avviato…"); setTimeout(loadControl, 3000); }, 2500);
    };
    $("ctrl-health").onclick = async () => {
      try {
        const r = await fetch("health"); if (!r.ok) throw new Error(`HTTP ${r.status}`); const h = await r.json();
        toast("success", "Server in salute", `${h.model} · contesto ${h.max_context} · immagini ${h.images ? "sì" : "no"}`);
      } catch (e) { toast("error", "Health check", e.message); }
    };
    // the images switch: writes the config and starts/stops the encoder and prepares the next engine start
    $("ctrl-vision").onclick = async () => {
      const on = !ctrlState.vision;
      const r = await post("config", {vision: on}, "Immagini",
                           on ? "Immagini abilitate: il motore si ricarica con il supporto immagini alla prossima richiesta." : "Encoder fermato, memoria restituita.");
      if (r) setTimeout(loadControl, on ? 4000 : 1500);
    };

    $("ctrl-model").onchange = () => {
      const i = MODEL_INFO[$("ctrl-model").value] || {};
      fillModelTiles(i);
    };
    $("ctrl-download").onclick = async () => {
      const model = $("ctrl-model").value;
      const v = await post("setup-download", {model}, "Download avviato", `${model}: setup.py sta scaricando e preparando (log in setup-${model}.log).`);
      if (v) setTimeout(loadControl, 5000);
    };

    // Passa al modello scelto ADESSO: il server si riavvia con l'altra configurazione, sulla stessa porta.
    // Non si puo' fare altrimenti: quale modello gira e' deciso all'avvio del server e tenuto in memoria.
    $("ctrl-switch").onclick = async () => {
      const model = $("ctrl-model").value;
      const chiave = model.toLowerCase().replace(/-/g, "_");
      const attuale = (ctrlState.model || "").toLowerCase().replace(/-/g, "_");
      if (attuale && attuale.includes(chiave)) {
        toast("info", "Gia' in uso", `${model} e' il modello che sta servendo adesso.`);
        return;
      }
      const v = await post("switch-model", {model}, "Cambio modello",
        `Passo a ${model}: il server si riavvia sulla stessa porta e la pagina si riconnette da sola.`);
      if (!v) return;
      // aspetto che il server torni, poi ricarico la pagina (il modello nuovo impiega fino a un minuto a caricarsi)
      const attendi = async () => {
        for (let i = 0; i < 90; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          try {
            const r = await fetch("health", {headers: headers()});
            if (r.ok) {
              const h = await r.json();
              toast("success", "Modello cambiato", `${h.model} in servizio. Ricarico la pagina…`);
              setTimeout(() => location.reload(), 1500);
              return;
            }
          } catch (e) { /* il server sta ancora ripartendo */ }
        }
        toast("error", "Il server non e' tornato", "Guarda strata-cambio-*.log nella cartella del progetto, o riavvia con il file .bat.");
      };
      setTimeout(attendi, 5000);
    };
    for (const [id, out, unit] of [["ctrl-vram-reserve", "ctrl-vram-out", " MiB"], ["ctrl-kv-resident", "ctrl-kv-out", " celle"], ["ctrl-max-ctx", "ctrl-ctx-out", ""]]) {
      const el = $(id);
      if (el) el.oninput = () => ctrlText(out, `${el.value}${unit}`);
    }
    $("ctrl-apply-resources").onclick = async () => {
      const body = {vram_reserve_mib: +$("ctrl-vram-reserve").value, kv_resident: +$("ctrl-kv-resident").value, max_context: +$("ctrl-max-ctx").value};
      const v = await post("config", body, "Risorse salvate", "Si applicano al prossimo avvio del motore.");
      if (v && Object.keys(v.changed || {}).length) {
        const unloaded = await post("unload", {}, "Riavvio", "Applico le nuove risorse…");
        if (!unloaded) return;
        const loaded = await post("load", {}, "Riavvio", "Motore riavviato con le nuove risorse.");
        if (loaded) await loadControl();
      }
    };
    $("ctrl-temp-limit").oninput = () => ctrlText("ctrl-temp-out", `${$("ctrl-temp-limit").value}°C`);
    $("ctrl-power-limit").oninput = () => ctrlText("ctrl-power-out", `${$("ctrl-power-limit").value}W`);
    $("ctrl-apply-power").onclick = () => post("power", {mode: $("ctrl-power-mode").value, temp_limit: +$("ctrl-temp-limit").value, power_limit: +$("ctrl-power-limit").value},
                                               "Power Manager", `${$("ctrl-power-mode").value} · ${$("ctrl-temp-limit").value}°C · ${$("ctrl-power-limit").value}W`);
    $("ctrl-reset-throttle").onclick = () => post("power", {reset: true}, "Avviso azzerato");
  }
  try {
    const [status, config] = await Promise.all([
      fetch("v1/status", {headers: headers()}).then((r) => r.json()).catch(() => ({})),
      fetch("config", {headers: headers()}).then((r) => (r.ok ? r.json() : {})).catch(() => ({})),
    ]);
    ctrlState.loaded = !!status.loaded;
    ctrlState.model = status.model || "";
    ctrlState.config = config || {};
    aggiornaMenuModelli(ctrlState.config, ctrlState.model);
    catSegui();          // host, spazio e verdetto dei modelli ufficiali, a ogni apertura del tab
    ctrlText("ctrl-stat-model", ctrlState.model || "—");
    // the sliders carry the values the server really runs with
    for (const [id, out, key, unit] of [["ctrl-vram-reserve", "ctrl-vram-out", "vram_reserve_mib", " MiB"],
                                        ["ctrl-kv-resident", "ctrl-kv-out", "kv_resident", " celle"],
                                        ["ctrl-max-ctx", "ctrl-ctx-out", "max_context", ""]]) {
      const el = $(id);
      if (el && config[key] != null) { el.value = config[key]; ctrlText(out, `${config[key]}${unit}`); }
    }
    ctrlText("ctrl-resources-status", `${config.vram_reserve_mib ?? "—"} · ${config.kv_resident ?? "—"} · ${config.max_context ?? "—"}`);
    ctrlText("ctrl-disk-free", config.disk_free_gib != null ? `${fmt(config.disk_free_gib, 1)} GB` : "—");

    const setup = config.setup || {};
    ctrlText("ctrl-dl-status", setup.status === "running" ? `Scarico ${setup.model}…` : setup.status === "done" ? `Ultimo: ${setup.model} ok` : "pronto");
    if (setup.status === "running" && setup.last) ctrlText("ctrl-engine-note", setup.last);
    // the Control tab owns these three lines: renderMonitor does not run when you open Control
    // directly, and an unfilled banner stayed on screen as an empty box
    [["hint-ctrl-run", "Lascia che carichi alla prima richiesta; “Ferma” libera la VRAM senza perdere la configurazione."],
     ["hint-ctrl-res", "Su questa macchina: VRAM riservata 1536 MiB · KV 32768 · contesto 131072. Applica e riavvia per attivarli."],
     ["hint-ctrl-power", "Balanced segnala oltre 80°C o 250 W. Eco usa soglie inferiori; nessun profilo modifica il driver."]]
      .forEach(([id, txt]) => { const el = $(id); if (el) { el.dataset.tone = ""; el.innerHTML = `<b>Consigliato</b><span>${esc(txt)}</span>`; el.hidden = false; } });
    $("ctrl-model").onchange();                       // fill the model info for the current selection
    const mi = MODEL_INFO[$("ctrl-model").value] || {};
    // the four tiles: download, the documented requirement, this very PC, free disk
    fillModelTiles(mi);              // one source for these three tiles, no stray references
    const h4 = $("hint-ctrl-model");
    if (h4) h4.innerHTML = `<b>Consigliato</b><span>Profilo richiesto: IQ3_XXS. La stima è ${mi.need || "–"} fra RAM e VRAM; controlla la memoria libera e lascia spazio alle altre applicazioni.</span>`;
    syncHints();
    renderControlLive();
    refreshVisionState();
  } catch (e) { console.warn('[strata] control tab:', e); }   // never swallow silently
}


// ---- tick marks under every slider (all sections that expose one)
// the value each slider should sit at on THIS machine: the measured arm of
// docs/AMD_HIP_PERFORMANCE.md for the resource knobs, the app's own defaults for sampling.
const RECOMMENDED = {
  "ctrl-vram-reserve": {v: 1536,   t: "1536 MiB: riferimento della consegna su questo PC"},
  "ctrl-kv-resident":  {v: 32768,  t: "32768 celle per layer in VRAM"},
  "ctrl-max-ctx":      {v: 131072, t: "consigliato 131072 token"},
  "ctrl-temp-limit":   {v: 80,     t: "consigliato 80\u00b0C (Balanced)"},
  "ctrl-power-limit":  {v: 250,    t: "consigliato 250 W (Balanced)"},
  "pm-temp":           {v: 80,     t: "consigliato 80\u00b0C (Balanced)"},
  "pm-power":          {v: 250,    t: "consigliato 250 W (Balanced)"},
  "s-temp":            {get: () => (typeof DEFAULTS !== "undefined" ? DEFAULTS.temperature : null), t: "valore consigliato dall'app"},
  "s-topp":            {get: () => (typeof DEFAULTS !== "undefined" ? DEFAULTS.top_p : null),       t: "valore consigliato dall'app"},
  "s-topk":            {get: () => (typeof DEFAULTS !== "undefined" ? DEFAULTS.top_k : null),       t: "valore consigliato dall'app"},
};


function fmtTick(v, step) {
  // binary units: these are memory/context sizes, so 131072 tokens is 128K, never "131.2K"
  const withUnit = (n, u) => (Math.abs(n - Math.round(n)) < 0.05 ? String(Math.round(n)) : n.toFixed(1)) + u;
  if (v >= 1048576) return withUnit(v / 1048576, "M");
  if (v >= 1024) return withUnit(v / 1024, "K");
  return step < 1 ? String(v) : String(Math.round(v));
}
function attachScales(root) {
  const scope = root || document;
  scope.querySelectorAll('input[type=range]').forEach((inp) => {
    if (inp.dataset.scaled) return;
    inp.dataset.scaled = "1";
    const min = parseFloat(inp.min || 0), max = parseFloat(inp.max || 100), step = parseFloat(inp.step || 1);
    const host = inp.closest('.dash-controls') || inp.closest('.slider-row') || inp.parentElement;
    // the reading of the knob belongs above a slider that now carries a scale underneath
    const lab = inp.closest('.dm') ? inp.closest('.dm').querySelector('.dm__label') : null;
    const out = host.querySelector('output');
    if (lab && out && out.parentElement === host) { lab.appendChild(out); out.classList.add('dm__out'); }
    if (!host) return;
    const scale = document.createElement('div');
    scale.className = 'range-scale';
    scale.setAttribute('aria-hidden', 'true');
    const tickValue = f => Number(Math.min(max, min + Math.round((max-min)*f/step)*step).toFixed(10));
    const fraction = v => max > min ? (v-min)/(max-min) : 0;
    // ONE geometry for the whole ruler: the same travel the knob has. Seating ticks, numbers and
    // the blue marker on plain percentages put them up to half a thumb away from the knob.
    for (let i = 0; i < 5; i++) {
      const t = document.createElement('span');
      t.className = 'range-scale__tick' + (i === 0 || i === 4 ? ' range-scale__tick--major' : '');
      t.dataset.f = fraction(tickValue(i / 4));
      scale.appendChild(t);
    }
    [0, 0.5, 1].forEach((frac) => {
      const l = document.createElement('span');
      l.className = 'range-scale__lab range-scale__lab--' + (frac === 0 ? 'min' : frac === 1 ? 'max' : 'mid');
      l.textContent = fmtTick(tickValue(frac), step);
      l.dataset.f = fraction(tickValue(frac));
      l.style.transform = 'translateX(-50%)';      // centred on its own tick, min and max included
      l.style.right = 'auto';
      scale.appendChild(l);
    });
    const now = document.createElement('span');
    now.className = 'range-scale__now';            // where the knob is: no number (the output box has it)
    now.dataset.f = 0;
    // where the knob SHOULD sit: a blue marker with its own line, distinct from the green cursor
    const rec = RECOMMENDED[inp.id];
    if (rec) {
      const rv = rec.get ? rec.get() : rec.v;
      if (rv != null && rv >= min && rv <= max) {
        const pct = 100 * (rv - min) / (max - min);
        const rl = document.createElement('span');
        rl.className = 'range-scale__rec';
        rl.dataset.f = pct / 100;
        rl.title = rec.t;
        const rt = document.createElement('span');
        rt.className = 'range-scale__rec-lab';
        rt.dataset.f = pct / 100;
        if (pct < 16) rt.style.transform = 'translateX(0)';
        else if (pct > 84) rt.style.transform = 'translateX(-100%)';
        rt.textContent = fmtTick(rv, step) + ' · consigliato';
        scale.appendChild(rl);
        scale.appendChild(rt);
      }
    }
    scale.appendChild(now);
    (host.matches('.dash-controls,.slider-row') ? host : inp).insertAdjacentElement('afterend', scale);

    // every element on the ruler carries its own fraction; the geometry lives in ONE place,
    // recomputed whenever the slider gets a width (hidden tab, resize, zoom).
    function placeScale() {
      const ib = inp.getBoundingClientRect();
      if (ib.width < 40) return;                 // not laid out yet: keep the last values
      const thumb = parseFloat(getComputedStyle(inp).getPropertyValue('--range-thumb-size')) || 16;
      scale.style.marginLeft = '0px';
      scale.style.width = ib.width + 'px';
      scale.style.marginRight = 'auto';
      scale.style.marginLeft = (ib.left - scale.getBoundingClientRect().left) + 'px';
      const travel = Math.max(0, ib.width - thumb);
      scale.querySelectorAll('[data-f]').forEach((el) => {
        const f = Math.max(0, Math.min(1, parseFloat(el.dataset.f) || 0));
        el.style.left = (thumb / 2 + f * travel) + 'px';
      });
    }
    const paint = () => {
      const f = max > min ? (parseFloat(inp.value) - min) / (max - min) : 0;
      now.dataset.f = Math.max(0, Math.min(1, f));
      const thumb = parseFloat(getComputedStyle(inp).getPropertyValue('--range-thumb-size')) || 16;
      inp.style.setProperty('--range-fill', `calc(${Math.max(0,Math.min(1,f))*100}% + ${thumb/2-f*thumb}px)`);
      placeScale();
    };
    placeScale();
    paint();
    inp.addEventListener('input', paint);
    inp.addEventListener('change', paint);
    // the dashboard WRITES these values on load (no input event fires): catch the assignment too,
    // otherwise the marker stays where the markup left it instead of under the knob.
    const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    Object.defineProperty(inp, 'value', {
      get() { return desc.get.call(inp); },
      set(v) { desc.set.call(inp, v); paint(); },
      configurable: true,
    });
    // a hidden tab measures 0: re-place whenever the slider actually gets a size
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(placeScale).observe(inp);
    else addEventListener('resize', placeScale, { passive: true });
  });
}

// ------------------------------------------------------------------ start
setBusy(false);
attachScales();
renderChat();
const startQuestion = new URLSearchParams(location.search).get("q");   // /?q=... starts a chat (a shortcut)
if (startQuestion) history.replaceState(null, "", location.pathname + location.hash);
loadHealth().then(loadMcp).then(() => { if (startQuestion) { $("input").value = startQuestion; send(); } });
showTab(location.hash.slice(1) || "chat");
poll();

/* ---------------------------------------------------------------------------
   Potenziamenti: il registro delle leve portate su questa build.
   I numeri delle misure sono la cronaca di quello che e' stato provato: restano
   scritti anche quando l'esito e' negativo, altrimenti si riproverebbero a vuoto.
--------------------------------------------------------------------------- */
const TUNE_COST = [
  // [{modo, decode, watt, j_per_token, ram_gb, vram_gb}, ...] — riempito dalle misure di efficienza
];

function renderTuning(eng, hw, h, st, last) {
  for (const el of document.querySelectorAll(".perf-model")) el.textContent = eng.model || "Modello non disponibile";
  const live = $("tune-live");
  if (live) {
    const rows = [
      ["Motore", eng.version ? `v${eng.version}` : "—"],
      ["Backend", eng.backend ? eng.backend.toUpperCase() : "—"],
      ["Runtime", eng.rocm ? `ROCm ${eng.rocm}` : "—"],
      ["Finestra draft", eng.mtp_max != null ? String(eng.mtp_max) : "—"],
      ["Soglia min-p", eng.spec_min_p != null ? String(eng.spec_min_p) : "—"],
      ["Lookup prompt", eng.lookup != null ? String(eng.lookup) : "—"],
      ["Pool worker", eng.pool_workers != null ? String(eng.pool_workers) : "—"],
      ["KV cache", eng.kv || "—"],
      ["Esperti in VRAM", eng.expert_slots ? fmt(eng.expert_slots) : "—"],
      ["Contesto", eng.max_context ? `${fmt(eng.max_context)} token` : "—"],
    ];
    live.innerHTML = rows.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("");
  }

  const body = $("tune-cost-body");
  if (body) {
    if (!TUNE_COST.length) {
      body.innerHTML = `<tr><td colspan="6" style="color:var(--st-ink-muted)">Costo per token non misurato.
        Servono campioni sincronizzati di energia e token; cambiare il profilo degli avvisi non modifica la potenza del driver.</td></tr>`;
    } else {
      body.innerHTML = TUNE_COST.map((r) => `<tr${r.win ? ' class="tune-t--win"' : ""}>` +
        `<td>${esc(r.modo)}</td><td class="num">${r.decode}</td><td class="num">${r.watt}</td>` +
        `<td class="num tune-b">${r.j_per_token}</td><td class="num">${r.ram_gb}</td>` +
        `<td class="num">${r.vram_gb}</td></tr>`).join("");
    }
  }
}
async function loadBenchmarks() {
  if (performanceBusy) return;
  performanceBusy = true;
  try {
    const r = await fetch("benchmarks", {headers:headers(),cache:"no-store",signal:AbortSignal.timeout(8000)});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    performanceReports = d.reports || [];
    renderPerformanceReports();
  } catch(e) {
    $("benchmark-results").innerHTML = `<tr><td colspan="6">Rapporti non disponibili: ${esc(e.message)}. Controlla il server e la chiave API in About.</td></tr>`;
    $("compare-local").textContent = "Prove non disponibili. Controlla il server e la chiave API in About.";
    $("perf-report-count").textContent = "Dati non disponibili";
  } finally { performanceBusy = false; }
}

function performanceLabel(report) {
  const labels = {"iq3-confirm-base":"Conferma · profilo operativo","iq3-confirm-minp07":"Conferma · soglia 0,7","iq3-paired-base":"Profilo operativo","iq3-paired-spec2":"Finestra draft 2","iq3-paired-minp07":"Soglia draft 0,7","iq3-source-control":"Sorgente · controllo","iq3-source-wmma":"Sorgente · attenzione WMMA","iq3-installed":"Binario installato"};
  Object.assign(labels, {"iq3-memory-baseline":"Memoria · riferimento precedente","iq3-memory-baseline-confirm":"Conferma · riferimento precedente","iq3-memory-dma":"Percorso PCIe · controllo","iq3-memory-resident16-dma":"Esperti in RAM · 16 GiB","iq3-memory-resident16-pool8":"RAM 16 GiB · 8 worker","iq3-memory-resident16-minp03":"RAM 16 GiB · soglia draft 0,3","iq3-memory-resident16-confirm":"Conferma · RAM 16 GiB"});
  Object.assign(labels, {"iq3-memory-chunk256-a1":"Blocchi 256 · riferimento A1","iq3-memory-chunk512-b1":"Blocchi 512 · variante B1","iq3-memory-chunk512-b2":"Blocchi 512 · conferma B2","iq3-memory-chunk256-a2":"Blocchi 256 · conferma A2"});
  return labels[Object.keys(labels).find(k => String(report.label).endsWith(k))] || report.label || "Prova senza nome";
}
function performanceDate(report) {
  return report.started_at && Number.isFinite(Date.parse(report.started_at)) ? new Date(report.started_at).toLocaleString("it-IT",{dateStyle:"short",timeStyle:"short"}) : "Data non disponibile";
}
function performanceSummary(report, metric) {
  const s = report.summary?.[metric];
  return report.status === "complete" && s && [s.min,s.max,s.median].every(v => typeof v === "number" && Number.isFinite(v) && v >= 0) && s.min <= s.median && s.median <= s.max ? s : null;
}
function renderPerformanceReports() {
  const model = lastMetrics?.engine?.model || health.model;
  const reports = performanceReports.filter(r => r.model === model);
  const filter = $("perf-filter").value;
  const shown = reports.filter(r => filter === "all" || (filter === "paired" ? !!r.protocol?.prompt_set : !r.protocol?.prompt_set));
  $("perf-report-count").textContent = `${shown.length} di ${reports.length} rapporti · modello selezionato`;
  $("benchmark-results").innerHTML = shown.map(r => {
    const metric = k => { const s = performanceSummary(r,k); return s ? `<b>${fmt(s.median,1)}</b><small>${fmt(s.min,1)}–${fmt(s.max,1)}</small>` : "—"; };
    const status = {complete:"Completato",running:"In corso",failed:"Fallito",incomplete:"Incompleto"}[r.status] || "Non disponibile";
    return `<tr><td><b>${esc(performanceLabel(r))}</b><small>${esc(performanceDate(r))}</small></td><td><span class="perf-outcome" data-state="${esc(r.status)}">${status}</span></td><td>${metric("decode_tok_s")}</td><td>${metric("wall_tok_s")}</td><td>${metric("prefill_tok_s")}</td><td>${esc(r.protocol?.runs ?? "—")} misure + ${esc(r.protocol?.warmup ?? "—")} riscaldamento<small>${esc(r.protocol?.prompt_set || "Esplorativo · prompt variabili")}</small></td></tr>`;
  }).join("") || `<tr><td colspan="6">${reports.length ? "Nessun rapporto per questo filtro. Seleziona Tutti i rapporti." : "Nessuna prova salvata per il modello selezionato. Il registro si popolerà con i rapporti del banco locale."}</td></tr>`;
  const metric = $("compare-metric").value;
  const paired = reports.filter(r => r.protocol?.prompt_set && performanceSummary(r,metric));
  const group = paired[0]?.protocol?.prompt_set;
  const rows = paired.filter(r => r.protocol.prompt_set === group).slice(0,5);
  if (!rows.length) {
    $("compare-local").textContent = "Nessuna prova appaiata completa per questa misura e questo modello. Consulta il registro in Potenziamenti.";
    $("compare-local-note").textContent = "I valori mancanti non vengono sostituiti con zero.";
    return;
  }
  const ceiling = Math.ceil(Math.max(...rows.map(r => performanceSummary(r,metric).max))*1.1/10)*10 || 10;
  const pct = n => Math.max(0,Math.min(100,n/ceiling*100));
  $("compare-local").innerHTML = rows.map(r => {
    const s = performanceSummary(r,metric), name = performanceLabel(r);
    return `<div class="perf-range"><div class="perf-range-label"><b>${esc(name)}</b><small>${esc(performanceDate(r))} · ${esc(r.protocol.runs)} misure</small></div><div class="perf-range-track" aria-hidden="true"><i style="left:${pct(s.min)}%;width:${pct(s.max)-pct(s.min)}%"></i><span style="left:${pct(s.median)}%"></span></div><div class="perf-range-values"><b>${fmt(s.median,1)}</b><small>${fmt(s.min,1)}–${fmt(s.max,1)} t/s</small></div></div>`;
  }).join("") + `<div class="perf-range-axis" aria-hidden="true"><span>0</span><span>${fmt(ceiling)} token/s</span></div>`;
  $("compare-local-note").textContent = `Serie: ${group}. Riscaldamento escluso dalle statistiche. Il segmento indica l'intervallo osservato, non un intervallo di confidenza. Il nome della serie non garantisce da solo l'identità di tutte le condizioni.`;
}

async function loadAboutBenchmarks() {
  const el = $("about-benchmarks");
  if (!el || aboutBenchBusy) return;
  aboutBenchBusy = true;
  try {
    const r = await fetch("benchmarks", {headers:headers(),cache:"no-store",signal:AbortSignal.timeout(8000)});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json(), model = lastMetrics?.engine?.model || health.model;
    const labels = {"iq3-confirm-base":"Conferma · profilo operativo","iq3-confirm-minp07":"Conferma · soglia 0,7","iq3-paired-base":"Profilo operativo","iq3-paired-spec2":"Finestra draft 2","iq3-paired-minp07":"Soglia draft 0,7","iq3-source-control":"Sorgente · controllo","iq3-source-wmma":"Sorgente · attenzione WMMA","iq3-installed":"Binario installato"};
    el.innerHTML = (d.reports || []).filter(x => x.model === model).slice(0,5).map(x => {
      const complete = x.status === "complete", p = x.protocol || {};
      const label = performanceLabel(x);
      const metric = k => complete && x.summary?.[k] ? `${fmt(x.summary[k].median,1)}<br><small>${fmt(x.summary[k].min,1)}–${fmt(x.summary[k].max,1)}</small>` : "—";
      const date = x.started_at && Number.isFinite(Date.parse(x.started_at)) ? new Date(x.started_at).toLocaleString("it-IT",{dateStyle:"short",timeStyle:"short"}) : "Data non disponibile";
      return `<tr><td><b>${esc(label)}</b><br><small>${esc(date)} · ${complete ? "completato" : esc({running:"in corso",failed:"fallito"}[x.status] || x.status)}</small></td><td>${metric("decode_tok_s")}</td><td>${metric("wall_tok_s")}</td><td>${esc(p.runs ?? "—")} misure + ${esc(p.warmup ?? "—")} riscaldamento<br><small>${p.prompt_set ? "Prompt appaiati: " + esc(p.prompt_set) : "Esplorativo: prompt variabili"}</small></td></tr>`;
    }).join("") || '<tr><td colspan="4">Nessun rapporto disponibile per il modello selezionato. Le misure appariranno dopo un banco completato.</td></tr>';
  } catch(e) { el.innerHTML = `<tr><td colspan="4">Evidenze non disponibili: ${esc(e.message)}</td></tr>`; }
  finally { aboutBenchBusy = false; }
}

/* ---------------------------------------------------------------------------
   Confronti: il quadro d'insieme. I numeri delle altre schede e delle altre
   quantizzazioni vengono dai doc del progetto; i nostri dalle misure di qui.
   L'unica parte viva e' la riga che dice su che motore si sta guardando.
--------------------------------------------------------------------------- */
function renderConfronti(eng) {
  for (const el of document.querySelectorAll(".perf-model")) el.textContent = eng.model || "Modello non disponibile";
  const k = document.querySelector(".cf-hero__kicker");
  if (k && eng && eng.model) k.textContent = `${eng.model} · ${eng.backend ? eng.backend.toUpperCase() : ""} · questa macchina`.trim();
}
$("perf-filter").addEventListener("change", renderPerformanceReports);
$("compare-metric").addEventListener("change", renderPerformanceReports);

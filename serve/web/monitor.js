"use strict";
const $ = id => document.getElementById(id);
let apiKey = sessionStorage.getItem("strata.monitor.key") || "";
document.documentElement.dataset.theme = localStorage.getItem("strata.theme") || "dark";
function text(id, value) { const el = $(id); if (el && el.textContent !== String(value)) el.textContent = value; }
async function api(path, body) {
  const response = await fetch(path, {cache: "no-store",
    headers: {...(apiKey ? {Authorization: "Bearer " + apiKey} : {}), ...(body !== undefined ? {"Content-Type": "application/json"} : {})},
    ...(body !== undefined ? {method: "POST", body: JSON.stringify(body)} : {})});
  const value = await response.json();
  if (!response.ok) {
    if (response.status === 401) $("auth").hidden = false;
    throw new Error(value.error && value.error.message || ("HTTP " + response.status));
  }
  return value;
}
function notice(message) { const el = $("error"); if (!el) return; el.hidden = !message; text("error", message || ""); }
function spark(id, values, max) {
  const svg = $(id);
  if (!svg) return;
  const v = (values || []).map(x => x == null ? 0 : x);
  const line = svg.querySelector(".line"), area = svg.querySelector(".area");
  if (v.length < 2) { line.setAttribute("d", ""); area.setAttribute("d", ""); return; }
  const top = Math.max(max || 0, ...v, 1e-9);
  const pts = v.map((x, i) => [(i / (v.length - 1)) * 100, 26 - (x / top) * 22]);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join("");
  line.setAttribute("d", d);
  area.setAttribute("d", d + "L100,28L0,28Z");
}
function bar(id, pct, tone) {
  const el = $(id);
  if (!el) return;
  el.style.width = Math.min(100, Math.max(0, pct)) + "%";
  el.className = "bar-fill" + (tone ? " " + tone : "");
}
function num(n, d) { return n == null || isNaN(n) ? "—" : Number(n).toFixed(d == null ? 0 : d); }

function render(m) {
  const hw = m.hardware || {}, st = m.hardware_static || {}, eng = m.engine || {}, live = m.live || {}, h = m.history || {};
  const pm = m.power || {};

  // ---- GPU & Power
  text("m-gpu-util", hw.gpu_util != null ? num(hw.gpu_util) + "%" : "—");
  spark("s-gpu-util", h.gpu_util, 100);
  text("m-vram", hw.gpu_mem_used != null ? num(hw.gpu_mem_used / 2**30, 1) + " GB" : "—");
  bar("b-vram", hw.gpu_mem_total ? (100 * hw.gpu_mem_used) / hw.gpu_mem_total : 0);
  text("m-vram-sub", hw.gpu_mem_total ? "of " + num(hw.gpu_mem_total / 2**30, 0) + " GB" : "");
  text("m-temp", hw.gpu_temp != null ? num(hw.gpu_temp) + "°C" : "—");
  spark("s-temp", h.gpu_temp, 90);
  text("m-hotspot", hw.gpu_temp_hotspot != null ? num(hw.gpu_temp_hotspot) + "°C" : "—");
  spark("s-hotspot", h.gpu_temp_hotspot, 90);
  text("m-power", hw.gpu_power != null ? num(hw.gpu_power) + " W" : "—");
  spark("s-power", h.gpu_power, 350);
  text("m-vramtemp", hw.gpu_vram_temp != null ? num(hw.gpu_vram_temp) + "°C" : "—");
  text("m-vramtemp-sub", hw.gpu_vram_temp != null ? "VRAM modules" : "");
  text("m-volt", hw.gpu_volt != null ? num(hw.gpu_volt, 3) + " V" : "—");
  text("m-volt-sub", hw.gpu_power && hw.gpu_volt ? num(hw.gpu_power / Math.max(hw.gpu_volt, 0.01)) + " A board" : "");
  const gen = hw.gpu_pcie_gen_max || hw.gpu_pcie_gen;
  text("m-pcie", gen ? "Gen" + gen + (hw.gpu_pcie_width ? " x" + hw.gpu_pcie_width : "")
                     : (eng.pcie_probe_gbs ? eng.pcie_probe_gbs + " GB/s" : "—"));
  text("m-pcie-sub", [gen ? "x" + (hw.gpu_pcie_width || "?") + " negotiated" : null,
                      eng.pcie_probe_gbs ? num(eng.pcie_probe_gbs, 1) + " GB/s measured" : null,
                      hw.gpu_pcie_rx_mb != null ? "RX " + num(hw.gpu_pcie_rx_mb) + " MB/s" : null]
                     .filter(Boolean).join(" · ") || "no AMD counter on Windows");
  text("m-eff", pm.efficiency > 0 ? num(pm.efficiency, 2) + " t/s/W" : "—");

  // ---- CPU & System
  text("m-cpu", hw.cpu != null ? num(hw.cpu) + "%" : "—");
  spark("s-cpu", h.cpu, 100);
  text("m-cpu-temp", hw.cpu_temp != null ? num(hw.cpu_temp) + "°C" : "—");
  spark("s-cpu-temp", h.cpu_temp, 90);
  text("m-cpu-power", hw.cpu_power != null ? num(hw.cpu_power) + " W" : "—");
  spark("s-cpu-power", h.cpu_power, 200);
  text("m-cores", st.cores ? st.cores + " / " + st.threads : "—");
  text("m-cores-sub", st.cores ? "cores / threads" : "");
  text("m-ram", hw.ram_total ? num(hw.ram_used / 2**30, 1) + " / " + num(hw.ram_total / 2**30, 0) + " GB" : "—");
  bar("b-ram", hw.ram_total ? (100 * hw.ram_used) / hw.ram_total : 0, hw.ram_total && hw.ram_used / hw.ram_total > 0.9 ? "danger" : "");
  text("m-ram-sub", hw.ram_total ? num((100 * hw.ram_used) / hw.ram_total) + "% used" : "");
  const big = hw.disk_read_mb >= 1000;
  text("m-disk", hw.disk_read_mb != null ? (big ? num(hw.disk_read_mb / 1024, 2) + " GB/s" : num(hw.disk_read_mb, 1) + " MB/s") : "—");
  text("m-disk-sub", hw.disk_write_mb != null ? "write " + num(hw.disk_write_mb, 1) + " MB/s" : "");

  // ---- Inference
  const spd = live.state === "generating" ? live.tok_s : null;
  text("m-speed", spd != null ? num(spd, 1) + " t/s" : "—");
  spark("s-speed", h.tok_s);
  const pf = live.state !== "idle" ? live.prefill_tok_s_mean : null;
  text("m-prefill", pf != null ? num(pf) + " t/s" : "—");
  spark("s-prefill", h.prefill_tok_s_mean);
  const ctx = eng.max_context || 0;
  let used = 0;
  if (live.state !== "idle") used = (live.prompt_tokens || 0) + (live.generated || 0);
  const frac = ctx ? Math.min(1, used / ctx) : 0;
  const g = $("g-ctx");
  if (g) g.setAttribute("stroke-dasharray", (150.8 * frac).toFixed(1) + " 150.8");
  text("m-ctx-pct", Math.round(frac * 100) + "%");
  text("m-ctx-sub", ctx ? used.toLocaleString() + " / " + ctx.toLocaleString() + " tokens" : "");
  const cacheMiB = eng.expert_cache_mib || 0;
  text("m-experts", eng.expert_slots ? eng.expert_slots.toLocaleString() + " experts" : "—");
  bar("b-experts", hw.gpu_mem_total ? (100 * cacheMiB * 2**20) / hw.gpu_mem_total : 0);
  text("m-experts-sub", cacheMiB ? num(cacheMiB / 1024, 1) + " GB in VRAM" : "");
  text("m-state", live.state ? live.state.charAt(0).toUpperCase() + live.state.slice(1) : "—");
  text("m-state-sub", live.state === "generating" ? (live.generated || 0) + " tokens" : (live.state === "reading" ? "reading prompt" : ""));
  text("m-max-ctx", ctx ? ctx.toLocaleString() : "—");
  text("m-max-ctx-sub", eng.model || "");

  // ---- Power Manager
  text("pm-status", pm.throttling ? "Alert" : "Monitoring");
  text("pm-eff", pm.efficiency > 0 ? num(pm.efficiency, 2) : "—");
  text("pm-tlim", (pm.temp_limit != null ? pm.temp_limit : "—") + (pm.temp_limit != null ? "°C" : ""));
  text("pm-plim", (pm.power_limit != null ? pm.power_limit : "—") + (pm.power_limit != null ? "W" : ""));
  const thr = $("pm-throttle");
  if (thr) { thr.hidden = !pm.throttling; if (pm.throttling) thr.textContent = "Advisory alert: " + pm.throttle_reason + " · cooldown " + pm.cooldown_s + "s"; }
  const modeEl = $("pm-mode");
  if (modeEl && pm.mode && modeEl.value !== pm.mode) modeEl.value = pm.mode;
  const tEl = $("pm-temp"), pEl = $("pm-power");
  if (tEl && pm.temp_limit != null) { tEl.value = pm.temp_limit; $("pm-temp-out").textContent = pm.temp_limit + "°C"; }
  if (pEl && pm.power_limit != null) { pEl.value = pm.power_limit; $("pm-power-out").textContent = pm.power_limit + "W"; }
  // the two limits answer with what the card is doing right now
  const gt = hw.gpu_temp, gp = hw.gpu_power;
  text("pm-temp-sub", gt != null && pm.temp_limit != null
    ? num(gt, 0) + "°C ora · " + Math.max(0, Math.round(pm.temp_limit - gt)) + "° di margine su " + pm.temp_limit + "°C"
    : "in attesa della telemetria");
  text("pm-power-sub", gp != null && pm.power_limit != null
    ? num(gp, 0) + " W ora · " + Math.max(0, Math.round(pm.power_limit - gp)) + " W di margine su " + pm.power_limit + " W"
    : "in attesa della telemetria");
  text("updated", "Live · updated " + new Date().toLocaleTimeString());
}

$("pm-temp").oninput = e => { $("pm-temp-out").textContent = e.target.value + "°C"; };
$("pm-power").oninput = e => { $("pm-power-out").textContent = e.target.value + "W"; };
$("pm-apply").onclick = async () => {
  try {
    await api("power", {mode: $("pm-mode").value, temp_limit: +$("pm-temp").value, power_limit: +$("pm-power").value});
    notice("");
  } catch (e) { notice(e.message); }
};
$("pm-reset").onclick = async () => { try { await api("power", {reset: true}); notice(""); } catch (e) { notice(e.message); } };

async function poll() {
  try { render(await api("metrics")); notice(""); }
  catch (e) { notice(e.message); }
  setTimeout(poll, document.hidden ? 5000 : 2000);
}
$("key").onclick = () => { $("auth").hidden = !$("auth").hidden; if (!$("auth").hidden) $("api-key").focus(); };
$("auth").onsubmit = async e => { e.preventDefault(); apiKey = $("api-key").value.trim(); sessionStorage.setItem("strata.monitor.key", apiKey); $("auth").hidden = true; poll(); };
// ---- tick marks under every slider (all sections that expose one)
const RECOMMENDED = {"pm-temp": {v: 80, t: "consigliato 80\u00b0C"}, "pm-power": {v: 250, t: "consigliato 250 W"}};

function fmtTick(v, step) {
  // binary units: these are memory/context sizes, so 131072 tokens is 128K, never "131.2K"
  const withUnit = (n, u) => (Math.abs(n - Math.round(n)) < 0.05 ? String(Math.round(n)) : n.toFixed(1)) + u;
  if (v >= 1048576) return withUnit(v / 1048576, "M");
  if (v >= 1024) return withUnit(v / 1024, "K");
  return step < 1 ? String(v) : String(Math.round(v));
}
const THUMB_PX = 19;   // measured on this machine: the round knob is 19px across
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
    for (let i = 0; i < 5; i++) {
      const t = document.createElement('span');
      t.className = 'range-scale__tick' + (i === 0 || i === 4 ? ' range-scale__tick--major' : '');
      t.dataset.f = i / 4;
      scale.appendChild(t);
    }
    [0, 0.5, 1].forEach((frac) => {
      const l = document.createElement('span');
      l.className = 'range-scale__lab range-scale__lab--' + (frac === 0 ? 'min' : frac === 1 ? 'max' : 'mid');
      l.textContent = fmtTick(min + (max - min) * frac, step);
      l.dataset.f = frac;
      l.style.transform = 'translateX(-50%)';      // centred on its own tick, min and max included
      l.style.right = 'auto';
      scale.appendChild(l);
    });
    const now = document.createElement('span');
    now.className = 'range-scale__now';            // where the knob is: no number (the output box has it)
    now.dataset.f = 0;
    const paint = () => {
      const f = max > min ? (parseFloat(inp.value) - min) / (max - min) : 0;
      now.dataset.f = Math.max(0, Math.min(1, f));
      placeScale();                                // one geometry: reposition the whole ruler
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
        rt.textContent = '\u25b2 ' + fmtTick(rv, step);
        scale.appendChild(rl);
        scale.appendChild(rt);
      }
    }
    scale.appendChild(now);
    host.insertAdjacentElement('afterend', scale);
    placeScale();
    // a hidden tab measures 0: re-place whenever the slider actually gets a size
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(placeScale).observe(inp);
    else addEventListener('resize', placeScale, { passive: true });

    function placeScale() {
      const ib = inp.getBoundingClientRect(), hb = host.getBoundingClientRect();
      if (ib.width < 40) return;                 // not laid out yet (hidden tab): keep the last values
      // The ruler is as wide as the VISIBLE BAR (measured: it spans the control's padding box),
      // while the knob's centre travels half a thumb inside it. Ticks follow the bar, the marker
      // follows the knob, so both read correctly.
      // measured on the live page: the visible bar spans the whole control, 2px inside its edges
      // (the rounded ends of the track). Everything else was guessing.
      const inset = 2;
      const barW = Math.max(40, ib.width - 2 * inset);
      scale.style.marginLeft = (ib.left - hb.left + inset) + 'px';
      scale.style.width = barW + 'px';
      scale.style.marginRight = 'auto';
      const travel = Math.max(0, barW - THUMB_PX);
      scale.querySelectorAll('[data-f]').forEach((el) => {
        const f = Math.max(0, Math.min(1, parseFloat(el.dataset.f) || 0));
        el.style.left = (THUMB_PX / 2 + f * travel) + 'px';
      });
    }
  });
}

$("theme").onclick = () => { const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = t; localStorage.setItem("strata.theme", t); };
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => attachScales());
else attachScales();
poll();

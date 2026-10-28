/* Interface of the thesis model. The System page picks the blocks on a drawing of the greenhouse (a scenario preset or
   your own); each chosen block has its own page (its input file and technical settings), the Input data page shows
   every curve, and the general pages hold what is not a physical block (market, commercial, subsidies, EMS). The Run
   page checks and runs the case with the model that fits the system (a run type, interface/adapters). The page builds
   a system case (system/setup.py), asks the local Python server (interface/server.py) to inspect, preview and run it,
   and draws the results. No framework; charts with Chart.js (chart.umd.js, stored locally). */
"use strict";

const $ = (id) => document.getElementById(id);
const S = {
  options: null, params: null, preview: null, results: null,
  system: { preset: null, blocks: new Set() }, runType: null, runTypeWanted: null,
  data: {}, step: "system", fieldValues: {}, charts: {}, logLength: 0, polling: null, monthlyTab: "monthly_battery",
};
// the battery model has no ancillary switch: "off" is these overrides (rate 0, no reserve)
const ANCILLARY_OFF = { ancillary: { rate_per_kw_year: 0, reserve: { mode: "percent", frac: 0 } } };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const COLORS = { load: "#334155", pv: "#e0a100", existing: "#a16207", imp: "#2563eb", exp: "#16a34a",
  bat: "#0f766e", soc: "#7c3aed", da: "#dc2626", neg: "#b42318", accent: "#0f766e", grey: "#94a3b8" };
const CONVERSION = { power: "repeated", price: "repeated", state: "repeated", energy: "divided", time: "rebuilt" };
// the general items: what is not a physical block, and when its page is shown
const GENERAL = [
  { id: "market", name: "Market", small: "country, tariff, currency", show: () => true },
  { id: "commercial", name: "Commercial", small: "business model, prices, lifetimes", show: () => has("voltiris") || has("battery") },
  { id: "subsidies", name: "Subsidies", small: "Voltiris and battery", show: () => has("voltiris") || has("battery") },
  { id: "ems", name: "EMS", small: "energy management costs", show: () => has("battery") },
];

// -- small helpers --------------------------------------------------------------------------------------------------
async function api(path, body) {
  const init = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) };
  const res = await fetch(path, init);
  const data = await res.json();
  if (!res.ok || (data && data.error && res.status !== 200)) throw new Error(data.error || res.statusText);
  return data;
}
function fmt(v, digits = 0) {
  if (v === null || v === undefined || (typeof v === "number" && !isFinite(v))) return "–";
  if (typeof v !== "number") return String(v);
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function auto(v) {
  if (typeof v !== "number") return v === null || v === undefined ? "–" : String(v);
  const a = Math.abs(v);
  return fmt(v, a >= 100 ? 0 : a >= 1 ? 2 : a === 0 ? 0 : 4);
}
const cur = () => (S.params && S.params.currency) || (S.preview && S.preview.currency) || "";
const money = (v, d = 0) => `${fmt(v, d)} ${cur()}`;
function toast(text, error = false) {
  const t = $("toast");
  t.textContent = text; t.className = "toast" + (error ? " err" : ""); t.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => (t.hidden = true), error ? 7000 : 3500);
}
function el(tag, attrs = {}, html = "") {
  const e = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => (k === "class" ? (e.className = v) : e.setAttribute(k, v)));
  e.innerHTML = html;
  return e;
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
function tiles(container, items) {
  const box = typeof container === "string" ? $(container) : container;
  box.innerHTML = items.filter(Boolean).map(([k, v, s, cls]) =>
    `<div class="tile ${cls || ""}"><div class="k">${esc(k)}</div><div class="v">${v}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`).join("");
}
function getPath(obj, path) { return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj); }
function setPath(obj, path, value) {
  const keys = path.split("."); let o = obj;
  keys.slice(0, -1).forEach((k) => { if (typeof o[k] !== "object" || o[k] === null) o[k] = {}; o = o[k]; });
  o[keys[keys.length - 1]] = value;
}
function delPath(obj, path) {
  const keys = path.split("."); const parents = [obj];
  for (const k of keys.slice(0, -1)) { const next = parents[parents.length - 1][k]; if (typeof next !== "object" || !next) return; parents.push(next); }
  delete parents[parents.length - 1][keys[keys.length - 1]];
  for (let i = parents.length - 1; i > 0; i--) if (!Object.keys(parents[i]).length) delete parents[i - 1][keys[i - 1]];
}
function deepMerge(a, b) {
  const out = JSON.parse(JSON.stringify(a || {}));
  Object.entries(b || {}).forEach(([k, v]) => {
    out[k] = v && typeof v === "object" && !Array.isArray(v) && out[k] && typeof out[k] === "object" && !Array.isArray(out[k])
      ? deepMerge(out[k], v) : JSON.parse(JSON.stringify(v));
  });
  return out;
}
function flatten(obj, prefix = "") {
  return Object.entries(obj || {}).flatMap(([k, v]) => v && typeof v === "object" && !Array.isArray(v)
    ? flatten(v, prefix + k + ".") : [[prefix + k, v]]);
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function numbers(text) { return String(text || "").split(/[,;\s]+/).map(Number).filter((n) => isFinite(n) && n > 0); }
function fillSelect(id, items, placeholder) {
  const box = typeof id === "string" ? $(id) : id;
  box.innerHTML = (placeholder ? `<option value="">${esc(placeholder)}</option>` : "") +
    items.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("");
}
const fileName = (p) => String(p || "").split(/[\\/]/).pop();

// -- charts ---------------------------------------------------------------------------------------------------------
Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
Chart.defaults.font.size = 12;
Chart.defaults.color = "#47515c";
Chart.defaults.plugins.legend.labels.boxWidth = 12;
function chart(id, config) {
  if (S.charts[id]) S.charts[id].destroy();
  // shallow on purpose: tick callbacks are functions, which a JSON copy would drop
  config.options = { responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false }, ...(config.options || {}) };
  S.charts[id] = new Chart($(id), config);
}
function hourLabels(start, from, count) {
  const t0 = new Date(start + "Z").getTime();
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(t0 + (from + i) * 3600e3);
    return `${DAYS[d.getUTCDay()]} ${String(d.getUTCDate()).padStart(2, "0")} ${MONTHS[d.getUTCMonth()]} ${String(d.getUTCHours()).padStart(2, "0")}:00`;
  });
}
const dayTicks = { autoSkip: false, maxRotation: 0,
  callback(value) { const l = this.getLabelForValue(value); return l.endsWith(" 00:00") ? l.slice(0, -6) : ""; } };
const weekTicks = { autoSkip: false, maxRotation: 0,
  callback(value) { const l = this.getLabelForValue(value); return l.endsWith(" 00:00") && ["01", "08", "15", "22", "29"].includes(l.slice(4, 6)) ? l.slice(4, 10) : ""; } };
const monthTicks = { autoSkip: false, maxRotation: 0,
  callback(value) { const l = this.getLabelForValue(value); return l.endsWith("-01") ? MONTHS[Number(l.slice(5, 7)) - 1] : ""; } };
function line(label, data, color, extra = {}) {
  return { label, data, borderColor: color, backgroundColor: color, borderWidth: 1.6, pointRadius: 0, tension: 0.15, ...extra };
}

// -- navigation: System and its blocks, Input data, General, Run, Results ------------------------------------------
const has = (block) => S.system.blocks.has(block);
const blockInfo = (id) => S.options.blocks.find((b) => b.id === id) || { id, name: id };
const isBuilt = (id) => blockInfo(id).status === "model";
const hasData = (id) => !!S.options.block_columns[id];
const chosenBlocks = () => S.options.blocks.map((b) => b.id).filter(has);
const pageOf = (id) => (isBuilt(id) ? id : "planned:" + id);
const generalShown = () => GENERAL.filter((g) => g.show());
const order = () => ["system", ...chosenBlocks().map(pageOf), "inputs", ...generalShown().map((g) => g.id), "run", "results"];
function stepLabel(step) {
  const fixed = { system: "System", inputs: "Input data", run: "Run", results: "Results" };
  if (fixed[step]) return fixed[step];
  const g = GENERAL.find((x) => x.id === step);
  return g ? g.name : blockInfo(step.replace("planned:", "")).name;
}
function blockSmall(id) {
  if (!isBuilt(id)) return "not built yet";
  if (hasData(id)) {
    const d = S.data[id] || {};
    if (!d.path) return id === "grid" ? "connection, regime" : "no input file yet";
    return (d.info && d.info.error ? "problem · " : d.info && d.info.converted ? "→ 15 min · " : "") + fileName(d.path);
  }
  return id === "battery" ? "technology, reserve, sizing" : "settings";
}
function renderNav() {
  const item = (step, title, small, cls = "") => `<button data-step="${step}" class="sub ${cls}" title="${esc(title)}: ${esc(small)}"><i></i><span>${esc(title)}<small>${esc(small)}</small></span></button>`;
  $("steps").innerHTML =
    `<button data-step="system"><b>1</b><span>System<small>the greenhouse and its blocks</small></span></button>` +
    chosenBlocks().map((id) => item(pageOf(id), blockInfo(id).name, blockSmall(id), isBuilt(id) ? "" : "planned")).join("") +
    `<button data-step="inputs"><b>2</b><span>Input data<small>every curve: year, month, week</small></span></button>` +
    `<div class="nav-group"><b>3</b><span>General<small>not tied to one block</small></span></div>` +
    generalShown().map((g) => item(g.id, g.name, g.small)).join("") +
    `<button data-step="run"><b>4</b><span>Run<small>check, case file, progress</small></span></button>` +
    `<button data-step="results" class="${S.results ? "done" : ""}"><b>5</b><span>Results<small>value, sweep, bills, dispatch</small></span></button>`;
  $("steps").querySelectorAll("button").forEach((b) => {
    b.classList.toggle("active", b.dataset.step === S.step);
    b.addEventListener("click", () => showStep(b.dataset.step));
  });
  document.querySelectorAll("[data-nav]").forEach((box) => {
    const steps = order(), i = steps.indexOf(S.step);
    const prev = steps[i - 1], next = steps[i + 1];
    box.innerHTML = (prev ? `<button data-goto="${prev}">&larr; ${esc(stepLabel(prev))}</button>` : "<span></span>") +
      (next ? `<button class="primary" data-goto="${next}">${esc(stepLabel(next))} &rarr;</button>` : "<span></span>");
    box.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => showStep(b.dataset.goto)));
  });
}
function showStep(step) {
  if (!order().includes(step)) step = "system";
  S.step = step;
  history.replaceState(null, "", "#" + step);   // a refresh opens the same page
  const section = step.startsWith("planned:") ? "planned" : step;
  document.querySelectorAll(".step").forEach((s) => s.classList.toggle("active", s.id === "step-" + section));
  if (section === "planned") {
    const b = blockInfo(step.slice(8));
    $("plannedTitle").textContent = b.name;
    $("plannedText").textContent = `${b.role}. Takes: ${(b.in || []).join(", ") || "nothing"}; gives: ${(b.out || []).join(", ") || "nothing"}.`;
  }
  renderNav();
  window.scrollTo(0, 0);
  if (["voltiris", "battery", "market", "commercial", "subsidies", "ems", "run"].includes(step)) loadParams();
  if (["battery", "market", "commercial", "subsidies", "run"].includes(step)) checkSetup(true);
  if (step === "run") renderCaseFile();
  if (hasData(step)) drawViewer("blk-" + step);
  if (step === "inputs") { renderFilesTable(); drawViewer("all"); }
  if (step === "results" && S.results) Object.values(S.charts).forEach((c) => c.resize());
}

// -- the System page: the greenhouse drawing -------------------------------------------------------------------------
const RT = () => S.options.run_types[S.runType] || Object.values(S.options.run_types)[0];
const CARRIER_COLOR = { electricity: "#e0a100", heat: "#dc2626", co2: "#64748b", "low-temperature heat": "#f97316" };
const NODE = { w: 172, h: 58 };
const GH = { x0: 330, x1: 670, peak: 214, eave: 258, base: 452, spans: 6 };
// the centre of each block on the drawing (viewBox 1000 x 620): electricity on the left, heat on the right, fuels below
const LAYOUT = {
  existing_pv: [175, 95], voltiris: [500, 95], aux_heater: [700, 95], external_co2: [885, 95],
  grid: [120, 300], battery: [120, 470], heat_pump: [885, 270], data_center: [885, 420],
  ng_boiler: [340, 565], chp: [520, 565], sofc: [700, 565], thermal_storage: [885, 565],
};
const SHORT = { existing_pv: "Existing PV", voltiris: "Voltiris", aux_heater: "Backup heater", external_co2: "Liquid CO2",
  grid: "Grid", battery: "Battery", heat_pump: "Heat pump", data_center: "Data center", ng_boiler: "Gas boiler",
  chp: "CHP (gas)", sofc: "SOFC (ethanol)", thermal_storage: "Heat storage" };
const ICONS = {
  voltiris: '<rect x="2" y="10" width="24" height="13" rx="2"/><path d="M8 10v13M14 10v13M20 10v13"/><circle cx="21" cy="4" r="3"/>',
  existing_pv: '<path d="M3 22l4-12h18l-4 12z"/><path d="M11 10l-4 12M17 10l-4 12M5 16h18"/>',
  grid: '<path d="M14 2L7 26M14 2l7 24M9 10h10M8 17h12"/>',
  battery: '<rect x="2" y="8" width="21" height="14" rx="2"/><path d="M23 12h3v6h-3M13 10l-3 5h5l-3 5"/>',
  ng_boiler: '<path d="M14 3c4 5 7 8 7 13a7 7 0 0 1-14 0c0-3 2-5 3-7 1 3 2 4 4 4-1-4 0-7 0-10z"/>',
  chp: '<circle cx="14" cy="14" r="11"/><path d="M15 7l-4 7h5l-3 7"/>',
  heat_pump: '<circle cx="14" cy="14" r="11"/><path d="M14 14c0-5 5-6 6-3M14 14c4 3 2 8-1 7M14 14c-5 1-7-3-4-6"/>',
  thermal_storage: '<rect x="6" y="2" width="16" height="24" rx="5"/><path d="M6 15c3 2 5-2 8 0s5 2 8 0"/>',
  data_center: '<rect x="4" y="3" width="20" height="6" rx="1"/><rect x="4" y="11" width="20" height="6" rx="1"/><rect x="4" y="19" width="20" height="6" rx="1"/><path d="M8 6h1M8 14h1M8 22h1"/>',
  sofc: '<path d="M5 6h18M5 10h18M5 14h18M5 18h18M5 22h18"/>',
  external_co2: '<rect x="8" y="6" width="12" height="20" rx="5"/><path d="M12 6V2h4v4"/>',
  aux_heater: '<path d="M2 14h4l2-6 3 12 3-12 3 12 3-12 2 6h4"/>',
};
function nearestOnGreenhouse(cx, cy) {
  return [Math.min(Math.max(cx, GH.x0), GH.x1), Math.min(Math.max(cy, GH.eave), GH.base)];
}
function greenhouseSvg() {
  const on = has("greenhouse"), w = (GH.x1 - GH.x0) / GH.spans;
  let roof = `M${GH.x0} ${GH.eave}`;
  for (let i = 0; i < GH.spans; i++) roof += ` L${GH.x0 + w * i + w / 2} ${GH.peak} L${GH.x0 + w * (i + 1)} ${GH.eave}`;
  let panes = "", modules = "", plants = "";
  for (let i = 0; i <= GH.spans * 2; i++) panes += `<path class="pane" d="M${GH.x0 + (w / 2) * i} ${GH.eave} V${GH.base}"/>`;
  for (let i = 0; i < GH.spans; i++) {
    const x = GH.x0 + w * i;   // Voltiris modules on the south slope of each span
    if (has("voltiris")) modules += `<path class="module" d="M${x + 5} ${GH.eave - 6} L${x + w / 2 - 3} ${GH.peak + 8}"/>`;
  }
  for (let r = 0; r < 2; r++) for (let i = 0; i < 14; i++)
    plants += `<ellipse class="plant" cx="${GH.x0 + 18 + i * 23.5}" cy="${GH.base - 14 - r * 22}" rx="8" ry="${6 + (i % 3)}"/>`;
  return `<g class="node gh ${on ? "on" : ""} built" data-block="greenhouse" tabindex="0" role="checkbox" aria-checked="${on}">
    <title>Greenhouse demand: the site's electricity load (heat and CO2 demand not built yet)</title>
    <path class="glass" d="${roof} L${GH.x1} ${GH.base} L${GH.x0} ${GH.base} Z"/>${panes}${plants}${modules}
    <text x="500" y="320" class="gh-name">Greenhouse demand</text>
    <text x="500" y="340" class="gh-sub">${on ? "electricity load · heat and CO2 not built" : "click to add"}</text></g>`;
}
function nodeSvg(b, cx, cy) {
  const x = cx - NODE.w / 2, y = cy - NODE.h / 2, on = has(b.id), built = b.status === "model";
  const preset = S.options.presets.find((p) => p.id === S.system.preset);
  const note = on && preset && preset.options && preset.options[b.id];
  const sub = note || (on ? (built ? "in the system" : "chosen · not built yet") : built ? "click to add" : "not built yet");
  return `<g class="node ${on ? "on" : ""} ${built ? "built" : "planned"}" data-block="${b.id}" tabindex="0" role="checkbox" aria-checked="${on}">
    <title>${esc(b.name)}: ${esc(b.role)}${built ? "" : " (not built yet)"}</title>
    <rect x="${x}" y="${y}" width="${NODE.w}" height="${NODE.h}" rx="12"/>
    <g transform="translate(${x + 12} ${y + 15})" class="icon">${ICONS[b.id] || ""}</g>
    <text x="${x + 50}" y="${y + 25}" class="name">${esc(SHORT[b.id] || b.name)}</text>
    <text x="${x + 50}" y="${y + 43}" class="sub">${esc(sub)}</text>
    ${on ? `<circle cx="${x + NODE.w - 13}" cy="${y + 13}" r="8" class="tick"/><path d="M${x + NODE.w - 17} ${y + 13} l3 3 l5 -6" class="tickmark"/>` : ""}</g>`;
}
function renderDiagram() {
  let lines = "", nodes = "";
  S.options.blocks.forEach((b) => {
    if (!LAYOUT[b.id]) return;
    const [cx, cy] = LAYOUT[b.id];
    // data center heat reaches the greenhouse only through the heat pump (thesis.md 2.3)
    const toHp = b.id === "data_center";
    const [tx, ty] = toHp ? [LAYOUT.heat_pump[0], LAYOUT.heat_pump[1]] : b.id === "voltiris" ? [500, GH.peak + 14] : nearestOnGreenhouse(cx, cy);
    const on = has(b.id) && has(toHp ? "heat_pump" : "greenhouse");
    const carriers = (b.out || []).filter((c) => CARRIER_COLOR[c]);
    const len = Math.hypot(tx - cx, ty - cy) || 1, nx = -(ty - cy) / len, ny = (tx - cx) / len;
    carriers.forEach((c, i) => {
      const o = (i - (carriers.length - 1) / 2) * 7;
      lines += `<line class="flow ${on ? "on" : ""}" x1="${cx + nx * o}" y1="${cy + ny * o}" x2="${tx + nx * o}" y2="${ty + ny * o}" stroke="${CARRIER_COLOR[c]}"/>`;
    });
    nodes += nodeSvg(b, cx, cy);
  });
  $("diagram").innerHTML = `<svg viewBox="0 52 1000 568" aria-label="The greenhouse and its energy system: click a block to add or remove it">${lines}${greenhouseSvg()}${nodes}</svg>`;
}
function toggleBlock(id) {
  if (has(id)) S.system.blocks.delete(id); else S.system.blocks.add(id);
  const preset = S.options.presets.find((p) => p.id === S.system.preset);
  if (preset && !sameSet(new Set(preset.blocks), S.system.blocks)) S.system.preset = null;
  S.preview = null;
  systemChanged();
}
$("diagram").addEventListener("click", (ev) => { const g = ev.target.closest("[data-block]"); if (g) toggleBlock(g.dataset.block); });
$("diagram").addEventListener("keydown", (ev) => {
  const g = ev.target.closest("[data-block]");
  if (g && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); toggleBlock(g.dataset.block); }
});

// every run type that can run these blocks (the first is the default), or why none can
function runTypeFor(blocks) {
  const ids = [], reasons = [];
  for (const rt of Object.values(S.options.run_types)) {
    const missing = rt.blocks_required.filter((b) => !blocks.has(b));
    const extra = [...blocks].filter((b) => !rt.blocks_allowed.includes(b));
    if (!missing.length && !extra.length) { ids.push(rt.id); continue; }
    const name = (id) => blockInfo(id).name;
    reasons.push(`${rt.name}: ${[missing.length && `needs ${missing.map(name).join(", ")}`,
      extra.length && `cannot run ${extra.map(name).join(", ")}`].filter(Boolean).join("; ")}`);
  }
  const id = ids.includes(S.runTypeWanted) ? S.runTypeWanted : ids[0] || null;
  return { id, ids, why: reasons };
}
$("runTypeSelect").addEventListener("change", () => { S.runTypeWanted = $("runTypeSelect").value; systemChanged(); });
function sameSet(a, b) { return a.size === b.size && [...a].every((x) => b.has(x)); }
function setSystem(blocks, preset) {
  S.system = { preset: preset || null, blocks: new Set(blocks) };
  if (!S.system.preset) {
    const match = S.options.presets.find((p) => sameSet(new Set(p.blocks), S.system.blocks));
    if (match) S.system.preset = match.id;
  }
  systemChanged();
}
function systemChanged() {
  $("presetSelect").value = S.system.preset || "";
  const preset = S.options.presets.find((p) => p.id === S.system.preset);
  $("presetInfo").textContent = preset ? `Scenario: ${preset.name}` : "Your own system";
  renderDiagram();
  const fit = runTypeFor(S.system.blocks);
  const changed = fit.id !== S.runType;
  S.runType = fit.id;
  const planned = chosenBlocks().filter((id) => !isBuilt(id));
  $("systemCheck").innerHTML = fit.id
    ? `This system runs with <b>${esc(RT().name)}</b>.` + (fit.ids.length > 1 ? " Another model can run it too: choose below." : "")
    : `<b>No model can run this system yet.</b> ${fit.why.map(esc).join(" ")}` +
      (planned.length ? `<br>Not built yet: ${planned.map((b) => esc(blockInfo(b).name)).join(", ")}.` : "");
  $("runTypeRow").hidden = fit.ids.length < 2;
  fillSelect("runTypeSelect", fit.ids.map((id) => [id, S.options.run_types[id].name]));
  if (fit.id) $("runTypeSelect").value = fit.id;
  document.querySelectorAll(".sys-note").forEach((n) => {
    n.hidden = !!fit.id;
    n.innerHTML = "<b>No model can run the system of the System page yet.</b> The pages still show each block's input and settings.";
  });
  $("runBtn").disabled = !fit.id;
  $("runInfo").textContent = fit.id ? "" : "Choose a system that runs on the System page.";
  if (changed && fit.id && $("mUtility").value) loadParamsSoon();
  renderNav();
  updateTop();
}
$("presetApply").addEventListener("click", () => {
  const preset = S.options.presets.find((p) => p.id === $("presetSelect").value);
  if (!preset) return toast("Choose a preset first.", true);
  setSystem(preset.blocks, preset.id);
  toast(`Preset ${preset.name}`);
});
$("dataYear").addEventListener("change", () => { S.preview = null; chosenBlocks().filter(hasData).forEach((b) => S.data[b].path && readBlock(b)); });

// -- the case: pages <-> system case ---------------------------------------------------------------------------------
function collectCase() {
  const market = { country: $("mCountry").value, region: $("mRegion").value };
  const [utility, year] = ($("mUtility").value || "|").split("|");
  Object.assign(market, { utility, year: Number(year) });
  const blocks = {};
  for (const id of chosenBlocks()) {
    const cfg = {};
    if (hasData(id)) {
      const d = S.data[id];
      if (d.path) cfg.input_file = d.path;
      if (Object.keys(d.columns).length) cfg.columns = { ...d.columns };
    }
    if (id === "voltiris") cfg.modules = Number($("sModules").value) || 0;
    if (id === "grid") {
      const imp = $("sImport").value, exp = $("sExport").value;
      if (imp !== "") cfg.import_max_kw = Number(imp);
      if (exp !== "") cfg.export_max_kw = Number(exp);
      cfg.regime = document.querySelector("input[name=regimeMode]:checked").value === "manual"
        ? { auto: false, manual: $("sRegime").value } : { auto: true };
    }
    if (id === "battery") {
      const sizing = {
        objective: document.querySelector("input[name=objective]:checked").value,
        custom_kwh: Number($("zCustom").value) || 422,
        fine_grid_kwh: numbers($("zFine").value),
        fine_window_kwh: Number($("zWindow").value) || 0,
        cap_at_subsidy_size: $("zCap").checked,
      };
      const sweep = numbers($("zSweep").value);
      if (sweep.length) sizing.sweep_kwh = sweep;
      cfg.sizing = sizing;
    }
    blocks[id] = cfg;
  }
  return {
    year: Number($("dataYear").value),
    market,
    blocks,
    general: { commercial: { business_model: $("mBusiness").value } },
    overrides: $("sAncillary").checked ? currentOverrides() : deepMerge(currentOverrides(), ANCILLARY_OFF),
    tag: $("rTag").value.trim() || "study",
    system: { preset: S.system.preset, run_type: S.runType },
  };
}

function applyCase(c) {
  const blocks = c.blocks || {};
  const market = c.market || {};
  S.runTypeWanted = (c.system || {}).run_type || null;
  setSystem(Object.keys(blocks), (c.system || {}).preset);
  $("dataYear").value = c.year || market.year || 2026;
  Object.keys(S.options.block_columns).forEach((id) => {
    const cfg = blocks[id] || {};
    S.data[id] = { path: cfg.input_file || "", columns: { ...(cfg.columns || {}) }, info: null };
    renderDataCard(id);
  });
  setMarket(market.country, market.region || market.canton, market.utility, market.year);
  const v = blocks.voltiris || {}, g = blocks.grid || {}, sz = (blocks.battery || {}).sizing || {};
  $("mBusiness").value = ((c.general || {}).commercial || {}).business_model || v.business_model || "direct_sales";
  $("sModules").value = v.modules || 0;
  $("sImport").value = g.import_max_kw != null ? g.import_max_kw : "";
  $("sExport").value = g.export_max_kw != null ? g.export_max_kw : "";
  const regime = g.regime || { auto: true };
  document.querySelector(`input[name=regimeMode][value=${regime.auto === false ? "manual" : "auto"}]`).checked = true;
  S.manualRegime = regime.manual || null;
  // overrides: "ancillary off" first, then the key fields take what they know, the rest goes to the JSON box
  const rest = JSON.parse(JSON.stringify(c.overrides || {}));
  const anc = rest.ancillary || {};
  const off = anc.rate_per_kw_year === 0 && anc.reserve && anc.reserve.frac === 0 && (anc.reserve.mode || "percent") === "percent";
  if (off) { delPath(rest, "ancillary.rate_per_kw_year"); delPath(rest, "ancillary.reserve.frac"); delPath(rest, "ancillary.reserve.mode"); }
  S.fieldValues = {};
  KEY_FIELDS.forEach((f) => {
    const val = getPath(rest, f.path);
    if (val !== undefined && (typeof val !== "object" || Array.isArray(val))) { S.fieldValues[f.path] = val; delPath(rest, f.path); }
  });
  $("jsonOverrides").value = Object.keys(rest).length ? JSON.stringify(rest, null, 2) : "";
  $("sAncillary").checked = !off;
  document.querySelector(`input[name=objective][value=${sz.objective || "profit"}]`).checked = true;
  objectiveChanged();
  $("zCustom").value = sz.custom_kwh || 422;
  $("zSweep").value = (sz.sweep_kwh || []).join(", ");
  $("zFine").value = (sz.fine_grid_kwh || []).join(", ");
  $("zWindow").value = sz.fine_window_kwh != null ? sz.fine_window_kwh : 250;
  $("zCap").checked = sz.cap_at_subsidy_size !== false;
  $("rTag").value = c.tag || "study";
  $("rFolder").value = "";
  S.preview = null;
  document.querySelectorAll(".pv-part").forEach((p) => (p.hidden = true));
  updateTop();
  chosenBlocks().filter(hasData).forEach((id) => S.data[id].path && readBlock(id));
  loadParams();
  renderNav();
}

function renderCaseFile() {
  const c = collectCase();
  $("rCase").textContent = JSON.stringify(c, null, 2);
  $("rFolder").placeholder = `${S.options.runs_dir}${S.options.runs_dir.includes("\\") ? "\\" : "/"}${c.tag}`;
}
$("rDownloadCase").addEventListener("click", () => {
  const c = collectCase();
  const blob = new Blob([JSON.stringify(c, null, 2)], { type: "application/json" });
  const a = el("a", { href: URL.createObjectURL(blob), download: `case_${c.tag}.json` });
  a.click();
});
$("rTag").addEventListener("input", () => { renderCaseFile(); updateTop(); });
function updateTop() {
  const t = $("topStatus");
  if (t.dataset.state === "running") return;
  t.className = "top-status" + (t.dataset.state ? " " + t.dataset.state : "");
  const preset = S.options && S.options.presets.find((p) => p.id === S.system.preset);
  const m = $("mCountry").value ? `${$("mCountry").value} · ${$("mRegion").value} · ${($("mUtility").value || "").replace("|", " ")}` : "";
  t.textContent = `${$("rTag").value || "study"} · ${preset ? preset.name : "own system"}${m ? " · " + m : ""}`;
}

// -- case files ------------------------------------------------------------------------------------------------------
$("caseLoad").addEventListener("click", async () => {
  if (!$("caseSelect").value) return toast("Choose a case file first.", true);
  try {
    const data = await api("/api/case", { path: $("caseSelect").value });
    applyCase(data.case);
    $("caseInfo").textContent = `Loaded ${data.path}`;
    toast("Case loaded");
    if (S.pendingStep) { showStep(S.pendingStep); S.pendingStep = null; }
  } catch (e) { toast(e.message, true); }
});
$("caseFile").addEventListener("change", async (ev) => {
  const file = ev.target.files[0]; if (!file) return;
  try {
    const c = JSON.parse(await file.text());
    if (!c.blocks) throw new Error("this button opens system case files (with \"blocks\"); a reference case file opens from the list (put it in examples/) or from the command line");
    applyCase(c);
    $("caseInfo").textContent = `Loaded ${file.name}. Its input files must be full paths; if one is not found, pick or upload it on the block's page.`;
  } catch (e) { toast("Not a valid case file: " + e.message, true); }
  ev.target.value = "";
});
$("caseNew").addEventListener("click", () => {
  const m = RT().markets[0];
  const preset = S.options.presets.find((p) => p.id === "battery_study");
  applyCase({ year: m.year, market: m, blocks: Object.fromEntries(preset.blocks.map((b) => [b, {}])), tag: "study",
    system: { preset: preset.id } });
  $("caseInfo").textContent = "Empty case with the battery study preset: change the blocks, then give each block its input file on its page.";
});

// -- curves: one viewer per block page, one for every block (Input data page) ---------------------------------------
const SERIES_STYLE = {
  load_kw: { label: "Greenhouse load", color: COLORS.load },
  pv_w_per_module: { label: "Voltiris PV", color: COLORS.pv },
  existing_pv_kw: { label: "Existing PV", color: COLORS.existing },
  day_ahead_eur_kwh: { label: "Day-ahead price", color: COLORS.da },
};
function curveSeries(blocks) {
  const out = [];
  blocks.forEach((id) => {
    const w = S.data[id] && S.data[id].info;
    if (!w || !w.series) return;
    w.series.forEach((s) => {
      const st = SERIES_STYLE[s.role] || { label: s.about, color: COLORS.accent };
      let values = s.hourly, unit = s.unit, label = st.label;
      if (s.unit === "W per module") {   // shown for the module count of the Voltiris page
        const n = Number($("sModules").value) || 0;
        if (n > 0) { values = values.map((v) => (v == null ? null : (v * n) / 1000)); unit = "kW"; label += ` (${fmt(n)} modules)`; }
        else label += " (one module)";
      }
      out.push({ key: s.role, label, unit, color: st.color, price: s.kind === "price", values, start: w.hourly_start });
    });
  });
  return out;
}
const VIEWERS = {};
function makeViewer(box, key, source, chips = false) {
  const prev = VIEWERS[key] || { scale: "week", month: 5, week: 25, hidden: new Set() };
  VIEWERS[key] = { ...prev, source, box };
  const v = VIEWERS[key];
  box.innerHTML = `<div class="viewer-bar">
      <div class="seg">${["year", "month", "week"].map((s) => `<label><input type="radio" name="scale-${key}" value="${s}" ${s === v.scale ? "checked" : ""}><span>${s[0].toUpperCase() + s.slice(1)}</span></label>`).join("")}</div>
      <select data-v="month">${MONTHS.map((m, i) => `<option value="${i}" ${i === v.month ? "selected" : ""}>${m}</option>`).join("")}</select>
      <input type="range" data-v="week" min="0" max="51" value="${v.week}">
      <span class="muted" data-v="label"></span>
    </div>
    ${chips ? '<div class="chips" data-v="chips"></div>' : ""}
    <div class="chart tall"><canvas id="cv-${key}"></canvas></div>`;
  box.querySelectorAll(`input[name="scale-${key}"]`).forEach((r) => r.addEventListener("change", () => { v.scale = r.value; drawViewer(key); }));
  box.querySelector('[data-v="month"]').addEventListener("change", (e) => { v.month = Number(e.target.value); drawViewer(key); });
  box.querySelector('[data-v="week"]').addEventListener("input", (e) => { v.week = Number(e.target.value); drawViewer(key); });
}
function drawViewer(key) {
  const v = VIEWERS[key];
  if (!v || !v.box.offsetParent) return;   // not built or not on screen
  const q = (r) => v.box.querySelector(`[data-v="${r}"]`);
  const all = v.source();
  q("month").hidden = v.scale !== "month";
  q("week").hidden = v.scale !== "week";
  const chipBox = q("chips");
  if (chipBox) {
    chipBox.innerHTML = all.map((s) => `<label class="chip"><input type="checkbox" data-key="${s.key}" ${v.hidden.has(s.key) ? "" : "checked"}><i style="background:${s.color}"></i>${esc(s.label)}, ${esc(s.unit)}</label>`).join("");
    chipBox.querySelectorAll("input").forEach((i) => i.addEventListener("change", () => {
      if (i.checked) v.hidden.delete(i.dataset.key); else v.hidden.add(i.dataset.key);
      drawViewer(key);
    }));
  }
  const series = all.filter((s) => !v.hidden.has(s.key));
  if (!series.length) { q("label").textContent = all.length ? "Tick a curve to show it." : "No input file read yet."; if (S.charts["cv-" + key]) S.charts["cv-" + key].destroy(); return; }
  const start = series[0].start, t0 = Date.parse(start + "Z"), year = new Date(t0).getUTCFullYear(), len = series[0].values.length;
  let labels, pick, ticks, text;
  if (v.scale === "year") {
    const days = Math.floor(len / 24);
    labels = Array.from({ length: days }, (_, d) => new Date(t0 + d * 864e5).toISOString().slice(0, 10));
    pick = (a) => Array.from({ length: days }, (_, d) => {
      let sum = 0, n = 0;
      for (let h = d * 24; h < d * 24 + 24; h++) if (a[h] != null) { sum += a[h]; n++; }
      return n ? sum / n : null;
    });
    ticks = monthTicks; text = `${year}, daily means`;
  } else {
    const from = v.scale === "week" ? v.week * 168 : Math.round((Date.UTC(year, v.month, 1) - t0) / 3600e3);
    const to = v.scale === "week" ? Math.min(len, from + 168) : Math.min(len, Math.round((Date.UTC(year, v.month + 1, 1) - t0) / 3600e3));
    labels = hourLabels(start, from, to - from);
    pick = (a) => a.slice(from, to);
    ticks = v.scale === "week" ? dayTicks : weekTicks;
    text = `${labels[0].slice(4, 10)} to ${labels[labels.length - 1].slice(4, 10)} ${year}, hourly means`;
  }
  q("label").textContent = text;
  const energy = series.filter((s) => !s.price), prices = series.filter((s) => s.price);
  const dual = energy.length && prices.length;
  chart("cv-" + key, { type: "line", data: { labels, datasets: series.map((s) =>
    line(`${s.label}, ${s.unit}`, pick(s.values), s.color, s.price && dual ? { yAxisID: "y1", borderDash: [4, 3], borderWidth: 1.3 } : {})) },
    options: { plugins: { legend: { display: !chipBox } }, scales: { x: { ticks, grid: { display: false } },
      y: { title: { display: true, text: (energy[0] || prices[0]).unit } },
      y1: { display: !!dual, position: "right", grid: { display: false }, title: { display: !!dual, text: dual ? prices[0].unit : "" } } } } });
}
$("sModules").addEventListener("input", debounce(() => { drawViewer("blk-voltiris"); drawViewer("all"); }, 300));

function renderFilesTable() {
  const blocks = chosenBlocks().filter((id) => isBuilt(id) && hasData(id));
  $("filesTable").innerHTML = `<tr><th>Block</th><th>File</th><th>Step in the file</th><th>Steps at 15 min</th><th>Status</th><th></th></tr>` +
    (blocks.length ? blocks.map((id) => {
      const d = S.data[id], w = d.info;
      const status = !d.path ? (id === "grid" ? '<span class="optional">none (only for day-ahead tariffs)</span>' : '<span class="missing">missing</span>')
        : !w ? "reading…" : w.error ? `<span class="missing">${esc(w.error)}</span>` : w.converted ? '<span class="ok">converted to 15 min</span>' : '<span class="ok">ready</span>';
      return `<tr><td class="text"><b>${esc(blockInfo(id).name)}</b></td><td class="text">${esc(fileName(d.path)) || "–"}</td>
        <td>${w && w.step ? `${fmt(w.step.step_minutes)} min` : "–"}</td><td>${w && w.steps ? fmt(w.steps) : "–"}</td>
        <td class="text">${status}</td><td><button data-open="${id}">Open page</button></td></tr>`;
    }).join("") : `<tr><td class="text" colspan="6">No chosen block reads an input file.</td></tr>`);
  $("filesTable").querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => showStep(b.dataset.open)));
}

// -- a block's input file --------------------------------------------------------------------------------------------
function renderDataCard(id) {
  const box = document.querySelector(`.data-card[data-block="${id}"]`);
  if (!box) return;
  const cols = S.options.block_columns[id];
  const needs = cols.data.map((c) => `<b>${esc(c.about)}</b> in ${esc(c.unit)} (column <code>${esc(c.column)}</code>, ${esc(c.needed)})`).join("; ");
  box.innerHTML = `<div class="card">
      <h2>Input file <span class="muted">this block's own</span></h2>
      <p class="hint">Reads ${needs}, with the time columns Month, Day, Hour (and Minute). An hourly or 30-minute file is converted to 15 min when the system runs (kW, W and prices repeated in each quarter hour, kWh per step divided).</p>
      <div class="row">
        <label class="field grow">File in examples/ or uploaded <select data-r="pick"></select></label>
        <label class="button">Upload&hellip;<input type="file" data-r="upload" accept=".xlsx,.xls" hidden></label>
      </div>
      <div class="row">
        <label class="field grow">Full path of the file <input data-r="path" placeholder="C:\\...\\file.xlsx"></label>
        <button class="primary" data-r="read">Read file</button>
        <button data-r="clear">No file</button>
      </div>
      <div class="tiles" data-r="step"></div>
      <p class="error" data-r="error"></p>
      <details data-r="cols-card" hidden><summary data-r="cols-sum">Columns</summary>
        <p class="hint">What the block reads from each column. If the file uses other names, pick the right column; the mapping is saved in the case under this block's <code>columns</code>.</p>
        <div class="table-wrap"><table class="grid" data-r="roles"></table></div>
      </details>
    </div>
    <div class="card" data-r="content" hidden>
      <h2>What is in it</h2>
      <div class="tiles" data-r="tiles"></div>
      <div class="viewer" data-r="viewer"></div>
    </div>`;
  const q = (r) => box.querySelector(`[data-r="${r}"]`);
  fillSelect(q("pick"), S.options.workbooks.map((w) => [w.path, w.name]), "— choose —");
  const d = S.data[id];
  q("path").value = d.path;
  q("pick").value = S.options.workbooks.some((w) => w.path === d.path) ? d.path : "";
  q("pick").addEventListener("change", () => { if (q("pick").value) { d.path = q("pick").value; q("path").value = d.path; readBlock(id); } });
  q("read").addEventListener("click", () => { d.path = q("path").value.trim().replace(/^"|"$/g, ""); readBlock(id); });
  q("clear").addEventListener("click", () => { Object.assign(d, { path: "", info: null }); renderDataCard(id); S.preview = null; renderNav(); });
  q("upload").addEventListener("change", async (ev) => {
    const file = ev.target.files[0]; if (!file) return;
    try {
      const res = await fetch(`/api/upload?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      S.options.workbooks.push({ name: "uploads/" + data.name, path: data.path });
      d.path = data.path;
      Object.keys(S.options.block_columns).forEach((b) => b !== id && renderDataCard(b));
      renderDataCard(id);
      toast(`Uploaded ${data.name}`);
      readBlock(id);
    } catch (e) { toast(e.message, true); }
  });
  makeViewer(q("viewer"), "blk-" + id, () => curveSeries([id]));
  if (d.info) renderBlockData(id);
}

async function readBlock(id) {
  const d = S.data[id];
  if (!d.path) return toast("Give the file first.", true);
  const btn = document.querySelector(`.data-card[data-block="${id}"] [data-r="read"]`);
  btn.disabled = true; btn.textContent = "Reading…";
  try {
    d.info = await api("/api/block-file", { block: id, path: d.path, year: Number($("dataYear").value), columns: d.columns });
    S.preview = null;
  } catch (e) { d.info = { error: e.message, roles: [], columns: [] }; }
  btn.disabled = false; btn.textContent = "Read file";
  renderBlockData(id);
  renderNav();
  if (S.step === "inputs") { renderFilesTable(); drawViewer("all"); }
}

function renderBlockData(id) {
  const box = document.querySelector(`.data-card[data-block="${id}"]`);
  const q = (r) => box.querySelector(`[data-r="${r}"]`);
  const d = S.data[id], w = d.info, defaults = S.options.block_columns[id].defaults;
  q("path").value = d.path;
  q("error").textContent = w.error || "";
  q("cols-card").hidden = !w.roles.length;
  const missing = w.roles.filter((r) => !r.found && r.needed === "always" && r.role !== "minute");
  q("cols-sum").textContent = missing.length ? `Columns: ${missing.length} missing, map ${missing.length > 1 ? "them" : "it"} here` : "Columns: every column found";
  q("cols-card").open = !!missing.length;
  const opts = (sel) => `<option value="">— none —</option>` + w.columns.map((c) => `<option ${c === sel ? "selected" : ""}>${esc(c)}</option>`).join("");
  q("roles").innerHTML = `<tr><th>Used for</th><th>Unit</th><th>Coarser step</th><th>Needed</th><th>Column in the file</th><th>Status</th></tr>` +
    w.roles.map((r) => `<tr><td class="text"><b>${esc(r.about)}</b><br><small class="muted">${r.role}</small></td>
      <td class="text">${esc(r.unit)}</td><td class="text">${CONVERSION[r.kind] || "–"}</td><td class="text">${esc(r.needed)}</td>
      <td class="text"><select data-role="${r.role}">${opts(r.found ? r.column : "")}</select></td>
      <td class="text">${r.found ? '<span class="ok">found</span>' : r.needed === "always" ? '<span class="missing">missing</span>' : '<span class="optional">not found</span>'}</td></tr>`).join("");
  q("roles").querySelectorAll("select").forEach((s) => s.addEventListener("change", () => {
    const role = s.dataset.role;
    if (s.value && s.value !== defaults[role]) d.columns[role] = s.value; else delete d.columns[role];
    readBlock(id);
  }));
  const step = w.step;
  if (step) {
    tiles(q("step"), [
      ["Step in the file", `${fmt(step.step_minutes)} min`, `${fmt(step.rows)} rows${step.irregular_steps ? ` · ${fmt(step.irregular_steps)} irregular steps` : ""}`, w.converted ? "accent" : ""],
      ["Step of the model", `${S.options.model_step_min} min`, w.converted ? `converted when the system runs: ${fmt(w.steps)} steps` : "no conversion needed"],
      ["Period", w.start.slice(0, 10), `to ${w.end.slice(0, 16).replace("T", " ")}`],
    ]);
  } else q("step").innerHTML = "";
  q("content").hidden = !w.series || !w.series.length;
  if (!w.series) return;
  tiles(q("tiles"), w.series.map((s) => s.kind === "price"
    ? [s.about, `${fmt(s.mean, 4)} ${s.unit}`, `min ${fmt(s.min, 4)} · max ${fmt(s.max, 4)} · ${fmt(s.negative_h, 1)} h negative${s.missing ? ` · ${s.missing} missing` : ""}`]
    : [s.about, s.unit === "W per module" ? `${fmt(s.total_kwh, 1)} kWh/yr per module` : `${fmt(s.total_kwh / 1000, 1)} MWh/yr`,
      `peak ${fmt(s.peak, 0)} ${s.unit} · mean ${fmt(s.mean, 1)} ${s.unit}${s.missing ? ` · ${s.missing} missing` : ""}`]));
  drawViewer("blk-" + id);
}

// -- market (general) -------------------------------------------------------------------------------------------------
function setMarket(country, region, utility, year) {
  const ms = RT().markets;
  const countries = [...new Set(ms.map((m) => m.country))];
  fillSelect("mCountry", countries.map((c) => [c, c]));
  if (country && countries.includes(country)) $("mCountry").value = country;
  const regions = [...new Set(ms.filter((m) => m.country === $("mCountry").value).map((m) => m.region))];
  fillSelect("mRegion", regions.map((r) => [r, r]));
  if (region && regions.includes(region)) $("mRegion").value = region;
  const utils = ms.filter((m) => m.country === $("mCountry").value && m.region === $("mRegion").value);
  fillSelect("mUtility", utils.map((m) => [`${m.utility}|${m.year}`, `${m.utility} ${m.year}`]));
  if (utility && utils.some((m) => m.utility === utility && m.year === Number(year))) $("mUtility").value = `${utility}|${year}`;
}
$("mCountry").addEventListener("change", () => { setMarket($("mCountry").value); marketChanged(); });
$("mRegion").addEventListener("change", () => { setMarket($("mCountry").value, $("mRegion").value); marketChanged(); });
$("mUtility").addEventListener("change", marketChanged);
$("mBusiness").addEventListener("change", marketChanged);
function marketChanged() { S.preview = null; updateTop(); loadParams(); }

// -- parameters: on the Voltiris and Battery pages and the general pages ---------------------------------------------
// the parameters you can change without writing JSON: page (its container kp-<page>), group, path, label, unit, kind
const KEY_FIELDS = [
  ["voltiris", "", "tech.module_wp", "Module power", "Wp per module", "num"],
  ["battery", "", "tech.battery.c_rate", "C-rate", "kW per kWh bought", "num"],
  ["battery", "", "tech.battery.soc_min", "Lowest state of charge", "% of the size", "pct"],
  ["battery", "", "tech.battery.soc_max", "Highest state of charge", "% of the size", "pct"],
  ["battery", "", "tech.battery.efficiency_store", "Charging efficiency", "%", "pct"],
  ["battery", "", "tech.battery.efficiency_dispatch", "Discharging efficiency", "%", "pct"],
  ["battery", "", "tech.battery.self_discharge_per_day", "Self-discharge", "% per day", "pct"],
  ["reserve", "", "ancillary.reserve.mode", "How it is set", "", "select:percent|fixed_kwh"],
  ["reserve", "", "ancillary.reserve.frac", "Share", "% of the window and the power", "pct"],
  ["reserve", "", "ancillary.reserve.kwh", "Fixed size", "kWh (fixed_kwh)", "num"],
  ["commercial", "Business model", "business_model.price_per_mwh", "EaaS price", "per MWh of Voltiris energy used on site", "num"],
  ["commercial", "Investment prices", "capex.pv_per_wp", "Voltiris modules", "per Wp", "num"],
  ["commercial", "Investment prices", "capex.battery_tiers_per_kwh", "Battery price tiers", "kWh:price per kWh, …", "tiers"],
  ["commercial", "Investment prices", "capex.battery_replacement_frac", "Battery replacements", "% of the gross price", "pct"],
  ["commercial", "Lifetimes", "finance.pv_life_yr", "PV life", "years; the battery study's horizon", "num"],
  ["commercial", "Lifetimes", "finance.battery_life_yr", "Battery life", "years", "num"],
  ["commercial", "Ancillary services", "ancillary.rate_per_kw_year", "Revenue rate", "per reserved kW and year", "num"],
  ["subsidies", "Voltiris modules", "subsidies.pv.mode", "Mode", "", "select:percent|fixed|threshold"],
  ["subsidies", "Voltiris modules", "subsidies.pv.frac", "Share", "%", "pct"],
  ["subsidies", "Voltiris modules", "subsidies.pv.amount", "Amount", "fixed mode", "num"],
  ["subsidies", "Battery", "subsidies.battery.mode", "Mode", "", "select:percent|fixed|threshold"],
  ["subsidies", "Battery", "subsidies.battery.frac", "Share", "%", "pct"],
  ["subsidies", "Battery", "subsidies.battery.amount", "Amount", "fixed mode", "num"],
  ["subsidies", "Battery", "subsidies.battery.threshold_mode", "Threshold size from", "", "select:ocan|manual"],
  ["subsidies", "Battery", "subsidies.battery.threshold_kwh", "Threshold size", "kWh (manual)", "num"],
  ["subsidies", "Battery", "subsidies.battery.ocan_factor", "OCAN factor", "kWh per daily kWh of load", "num"],
  ["ems", "Costs", "ems.fixed_per_year", "Fixed cost", "per year", "num"],
  ["ems", "Costs", "ems.capex", "Hardware", "once, with the battery", "num"],
  ["ems", "Fees", "ems.savings_fee_pct.voltiris", "On the bill saving, Voltiris", "%", "pct"],
  ["ems", "Fees", "ems.savings_fee_pct.external", "On the bill saving, external", "%", "pct"],
  ["ems", "Fees", "ems.ancillary_fee_pct.voltiris", "On the ancillary revenue, Voltiris", "%", "pct"],
  ["ems", "Fees", "ems.ancillary_fee_pct.external", "On the ancillary revenue, external", "%", "pct"],
].map(([page, group, path, label, unit, kind]) => ({ page, group, path, label, unit, kind }));

function shown(f, v) {
  if (v === undefined || v === null) return "";
  if (f.kind === "pct") return String(+(v * 100).toFixed(6));
  if (f.kind === "tiers") return v.map((t) => `${t[0]}:${+Number(t[1]).toFixed(4)}`).join(", ");
  return String(v);
}
function parsed(f, text) {
  if (f.kind === "pct") return Number(text) / 100;
  if (f.kind === "num") return Number(text);
  if (f.kind === "tiers") return text.split(",").map((p) => p.split(":").map(Number)).filter((t) => t.length === 2 && t.every(isFinite));
  return text;
}
function currentOverrides() {
  let json = {};
  const text = $("jsonOverrides").value.trim();
  if (text) { try { json = JSON.parse(text); $("jsonError").textContent = ""; } catch (e) { $("jsonError").textContent = "Not valid JSON in the other overrides: " + e.message; } }
  const fields = {};
  Object.entries(S.fieldValues).forEach(([p, v]) => setPath(fields, p, v));
  return deepMerge(json, fields);
}

function renderKeyParams() {
  const d = S.params.defaults;
  ["voltiris", "battery", "reserve", "commercial", "subsidies", "ems"].forEach((page) => {
    const box = $("kp-" + page), groups = {};
    KEY_FIELDS.filter((f) => f.page === page && getPath(d, f.path) !== undefined)
      .forEach((f) => (groups[f.group] = groups[f.group] || []).push(f));
    box.innerHTML = "";
    Object.entries(groups).forEach(([group, fields]) => {
      const g = el("div", { class: group ? "pgroup" : "pgroup bare" }, group ? `<h3>${esc(group)}</h3>` : "");
      fields.forEach((f) => {
        const def = getPath(d, f.path), changed = f.path in S.fieldValues;
        const r = el("div", { class: "prow" + (f.kind === "tiers" ? " wide" : "") + (changed ? " changed" : "") });
        r.innerHTML = `<label>${esc(f.label)}<small>${esc(f.unit)}${f.unit ? " · " : ""}file: ${esc(shown(f, def))}</small></label>`;
        let input;
        if (f.kind.startsWith("select:")) {
          input = el("select", {}, `<option value="">${esc(def)} (file)</option>` + f.kind.slice(7).split("|").filter((o) => o !== def)
            .map((o) => `<option ${S.fieldValues[f.path] === o ? "selected" : ""}>${o}</option>`).join(""));
        } else {
          input = el("input", { placeholder: shown(f, def), inputmode: "decimal" });
          input.value = changed ? shown(f, S.fieldValues[f.path]) : "";
        }
        input.addEventListener("input", () => {
          const text = input.value.trim();
          const value = text === "" ? undefined : parsed(f, text);
          const same = value === undefined || JSON.stringify(value) === JSON.stringify(def) ||
            (typeof value === "number" && Math.abs(value - def) < 1e-12) || (typeof value === "number" && !isFinite(value));
          if (same) delete S.fieldValues[f.path]; else S.fieldValues[f.path] = value;
          r.classList.toggle("changed", !same);
          S.preview = null;
          loadParamsSoon();
        });
        r.appendChild(input);
        g.appendChild(r);
      });
      box.appendChild(g);
    });
  });
}

// what 100 kWh bought gives the optimiser, from the parameters in force (the rule of elements/battery/tech.py)
function renderBatteryLive() {
  const e = S.params && S.params.effective;
  if (!e || !e.tech || !e.tech.battery) return;
  const b = e.tech.battery, anc = e.ancillary || {}, r = anc.reserve || { mode: "percent", frac: 0 }, rate = anc.rate_per_kw_year || 0;
  const size = 100, window = size * (b.soc_max - b.soc_min);
  const reserved = r.mode === "fixed_kwh" ? Math.min(r.kwh || 0, window) : window * (r.frac || 0);
  const power = size * b.c_rate, reservedKw = window > 0 ? (power * reserved) / window : 0;
  const pct = (v, total) => `${Math.max(0, (v / total) * 100)}%`;
  const below = b.soc_min * size, above = (1 - b.soc_max) * size;
  $("pvBattery").innerHTML = `
    <div class="bbar"><div class="label">Energy: 100 kWh bought</div><div class="bar">
      <div class="seg-off" style="width:${pct(below, size)}">${fmt(below, 0)}</div>
      ${reserved > 0 ? `<div class="seg-res" style="width:${pct(reserved, size)}">reserve ${fmt(reserved, 0)}</div>` : ""}
      <div class="seg-use" style="width:${pct(window - reserved, size)}">optimiser ${fmt(window - reserved, 0)} kWh</div>
      <div class="seg-off" style="width:${pct(above, size)}">${fmt(above, 0)}</div></div></div>
    <div class="bbar"><div class="label">Power: ${fmt(power, 0)} kW (C-rate ${fmt(b.c_rate, 2)})</div><div class="bar">
      ${reservedKw > 0 ? `<div class="seg-res" style="width:${pct(reservedKw, power)}">reserve ${fmt(reservedKw, 1)} kW</div>` : ""}
      <div class="seg-use" style="width:${pct(power - reservedKw, power)}">optimiser ${fmt(power - reservedKw, 1)} kW</div></div></div>`;
  tiles("pvBatteryTiles", [
    ["Round trip", `${fmt(b.efficiency_store * b.efficiency_dispatch * 100, 1)} %`],
    ["Self-discharge", `${fmt(b.self_discharge_per_day * 100, 2)} %/day`],
    ["Reserve revenue", reservedKw > 0 ? `${money(reservedKw * rate)}/yr` : "off", reservedKw > 0 ? `${fmt(reservedKw, 1)} kW × ${fmt(rate, 1)} per kW` : "no reserve"],
  ]);
}

async function loadParams() {
  if (!$("mUtility").value) return;
  const c = collectCase();
  try {
    S.params = await api("/api/parameters", { run_type: RT().id, market: c.market,
      business_model: c.general.commercial.business_model, overrides: c.overrides });
  } catch (e) { $("paramsError").textContent = e.message; return; }
  $("paramsError").textContent = S.params.error ? "These overrides cannot be applied, the file values are shown: " + S.params.error : "";
  $("mCurrency").textContent = `Money is in ${S.params.currency} for the whole run. Shared prices (battery, PV, EMS, EaaS) are converted from CHF/EUR with the exchange rate file.`;
  ["curCommercial", "curSubsidies", "curEms"].forEach((id) => ($(id).textContent = `in ${S.params.currency}`));
  renderKeyParams();
  renderParamBlocks(c.overrides);
  renderBatteryLive();
  const regimes = getPath(S.params.effective, "tariff.regimes") || ["default"];
  const keep = S.manualRegime || $("sRegime").value;
  fillSelect("sRegime", regimes.map((r) => [r, r]));
  if (regimes.includes(keep)) $("sRegime").value = keep;
}
const loadParamsSoon = debounce(loadParams, 400);
$("jsonOverrides").addEventListener("input", () => { S.preview = null; loadParamsSoon(); });

function renderParamBlocks(overrides) {
  const eff = S.params.effective, src = S.params.sources;
  const changed = flatten(overrides);
  $("paramBlocks").innerHTML = (changed.length ? `<p class="hint">Changed for this run: ${changed.map(([k, v]) => `<code>${esc(k)} = ${esc(JSON.stringify(v))}</code>`).join(" ")}</p>` : "") +
    Object.keys(eff).map((block) => `<details class="pblock"><summary><b>${block}</b> <span class="muted">${(src[block] || { files: [] }).files.join(" + ") || "—"}</span></summary>
      ${((src[block] || {}).about || []).map((a) => `<p class="about">${esc(a)}</p>`).join("")}
      <pre class="code">${esc(JSON.stringify(stripNotes(eff[block]), null, 2))}</pre></details>`).join("");
}
function stripNotes(o) {
  if (Array.isArray(o)) return o.map(stripNotes);
  if (o && typeof o === "object") return Object.fromEntries(Object.entries(o).filter(([k]) => k !== "_about").map(([k, v]) => [k, stripNotes(v)]));
  return o;
}

// -- battery: sizing ----------------------------------------------------------------------------------------------------
const OBJECTIVE_HINT = {
  profit: "The highest lifetime profit (yearly value × battery life − investment) among the sizes that pay back within the battery life; if none does, the shortest payback.",
  payback: "The shortest payback among the sizes tested.",
  custom: "The tested size closest to the custom size, which is added to the list.",
};
function objectiveChanged() {
  const o = document.querySelector("input[name=objective]:checked").value;
  $("objHint").textContent = OBJECTIVE_HINT[o];
  $("customRow").hidden = o !== "custom";
}
["sModules", "sImport", "sExport", "sRegime", "sAncillary", "zCustom", "zSweep", "zFine", "zWindow", "zCap"].forEach((id) =>
  $(id).addEventListener("change", () => { S.preview = null; updateTop(); if (id === "sAncillary") loadParamsSoon(); checkSetupSoon(); }));
document.querySelectorAll("input[name=regimeMode]").forEach((r) => r.addEventListener("change", () => { S.preview = null; checkSetupSoon(); }));
document.querySelectorAll("input[name=objective]").forEach((r) => r.addEventListener("change", () => { objectiveChanged(); S.preview = null; checkSetupSoon(); }));
$("checkSetup").addEventListener("click", () => checkSetup(false));
$("zDefault").addEventListener("click", () => { $("zSweep").value = RT().sizing_defaults.sweep_kwh.join(", "); S.preview = null; checkSetupSoon(); });
const checkSetupSoon = debounce(() => checkSetup(true), 500);

// sizes from a range and an interval
function rangeList() {
  const from = Number($("gFrom").value), to = Number($("gTo").value), step = Number($("gStep").value);
  if (!(from > 0) || !(to >= from) || !(step > 0)) return { error: "Give From > 0, To at least From, and Every > 0." };
  const count = Math.floor((to - from) / step + 1e-9) + 1;
  if (count > 300) return { error: `That is ${fmt(count)} sizes; keep it under 300 (each takes a few seconds).` };
  return { list: Array.from({ length: count }, (_, i) => +(from + i * step).toFixed(3)) };
}
function rangeInfo() {
  const r = rangeList();
  if (r.error) { $("gInfo").textContent = r.error; return r; }
  $("gInfo").textContent = `${r.list.length} size${r.list.length > 1 ? "s" : ""}, about ${fmt(r.list.length * 6 / 60, 1)} min to solve`;
  return r;
}
["gFrom", "gTo", "gStep"].forEach((id) => $(id).addEventListener("input", rangeInfo));
function applyRange(add) {
  const r = rangeInfo(); if (r.error) return toast(r.error, true);
  const target = $($("gTarget").value);
  const list = add ? [...new Set(numbers(target.value).concat(r.list))].sort((a, b) => a - b) : r.list;
  target.value = list.join(", ");
  S.preview = null; checkSetupSoon();
  toast(`${target.id === "zFine" ? "Fine grid" : "Sizes to test"}: ${list.length} sizes`);
}
$("gReplace").addEventListener("click", () => applyRange(false));
$("gAdd").addEventListener("click", () => applyRange(true));
rangeInfo();

// -- the setup check (no solve) ---------------------------------------------------------------------------------------
// the blocks that still need their input file (the grid's is optional: the setup check says if its tariff needs it)
function missingFiles() {
  return chosenBlocks().filter((id) => isBuilt(id) && hasData(id) && id !== "grid" && !S.data[id].path);
}

async function checkSetup(quiet) {
  if (quiet && (!["battery", "market", "commercial", "subsidies", "run"].includes(S.step) || S.preview)) return;
  if (!S.runType) { if (!quiet) toast("No model can run the system of the System page yet.", true); return; }
  const missing = missingFiles();
  if (missing.length) { if (!quiet) toast(`Give the input file of: ${missing.map((b) => blockInfo(b).name).join(", ")}.`, true); return; }
  $("checkInfo").textContent = "Building the run context…";
  try {
    S.preview = await api("/api/preview", { case: collectCase() });
    $("checkInfo").textContent = "Setup checked: nothing has been solved yet.";
    renderPreview();
  } catch (e) {
    $("checkInfo").textContent = "";
    $("zPlan").textContent = "The setup has a problem: " + e.message;
    toast(e.message, true);
  }
}

function renderPreview() {
  const p = S.preview, s = p.site, m = p.money, t = p.tariff;
  document.querySelectorAll(".pv-part").forEach((x) => (x.hidden = false));
  tiles("pvSite", [
    ["Yearly load", `${fmt(s.load_mwh, 0)} MWh`, `peak ${fmt(s.load_peak_kw, 0)} kW`],
    ["Voltiris PV", `${fmt(s.voltiris_kwp, 1)} kWp`, `${fmt(s.modules)} modules · ${fmt(s.voltiris_mwh, 1)} MWh/yr`],
    ["Existing PV", `${fmt(s.existing_mwh, 1)} MWh`, has("existing_pv") ? "with the Voltiris PV, behind one meter" : "not in the system"],
    ["PV surplus without battery", `${fmt(s.pv_surplus_mwh, 1)} MWh`, `of ${fmt(s.pv_mwh, 1)} MWh PV`],
    ["Grid import limit", `${fmt(p.grid.import_max_kw, 0)} kW`, p.grid.import_auto ? "automatic" : "from the Grid page"],
    ["Grid export limit", `${fmt(p.grid.export_max_kw, 0)} kW`, p.grid.export_auto ? "automatic" : "from the Grid page"],
    ["One-meter rules", `${fmt(p.meter.export_pays_more_h, 0)} h`, `exporting pays more · ${fmt(p.meter.negative_price_h, 1)} h negative price`],
  ]);
  tiles("pvMoney", [
    ["Business model", t.business_model === "eaas" ? (t.eaas ? "EaaS" : "EaaS (inactive: 0 modules)") : "Direct sales"],
    has("voltiris") && ["Voltiris modules", money(m.pv_capex), `${fmt(s.modules)} modules, before subsidy`],
    has("battery") && ["Battery price", `${money(m.price_per_kwh_at["100"])}/kWh`, `at 100 kWh · ${money(m.price_per_kwh_at["1000"])}/kWh at 1,000 kWh`],
    ["Lifetimes", `${fmt(m.pv_life_yr)} / ${fmt(m.battery_life_yr)} yr`, "PV (the study's horizon) / battery"],
  ]);
  tiles("pvSubsidy", [
    has("battery") && ["100 kWh of battery after subsidy", money(m.price_after_subsidy_100), `${m.subsidy_mode}${m.subsidy_frac ? ` ${fmt(m.subsidy_frac * 100, 0)} %` : ""}`],
    has("battery") && m.subsidy_mode === "threshold" && ["Subsidised maximum", `${fmt(m.subsidy_threshold_kwh, 0)} kWh`, "OCAN: yearly load / 365 × factor"],
    has("voltiris") && ["Voltiris modules", `${m.pv_subsidy_mode}${m.pv_subsidy_frac ? ` ${fmt(m.pv_subsidy_frac * 100, 0)} %` : " 0 %"}`],
  ]);
  const r = p.regime;
  tiles("pvTariff", [
    ["Starting regime", r.start, r.dup_h != null ? `DUP ${fmt(r.dup_h, 0)} h without battery · threshold ${fmt(t.threshold_h, 0)} h` : (r.auto ? "the tariff has no regime rule" : "fixed on the Grid page")],
    ["Regimes", t.regimes.join(" / "), t.has_rule ? "chosen by the DUP rule" : "chosen on the Grid page"],
    ["Energy price", t.uses_day_ahead ? "day-ahead based" : "fixed by period", `export value ${fmt(t.export_value_mean, 4)} ${cur()}/kWh on average`],
    ["Capacity charges", t.capacity_charges.length ? t.capacity_charges.join(", ") : "none"],
    ["Battery export", t.battery_export === "pv_only" ? "PV energy only" : "any energy"],
  ]);
  $("pvPrices").innerHTML = `<tr><th>Import price, ${cur()}/kWh</th><th>Mean</th><th>Weighted by load</th><th>Lowest</th><th>Highest</th></tr>` +
    Object.entries(t.import_price).map(([reg, v]) => `<tr${reg === r.start ? ' class="hl"' : ""}><td>Regime ${esc(reg)}</td><td>${fmt(v.mean, 4)}</td><td>${fmt(v.weighted, 4)}</td><td>${fmt(v.min, 4)}</td><td>${fmt(v.max, 4)}</td></tr>`).join("");
  const z = p.sizing;
  $("zPlan").innerHTML = `The model will solve <b>${z.sizes.length} sizes</b>: ${z.sizes.map((x) => fmt(x)).join(", ")} kWh` +
    (z.cap ? ` (the list stops at the subsidised maximum, ${fmt(z.cap)} kWh)` : "") +
    (z.fine_grid_kwh && z.fine_grid_kwh.length ? `, then those of ${z.fine_grid_kwh.map((x) => fmt(x)).join(", ")} kWh that are within ${fmt(z.fine_window_kwh)} kWh of the best size` : "") +
    `. Objective: <b>${z.objective}</b>${z.objective === "custom" ? ` (${fmt(z.custom_kwh)} kWh)` : ""}.` +
    (t.has_rule ? ` Sizes whose DUP crosses ${fmt(t.threshold_h)} h are solved twice more.` : "");
}

// -- run ------------------------------------------------------------------------------------------------------------
$("runBtn").addEventListener("click", async () => {
  if (!S.runType) return toast("No model can run the system of the System page yet.", true);
  const missing = missingFiles();
  if (missing.length) { toast(`Give the input file of: ${missing.map((b) => blockInfo(b).name).join(", ")}.`, true); return showStep(missing[0]); }
  if ($("jsonError").textContent) return toast("Fix the JSON overrides first.", true);
  try {
    const r = await api("/api/run", { case: collectCase(), output_dir: $("rFolder").value.trim() });
    $("runInfo").textContent = `Results will be written to ${r.output_dir}`;
    $("runCard").hidden = false; $("runLog").textContent = ""; $("runError").textContent = "";
    $("runSteps").innerHTML = S.options.run_types[r.run_type].stages.map((s) =>
      `<li data-stage="${s.stage}">${esc(s.label)}${s.counts ? ' <span class="count"></span>' : ""}</li>`).join("");
    S.logLength = 0; $("runBtn").disabled = true;
    const t = $("topStatus"); t.dataset.state = "running"; t.className = "top-status running"; t.textContent = `Running ${r.tag}…`;
    clearInterval(S.polling); S.polling = setInterval(poll, 1000); poll();
  } catch (e) { toast(e.message, true); }
});
async function poll() {
  let st;
  try { st = await api(`/api/status?since=${S.logLength}`); } catch (e) { return; }
  if (st.log.length) {
    const log = $("runLog");
    log.textContent += st.log.join("");
    log.scrollTop = log.scrollHeight;
    S.logLength = st.log_length;
  }
  $("runElapsed").textContent = `${fmt(st.elapsed, 0)} s`;
  const items = [...document.querySelectorAll("#runSteps li")];
  const reached = items.map((li) => Number(li.dataset.stage)).filter((s) => s <= st.stage);
  const current = reached.length ? Math.max(...reached) : null;
  items.forEach((li) => {
    const stage = Number(li.dataset.stage);
    li.className = st.state === "done" || (current !== null && stage < current) ? "done"
      : stage === current && st.state === "running" ? "active" : "";
    const count = li.querySelector(".count");
    if (count) count.textContent = st.done ? `(${st.done} solved)` : "";
  });
  if (st.state === "running") return;
  clearInterval(S.polling); $("runBtn").disabled = !S.runType;
  const t = $("topStatus"); t.dataset.state = st.state;
  if (st.state === "error") { $("runError").textContent = st.error; updateTop(); return toast("The run failed: " + st.error, true); }
  if (st.state === "done") {
    S.results = await api("/api/results");
    updateTop();
    toast(`Done in ${fmt(st.elapsed, 0)} s`);
    showStep("results");
    renderResults();
  }
}

// -- results --------------------------------------------------------------------------------------------------------
function renderTable(id, data, opts = {}) {
  const plainIndex = data.index.every((v, i) => v === i);
  const head = (plainIndex ? [] : [opts.indexLabel || ""]).concat(data.columns.map((c) => (opts.rename || {})[c] || c));
  const rows = data.rows.map((row, i) => {
    const cells = (plainIndex ? [] : [data.index[i]]).concat(row);
    const cls = opts.highlight && opts.highlight(row, i, data) ? ' class="hl"' : "";
    return `<tr${cls}>${cells.map((v, j) => `<td${typeof v === "string" && j > 0 ? ' class="text"' : ""}>${esc(opts.format ? opts.format(v, j) : auto(v))}</td>`).join("")}</tr>`;
  });
  $(id).innerHTML = `<tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>` + rows.join("");
}

function renderResults() {
  const R = S.results;
  document.querySelectorAll(".res-body").forEach((b) => (b.hidden = b.id !== "res-" + R.view));
  $("resFilesCard").hidden = false;
  $("resFiles").textContent = `Written to ${R.files.folder} · model: ${S.options.run_types[R.run_type].name}`;
  $("resSummary").innerHTML = `<tr><th>Field</th><th>Value</th></tr>` + Object.entries(R.summary).filter(([k]) => k !== "sweep")
    .map(([k, v]) => `<tr><td><code>${k}</code></td><td>${esc(typeof v === "number" ? auto(v) : v === null ? "–" : String(v))}</td></tr>`).join("");
  if (R.view === "battery_study") renderBatteryStudy();
}

function renderBatteryStudy() {
  const R = S.results, s = R.summary, c = s.currency;
  const m = (v, d = 0) => `${fmt(v, d)} ${c}`;
  $("resLead").textContent = `${s.site_tag} · ${s.country} ${s.region} ${s.utility} · ${s.pv_modules} Voltiris modules (${s.voltiris_model}) · ancillary services ${R.choice.ancillary_on ? "on" : "off"}`;
  tiles("resTiles", [
    ["Chosen battery", `${fmt(s.battery_kwh)} kWh`, `regime ${s.regime_battery} (${s.regime_no_battery} without battery)`, "accent"],
    ["Yearly value", m(s.battery_value_yr), "bill saving + ancillary − EMS"],
    ["Investment", m(s.battery_investment), `battery after subsidy ${m(s.battery_net_capex)} + EMS ${m(s.ems_capex)}`],
    ["Payback", s.battery_payback_yr == null ? "never" : `${fmt(s.battery_payback_yr, 1)} yr`],
    ["Lifetime profit", m(s.battery_lifetime_profit), "value × battery life − investment"],
    ["Ancillary revenue", R.choice.ancillary_on ? `${m(s.battery_ancillary_yr)}/yr` : "off"],
    ["Cycles", `${fmt(s.battery_cycles, 0)} per year`],
    ["Self-sufficiency", `${fmt(s.ss_no_battery, 1)} → ${fmt(s.ss_battery, 1)} %`, `self-consumption ${fmt(s.sc_no_battery, 1)} → ${fmt(s.sc_battery, 1)} %`],
  ]);
  renderWhy();
  drawYear();
  // value breakdown
  const parts = [
    ["Self-consumption", s.battery_sc_saving_yr], ["Arbitrage", s.battery_arbitrage_yr],
    ["Capacity charges saved", s.battery_peak_demand_yr], ["Regime switch", s.battery_regime_switch_yr],
    ["Ancillary revenue", s.battery_ancillary_yr], ["EMS costs", -s.battery_ems_yr],
  ];
  chart("resValue", { type: "bar", data: { labels: parts.map((p) => p[0]).concat("Yearly value"),
    datasets: [{ data: parts.map((p) => p[1]).concat(s.battery_value_yr),
      backgroundColor: parts.map((p) => (p[1] >= 0 ? COLORS.accent : COLORS.neg)).concat(COLORS.load) }] },
    options: { indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: { title: { display: true, text: `${c} per year` } } } } });
  const rows = [
    ["Self-consumption: PV surplus stored instead of exported", s.battery_sc_saving_yr],
    ["Arbitrage: grid energy bought cheap, used dear", s.battery_arbitrage_yr],
    ["Energy savings", s.battery_energy_savings_yr, "total"],
    ["Capacity charges saved", s.battery_peak_demand_yr],
    ["Regime switch", s.battery_regime_switch_yr],
    ["Peak shaving", s.battery_peak_shaving_yr, "total"],
    ["Ancillary revenue", s.battery_ancillary_yr],
    ["EMS: fixed cost and fees", -s.battery_ems_yr],
    ["Yearly value", s.battery_value_yr, "total"],
  ];
  $("resValueTable").innerHTML = `<tr><th>Part</th><th>${c}/yr</th></tr>` +
    rows.map(([k, v, cls]) => `<tr${cls ? ` class="${cls}"` : ""}><td class="text">${esc(k)}</td><td>${fmt(v, 0)}</td></tr>`).join("");
  // sweep
  const sw = R.sweep, col = (n) => sw.columns.indexOf(n);
  const sizes = sw.rows.map((r) => r[col("size")]);
  chart("resSweep", { type: "bar", data: { labels: sizes.map((x) => `${fmt(x)} kWh`), datasets: [
    { type: "bar", label: `Yearly value, ${c}`, data: sw.rows.map((r) => r[col("bat_value")]),
      backgroundColor: sizes.map((x) => (x === s.battery_kwh ? COLORS.accent : "#9fd3cd")), yAxisID: "y", order: 2 },
    { type: "line", label: "Payback, years", data: sw.rows.map((r) => r[col("payback")]), borderColor: COLORS.load,
      backgroundColor: COLORS.load, pointRadius: 3, yAxisID: "y1", order: 1 },
    { type: "line", label: `Battery life, ${fmt(R.choice.battery_life_yr)} years (payback limit)`,
      data: sizes.map(() => R.choice.battery_life_yr), borderColor: COLORS.grey, backgroundColor: COLORS.grey,
      borderDash: [6, 4], borderWidth: 1.4, pointRadius: 0, yAxisID: "y1", order: 0 }] },
    options: { scales: { y: { title: { display: true, text: `${c} per year` } },
      y1: { position: "right", grid: { display: false }, title: { display: true, text: "years" }, beginAtZero: true } } } });
  renderTable("resSweepTable", sw, { rename: { size: "Size, kWh", bat_value: `Value, ${c}/yr`, investment: `Investment, ${c}`,
    payback: "Payback, yr", ss: "SS, %", sc: "SC, %", lifetime_profit: `Lifetime profit, ${c}`, ems_fees: `EMS fees, ${c}/yr`,
    dup: "DUP, h", regime: "Regime", dup_lock: "DUP held in" },
    highlight: (row) => row[col("size")] === s.battery_kwh, format: (v, j) => (j === col("payback") ? fmt(v, 1) : auto(v)) });
  // with / without
  const cmp = [
    ["Yearly bill", s.bill_no_battery, s.bill_battery, c],
    ["Grid import", s.import_mwh_no_battery, s.import_mwh_battery, "MWh"],
    ["Grid export", s.export_mwh_no_battery, s.export_mwh_battery, "MWh"],
    ["Self-consumption", s.sc_no_battery, s.sc_battery, "%"],
    ["Self-sufficiency", s.ss_no_battery, s.ss_battery, "%"],
    s.eaas_fee_battery ? ["EaaS fee", s.eaas_fee_no_battery, s.eaas_fee_battery, c] : null,
  ].filter(Boolean);
  $("resCompare").innerHTML = `<tr><th></th><th>Without battery</th><th>With ${fmt(s.battery_kwh)} kWh</th><th>Change</th><th>Unit</th></tr>` +
    cmp.map(([k, a, b, u]) => `<tr><td>${k}</td><td>${auto(a)}</td><td>${auto(b)}</td><td>${auto(b - a)}</td><td>${u}</td></tr>`).join("") +
    `<tr><td>Regime</td><td>${s.regime_no_battery}</td><td>${s.regime_battery}</td><td></td><td></td></tr>`;
  renderTable("resBills", R.bills, { indexLabel: `Component, ${c}/yr` });
  // monthly, payback
  renderMonthly();
  renderTable("resPayback", R.payback);
  // dispatch
  drawDispatch();
}
function renderWhy() {
  const R = S.results, s = R.summary, ch = R.choice, c = s.currency, life = ch.battery_life_yr;
  const sw = R.sweep, col = (n) => sw.columns.indexOf(n);
  const rows = sw.rows.map((r) => ({ size: r[col("size")], value: r[col("bat_value")], inv: r[col("investment")],
    pb: r[col("payback")], profit: r[col("lifetime_profit")], regime: r[col("regime")], lock: r[col("dup_lock")] }))
    .sort((a, b) => a.size - b.size);
  const chosen = rows.find((r) => r.size === s.battery_kwh) || {};
  const pays = (r) => r.pb != null && r.pb <= life;
  const paying = rows.filter(pays);
  const pbText = (r) => (r.pb == null ? "never" : `${fmt(r.pb, 1)} years`);
  const kwh = (x) => `<b>${fmt(x)} kWh</b>`;
  let why;
  if (ch.objective === "profit" && paying.length) {
    const next = paying.filter((r) => r !== chosen).sort((a, b) => b.profit - a.profit)[0];
    why = `Objective <b>profit</b>. ${paying.length} of the ${rows.length} sizes tested pay back within the battery life of ${fmt(life)} years. ` +
      `Among them ${kwh(chosen.size)} has the highest lifetime profit: ${fmt(chosen.value)} ${c}/yr &times; ${fmt(life)} years &minus; ${fmt(chosen.inv)} ${c} = <b>${fmt(chosen.profit)} ${c}</b>.` +
      (next ? ` Next best: ${fmt(next.size)} kWh with ${fmt(next.profit)} ${c}.` : "");
  } else if (ch.objective === "profit") {
    why = `Objective <b>profit</b>, but none of the ${rows.length} sizes tested pays back within the battery life of ${fmt(life)} years, ` +
      (rows.every((r) => r.pb == null) ? `and none pays back at all (yearly value zero or negative), so the first size in the list, ${kwh(chosen.size)}, is kept. Treat it as "no battery is worth it" under these settings.`
        : `so the size with the shortest payback is kept: ${kwh(chosen.size)}, ${pbText(chosen)}.`);
  } else if (ch.objective === "payback") {
    why = `Objective <b>payback</b>: ${kwh(chosen.size)} has the shortest payback of the ${rows.length} sizes tested, ${pbText(chosen)}.`;
  } else {
    why = `Objective <b>custom</b>: ${kwh(chosen.size)} is the tested size closest to the size you gave, ${fmt(ch.custom_kwh)} kWh.`;
  }
  const notes = [];
  const largest = rows[rows.length - 1].size, smallest = rows[0].size;
  if (ch.cap && chosen.size === ch.cap) notes.push(`The list stopped at ${fmt(ch.cap)} kWh, the largest subsidised size (OCAN rule), and that is the size chosen.`);
  else if (ch.objective !== "custom" && chosen.size === largest && rows.length > 1) notes.push(`The chosen size is the largest one tested: a larger battery might do better. Extend the list on the Battery page to check.`);
  else if (ch.objective !== "custom" && chosen.size === smallest && rows.length > 1 && chosen.value > 0) notes.push(`The chosen size is the smallest one tested: a smaller battery might do better. Extend the list on the Battery page to check.`);
  const fine = rows.filter((r) => !ch.first_stage.includes(r.size)).map((r) => fmt(r.size));
  if (fine.length) notes.push(`${fine.join(", ")} kWh came from the fine grid, solved after the first list.`);
  if (chosen.regime !== s.regime_no_battery) notes.push(`This size is billed under regime ${chosen.regime}, not the starting regime ${s.regime_no_battery}: its hours of use crossed the threshold${chosen.lock ? `, and the DUP was held in regime ${chosen.lock}` : ""}.`);
  $("resWhy").innerHTML = why + (notes.length ? "<br>" + notes.join(" ") : "");
  $("resWhyTable").innerHTML = `<tr><th>Size, kWh</th><th>Yearly value, ${c}</th><th>Investment, ${c}</th><th>Payback</th><th>Within ${fmt(life)} yr</th><th>Lifetime profit, ${c}</th><th>Regime</th><th></th></tr>` +
    rows.map((r) => `<tr${r === chosen ? ' class="hl"' : ""}><td>${fmt(r.size)}</td><td>${fmt(r.value)}</td><td>${fmt(r.inv)}</td>
      <td>${pbText(r)}</td><td class="${pays(r) ? "yes" : "no"}">${pays(r) ? "yes" : "no"}</td><td>${fmt(r.profit)}</td>
      <td>${esc(r.regime)}${r.lock ? ` (DUP held in ${esc(r.lock)})` : ""}</td><td>${r === chosen ? '<span class="tag">chosen</span>' : ""}</td></tr>`).join("");
  $("resWhyNote").textContent = `Payback and lifetime profit use the battery life of ${fmt(life)} years (Commercial page, Lifetimes). Yearly value = bill saving + ancillary revenue − EMS costs; investment = battery after subsidy + EMS hardware.`;
}

function drawYear() {
  const d = S.results.daily, n = d.load.length;
  const t0 = new Date(d.start + "Z").getTime();
  const labels = Array.from({ length: n }, (_, i) => new Date(t0 + i * 864e5).toISOString().slice(0, 10));
  const x = { ticks: monthTicks, grid: { display: false } };
  chart("resYear", { type: "line", data: { labels, datasets: [
    line("Load", d.load, COLORS.load), line("PV", d.pv, COLORS.pv),
    line("Grid import", d.grid_import, COLORS.imp), line("Grid export", d.grid_export, COLORS.exp),
  ] }, options: { scales: { x, y: { beginAtZero: true, title: { display: true, text: "kWh per day" } } } } });
  chart("resYearBattery", { type: "bar", data: { labels, datasets: [
    { type: "bar", label: "Discharged, kWh", data: d.discharged, backgroundColor: COLORS.bat, yAxisID: "y", order: 2 },
    { type: "bar", label: "Charged, kWh", data: d.charged.map((v) => -v), backgroundColor: "#9fd3cd", yAxisID: "y", order: 3 },
    { type: "line", label: "Highest state of charge, kWh", data: d.soc_max, borderColor: COLORS.soc, backgroundColor: COLORS.soc,
      borderWidth: 1.4, pointRadius: 0, yAxisID: "y", order: 1 },
  ] }, options: { scales: { x: { ...x, stacked: true }, y: { stacked: false, title: { display: true, text: "kWh per day" } } } } });
  $("resYearWindow").textContent = fmt(S.results.choice.dispatch_kwh_per_kwh * S.results.summary.battery_kwh);
}

function renderMonthly() {
  if (!S.results || S.results.view !== "battery_study") return;
  renderTable("resMonthly", S.results[S.monthlyTab], { indexLabel: "Month" });
}
document.querySelectorAll("#resMonthlyTabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("#resMonthlyTabs button").forEach((x) => x.classList.toggle("active", x === b));
  S.monthlyTab = b.dataset.tab; renderMonthly();
}));
function drawDispatch() {
  const d = S.results && S.results.dispatch; if (!d) return;
  const week = Number($("resWeek").value), from = week * 168, n = Math.min(168, d.load.length - from);
  const labels = hourLabels(d.start, from, n), sl = (a) => (a || []).slice(from, from + n);
  $("resWeekLabel").textContent = `${labels[0].slice(0, 10)} to ${labels[n - 1].slice(0, 10)}`;
  const x = { ticks: dayTicks, grid: { display: false } };
  chart("resDispatch", { type: "line", data: { labels, datasets: [
    line("Load", sl(d.load), COLORS.load), line("PV", sl(d.pv), COLORS.pv),
    line("Grid import", sl(d.grid_import), COLORS.imp), line("Grid export", sl(d.grid_export), COLORS.exp),
    line("Battery power", sl(d.battery_power), COLORS.bat, { borderWidth: 2, fill: { target: "origin", above: "rgba(15,118,110,.12)", below: "rgba(15,118,110,.12)" } }),
  ] }, options: { scales: { x, y: { title: { display: true, text: "kW" } } } } });
  chart("resSoc", { type: "line", data: { labels, datasets: [
    line("State of charge, kWh", sl(d.battery_soc), COLORS.soc, { fill: { target: "origin" }, backgroundColor: "rgba(124,58,237,.12)" }),
  ] }, options: { scales: { x, y: { beginAtZero: true, title: { display: true, text: "kWh" } } } } });
}
$("resWeek").addEventListener("input", drawDispatch);
$("openFolder").addEventListener("click", async () => {
  try { await api("/api/open-folder", { path: S.results.files.folder }); } catch (e) { toast(e.message, true); }
});

// -- start ----------------------------------------------------------------------------------------------------------
(async function init() {
  try { S.options = await api("/api/options"); } catch (e) { return toast("The server does not answer: " + e.message, true); }
  S.pendingStep = decodeURIComponent(location.hash.slice(1)) || null;
  Object.keys(S.options.block_columns).forEach((id) => (S.data[id] = { path: "", columns: {}, info: null }));
  makeViewer($("viewer-all"), "all", () => curveSeries(chosenBlocks().filter(hasData)), true);
  fillSelect("caseSelect", S.options.cases.map((c) => [c.path, c.name]), "— choose —");
  fillSelect("presetSelect", S.options.presets.map((p) => [p.id, p.name]), "— your own system —");
  fillSelect("mBusiness", RT().business_models.map((b) => [b, b === "eaas" ? "EaaS: Voltiris owns them" : "Direct sales: the grower buys them"]));
  setMarket();
  $("zSweep").placeholder = RT().sizing_defaults.sweep_kwh.join(", ");
  objectiveChanged();
  const first = S.options.cases.find((c) => c.name.startsWith("blocks/")) || S.options.cases[0];
  if (first) {
    $("caseSelect").value = first.path;
    $("caseLoad").click();
  } else {
    $("caseNew").click();
  }
})();

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
  bat: "#0f766e", soc: "#7c3aed", da: "#dc2626", neg: "#b42318", accent: "#0f766e", grey: "#94a3b8",
  heat: "#ea580c", co2: "#64748b", gas: "#0891b2" };
const CONVERSION = { power: "repeated", price: "repeated", state: "repeated", energy: "divided", time: "rebuilt" };
// the general items: what is not a physical block, and when its page is shown
const GENERAL = [
  { id: "market", name: "Market", small: "country, tariff, currency", show: () => true },
  { id: "commercial", name: "Commercial", small: "business model, prices, lifetimes", show: () => has("voltiris") || has("battery") || has("ng_boiler") },
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
  if (Math.abs(v) < 0.5 * 10 ** -digits) v = 0;   // no "-0"
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
    if (!d.path) return id === "grid" ? "connection, regime" : !fileOptional(id) ? "no input file yet" : id === "gas_supply" ? "fixed price" : "losses, sizing";
    return (d.info && d.info.error ? "problem · " : d.info && d.info.converted ? "→ 15 min · " : "") + fileName(d.path);
  }
  return id === "battery" ? "technology, reserve, sizing" : id === "ng_boiler" ? "efficiency, sizing" : "settings";
}
// the menu's groups (the blocks under System, the items under General) can be folded; the choice is kept in this browser
S.navFolded = new Set();
try { S.navFolded = new Set(JSON.parse(localStorage.getItem("navFolded") || "[]")); } catch (e) { /* no storage: all open */ }
function renderNav() {
  const item = (step, title, small, cls = "") => `<button data-step="${step}" class="sub ${cls}" title="${esc(title)}: ${esc(small)}"><i></i><span>${esc(title)}<small>${esc(small)}</small></span></button>`;
  const fold = (group, count) => `<button type="button" class="caret" data-group="${group}" aria-expanded="${!S.navFolded.has(group)}" title="${S.navFolded.has(group) ? `Show the ${count} items` : "Hide the items"}">${S.navFolded.has(group) ? "&#9656;" : "&#9662;"}</button>`;
  const sub = (group, html) => `<div class="nav-sub" data-group="${group}"${S.navFolded.has(group) ? " hidden" : ""}>${html}</div>`;
  const blocks = chosenBlocks(), general = generalShown();
  $("steps").innerHTML =
    `<div class="nav-row"><button data-step="system"><b>1</b><span>System<small>the greenhouse and its blocks</small></span></button>${fold("system", blocks.length)}</div>` +
    sub("system", blocks.map((id) => item(pageOf(id), blockInfo(id).name, blockSmall(id), isBuilt(id) ? "" : "planned")).join("")) +
    `<button data-step="inputs"><b>2</b><span>Input data<small>every curve: year, month, week</small></span></button>` +
    `<div class="nav-row"><div class="nav-group"><b>3</b><span>General<small>not tied to one block</small></span></div>${fold("general", general.length)}</div>` +
    sub("general", general.map((g) => item(g.id, g.name, g.small)).join("")) +
    `<button data-step="run"><b>4</b><span>Run<small>check, case file, progress</small></span></button>` +
    `<button data-step="results" class="${S.results ? "done" : ""}"><b>5</b><span>Results<small>electricity, sizes, bills, dispatch</small></span></button>`;
  $("steps").querySelectorAll("button[data-step]").forEach((b) => {
    b.classList.toggle("active", b.dataset.step === S.step);
    b.addEventListener("click", () => showStep(b.dataset.step));
  });
  $("steps").querySelectorAll("button.caret").forEach((b) => b.addEventListener("click", () => {
    const g = b.dataset.group;
    if (S.navFolded.has(g)) S.navFolded.delete(g); else S.navFolded.add(g);
    try { localStorage.setItem("navFolded", JSON.stringify([...S.navFolded])); } catch (e) { /* the choice lasts until reload */ }
    renderNav();
  }));
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
  if (["voltiris", "battery", "gas_supply", "ng_boiler", "thermal_storage", "market", "commercial", "subsidies", "ems", "run"].includes(step)) loadParams();
  if (CHECKED_PAGES.includes(step)) checkSetup(true);
  if (step === "run") renderCaseFile();
  if (hasData(step)) drawViewer("blk-" + step);
  if (step === "inputs") { renderFilesTable(); drawViewer("all"); }
  if (step === "results" && S.results) Object.values(S.charts).forEach((c) => c.resize());
}

// the menu can be hidden; the choice is kept in this browser
function setNav(hidden) {
  document.body.classList.toggle("nav-hidden", hidden);
  $("navToggle").setAttribute("aria-expanded", String(!hidden));
  try { localStorage.setItem("navHidden", hidden ? "1" : "0"); } catch (e) { /* storage blocked: the choice lasts until reload */ }
  Object.values(S.charts).forEach((c) => c.resize());
}
$("navToggle").addEventListener("click", () => setNav(!document.body.classList.contains("nav-hidden")));
try { if (localStorage.getItem("navHidden") === "1") setNav(true); } catch (e) { /* no storage: the menu shows */ }

// -- the System page: the greenhouse drawing -------------------------------------------------------------------------
const RT = () => S.options.run_types[S.runType] || Object.values(S.options.run_types)[0];
const CARRIER_COLOR = { electricity: "#e0a100", heat: "#dc2626", co2: "#64748b", "low-temperature heat": "#f97316",
  gas: "#0891b2" };
const NODE = { w: 158, h: 50 };
const GH = { x0: 410, x1: 590, peak: 178, eave: 206, base: 326, spans: 4 };
// where each carrier enters the greenhouse: electricity on the left, heat on the right, CO2 top right; units below
// the greenhouse enter from below
const PORT = { electricity: [GH.x0, 292], heat: [GH.x1, 292], co2: [GH.x1, 238] };
const PORT_BELOW = { electricity: [455, GH.base], co2: [500, GH.base], heat: [545, GH.base] };
// the centre of each block on the drawing: electricity on the left, heat on the right, fuel units below
const LAYOUT = {
  existing_pv: [300, 54], voltiris: [500, 54], external_co2: [700, 54], data_center: [880, 54],
  grid: [110, 232], battery: [110, 350], heat_pump: [880, 172], aux_heater: [880, 282], thermal_storage: [880, 392],
  gas_supply: [110, 424], ng_boiler: [320, 424], chp: [500, 424], sofc: [680, 424],
};
const SHORT = { existing_pv: "Existing PV", voltiris: "Voltiris", aux_heater: "Backup heater", external_co2: "Liquid CO2",
  grid: "Grid", battery: "Battery", heat_pump: "Heat pump", data_center: "Data center", ng_boiler: "Gas boiler",
  chp: "CHP (gas)", sofc: "SOFC (ethanol)", thermal_storage: "Heat storage", gas_supply: "Gas supply" };
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
  gas_supply: '<path d="M2 18h7M19 18h7M9 12h10v12H9z"/><path d="M14 12V6M10 6h8"/>',
};
function greenhouseSvg() {
  const on = has("greenhouse"), w = (GH.x1 - GH.x0) / GH.spans;
  let roof = `M${GH.x0} ${GH.eave}`, panes = "", modules = "", plants = "";
  for (let i = 0; i < GH.spans; i++) roof += ` L${GH.x0 + w * i + w / 2} ${GH.peak} L${GH.x0 + w * (i + 1)} ${GH.eave}`;
  for (let i = 1; i < GH.spans * 2; i++) panes += `<path class="pane" d="M${GH.x0 + (w / 2) * i} ${GH.eave} V${GH.base}"/>`;
  for (let i = 0; i < GH.spans && has("voltiris"); i++)   // Voltiris modules on the south slope of each span
    modules += `<path class="module" d="M${GH.x0 + w * i + 4} ${GH.eave - 5} L${GH.x0 + w * i + w / 2 - 3} ${GH.peak + 7}"/>`;
  for (let i = 0; i < 9; i++) plants += `<ellipse class="plant" cx="${GH.x0 + 14 + i * 19}" cy="${GH.base - 11}" rx="7" ry="${5 + (i % 3)}"/>`;
  return `<g class="node gh ${on ? "on" : ""} built" data-block="greenhouse" tabindex="0" role="checkbox" aria-checked="${on}">
    <title>Greenhouse demand: the site's electricity load, and its heat and CO2 demand when a block supplies them</title>
    <path class="glass" d="${roof} L${GH.x1} ${GH.base} L${GH.x0} ${GH.base} Z"/>${panes}${plants}${modules}
    <text x="500" y="256" class="gh-name">Greenhouse</text>
    <text x="500" y="274" class="gh-sub">${on ? (has("ng_boiler") ? "electricity, heat, CO2" : "electricity load") : "click to add"}</text></g>`;
}
function nodeSvg(b, cx, cy) {
  const x = cx - NODE.w / 2, y = cy - NODE.h / 2, on = has(b.id), built = b.status === "model";
  const preset = S.options.presets.find((p) => p.id === S.system.preset);
  const note = on && preset && preset.options && preset.options[b.id];
  const sub = note || (on ? (built ? "in the system" : "not built yet") : built ? "add" : "not built yet");
  return `<g class="node ${on ? "on" : ""} ${built ? "built" : "planned"}" data-block="${b.id}" tabindex="0" role="checkbox" aria-checked="${on}">
    <title>${esc(b.name)}: ${esc(b.role)}${built ? "" : " (not built yet)"}. Click to ${on ? "remove" : "add"}.</title>
    <rect x="${x}" y="${y}" width="${NODE.w}" height="${NODE.h}" rx="10"/>
    <g transform="translate(${x + 10} ${y + 12}) scale(.9)" class="icon">${ICONS[b.id] || ""}</g>
    <text x="${x + 42}" y="${y + 21}" class="name">${esc(SHORT[b.id] || b.name)}</text>
    <text x="${x + 42}" y="${y + 37}" class="sub">${esc(sub)}</text>
    ${on ? `<circle cx="${x + NODE.w - 12}" cy="${y + 12}" r="7" class="tick"/><path d="M${x + NODE.w - 15.5} ${y + 12} l2.5 2.5 l4.5 -5" class="tickmark"/>` : ""}</g>`;
}
// a curve from a block to the greenhouse, arriving square to the side it enters
function flowPath(cx, cy, carrier, below) {
  const [px, py] = below ? PORT_BELOW[carrier] : PORT[carrier];
  if (below) return `M${cx} ${cy} C${cx} ${cy - 40} ${px} ${py + 60} ${px} ${py}`;
  const side = px <= GH.x0 ? -1 : 1;
  return `M${cx} ${cy} C${cx + (px - cx) * 0.45} ${cy} ${px + side * 70} ${py} ${px} ${py}`;
}
function renderDiagram() {
  let lines = "", nodes = "";
  S.options.blocks.forEach((b) => {
    if (!LAYOUT[b.id]) return;
    const [cx, cy] = LAYOUT[b.id];
    nodes += nodeSvg(b, cx, cy);
    if (!has(b.id)) return;   // only the chosen blocks are connected
    if (b.id === "data_center") {   // its heat reaches the greenhouse only through the heat pump (thesis.md 2.3)
      if (has("heat_pump")) lines += `<path class="flow" d="M${cx} ${cy} L${LAYOUT.heat_pump[0]} ${LAYOUT.heat_pump[1]}" stroke="${CARRIER_COLOR["low-temperature heat"]}"/>`;
      return;
    }
    if (b.id === "gas_supply") {   // to every unit that burns gas, along a rail under the fuel row
      const rail = cy + NODE.h / 2 + 14;
      S.options.blocks.filter((u) => has(u.id) && LAYOUT[u.id] && (u.in || []).includes("gas")).forEach((u) => {
        const [ux, uy] = LAYOUT[u.id];
        lines += `<path class="flow" d="M${cx} ${cy + NODE.h / 2} V${rail} H${ux} V${uy + NODE.h / 2}" stroke="${CARRIER_COLOR.gas}"/>`;
      });
      return;
    }
    if (b.id === "thermal_storage") {   // heat in from the units under the greenhouse that make it, along a rail below them
      S.options.blocks.filter((u) => has(u.id) && LAYOUT[u.id] && (u.out || []).includes("heat") && LAYOUT[u.id][1] > GH.base + 80)
        .forEach((u) => {
          const [ux, uy] = LAYOUT[u.id];
          lines += `<path class="flow" d="M${ux + 30} ${uy + NODE.h / 2} V${uy + NODE.h / 2 + 16} H${cx} V${cy + NODE.h / 2}" stroke="${CARRIER_COLOR.heat}"/>`;
        });
    }
    if (!has("greenhouse")) return;
    if (b.id === "voltiris") { lines += `<path class="flow" d="M${cx} ${cy} L${cx} ${GH.peak + 8}" stroke="${CARRIER_COLOR.electricity}"/>`; return; }
    const below = cy > GH.base + 80;   // the fuel units under the greenhouse
    (b.out || []).filter((c) => PORT[c]).forEach((c) => {
      lines += `<path class="flow" d="${flowPath(cx, cy, c, below)}" stroke="${CARRIER_COLOR[c]}"/>`;
    });
  });
  $("diagram").innerHTML = `<svg viewBox="0 20 1000 452" aria-label="The greenhouse and its energy system: click a block to add or remove it">${lines}${greenhouseSvg()}${nodes}</svg>`;
}
// the links between blocks (common/blocks.json): fixed blocks are always in; a follower (the gas supply) is in exactly
// when one of the blocks it follows is; a block that lost what it needs (a heat storage without a heat source) is out
function linked(blocks) {
  const set = new Set(blocks);
  S.options.blocks.filter((b) => b.fixed).forEach((b) => set.add(b.id));
  for (let changed = true; changed;) {
    changed = false;
    S.options.blocks.forEach((b) => {
      const on = set.has(b.id);
      if (b.follows && b.follows.some((x) => set.has(x)) !== on) { if (on) set.delete(b.id); else set.add(b.id); changed = true; return; }
      if (on && ((b.needs_one_of && !b.needs_one_of.some((x) => set.has(x)))
        || (b.needs || []).some((x) => !set.has(x) && !blockInfo(x).follows))) { set.delete(b.id); changed = true; }
    });
  }
  return set;
}
const names = (ids) => ids.map((x) => blockInfo(x).name).join(", ");
function linkReason(id) {
  const b = blockInfo(id);
  if (b.follows) return `it comes with the ${b.follows.filter(isBuilt).map((x) => blockInfo(x).name.toLowerCase()).join(" or ")}`;
  if (b.needs_one_of) return `it needs ${b.needs_one_of_label || "one of " + names(b.needs_one_of)}`;
  return `it needs ${names(b.needs || [])}`;
}
function toggleBlock(id) {
  const b = blockInfo(id);
  if (b.fixed) return toast(`${b.name} is always in the system.`);
  if (b.follows) {
    const with_ = b.follows.filter(isBuilt);
    return toast(`${b.name} comes with the ${with_.map((x) => blockInfo(x).name.toLowerCase()).join(" or ")}: it is added and taken out with ${with_.length > 1 ? "them" : "it"}.`);
  }
  const before = new Set(S.system.blocks), next = new Set(before);
  if (has(id)) next.delete(id);
  else {
    next.add(id);
    if (b.needs_one_of && !b.needs_one_of.some((x) => next.has(x))) next.add(b.needs_one_of.find(isBuilt) || b.needs_one_of[0]);
    (b.needs || []).forEach((x) => next.add(x));
  }
  const after = linked(next);
  const added = [...after].filter((x) => !before.has(x) && x !== id), removed = [...before].filter((x) => !after.has(x) && x !== id);
  S.system.blocks = after;
  const preset = S.options.presets.find((p) => p.id === S.system.preset);
  if (preset && !sameSet(new Set(preset.blocks), S.system.blocks)) S.system.preset = null;
  const notes = [];
  if (added.length) notes.push(`Also added: ${added.map((x) => `${blockInfo(x).name} (${x === b.needs_one_of?.find(isBuilt) ? `the ${b.name.toLowerCase()} ${linkReason(id).replace("it ", "")}` : linkReason(x)})`).join(", ")}.`);
  if (removed.length) notes.push(`Also taken out: ${removed.map((x) => `${blockInfo(x).name} (${linkReason(x)})`).join(", ")}.`);
  if (notes.length) toast(notes.join(" "));
  S.preview = null;
  systemChanged();
}
$("diagram").addEventListener("click", (ev) => { const g = ev.target.closest("[data-block]"); if (g) toggleBlock(g.dataset.block); });
$("diagram").addEventListener("keydown", (ev) => {
  const g = ev.target.closest("[data-block]");
  if (g && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); toggleBlock(g.dataset.block); }
});

// every run type that can run these blocks (the first is the default), or why none can
// scenario B: this system without some blocks (it can only leave blocks out); the links between blocks apply
S.compare = new Set();
const compareOn = () => $("cmpOn").checked && S.compare.size > 0 && S.runType === "blocks";
function scenarioB() {
  const kept = linked(new Set(chosenBlocks().filter((x) => !S.compare.has(x))));
  return { kept: chosenBlocks().filter((x) => kept.has(x)), also: chosenBlocks().filter((x) => !kept.has(x) && !S.compare.has(x)) };
}
function renderCompare() {
  $("compareCard").hidden = S.runType !== "blocks";
  const removable = chosenBlocks().filter((b) => isBuilt(b) && !blockInfo(b).fixed && !blockInfo(b).follows);
  [...S.compare].forEach((b) => { if (!removable.includes(b)) S.compare.delete(b); });
  $("cmpBox").hidden = !$("cmpOn").checked;
  $("cmpBlocks").innerHTML = removable.length ? removable.map((b) => `<label class="chip"><input type="checkbox" data-block="${b}" ${S.compare.has(b) ? "checked" : ""}>${esc(blockInfo(b).name)}</label>`).join("")
    : '<span class="muted">No block can be left out: greenhouse and grid are always in.</span>';
  $("cmpBlocks").querySelectorAll("input").forEach((i) => i.addEventListener("change", () => {
    if (i.checked) S.compare.add(i.dataset.block); else S.compare.delete(i.dataset.block);
    S.preview = null; renderCompare();
  }));
  const b = scenarioB();
  $("cmpInfo").innerHTML = S.compare.size
    ? `<b>A</b>: ${esc(names(chosenBlocks()))}.<br><b>B</b>: ${esc(names(b.kept))}.` +
      (b.also.length ? `<br>Also left out in B: ${b.also.map((x) => `${esc(blockInfo(x).name)} (${esc(linkReason(x))})`).join(", ")}.` : "")
    : "Tick at least one block for scenario B.";
}
$("cmpOn").addEventListener("change", () => { S.preview = null; renderCompare(); });

// the sized blocks, and whether they are sized together
const SIZED = ["ng_boiler", "thermal_storage", "battery"];
const sizingMode = () => document.querySelector("input[name=sizing]:checked").value;
const jointSizing = () => sizingMode() === "joint" && SIZED.filter(has).length >= 2 && S.runType === "blocks";
document.querySelectorAll("input[name=sizing]").forEach((r) => r.addEventListener("change", () => { S.preview = null; updateTop(); }));
function runTypeFor(blocks) {
  const ids = [], reasons = [];
  for (const rt of Object.values(S.options.run_types)) {
    const missing = rt.blocks_required.filter((b) => !blocks.has(b));
    const extra = [...blocks].filter((b) => !rt.blocks_allowed.includes(b));
    const oneOf = rt.blocks_one_of || [], none = oneOf.length > 0 && !oneOf.some((b) => blocks.has(b));
    if (!missing.length && !extra.length && !none) { ids.push(rt.id); continue; }
    const name = (id) => blockInfo(id).name;
    reasons.push(`${rt.name}: ${[missing.length && `needs ${missing.map(name).join(", ")}`,
      none && `needs one of ${oneOf.map(name).join(", ")}`,
      extra.length && `cannot run ${extra.map(name).join(", ")}`].filter(Boolean).join("; ")}`);
  }
  const id = ids.includes(S.runTypeWanted) ? S.runTypeWanted : ids[0] || null;
  return { id, ids, why: reasons };
}
$("runTypeSelect").addEventListener("change", () => { S.runTypeWanted = $("runTypeSelect").value; systemChanged(); });
function sameSet(a, b) { return a.size === b.size && [...a].every((x) => b.has(x)); }
function setSystem(blocks, preset) {
  S.system = { preset: preset || null, blocks: linked(blocks) };
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
  $("co2Seg").closest(".card").hidden = !has("ng_boiler");
  $("sizingRow").hidden = !(fit.id === "blocks" && SIZED.filter(has).length >= 2);
  renderCompare();
  if (S.params) renderKeyParams();
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
    if (id === "greenhouse" && has("ng_boiler")) cfg.co2_mode = document.querySelector("input[name=co2mode]:checked").value;
    if (id === "thermal_storage") {
      const sizing = { objective: document.querySelector("input[name=sobjective]:checked").value };
      const custom = Number($("sCustom").value), sizes = numbers($("sSizes").value);
      if (custom > 0) sizing.custom_kwh = custom;
      if (sizes.length) sizing.sizes_kwh = sizes;
      cfg.sizing = sizing;
    }
    if (id === "ng_boiler") {
      const sizing = { objective: document.querySelector("input[name=bobjective]:checked").value };
      const custom = Number($("bCustom").value), sizes = numbers($("bSizes").value);
      if (custom > 0) sizing.custom_kw = custom;
      if (sizes.length) sizing.sizes_kw = sizes;
      cfg.sizing = sizing;
    }
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
    system: { preset: S.system.preset, run_type: S.runType, sizing: sizingMode() },
    compare: compareOn() ? { without: [...S.compare] } : undefined,
  };
}

function applyCase(c) {
  const blocks = c.blocks || {};
  const market = c.market || {};
  S.runTypeWanted = (c.system || {}).run_type || null;
  document.querySelector(`input[name=sizing][value=${(c.system || {}).sizing === "sequential" ? "sequential" : "joint"}]`).checked = true;
  S.compare = new Set((c.compare || {}).without || []);
  $("cmpOn").checked = S.compare.size > 0;
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
  const gh = blocks.greenhouse || {}, bz = (blocks.ng_boiler || {}).sizing || {};
  document.querySelector(`input[name=co2mode][value=${gh.co2_mode === "by_product" ? "by_product" : "required"}]`).checked = true;
  document.querySelector(`input[name=bobjective][value=${BOILER_HINT[bz.objective] ? bz.objective : "lifetime_cost"}]`).checked = true;
  boilerObjectiveChanged();
  $("bCustom").value = bz.custom_kw || "";
  $("bSizes").value = (bz.sizes_kw || []).join(", ");
  const tz = (blocks.thermal_storage || {}).sizing || {};
  document.querySelector(`input[name=sobjective][value=${STORAGE_HINT[tz.objective] ? tz.objective : "profit"}]`).checked = true;
  storageObjectiveChanged();
  $("sCustom").value = tz.custom_kwh || "";
  $("sSizes").value = (tz.sizes_kwh || []).join(", ");
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
  heat_kw: { label: "Heat demand", color: COLORS.heat },
  co2_kg_h: { label: "CO2 demand", color: COLORS.co2 },
  gas_price_eur_kwh: { label: "Gas price", color: COLORS.gas },
  outside_temp_c: { label: "Outside temperature", color: "#0284c7" },
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
  // one axis per unit: the first on the left, the others on the right; prices dashed when they share the chart
  const units = [...new Set(series.filter((s) => !s.price).concat(series.filter((s) => s.price)).map((s) => s.unit))];
  const axis = (u) => (units.indexOf(u) ? "y" + units.indexOf(u) : "y");
  const scales = { x: { ticks, grid: { display: false } } };
  units.forEach((u, i) => (scales[axis(u)] = { position: i ? "right" : "left", grid: { display: !i }, title: { display: true, text: u } }));
  chart("cv-" + key, { type: "line", data: { labels, datasets: series.map((s) =>
    line(`${s.label}, ${s.unit}`, pick(s.values), s.color, { yAxisID: axis(s.unit), ...(s.price && units.length > 1 ? { borderDash: [4, 3], borderWidth: 1.3 } : {}) })) },
    options: { plugins: { legend: { display: !chipBox } }, scales } });
}
$("sModules").addEventListener("input", debounce(() => { drawViewer("blk-voltiris"); drawViewer("all"); }, 300));

function renderFilesTable() {
  const blocks = chosenBlocks().filter((id) => isBuilt(id) && hasData(id));
  $("filesTable").innerHTML = `<tr><th>Block</th><th>File</th><th>Step in the file</th><th>Steps at 15 min</th><th>Status</th><th></th></tr>` +
    (blocks.length ? blocks.map((id) => {
      const d = S.data[id], w = d.info;
      const status = !d.path ? (id === "grid" ? '<span class="optional">none (only for day-ahead tariffs)</span>'
        : fileOptional(id) ? `<span class="optional">none (${OPTIONAL_FILE[id]})</span>` : '<span class="missing">missing</span>')
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
      <p class="hint">Reads ${needs}, with the time columns Month, Day, Hour (and Minute). A coarser file (30 min, hourly, daily) is converted to 15 min when the system runs (kW, kg/h, W and prices repeated in each quarter hour, kWh per step divided).</p>
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
  if (S.data[id] !== d) return;   // another case was loaded meanwhile: this read is stale
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
  tiles(q("tiles"), w.series.map((s) => s.kind === "state"
    ? [s.about, `${fmt(s.mean, 1)} ${s.unit}`, `mean · min ${fmt(s.min, 1)} · max ${fmt(s.max, 1)} · ${fmt(s.negative_h, 0)} h below 0${s.missing ? ` · ${s.missing} missing` : ""}`]
    : s.kind === "price"
    ? [s.about, `${fmt(s.mean, 4)} ${s.unit}`, `min ${fmt(s.min, 4)} · max ${fmt(s.max, 4)} · ${fmt(s.negative_h, 1)} h negative${s.missing ? ` · ${s.missing} missing` : ""}`]
    : [s.about, s.unit === "W per module" ? `${fmt(s.total_kwh, 1)} kWh/yr per module` : s.unit === "kg/h" ? `${fmt(s.total_kwh / 1000, 1)} t/yr` : `${fmt(s.total_kwh / 1000, 1)} MWh/yr`,
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
  ["voltiris", "", "tech.module_wp", "Module power", "Wp per module", "num", "Peak power of one module. It sets the modules' price (price per Wp × Wp × modules) and the kWp shown; the output comes from the yield file."],
  ["battery", "", "tech.battery.c_rate", "C-rate", "kW per kWh bought", "num", "Power per kWh bought: a 100 kWh battery charges and discharges at most 100 × C-rate kW."],
  ["battery", "", "tech.battery.soc_min", "Lowest state of charge", "% of the size", "pct", "The battery is never emptied below this share of its size. The window between the lowest and highest state is what can be used."],
  ["battery", "", "tech.battery.soc_max", "Highest state of charge", "% of the size", "pct", "The battery is never filled above this share of its size."],
  ["battery", "", "tech.battery.efficiency_store", "Charging efficiency", "%", "pct", "Share of the energy sent to the battery that is stored. The round trip is charging × discharging efficiency."],
  ["battery", "", "tech.battery.efficiency_dispatch", "Discharging efficiency", "%", "pct", "Share of the stored energy that comes back out."],
  ["battery", "", "tech.battery.self_discharge_per_day", "Self-discharge", "% per day", "pct", "Share of the stored energy lost per day."],
  ["reserve", "", "ancillary.reserve.mode", "How it is set", "", "select:percent|fixed_kwh", "percent: a share of the battery; fixed_kwh: a fixed number of kWh (capped at the usable window)."],
  ["reserve", "", "ancillary.reserve.frac", "Share", "% of window and power", "pct", "Share of the usable window, and the same share of the power, kept out of the dispatch for grid services."],
  ["reserve", "", "ancillary.reserve.kwh", "Fixed size", "kWh (fixed_kwh)", "num"],
  ["commercial", "Business model", "business_model.price_per_mwh", "EaaS price", "per MWh of Voltiris energy used on site", "num", "Under EaaS, what the grower pays Voltiris per MWh of Voltiris energy used on site."],
  ["commercial", "Investment prices", "capex.pv_per_wp", "Voltiris modules", "per Wp", "num", "Price of the modules per Wp, before subsidy. Not paid by the grower under EaaS."],
  ["commercial", "Investment prices", "capex.battery_tiers_per_kwh", "Battery price tiers", "kWh:price per kWh, …", "tiers", "Price per kWh by battery size, as size:price pairs; linear between them, flat beyond the first and last."],
  ["commercial", "Investment prices", "capex.battery_replacement_frac", "Battery replacements", "% of the gross price", "pct", "Over the PV life the battery is bought again (PV life ÷ battery life − 1) times, at this share of its gross price, without subsidy."],
  ["commercial", "Lifetimes", "finance.pv_life_yr", "PV life", "years", "num", "Years of the payback table over the project, and the horizon for battery replacements, with or without Voltiris."],
  ["commercial", "Lifetimes", "finance.battery_life_yr", "Battery life", "years", "num", "A size counts as paying back if it does within this many years; lifetime profit = yearly value × battery life − investment."],
  ["commercial", "Ancillary services", "ancillary.rate_per_kw_year", "Revenue rate", "per reserved kW and year", "num", "What the battery earns per kW kept for grid services, per year."],
  ["commercial", "Gas boiler", "capex.boiler_per_kw_th", "Boiler price", "per kW of heat", "num", "Investment per kW of heat output, installed. TO CHECK: placeholder."],
  ["commercial", "Gas boiler", "capex.boiler_fixed_om_per_kw_year", "Fixed O&M", "per kW of heat and year", "num", "Yearly maintenance per kW of size, whether the boiler runs or not. TO CHECK: placeholder."],
  ["commercial", "Gas boiler", "capex.boiler_var_om_per_mwh_heat", "Variable O&M", "per MWh of heat", "num", "Maintenance per MWh of heat given. It is part of the dispatch cost. TO CHECK: placeholder."],
  ["commercial", "Gas boiler", "finance.boiler_life_yr", "Boiler life", "years", "num", "Lifetime cost of a size = investment + yearly cost × this life. TO CHECK: placeholder."],
  ["commercial", "Heat storage", "capex.thermal_storage_per_kwh", "Storage price", "per kWh of heat stored", "num", "Investment per kWh of size, installed. TO CHECK: placeholder."],
  ["commercial", "Heat storage", "capex.thermal_storage_fixed_om_per_kwh_year", "Fixed O&M", "per kWh of size and year", "num", "Yearly maintenance per kWh of size, taken off the storage's yearly value. TO CHECK: placeholder."],
  ["commercial", "Heat storage", "finance.thermal_storage_life_yr", "Storage life", "years", "num", "A size counts as paying back if it does within this many years; lifetime profit = yearly value × life − investment. TO CHECK: placeholder."],
  ["storage", "", "thermal_storage.charge_efficiency", "Charge efficiency", "%", "pct", "Share of the heat sent to the tank that is stored. TO CHECK: placeholder."],
  ["storage", "", "thermal_storage.discharge_efficiency", "Discharge efficiency", "%", "pct", "Share of the stored heat that reaches the greenhouse. TO CHECK: placeholder."],
  ["storage", "", "thermal_storage.power_kw_per_kwh", "Power", "kW in or out per kWh of size", "num", "The most heat the tank takes in, and gives out, per hour, per kWh of size: 0.25 fills it in 4 hours. TO CHECK: placeholder."],
  ["storage", "Heat loss", "thermal_storage.loss.mode", "Loss model", "", "select:constant|seasonal|dynamic", "constant: the same share of the stored heat lost every hour; seasonal: one share per season; dynamic: from the outside temperature of the input file, hour by hour (more loss when it is colder outside)."],
  ["storage", "Heat loss", "thermal_storage.loss.constant_per_hour", "Loss", "% of the heat stored, per hour", "pct", "TO CHECK: placeholder."],
  ["storage", "Heat loss", "thermal_storage.loss.seasonal_per_hour.winter", "Winter (Dec to Feb)", "% per hour", "pct", "TO CHECK: placeholder."],
  ["storage", "Heat loss", "thermal_storage.loss.seasonal_per_hour.spring", "Spring (Mar to May)", "% per hour", "pct"],
  ["storage", "Heat loss", "thermal_storage.loss.seasonal_per_hour.summer", "Summer (Jun to Aug)", "% per hour", "pct"],
  ["storage", "Heat loss", "thermal_storage.loss.seasonal_per_hour.autumn", "Autumn (Sep to Nov)", "% per hour", "pct"],
  ["storage", "Heat loss", "thermal_storage.loss.dynamic.loss_per_hour_at_ref", "Loss at the reference", "% per hour", "pct", "Share lost per hour when it is the reference temperature outside. At another temperature it scales with (tank − outside) ÷ (tank − reference). TO CHECK: placeholder."],
  ["storage", "Heat loss", "thermal_storage.loss.dynamic.store_temp_c", "Tank temperature", "°C", "num", "Mean water temperature in the tank. TO CHECK: placeholder."],
  ["storage", "Heat loss", "thermal_storage.loss.dynamic.ref_outside_temp_c", "Reference outside temperature", "°C", "num", "The outside temperature at which the loss is the reference loss. TO CHECK: placeholder."],
  ["boiler", "", "boiler.efficiency", "Efficiency", "% (heat per kWh of gas, LHV)", "pct", "kWh of heat per kWh of gas burnt, on the lower heating value. TO CHECK: placeholder."],
  ["boiler", "", "boiler.co2_use_frac", "Flue gas CO2 usable", "% of the CO2 of the gas burnt", "pct", "Share of the CO2 of the gas burnt that can go to the greenhouse after cleaning; the rest is vented. TO CHECK: placeholder."],
  ["gas", "", "gas.price_per_kwh", "Fixed gas price", "per kWh of gas; none = the input file", "num", "Used only when the block has no input file: the gas then costs this price at every step. In the market's currency."],
  ["gas", "", "gas.emission_factor_kg_per_kwh", "Emission factor", "kg CO2 per kWh of gas (LHV)", "num", "CO2 of 1 kWh of gas burnt. Default: IPCC 2006 for natural gas, 56.1 t CO2 per TJ. It sets the CO2 the boiler can give and the CO2 emitted."],
  ["gas", "", "gas.co2_levy_per_kg", "Carbon levy", "per kg of CO2", "num", "Paid on every kg of CO2 of the gas burnt, added to the gas price in the dispatch and the costs. TO CHECK: placeholder (0)."],
  ["subsidies", "Voltiris modules", "subsidies.pv.mode", "Mode", "", "select:percent|fixed|threshold", "percent: a share of the price is paid back; fixed: an amount off the price; threshold: the share applies up to a threshold size, the rest is paid in full."],
  ["subsidies", "Voltiris modules", "subsidies.pv.frac", "Share", "%", "pct"],
  ["subsidies", "Voltiris modules", "subsidies.pv.amount", "Amount", "fixed mode", "num"],
  ["subsidies", "Battery", "subsidies.battery.mode", "Mode", "", "select:percent|fixed|threshold", "percent: a share of the price is paid back; fixed: an amount off the price; threshold: the share applies up to a threshold size, the rest is paid in full."],
  ["subsidies", "Battery", "subsidies.battery.frac", "Share", "%", "pct"],
  ["subsidies", "Battery", "subsidies.battery.amount", "Amount", "fixed mode", "num"],
  ["subsidies", "Battery", "subsidies.battery.threshold_mode", "Threshold size from", "", "select:ocan|manual", "ocan: CH rule, the threshold follows from the site's load (factor below); manual: the threshold size typed below."],
  ["subsidies", "Battery", "subsidies.battery.threshold_kwh", "Threshold size", "kWh (manual)", "num"],
  ["subsidies", "Battery", "subsidies.battery.ocan_factor", "OCAN factor", "kWh per daily kWh of load", "num", "CH rule: the largest subsidised battery = yearly load ÷ 365 × this factor. With a threshold subsidy, the size list stops there."],
  ["ems", "Costs", "ems.fixed_per_year", "Fixed cost", "per year", "num", "Yearly cost of the energy management system, taken off the battery's yearly value."],
  ["ems", "Costs", "ems.capex", "Hardware", "once, with the battery", "num", "Bought once with the battery: added to its investment, not subsidised, not bought again at replacements."],
  ["ems", "Fees", "ems.savings_fee_pct.voltiris", "On the bill saving, Voltiris", "%", "pct", "Share of the yearly bill saving (when positive) paid to Voltiris for running the battery."],
  ["ems", "Fees", "ems.savings_fee_pct.external", "On the bill saving, external", "%", "pct"],
  ["ems", "Fees", "ems.ancillary_fee_pct.voltiris", "On the ancillary revenue, Voltiris", "%", "pct", "Share of the yearly ancillary revenue paid to Voltiris."],
  ["ems", "Fees", "ems.ancillary_fee_pct.external", "On the ancillary revenue, external", "%", "pct"],
].map(([page, group, path, label, unit, kind, info]) => ({ page, group, path, label, unit, kind, info }));

// a field about one block shows only when the system has that block
function fieldShown(f) {
  const loss = /^thermal_storage\.loss\.(constant|seasonal|dynamic)/.exec(f.path);   // only the loss model in use
  if (loss) return has("thermal_storage") && loss[1] === (getPath((S.params || {}).effective, "thermal_storage.loss.mode") || "constant");
  if (/thermal_storage/.test(f.path)) return has("thermal_storage");
  if (/boiler/.test(f.path)) return has("ng_boiler");
  if (/battery|^ancillary\.|^ems\./.test(f.path)) return has("battery");
  if (/^subsidies\.pv|pv_per_wp|price_per_mwh/.test(f.path)) return has("voltiris");
  if (f.path === "finance.pv_life_yr") return has("voltiris") || has("battery");
  return true;
}
function shown(f, v) {
  if (v === undefined) return "";
  if (v === null) return "none";
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
  ["voltiris", "battery", "reserve", "commercial", "subsidies", "ems", "boiler", "gas", "storage"].forEach((page) => {
    const box = $("kp-" + page), groups = {};
    KEY_FIELDS.filter((f) => f.page === page && fieldShown(f) && getPath(d, f.path) !== undefined)
      .forEach((f) => (groups[f.group] = groups[f.group] || []).push(f));
    box.innerHTML = "";
    Object.entries(groups).forEach(([group, fields]) => {
      const g = el("div", { class: group ? "pgroup" : "pgroup bare" }, group ? `<h3>${esc(group)}</h3>` : "");
      fields.forEach((f) => {
        const def = getPath(d, f.path), changed = f.path in S.fieldValues;
        const r = el("div", { class: "prow" + (f.kind === "tiers" ? " wide" : "") + (changed ? " changed" : "") });
        r.innerHTML = `<label><span>${esc(f.label)}${f.info ? ` <span class="info" tabindex="0" data-tip="${esc(f.info)}">i</span>` : ""}</span>` +
          `<small>${esc(f.unit)}${f.unit ? " · " : ""}default ${esc(shown(f, def))}</small></label>`;
        let input;
        if (f.kind.startsWith("select:")) {
          input = el("select", {}, `<option value="">${esc(def)} (default)</option>` + f.kind.slice(7).split("|").filter((o) => o !== def)
            .map((o) => `<option ${S.fieldValues[f.path] === o ? "selected" : ""}>${o}</option>`).join(""));
        } else {
          input = el("input", { placeholder: shown(f, def), inputmode: "decimal" });
          input.value = changed ? shown(f, S.fieldValues[f.path]) : "";
        }
        const reset = el("button", { class: "reset", type: "button", title: "Back to the default", "aria-label": "Back to the default" }, "&#8634;");
        reset.hidden = !changed;
        const update = () => { S.preview = null; loadParamsSoon(); };
        input.addEventListener("input", () => {
          const text = input.value.trim();
          const value = text === "" ? undefined : parsed(f, text);
          const same = value === undefined || JSON.stringify(value) === JSON.stringify(def) ||
            (typeof value === "number" && Math.abs(value - def) < 1e-12) || (typeof value === "number" && !isFinite(value));
          if (same) delete S.fieldValues[f.path]; else S.fieldValues[f.path] = value;
          r.classList.toggle("changed", !same);
          reset.hidden = same;
          update();
        });
        reset.addEventListener("click", () => {
          delete S.fieldValues[f.path];
          input.value = "";
          r.classList.remove("changed");
          reset.hidden = true;
          update();
        });
        const box = el("div", { class: "pin" });
        box.append(input, reset);
        r.appendChild(box);
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

// -- gas boiler: sizing -------------------------------------------------------------------------------------------------
const BOILER_HINT = {
  lifetime_cost: "The lowest lifetime cost (investment + yearly cost × boiler life) among the sizes that cover the demand; if none covers it, the largest size tested.",
  smallest: "The smallest size that covers the demand (nothing left unmet); if none does, the largest size tested.",
  custom: "The tested size closest to the custom size, which is added to the list.",
};
const BOILER_OBJECTIVE = { lifetime_cost: "lowest lifetime cost", smallest: "smallest that covers", custom: "custom size" };
function boilerObjectiveChanged() {
  const o = document.querySelector("input[name=bobjective]:checked").value;
  $("bObjHint").textContent = BOILER_HINT[o];
  $("bCustomRow").hidden = o !== "custom";
}
document.querySelectorAll("input[name=bobjective]").forEach((r) => r.addEventListener("change", () => { boilerObjectiveChanged(); S.preview = null; checkSetupSoon(); }));
document.querySelectorAll("input[name=co2mode]").forEach((r) => r.addEventListener("change", () => { S.preview = null; checkSetupSoon(); }));
["bCustom", "bSizes"].forEach((id) => $(id).addEventListener("change", () => { S.preview = null; checkSetupSoon(); }));

// -- heat storage: sizing -----------------------------------------------------------------------------------------------
const STORAGE_HINT = {
  profit: "The highest lifetime profit (yearly value × storage life − investment) among the sizes that pay back within the storage life; if none does, the shortest payback.",
  payback: "The shortest payback among the sizes tested.",
  custom: "The tested size closest to the custom size, which is added to the list.",
};
const STORAGE_OBJECTIVE = { profit: "highest lifetime profit", payback: "shortest payback", custom: "custom size" };
function storageObjectiveChanged() {
  const o = document.querySelector("input[name=sobjective]:checked").value;
  $("sObjHint").textContent = STORAGE_HINT[o];
  $("sCustomRow").hidden = o !== "custom";
}
document.querySelectorAll("input[name=sobjective]").forEach((r) => r.addEventListener("change", () => { storageObjectiveChanged(); S.preview = null; checkSetupSoon(); }));
["sCustom", "sSizes"].forEach((id) => $(id).addEventListener("change", () => { S.preview = null; checkSetupSoon(); }));

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
// a block whose input file may be left out: the grid's (the setup check says if its tariff needs it), and the gas
// supply's when a fixed gas price is set
const OPTIONAL_FILE = { gas_supply: "fixed price", thermal_storage: "only for the dynamic heat loss" };
function fileOptional(id) {
  if (id === "grid") return true;
  if (id === "thermal_storage") {
    const mode = getPath(currentOverrides(), "thermal_storage.loss.mode") || getPath((S.params || {}).defaults, "thermal_storage.loss.mode");
    return mode !== "dynamic";
  }
  if (id !== "gas_supply") return false;
  return getPath(currentOverrides(), "gas.price_per_kwh") != null || getPath((S.params || {}).defaults, "gas.price_per_kwh") != null;
}
// the blocks that still need their input file
function missingFiles() {
  return chosenBlocks().filter((id) => isBuilt(id) && hasData(id) && !fileOptional(id) && !S.data[id].path);
}
const CHECKED_PAGES = ["battery", "ng_boiler", "thermal_storage", "market", "commercial", "subsidies", "run"];   // the setup check runs on them

async function checkSetup(quiet) {
  if (quiet && (!CHECKED_PAGES.includes(S.step) || S.preview)) return;
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
    $("zPlan").textContent = $("bPlan").textContent = $("sPlan").textContent = "The setup has a problem: " + e.message;
    toast(e.message, true);
  }
}

function renderPreview() {
  const p = S.preview, s = p.site, m = p.money, t = p.tariff, bat = !!p.battery, b = p.boiler;
  document.querySelectorAll(".pv-part").forEach((x) => (x.hidden = false));
  tiles("pvSite", [
    ["Yearly load", `${fmt(s.load_mwh, 0)} MWh`, `peak ${fmt(s.load_peak_kw, 0)} kW`],
    ["Voltiris PV", `${fmt(s.voltiris_kwp, 1)} kWp`, `${fmt(s.modules)} modules · ${fmt(s.voltiris_mwh, 1)} MWh/yr`],
    ["Existing PV", `${fmt(s.existing_mwh, 1)} MWh`, has("existing_pv") ? "with the Voltiris PV, behind one meter" : "not in the system"],
    ["PV surplus without battery", `${fmt(s.pv_surplus_mwh, 1)} MWh`, `of ${fmt(s.pv_mwh, 1)} MWh PV`],
    ["Grid import limit", `${fmt(p.grid.import_max_kw, 0)} kW`, p.grid.import_auto ? "automatic" : "from the Grid page"],
    ["Grid export limit", `${fmt(p.grid.export_max_kw, 0)} kW`, p.grid.export_auto ? "automatic" : "from the Grid page"],
    ["One-meter rules", `${fmt(p.meter.export_pays_more_h, 0)} h`, `exporting pays more · ${fmt(p.meter.negative_price_h, 1)} h negative price`],
    b && ["Heat demand", `${fmt(b.heat_demand_mwh, 0)} MWh`, `peak ${fmt(b.heat_peak_kw, 0)} kW`],
    b && ["CO2 demand", `${fmt(b.co2_demand_t, 1)} t`, `peak ${fmt(b.co2_peak_kg_h, 1)} kg/h`],
  ]);
  tiles("pvMoney", [
    ["Business model", t.business_model === "eaas" ? (t.eaas ? "EaaS" : "EaaS (inactive: 0 modules)") : "Direct sales"],
    has("voltiris") && ["Voltiris modules", money(m.pv_capex), `${fmt(s.modules)} modules, before subsidy`],
    bat && ["Battery price", `${money(m.price_per_kwh_at["100"])}/kWh`, `at 100 kWh · ${money(m.price_per_kwh_at["1000"])}/kWh at 1,000 kWh`],
    bat && ["Lifetimes", `${fmt(m.pv_life_yr)} / ${fmt(m.battery_life_yr)} yr`, "PV (the study's horizon) / battery"],
    b && ["Gas boiler", `${money(b.capex_per_kw)}/kW`, `of heat · life ${fmt(b.life_yr)} yr`],
  ]);
  tiles("pvSubsidy", [
    bat && ["100 kWh of battery after subsidy", money(m.price_after_subsidy_100), `${m.subsidy_mode}${m.subsidy_frac ? ` ${fmt(m.subsidy_frac * 100, 0)} %` : ""}`],
    bat && m.subsidy_mode === "threshold" && ["Subsidised maximum", `${fmt(m.subsidy_threshold_kwh, 0)} kWh`, "OCAN: yearly load / 365 × factor"],
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
  if (b) {
    const co2PerHeat = (b.emission_factor * b.co2_use_frac) / b.efficiency;   // kg CO2 usable per kWh of heat
    tiles("pvBoiler", [
      ["Size the demand needs", `${fmt(b.needed_kw, 0)} kW`, b.needed_kw > b.heat_peak_kw + 0.5 ? `set by the CO2 demand (heat peak ${fmt(b.heat_peak_kw, 0)} kW)` : "the peak of the heat demand", "accent"],
      ["Heat demand", `${fmt(b.heat_demand_mwh, 0)} MWh/yr`, `peak ${fmt(b.heat_peak_kw, 0)} kW`],
      ["CO2 demand", `${fmt(b.co2_demand_t, 1)} t/yr`, `peak ${fmt(b.co2_peak_kg_h, 1)} kg/h · ${b.co2_mode === "required" ? "must be met" : "by-product only"}`],
      ["CO2 per MWh of heat", `${fmt(co2PerHeat * 1000, 0)} kg`, `usable, at ${fmt(b.efficiency * 100, 0)} % efficiency`],
      ["Gas price", `${fmt(b.gas_price_mean, 4)} ${cur()}/kWh`, `min ${fmt(b.gas_price_min, 4)} · max ${fmt(b.gas_price_max, 4)}${b.levy_per_kg ? ` · levy ${fmt(b.levy_per_kg * b.emission_factor, 4)}/kWh` : ""}`],
    ]);
    $("bPlan").innerHTML = `The model will solve <b>${b.sizes.length} sizes</b>: ${b.sizes.map((x) => fmt(x)).join(", ")} kW of heat. ` +
      `Objective: <b>${BOILER_OBJECTIVE[b.objective]}</b>.` + (bat ? " The chosen size is then fixed for the battery study." : "");
  }
  const st = p.storage;
  if (st) {
    const pct = (v) => fmt(v * 100, 2);
    tiles("pvStorage", [
      ["Heat loss", `${pct(st.loss_mean)} %/h`, st.loss_mode + (st.loss_mode === "constant" ? "" : ` · ${pct(st.loss_min)} to ${pct(st.loss_max)} %/h`), "accent"],
      ["Kept after a day", `${fmt(Math.pow(1 - st.loss_mean, 24) * 100, 1)} %`, "of the heat stored, at the mean loss"],
      ["Round trip", `${fmt(st.charge_efficiency * st.discharge_efficiency * 100, 1)} %`, `charge ${fmt(st.charge_efficiency * 100, 0)} % · discharge ${fmt(st.discharge_efficiency * 100, 0)} %`],
      ["Power", `${fmt(st.power_per_kwh, 2)} kW per kWh`, `full in ${fmt(1 / st.power_per_kwh, 1)} h`],
      st.outside_temp && ["Outside temperature", `${fmt(st.outside_temp.mean, 1)} °C`, `min ${fmt(st.outside_temp.min, 1)} · max ${fmt(st.outside_temp.max, 1)} °C`],
      ["Price", `${money(st.capex_per_kwh, 1)}/kWh`, `life ${fmt(st.life_yr)} yr`],
    ]);
    $("sPlan").innerHTML = `The model will solve <b>${st.sizes.length} sizes</b>: ${st.sizes.map((x) => fmt(x)).join(", ")} kWh of heat ` +
      `(automatic sizes follow a boiler of about ${fmt(st.boiler_kw_estimate)} kW; the run uses the size the boiler study chooses). Objective: <b>${STORAGE_OBJECTIVE[st.objective]}</b>.`;
  }
  const js = p.joint_sizing, jz = js && js.mode === "joint";
  const jointNote = (block) => (jz && js.plan[block] === null
    ? " <br><b>Sizing together</b> (System page): the size comes from the joint optimisation, not from this list; the model then runs this block's study at that size." : "");
  if (b) $("bPlan").innerHTML += jointNote("ng_boiler");
  if (st) $("sPlan").innerHTML += jointNote("thermal_storage");
  if (!bat) return;
  const z = p.sizing;
  $("zPlan").innerHTML = `The battery study solves <b>${z.sizes.length} sizes</b>: ${z.sizes.map((x) => fmt(x)).join(", ")} kWh` +
    (z.cap ? ` (the list stops at the subsidised maximum, ${fmt(z.cap)} kWh)` : "") +
    (z.fine_grid_kwh && z.fine_grid_kwh.length ? `, then those of ${z.fine_grid_kwh.map((x) => fmt(x)).join(", ")} kWh that are within ${fmt(z.fine_window_kwh)} kWh of the best size` : "") +
    `. Objective: <b>${z.objective}</b>${z.objective === "custom" ? ` (${fmt(z.custom_kwh)} kWh)` : ""}.` +
    (t.has_rule ? ` Sizes whose DUP crosses ${fmt(t.threshold_h)} h are solved twice more.` : "") +
    (jz && js.plan.battery === null ? `<br><b>Sizing together</b> (System page): the size comes from the joint optimisation (at most ${fmt(js.battery_max_kwh)} kWh), not from this list; the battery study then runs at that size.` : "");
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
    $("runSteps").innerHTML = S.options.run_types[r.run_type].stages.filter((s) => !s.block || (s.block === "joint" ? jointSizing() : s.block === "compare" ? compareOn() : has(s.block))).map((s) =>
      `<li data-stage="${s.stage}" data-block="${s.block || ""}">${esc(s.label)}${s.counts ? ' <span class="count"></span>' : ""}</li>`).join("");
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
    const solved = (st.done || {})[li.dataset.block];
    if (count) count.textContent = solved ? `(${solved} solved)` : "";
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

S.rtab = "system";
function showResultTab(name) {
  S.rtab = name;
  document.querySelectorAll("#resTabs button").forEach((b) => b.classList.toggle("active", b.dataset.rtab === name));
  document.querySelectorAll("#step-results .rtab").forEach((t) => (t.hidden = t.dataset.rtab !== name));
  Object.values(S.charts).forEach((c) => c.resize());
}
document.querySelectorAll("#resTabs button").forEach((b) => b.addEventListener("click", () => showResultTab(b.dataset.rtab)));

function renderResults() {
  const R = S.results, bat = !!R.battery, boiler = !!R.boiler, storage = !!R.storage;
  $("res-battery_study").hidden = !bat;
  document.querySelector('#resTabs [data-rtab="electricity"]').hidden = !R.electricity;
  document.querySelector('#resTabs [data-rtab="system"]').hidden = !R.system;
  document.querySelectorAll("#resTabs .ct").forEach((b) => (b.hidden = !R.compare));
  document.querySelectorAll("#resTabs .bt").forEach((b) => (b.hidden = !bat));
  document.querySelectorAll("#resTabs .ht").forEach((b) => (b.hidden = !boiler));
  document.querySelectorAll("#resTabs .st").forEach((b) => (b.hidden = !storage));
  $("resTabs").hidden = false;
  $("resFiles").textContent = `Written to ${R.files.folder} · model: ${S.options.run_types[R.run_type].name}`;
  $("resSummary").innerHTML = `<tr><th>Field</th><th>Value</th></tr>` + Object.entries(R.summary).filter(([k]) => k !== "sweep")
    .map(([k, v]) => `<tr><td><code>${k}</code></td><td>${esc(typeof v === "number" ? auto(v) : v === null ? "–" : String(v))}</td></tr>`).join("");
  if (R.electricity) renderElectricity();
  if (R.system) renderSystemCost();
  if (R.compare) renderComparison();
  if (bat) renderBatteryStudy();
  if (boiler) renderBoilerStudy();
  if (storage) renderStorageStudy();
  if (bat && boiler) $("resLead").textContent += ` · gas boiler ${fmt(R.boiler.summary.boiler_kw)} kW`;
  if (storage) $("resLead").textContent += ` · heat storage ${fmt(R.storage.summary.storage_kwh)} kWh`;
  const shownTabs = [...document.querySelectorAll("#resTabs button")].filter((b) => !b.hidden).map((b) => b.dataset.rtab);
  if (!shownTabs.includes(S.rtab)) S.rtab = shownTabs[0];
  showResultTab(S.rtab);
}

function renderBatteryStudy() {
  const R = S.results.battery, s = R.summary, c = s.currency;
  const m = (v, d = 0) => `${fmt(v, d)} ${c}`;
  $("resLead").textContent = `${s.site_tag} · ${s.country} ${s.region} ${s.utility} · ${s.pv_modules} Voltiris modules (${s.voltiris_model}) · ancillary services ${R.choice.ancillary_on ? "on" : "off"}`;
  tiles("resTiles", [
    ["Chosen battery", `${fmt(s.battery_kwh)} kWh`, `regime ${s.regime_battery} (${s.regime_no_battery} without battery)`, "accent"],
    ["Yearly value", m(s.battery_value_yr), "bill saving + ancillary − EMS"],
    ["Investment", m(s.battery_investment), `battery after subsidy ${m(s.battery_net_capex)} + EMS ${m(s.ems_capex)}`],
    ["Payback", s.battery_payback_yr == null ? "never" : `${fmt(s.battery_payback_yr, 1)} yr`],
    ["Lifetime profit", m(s.battery_lifetime_profit), "value × battery life − investment"],
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
  const R = S.results.battery, s = R.summary, ch = R.choice, c = s.currency, life = ch.battery_life_yr;
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
  if (ch.joint) {
    why = `<b>Sized together</b> with the other blocks (System tab): ${kwh(chosen.size)}. Against the same system without battery: ` +
      `${fmt(chosen.value)} ${c}/yr, payback ${pbText(chosen)}, lifetime profit ${fmt(chosen.profit)} ${c} over ${fmt(life)} years.`;
  } else if (ch.objective === "profit" && paying.length) {
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
  const B = S.results.battery, d = B.daily, n = d.load.length;
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
  $("resYearWindow").textContent = fmt(B.choice.dispatch_kwh_per_kwh * B.summary.battery_kwh);
  $("resCycles").textContent = `About ${fmt(B.summary.battery_cycles, 0)} full cycles a year.`;
}

function renderMonthly() {
  if (!S.results || !S.results.battery) return;
  renderTable("resMonthly", S.results.battery[S.monthlyTab], { indexLabel: "Month" });
}
document.querySelectorAll("#resMonthlyTabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("#resMonthlyTabs button").forEach((x) => x.classList.toggle("active", x === b));
  S.monthlyTab = b.dataset.tab; renderMonthly();
}));
function drawDispatch() {
  const d = S.results && S.results.battery && S.results.battery.dispatch; if (!d) return;
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

// the site's yearly cost, for every run, and with the joint sizing each block's value in the system
const BLOCK_NAME = { ng_boiler: "Gas boiler", thermal_storage: "Heat storage", battery: "Battery" };
const BLOCK_UNIT = { ng_boiler: "kW", thermal_storage: "kWh", battery: "kWh" };
function renderSystemCost() {
  const Y = S.results.system, c = Y.costs, J = Y.joint;
  const cu = (S.results.summary && S.results.summary.currency) || (S.results.electricity && Object.values(S.results.electricity.cases)[0].kpi.currency) || "";
  const m = (v) => `${fmt(v, 0)} ${cu}`;
  $("yCur").textContent = `${cu} per year`;
  const sizes = Object.entries(c.sizes || {});
  tiles("yTiles", [
    ["Yearly cost of the site", m(c.total), `running ${m(c.running_total)} + investments ${m(c.investment_total)}`, "accent"],
    ["Running per year", m(c.running_total), "grid, gas, levy, O&M, EMS, less revenues"],
    ["Investment per year", m(c.investment_total), "each investment ÷ its life"],
    ...sizes.map(([b, v]) => [BLOCK_NAME[b], `${fmt(v)} ${BLOCK_UNIT[b]}`,
      J ? (J.plan[b] !== null && J.plan[b] !== undefined ? "size fixed (custom)" : J.value[b] !== undefined ? `sized together · worth ${m(J.value[b])}/yr` : "sized together")
        : "sized by its own study"]),
  ]);
  const notes = [];
  if (Y.mode === "joint") {
    notes.push(`<b>Sized together</b>: ${Object.keys(J.plan).filter((b) => J.plan[b] === null).map((b) => BLOCK_NAME[b].toLowerCase()).join(", ")} optimised in one go for the lowest yearly cost of the site (${m(J.total)} in the optimisation; ${m(c.total)} when the year is solved again at the sizes found${(c.sizes || {}).battery ? ", with the battery's EMS costs" : ""}).`);
    Object.entries(J.without).forEach(([b, w]) => {
      const others = Object.entries(w.sizes).map(([k, v]) => `${BLOCK_NAME[k].toLowerCase()} ${fmt(v)} ${BLOCK_UNIT[k]}`).join(", ");
      notes.push(`Without the ${BLOCK_NAME[b].toLowerCase()}, the best system is ${others || "the rest as it is"} at ${m(w.total)} a year.`);
    });
    (J.notes || []).forEach((n) => notes.push(n));
  } else {
    notes.push(SIZED.some((b) => (c.sizes || {})[b]) ? "Each block was sized by its own study, the others fixed (one at a time, in the order boiler, heat storage, battery)." : "No block to size: the system as it is.");
  }
  $("yWhy").innerHTML = notes.join("<br>");
  $("yJointCard").hidden = !J;
  if (J) {
    $("yJoint").innerHTML = `<tr><th>Block</th><th>Size</th><th>Sized</th><th>Best system without it</th><th>Site's yearly cost without it, ${cu}</th><th>Value in the system, ${cu}/yr</th></tr>` +
      Object.entries(J.sizes).map(([b, v]) => {
        const w = J.without[b];
        const others = w ? Object.entries(w.sizes).map(([k, x]) => `${BLOCK_NAME[k].toLowerCase()} ${fmt(x)} ${BLOCK_UNIT[k]}`).join(", ") : "";
        return `<tr><td class="text"><b>${BLOCK_NAME[b]}</b></td><td>${fmt(v)} ${BLOCK_UNIT[b]}</td><td class="text">${J.plan[b] === null ? "together" : "fixed"}</td>
          <td class="text">${w ? esc(others) : "not left out: the only heat source"}</td><td>${w ? fmt(w.total, 0) : "–"}</td>
          <td class="${w ? (J.value[b] > 0 ? "yes" : "no") : ""}">${w ? fmt(J.value[b], 0) : "–"}</td></tr>`;
      }).join("");
  }
  const items = [...Object.entries(c.running).map(([k, v]) => [k, v, "run"]), ...Object.entries(c.investment).map(([k, v]) => [k, v, "inv"])]
    .filter(([, v]) => Math.abs(v) > 0.5);
  chart("yChart", { type: "bar", data: { labels: items.map((i) => i[0]), datasets: [{ data: items.map((i) => i[1]),
    backgroundColor: items.map(([, v, kind]) => (v < 0 ? COLORS.exp : kind === "inv" ? COLORS.accent : COLORS.imp)) }] },
    options: { indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: { title: { display: true, text: `${cu} per year` } } } } });
  const row = (k, v, cls = "") => `<tr${cls ? ` class="${cls}"` : ""}><td class="text">${esc(k)}</td><td>${fmt(v, 0)}</td></tr>`;
  $("yTable").innerHTML = `<tr><th>Running</th><th>${cu}/yr</th></tr>` + Object.entries(c.running).map(([k, v]) => row(k, v)).join("") +
    row("Total running", c.running_total, "total") +
    `<tr><th>Investment per year</th><th></th></tr>` + Object.entries(c.investment).map(([k, v]) => row(`${k} (${fmt(c.invested[k], 0)} over its life)`, v)).join("") +
    row("Total investment per year", c.investment_total, "total") + row("Yearly cost of the site", c.total, "total") +
    `<tr><th>Quantities</th><th></th></tr>` + Object.entries(c.other).map(([k, v]) => `<tr><td class="text">${esc(k)}</td><td>${fmt(v, 1)}</td></tr>`).join("");
}

// scenario A against scenario B
function renderComparison() {
  const C = S.results.compare, cu = $("yCur").textContent.replace(" per year", "") || "";
  const m = (v) => `${fmt(v, 0)} ${cu}`;
  $("cCur").textContent = `${cu} per year`;
  const cheaper = C.difference > 0 ? "A" : "B";
  tiles("cTiles", [
    ["A: as built", m(C.total_a), "yearly cost of the site", cheaper === "A" ? "accent" : ""],
    [C.names.b, m(C.total_b), "yearly cost of the site", cheaper === "B" ? "accent" : ""],
    ["B − A", m(C.difference), C.difference > 0 ? `A is ${m(C.difference)} cheaper per year` : `B is ${m(-C.difference)} cheaper per year`],
    ["A invests more", m(C.extra_investment), `${m(C.invested_a)} against ${m(C.invested_b)}`],
    ["A's running saving", `${m(C.running_saving)}/yr`, "B's running cost − A's"],
    ["Payback of A's extra investment", C.payback_yr == null ? "–" : `${fmt(C.payback_yr, 1)} yr`, "extra investment ÷ running saving"],
  ]);
  const left = [...C.without, ...C.also].map((x) => blockInfo(x).name.toLowerCase());
  $("cWhy").innerHTML = `Scenario B is the same system without ${esc(left.join(", "))}` +
    (C.also.length ? ` (${esc(C.also.map((x) => `${blockInfo(x).name.toLowerCase()}: ${linkReason(x)}`).join("; "))})` : "") +
    `, sized the same way (${C.b_mode === "joint" ? "together" : "one at a time"}). ` +
    (C.difference > 0 ? `With these blocks the site costs <b>${m(C.difference)} less per year</b>, investments spread over their lives included.`
      : `Without these blocks the site costs <b>${m(-C.difference)} less per year</b>: they do not pay for themselves here.`) +
    (C.payback_yr != null ? ` A invests ${m(C.extra_investment)} more and saves ${m(C.running_saving)} a year in running costs: it pays back in ${fmt(C.payback_yr, 1)} years.` : "");
  const T = C.costs, col = (n) => T.columns.indexOf(n);
  const lines = T.rows.filter((r) => !String(r[col("Item")]).startsWith("Total") && r[col("Part")] !== "Total" && (Math.abs(r[col("A")]) > 0.5 || Math.abs(r[col("B")]) > 0.5));
  chart("cChart", { type: "bar", data: { labels: lines.map((r) => r[col("Item")]), datasets: [
    { label: "A", data: lines.map((r) => r[col("A")]), backgroundColor: COLORS.accent },
    { label: "B", data: lines.map((r) => r[col("B")]), backgroundColor: "#cbd5e1" },
  ] }, options: { indexAxis: "y", scales: { x: { title: { display: true, text: `${cu} per year` } } } } });
  $("cTable").innerHTML = `<tr><th>Item</th><th>A</th><th>B</th><th>B − A</th></tr>` + T.rows.map((r) => {
    const total = String(r[col("Item")]).startsWith("Total") || r[col("Part")] === "Total";
    return `<tr${total ? ' class="total"' : ""}><td class="text">${esc(r[col("Item")])}</td><td>${fmt(r[col("A")], 0)}</td><td>${fmt(r[col("B")], 0)}</td><td>${fmt(r[col("B - A")], 0)}</td></tr>`;
  }).join("");
  renderTable("cFigures", C.figures, { format: (v) => (typeof v === "number" ? fmt(v, Math.abs(v) < 100 ? 1 : 0) : v) });
}

// the electricity side, for every run: one case without battery, and one with the chosen battery when there is one
S.ecase = null;
function renderElectricity() {
  const E = S.results.electricity, keys = Object.keys(E.cases);
  if (!keys.includes(S.ecase)) S.ecase = keys[keys.length - 1];   // with the battery when there is one
  $("eCaseRow").hidden = keys.length < 2;
  $("eCaseSeg").innerHTML = keys.map((k) => `<label><input type="radio" name="ecase" value="${k}" ${k === S.ecase ? "checked" : ""}><span>${esc(E.cases[k].kpi.label)}</span></label>`).join("");
  $("eCaseSeg").querySelectorAll("input").forEach((i) => i.addEventListener("change", () => { S.ecase = i.value; renderElectricity(); }));
  const C = E.cases[S.ecase], k = C.kpi, c = k.currency;
  const m = (v) => `${fmt(v, 0)} ${c}`;
  if (!S.results.battery && !S.results.boiler) $("resLead").textContent = `Electricity of the system · regime ${k.regime}`;
  tiles("eTiles", [
    ["Electricity demand", `${fmt(k.load_mwh, 0)} MWh`, `peak ${fmt(k.load_peak_kw, 0)} kW · ${fmt(k.import_mwh, 0)} MWh bought`],
    ["PV production", `${fmt(k.pv_mwh, 0)} MWh`, `Voltiris ${fmt(k.voltiris_mwh, 0)} · existing PV ${fmt(k.existing_pv_mwh, 0)} MWh`],
    ["Self-consumption", `${fmt(k.sc_pct, 1)} %`, `${fmt(k.pv_used_on_site_mwh, 0)} of ${fmt(k.pv_mwh, 0)} MWh of PV used on site`, "accent"],
    ["Self-sufficiency", `${fmt(k.ss_pct, 1)} %`, "of the load covered by the PV"],
    ["Export revenue", m(k.export_revenue), `${fmt(k.export_mwh, 0)} MWh sold to the grid`],
    ["Yearly bill", m(k.bill), `${m(k.bill_no_pv)} without PV: the PV saves ${m(k.saving_vs_no_pv)}`],
  ]);
  const M = C.monthly, col = (n) => M.rows.map((r) => r[M.columns.indexOf(n)]);
  const labels = M.index, neg = (a) => a.map((v) => -v), some = (d) => d.data.some((v) => Math.abs(v) > 1e-9);
  const bar = (label, data, color, stack = "s") => ({ type: "bar", label, data, backgroundColor: color, stack, order: 2 });
  const lineOn = (label, data, color, stack, extra = {}) => ({ type: "line", label, data, borderColor: color, backgroundColor: color, pointRadius: 2, borderWidth: 2, stack, order: 1, ...extra });
  const x = { stacked: true, grid: { display: false } };
  chart("eMonthly", { type: "bar", data: { labels, datasets: [
    bar("Voltiris to load", col("Voltiris to load (MWh)"), COLORS.pv), bar("Existing PV to load", col("Existing PV to load (MWh)"), COLORS.existing),
    bar("Battery to load", col("Battery to load (MWh)"), COLORS.bat), bar("Grid to load", col("Grid to load (MWh)"), COLORS.imp),
    lineOn("Load", col("Load (MWh)"), COLORS.load, "load"),
  ].filter(some) }, options: { scales: { x, y: { stacked: true, beginAtZero: true, title: { display: true, text: "MWh per month" } } } } });
  const direct = col("Voltiris to load (MWh)").map((v, i) => v + col("Existing PV to load (MWh)")[i]);
  chart("eSc", { type: "bar", data: { labels, datasets: [
    bar("PV used directly", direct, COLORS.pv), bar("PV stored in the battery", col("PV to battery (MWh)"), "#9fd3cd"),
    bar("PV exported", col("PV exported (MWh)"), COLORS.exp),
    lineOn("Self-consumption, %", col("SC (%)"), COLORS.load, "sc", { yAxisID: "y1" }),
    lineOn("Self-sufficiency, %", col("SS (%)"), COLORS.soc, "ss", { yAxisID: "y1", borderDash: [4, 3] }),
  ].filter(some) }, options: { scales: { x, y: { stacked: true, title: { display: true, text: "MWh of PV per month" } },
    y1: { position: "right", min: 0, max: 100, grid: { display: false }, title: { display: true, text: "%" } } } } });
  chart("eMoney", { type: "bar", data: { labels, datasets: [
    bar("Import cost", col("Import cost"), COLORS.imp), bar("Capacity charges", col("Capacity charge"), "#93c5fd"),
    bar("EaaS fee", col("EaaS fee"), COLORS.pv), bar("Export revenue", neg(col("Export revenue")), COLORS.exp),
    lineOn("Net bill", col("Net"), COLORS.load, "net"),
  ].filter(some) }, options: { scales: { x, y: { stacked: true, title: { display: true, text: `${c} per month` } } } } });
  renderTable("eBill", C.bills, { indexLabel: `Component, ${c}/yr`, highlight: (row, i, data) => data.index[i] === "Total",
    format: (v) => fmt(v, 0) });
  $("eBill").innerHTML += `<tr class="total"><td class="text">Saving against no PV</td><td></td><td>${fmt(k.saving_vs_no_pv, 0)}</td></tr>`;
  renderTable("eMonthlyTable", M, { indexLabel: "Month" });
  drawElecWeek();
}
function drawElecWeek() {
  const E = S.results && S.results.electricity; if (!E || !E.cases[S.ecase]) return;
  const h = E.cases[S.ecase].hourly, week = Number($("eWeek").value), from = week * 168, n = Math.min(168, h.load.length - from);
  const labels = hourLabels(h.start, from, n), sl = (a) => (a || []).slice(from, from + n), neg = (a) => a.map((v) => -v);
  $("eWeekLabel").textContent = `${labels[0].slice(0, 10)} to ${labels[n - 1].slice(0, 10)}`;
  const bar = (label, data, color) => ({ type: "bar", label, data, backgroundColor: color, stack: "s", order: 2, barPercentage: 1, categoryPercentage: 1 });
  const total = (label, data, color, extra = {}) => ({ type: "line", label, data, borderColor: color, backgroundColor: color, pointRadius: 0, borderWidth: 1.8, stack: "line", order: 1, ...extra });
  const some = (d) => d.data.some((v) => Math.abs(v || 0) > 1e-9);
  const x = { stacked: true, ticks: dayTicks, grid: { display: false } };
  chart("eWeekChart", { type: "bar", data: { labels, datasets: [
    bar("Voltiris to load", sl(h.voltiris_to_load), COLORS.pv), bar("Existing PV to load", sl(h.existing_to_load), COLORS.existing),
    bar("Battery to load", sl(h.battery_to_load), COLORS.bat), bar("Grid to load", sl(h.grid_to_load), COLORS.imp),
    total("Load", sl(h.load), COLORS.load),
  ].filter(some) }, options: { scales: { x, y: { stacked: true, beginAtZero: true, title: { display: true, text: "kW" } } } } });
  const used = sl(h.voltiris_to_load).map((v, i) => v + sl(h.existing_to_load)[i]);
  chart("eWeekPv", { type: "bar", data: { labels, datasets: [
    bar("Used directly", used, COLORS.pv), bar("Stored in the battery", sl(h.pv_to_battery), "#9fd3cd"), bar("Exported", sl(h.pv_exported), COLORS.exp),
    total("PV produced", sl(h.pv), COLORS.load),
  ].filter(some) }, options: { scales: { x, y: { stacked: true, beginAtZero: true, title: { display: true, text: "kW" } } } } });
  const hasBattery = (h.battery_soc || []).some((v) => v > 1e-6) || (h.battery_to_load || []).some((v) => v > 1e-6);
  $("eWeekBatBox").hidden = !hasBattery;
  if (hasBattery) chart("eWeekBat", { type: "bar", data: { labels, datasets: [
    bar("Gives to the load", sl(h.battery_to_load), COLORS.bat), bar("Gives to the grid (exported)", sl(h.battery_to_grid), "#5eead4"),
    bar("Takes from the PV", neg(sl(h.pv_to_battery)), "#9fd3cd"), bar("Takes from the grid (bought)", neg(sl(h.grid_to_battery)), COLORS.imp),
    total("Energy held, kWh", sl(h.battery_soc), COLORS.soc, { yAxisID: "y1" }),
  ].filter(some) }, options: { scales: { x, y: { stacked: true, title: { display: true, text: "kW" } },
    y1: { position: "right", beginAtZero: true, grid: { display: false }, title: { display: true, text: "kWh" } } } } });
}
$("eWeek").addEventListener("input", drawElecWeek);

function renderStorageStudy() {
  const T = S.results.storage, s = T.summary, ch = T.choice, c = s.currency, life = ch.life_yr;
  const m = (v, d = 0) => `${fmt(v, d)} ${c}`;
  tiles("sTiles", [
    ["Chosen heat storage", `${fmt(s.storage_kwh)} kWh`, `${fmt(s.storage_power_kw)} kW in and out · boiler ${fmt(ch.boiler_kw)} kW`, "accent"],
    ["Yearly value", m(s.storage_value_yr), ch.objective === "joint" ? "site cost saved, before its investment" : "running cost saved − fixed O&M"],
    ["Investment", m(s.storage_investment), `life ${fmt(life)} yr`],
    ["Payback", s.storage_payback_yr == null ? "never" : `${fmt(s.storage_payback_yr, 1)} yr`, `lifetime profit ${m(s.storage_lifetime_profit)}`],
    ["Heat through the tank", `${fmt(s.storage_discharged_mwh, 0)} MWh`, `${fmt(s.storage_cycles, 0)} full cycles · ${fmt(s.storage_losses_mwh, 1)} MWh lost`],
    ["Gas saved", `${fmt(s.gas_mwh_no_storage - s.gas_mwh_storage, 0)} MWh`, `heat released ${fmt(s.heat_released_mwh_no_storage, 0)} → ${fmt(s.heat_released_mwh_storage, 0)} MWh`],
  ]);
  const sw = T.sweep, col = (n) => sw.columns.indexOf(n);
  const rows = sw.rows.map((r) => ({ size: r[col("size")], value: r[col("value")], inv: r[col("investment")], pb: r[col("payback")],
    profit: r[col("lifetime_profit")], released: r[col("released_heat_mwh")], stored: r[col("charged_mwh")], lost: r[col("losses_mwh")] }))
    .sort((a, b) => a.size - b.size);
  const chosen = rows.find((r) => r.size === s.storage_kwh) || {};
  const pays = (r) => r.pb != null && r.pb <= life;
  const paying = rows.filter(pays);
  const pbText = (r) => (r.pb == null ? "never" : `${fmt(r.pb, 1)} years`);
  const kwh = (x) => `<b>${fmt(x)} kWh</b>`;
  let why;
  if (ch.objective === "joint") why = `<b>Sized together</b> with the boiler (System tab): with ${kwh(chosen.size)} of storage the boiler is ${fmt(ch.boiler_kw)} kW; without storage it would be ${fmt(ch.boiler_kw_without)} kW. ` +
    `The site's yearly cost is ${fmt(ch.system_value)} ${c} lower with it, after its investment spread over ${fmt(life)} years. Compared with that system: yearly value ${fmt(chosen.value)} ${c} before its investment, payback ${pbText(chosen)}.`;
  else if (ch.objective === "custom") why = `Objective <b>custom</b>: ${kwh(chosen.size)} is the tested size closest to the size you gave, ${fmt(ch.custom_kwh)} kWh.`;
  else if (ch.objective === "payback") why = `Objective <b>payback</b>: ${kwh(chosen.size)} has the shortest payback of the ${rows.length} sizes tested, ${pbText(chosen)}.`;
  else if (paying.length) {
    const next = paying.filter((r) => r !== chosen).sort((a, b) => b.profit - a.profit)[0];
    why = `Objective <b>profit</b>. ${paying.length} of the ${rows.length} sizes tested pay back within the storage life of ${fmt(life)} years. ` +
      `Among them ${kwh(chosen.size)} has the highest lifetime profit: ${fmt(chosen.value)} ${c}/yr &times; ${fmt(life)} years &minus; ${fmt(chosen.inv)} ${c} = <b>${fmt(chosen.profit)} ${c}</b>.` +
      (next ? ` Next best: ${fmt(next.size)} kWh with ${fmt(next.profit)} ${c}.` : "");
  } else {
    why = `Objective <b>profit</b>, but none of the ${rows.length} sizes tested pays back within the storage life of ${fmt(life)} years` +
      (rows.every((r) => r.pb == null) ? `, and none saves anything, so the first size, ${kwh(chosen.size)}, is kept. Under these settings no heat storage is worth it.`
        : `, so the size with the shortest payback is kept: ${kwh(chosen.size)}, ${pbText(chosen)}.`);
  }
  if (ch.objective !== "joint") why += `<br>Sized one at a time, with the boiler fixed at ${fmt(ch.boiler_kw)} kW: the tank can only save heat the boiler would release (${fmt(s.heat_released_mwh_no_storage, 0)} MWh a year without storage) and shift gas to cheaper days. Sizing together (System page) lets it make the boiler smaller.`;
  $("sWhy").innerHTML = why;
  const sizes = rows.map((r) => r.size);
  chart("sSweep", { type: "bar", data: { labels: sizes.map((x) => `${fmt(x)} kWh`), datasets: [
    { type: "bar", label: `Yearly value, ${c}`, data: rows.map((r) => r.value), backgroundColor: sizes.map((x) => (x === s.storage_kwh ? COLORS.heat : "#fdba74")), yAxisID: "y", order: 2 },
    { type: "line", label: "Payback, years", data: rows.map((r) => r.pb), borderColor: COLORS.load, backgroundColor: COLORS.load, pointRadius: 3, yAxisID: "y1", order: 1 },
    { type: "line", label: `Storage life, ${fmt(life)} years (payback limit)`, data: sizes.map(() => life), borderColor: COLORS.grey, backgroundColor: COLORS.grey,
      borderDash: [6, 4], borderWidth: 1.4, pointRadius: 0, yAxisID: "y1", order: 0 }] },
    options: { scales: { y: { title: { display: true, text: `${c} per year` } },
      y1: { position: "right", grid: { display: false }, title: { display: true, text: "years" }, beginAtZero: true } } } });
  $("sSweepTable").innerHTML = `<tr><th>Size, kWh</th><th>Yearly value, ${c}</th><th>Investment, ${c}</th><th>Payback</th><th>Within ${fmt(life)} yr</th><th>Lifetime profit, ${c}</th><th>Heat stored, MWh</th><th>Lost, MWh</th><th>Heat released, MWh</th><th></th></tr>` +
    rows.map((r) => `<tr${r === chosen ? ' class="hl"' : ""}><td>${fmt(r.size)}</td><td>${fmt(r.value)}</td><td>${fmt(r.inv)}</td><td>${pbText(r)}</td>
      <td class="${pays(r) ? "yes" : "no"}">${pays(r) ? "yes" : "no"}</td><td>${fmt(r.profit)}</td><td>${fmt(r.stored, 1)}</td><td>${fmt(r.lost, 1)}</td>
      <td>${fmt(r.released, 0)}</td><td>${r === chosen ? '<span class="tag">chosen</span>' : ""}</td></tr>`).join("");
  const d = T.daily, n = d.storage_charge.length, t0 = new Date(d.start + "Z").getTime();
  const labels = Array.from({ length: n }, (_, i) => new Date(t0 + i * 864e5).toISOString().slice(0, 10));
  const x = { ticks: monthTicks, grid: { display: false } };
  chart("sYear", { type: "bar", data: { labels, datasets: [
    { type: "bar", label: "Stored, MWh", data: d.storage_charge, backgroundColor: "#fdba74", order: 2 },
    { type: "bar", label: "Given back, MWh", data: d.storage_discharge.map((v) => -v), backgroundColor: COLORS.heat, order: 3 },
    { type: "line", label: "Highest heat in the tank, MWh", data: d.soc_max, borderColor: COLORS.soc, backgroundColor: COLORS.soc, borderWidth: 1.4, pointRadius: 0, order: 1 },
  ] }, options: { scales: { x: { ...x, stacked: true }, y: { title: { display: true, text: "MWh per day" } } } } });
  chart("sRelease", { type: "line", data: { labels, datasets: [
    line("Heat released, no storage", d.heat_release_no_storage, COLORS.grey, { borderDash: [4, 3] }),
    line("Heat released, with storage", d.heat_release, COLORS.heat),
  ] }, options: { scales: { x, y: { beginAtZero: true, title: { display: true, text: "MWh per day" } } } } });
  renderTable("sMonthly", T.monthly, { indexLabel: "Month" });
  // where the value comes from
  const parts = Object.entries(T.value_parts || {}).filter(([, v]) => Math.abs(v) >= 0.5);
  chart("sValue", { type: "bar", data: { labels: parts.map((p) => p[0]).concat("Yearly value"),
    datasets: [{ data: parts.map((p) => p[1]).concat(s.storage_value_yr),
      backgroundColor: parts.map((p) => (p[1] >= 0 ? COLORS.heat : COLORS.neg)).concat(COLORS.load) }] },
    options: { indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: { title: { display: true, text: `${c} per year` } } } } });
  $("sValueTable").innerHTML = `<tr><th>Part</th><th>${c}/yr</th></tr>` +
    parts.map(([k, v]) => `<tr><td class="text">${esc(k)}</td><td>${fmt(v, 0)}</td></tr>`).join("") +
    `<tr class="total"><td class="text">Yearly value, before its investment</td><td>${fmt(s.storage_value_yr, 0)}</td></tr>` +
    `<tr><td class="text">Its investment per year (${fmt(s.storage_investment, 0)} over ${fmt(life)} years)</td><td>${fmt(-s.storage_investment / life, 0)}</td></tr>` +
    `<tr class="total"><td class="text">Value after its investment</td><td>${fmt(s.storage_value_yr - s.storage_investment / life, 0)}</td></tr>`;
  // gas per month
  const M = T.monthly, mc = (n) => M.rows.map((r) => r[M.columns.indexOf(n)]);
  chart("sGasMonthly", { type: "bar", data: { labels: M.index, datasets: [
    { type: "bar", label: "Gas without storage, MWh", data: mc("Gas, no storage (MWh)"), backgroundColor: "#cbd5e1", yAxisID: "y", order: 2 },
    { type: "bar", label: "Gas with storage, MWh", data: mc("Gas, storage (MWh)"), backgroundColor: COLORS.gas, yAxisID: "y", order: 2 },
    { type: "line", label: `Running cost saved, ${c}`, data: mc("Running cost saved"), borderColor: COLORS.heat, backgroundColor: COLORS.heat, pointRadius: 3, yAxisID: "y1", order: 1 },
  ] }, options: { scales: { x: { grid: { display: false } }, y: { beginAtZero: true, title: { display: true, text: "MWh of gas" } },
    y1: { position: "right", grid: { display: false }, title: { display: true, text: c } } } } });
  drawStorageWeek();
}
function drawStorageWeek() {
  const T = S.results && S.results.storage; if (!T || !T.hourly) return;
  const h = T.hourly, week = Number($("sWeek").value), from = week * 168, n = Math.min(168, h.heat_demand.length - from);
  const labels = hourLabels(h.start, from, n), sl = (a) => (a || []).slice(from, from + n);
  $("sWeekLabel").textContent = `${labels[0].slice(0, 10)} to ${labels[n - 1].slice(0, 10)}`;
  const bar = (label, data, color) => ({ type: "bar", label, data, backgroundColor: color, stack: "s", order: 2, barPercentage: 1, categoryPercentage: 1 });
  const total = (label, data, color, extra = {}) => ({ type: "line", label, data, borderColor: color, backgroundColor: color, pointRadius: 0, borderWidth: 1.8, stack: "line", order: 1, ...extra });
  const some = (d) => d.data.some((v) => Math.abs(v || 0) > 1e-9);
  const x = { stacked: true, ticks: dayTicks, grid: { display: false } };
  const direct = sl(h.heat_demand).map((v, i) => Math.max(v - sl(h.storage_discharge)[i] - sl(h.heat_unmet)[i], 0));
  chart("sWeekDemand", { type: "bar", data: { labels, datasets: [
    bar("Boiler, directly", direct, COLORS.heat), bar("From the tank", sl(h.storage_discharge), "#be185d"), bar("Unmet", sl(h.heat_unmet), COLORS.neg),
    total("Heat demand", sl(h.heat_demand), COLORS.load),
  ].filter(some) }, options: { scales: { x, y: { stacked: true, beginAtZero: true, title: { display: true, text: "kW" } } } } });
  chart("sWeekBoiler", { type: "bar", data: { labels, datasets: [
    bar("To the greenhouse", direct, COLORS.heat), bar("Into the tank", sl(h.storage_charge), "#fdba74"), bar("Released", sl(h.heat_release), COLORS.grey),
    total("Boiler output", sl(h.boiler_heat), COLORS.load),
    total("Boiler output without storage", sl(h.boiler_heat_no_storage), COLORS.load, { borderDash: [5, 4], borderWidth: 1.4 }),
  ].filter(some) }, options: { scales: { x, y: { stacked: true, beginAtZero: true, title: { display: true, text: "kW" } } } } });
  chart("sWeekTank", { type: "line", data: { labels, datasets: [
    line("Heat in the tank, kWh", sl(h.storage_soc), COLORS.soc, { fill: { target: "origin" }, backgroundColor: "rgba(124,58,237,.12)" }),
  ] }, options: { scales: { x: { ticks: dayTicks, grid: { display: false } }, y: { beginAtZero: true, title: { display: true, text: "kWh" } } } } });
}
$("sWeek").addEventListener("input", drawStorageWeek);

function renderBoilerStudy() {
  const H = S.results.boiler, s = H.summary, ch = H.choice, c = s.currency, life = ch.life_yr;
  const m = (v, d = 0) => `${fmt(v, d)} ${c}`;
  if (!S.results.battery) $("resLead").textContent = `${ch.joint ? "Sized together" : `Gas boiler study · objective: ${BOILER_OBJECTIVE[ch.objective]}`} · CO2 demand ${s.co2_mode === "required" ? "must be met" : "by-product of heating"}`;
  tiles("hTiles", [
    ["Chosen boiler", `${fmt(s.boiler_kw)} kW`, s.boiler_covers ? (ch.storage_kwh ? `covers the demand with the heat storage (peak ${fmt(s.boiler_needed_kw)} kW)` : `covers the demand (needs ${fmt(s.boiler_needed_kw)} kW)`) : "does not cover the demand", s.boiler_covers ? "accent" : "warn"],
    ["Heat cost", `${m(s.heat_cost_per_mwh, 2)}/MWh`, "investment ÷ life + yearly cost, per MWh of heat met"],
    ["Yearly cost", m(s.boiler_cost_yr), `gas ${m(s.gas_cost_yr)} · levy ${m(s.co2_levy_yr)} · O&M ${m(s.boiler_om_yr)}`],
    ["Investment", m(s.boiler_investment), `lifetime cost ${m(s.boiler_lifetime_cost)} over ${fmt(s.boiler_life_yr)} yr`],
    ["Gas burnt", `${fmt(s.gas_mwh, 0)} MWh`, `${fmt(s.boiler_full_load_h, 0)} full-load hours`],
    ["CO2 to the greenhouse", `${fmt(s.co2_supplied_t, 1)} t`, `${fmt(s.co2_self_sufficiency_pct, 1)} % of the ${fmt(s.co2_demand_t, 1)} t demand · ${fmt(s.co2_emitted_t, 0)} t emitted`],
  ]);
  // why this size
  const sw = H.sweep, col = (n) => sw.columns.indexOf(n);
  const rows = sw.rows.map((r) => ({ size: r[col("size")], covers: r[col("covers")], yearly: r[col("yearly_cost")], inv: r[col("investment")],
    life: r[col("lifetime_cost")], unmetHeat: r[col("unmet_heat_mwh")], unmetCo2: r[col("unmet_co2_t")], released: r[col("released_heat_mwh")] }))
    .sort((a, b) => a.size - b.size);
  const chosen = rows.find((r) => r.size === s.boiler_kw) || {};
  const covering = rows.filter((r) => r.covers);
  const kw = (x) => `<b>${fmt(x)} kW</b>`;
  let why;
  if (ch.joint) why = `<b>Sized together</b> with the other blocks (System tab): ${kw(chosen.size)}${ch.storage_kwh ? `, with the ${fmt(ch.storage_kwh)} kWh heat storage taking part of the peaks` : ""}.`;
  else if (ch.objective === "custom") why = `Objective <b>custom</b>: ${kw(chosen.size)} is the tested size closest to the size you gave, ${fmt(ch.custom_kw)} kW.`;
  else if (!covering.length) why = `None of the ${rows.length} sizes tested covers the demand, so the largest, ${kw(chosen.size)}, is kept. It leaves ${fmt(chosen.unmetHeat, 1)} MWh of heat and ${fmt(chosen.unmetCo2, 1)} t of CO2 unmet: test larger sizes on the Gas boiler page.`;
  else if (ch.objective === "smallest") why = `Objective <b>smallest that covers</b>: ${covering.length} of the ${rows.length} sizes tested cover the demand; the smallest is ${kw(chosen.size)}.`;
  else {
    const next = covering.filter((r) => r !== chosen).sort((a, b) => a.life - b.life)[0];
    why = `Objective <b>lowest lifetime cost</b>: ${covering.length} of the ${rows.length} sizes tested cover the demand. ${kw(chosen.size)} costs the least over ${fmt(life)} years: ` +
      `${fmt(chosen.inv)} ${c} + ${fmt(chosen.yearly)} ${c}/yr &times; ${fmt(life)} = <b>${fmt(chosen.life)} ${c}</b>.` + (next ? ` Next: ${fmt(next.size)} kW with ${fmt(next.life)} ${c}.` : "");
  }
  const notes = [];
  if (covering.length && rows.some((r) => !r.covers)) notes.push(`The sizes below ${fmt(covering[0].size)} kW leave demand unmet: the busiest step needs ${fmt(ch.needed_kw)} kW.`);
  if (s.heat_released_mwh > 0.5) notes.push(`${fmt(s.heat_released_mwh, 0)} MWh of heat is released: the boiler runs for CO2 when the greenhouse needs less heat.`);
  if (s.co2_unmet_t > 0.05) notes.push(`${fmt(s.co2_unmet_t, 1)} t of the CO2 demand stays unmet.`);
  $("hWhy").innerHTML = why + (notes.length ? "<br>" + notes.join(" ") : "");
  // sizes: investment and yearly cost over the life, stacked
  chart("hSweep", { type: "bar", data: { labels: rows.map((r) => `${fmt(r.size)} kW${r.covers ? "" : " (short)"}`), datasets: [
    { label: `Investment, ${c}`, data: rows.map((r) => r.inv), backgroundColor: rows.map((r) => (r === chosen ? COLORS.load : "#cbd5e1")) },
    { label: `Yearly cost × ${fmt(life)} years, ${c}`, data: rows.map((r) => r.yearly * life),
      backgroundColor: rows.map((r) => (r === chosen ? COLORS.heat : r.covers ? "#fdba74" : "#e2e8f0")) },
  ] }, options: { scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, title: { display: true, text: c } } } } });
  $("hSweepTable").innerHTML = `<tr><th>Size, kW</th><th>Covers</th><th>Unmet heat, MWh</th><th>Unmet CO2, t</th><th>Heat released, MWh</th><th>Yearly cost, ${c}</th><th>Investment, ${c}</th><th>Lifetime cost, ${c}</th><th></th></tr>` +
    rows.map((r) => `<tr${r === chosen ? ' class="hl"' : ""}><td>${fmt(r.size)}</td><td class="${r.covers ? "yes" : "no"}">${r.covers ? "yes" : "no"}</td>
      <td>${fmt(r.unmetHeat, 1)}</td><td>${fmt(r.unmetCo2, 1)}</td><td>${fmt(r.released, 0)}</td><td>${fmt(r.yearly)}</td><td>${fmt(r.inv)}</td>
      <td>${fmt(r.life)}</td><td>${r === chosen ? '<span class="tag">chosen</span>' : ""}</td></tr>`).join("");
  // the year, per day
  const d = H.daily, n = d.heat_demand.length, t0 = new Date(d.start + "Z").getTime();
  const labels = Array.from({ length: n }, (_, i) => new Date(t0 + i * 864e5).toISOString().slice(0, 10));
  const x = { ticks: monthTicks, grid: { display: false } };
  const any = (a) => a.some((v) => v > 1e-3);
  chart("hYear", { type: "line", data: { labels, datasets: [
    line("Heat demand", d.heat_demand, COLORS.load), line("Boiler heat", d.boiler_heat, COLORS.heat),
    any(d.heat_release) && line("Heat released", d.heat_release, COLORS.grey),
    any(d.heat_unmet) && line("Heat unmet", d.heat_unmet, COLORS.neg),
    line("Gas burnt", d.gas, COLORS.gas, { borderDash: [4, 3], borderWidth: 1.3 }),
  ].filter(Boolean) }, options: { scales: { x, y: { beginAtZero: true, title: { display: true, text: "MWh per day" } } } } });
  chart("hCo2", { type: "line", data: { labels, datasets: [
    line("CO2 demand", d.co2_demand, COLORS.load),
    line("CO2 to the greenhouse", d.co2_supplied, COLORS.co2, { fill: { target: "origin" }, backgroundColor: "rgba(100,116,139,.15)" }),
    line("CO2 vented", d.co2_vented, COLORS.grey, { borderDash: [4, 3], borderWidth: 1.3 }),
  ] }, options: { scales: { x, y: { beginAtZero: true, title: { display: true, text: "t per day" } } } } });
  renderTable("hMonthly", H.monthly, { indexLabel: "Month" });
}
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
  boilerObjectiveChanged();
  storageObjectiveChanged();
  try {   // after a refresh, the last finished run's results come back
    const last = await api("/api/results");
    if (!last.error) { S.results = last; renderResults(); }
  } catch (e) { /* no finished run yet */ }
  const first = S.options.cases.find((c) => c.name.startsWith("blocks/")) || S.options.cases[0];
  if (first) {
    $("caseSelect").value = first.path;
    $("caseLoad").click();
  } else {
    $("caseNew").click();
  }
})();

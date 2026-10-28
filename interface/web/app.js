/* Interface of the thesis model: the system (scenario preset or own blocks) picks the model that runs it (a run type,
   interface/adapters). The page builds a case from the form, asks the local Python server (interface/server.py) to
   inspect, preview and run it, and draws the results. No framework; charts with Chart.js (chart.umd.js, stored
   locally). */
"use strict";

const $ = (id) => document.getElementById(id);
const S = {
  options: null, workbook: null, params: null, preview: null, results: null,
  system: { preset: null, blocks: new Set() }, runType: null, runTypeWanted: null,
  columns: {}, fieldValues: {}, charts: {}, logLength: 0, polling: null, monthlyTab: "monthly_battery",
};
// the battery model has no ancillary switch: "off" is these overrides (rate 0, no reserve)
const ANCILLARY_OFF = { ancillary: { rate_per_kw_year: 0, reserve: { mode: "percent", frac: 0 } } };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const COLORS = { load: "#334155", pv: "#e0a100", existing: "#a16207", imp: "#2563eb", exp: "#16a34a",
  bat: "#0f766e", soc: "#7c3aed", da: "#dc2626", neg: "#b42318", accent: "#0f766e", grey: "#94a3b8" };
const CONVERSION = { power: "repeated", price: "repeated", state: "repeated", energy: "divided", time: "rebuilt" };

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
  $(container).innerHTML = items.filter(Boolean).map(([k, v, s, cls]) =>
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
function line(label, data, color, extra = {}) {
  return { label, data, borderColor: color, backgroundColor: color, borderWidth: 1.6, pointRadius: 0, tension: 0.15, ...extra };
}

// -- navigation -----------------------------------------------------------------------------------------------------
function showStep(name) {
  document.querySelectorAll(".step").forEach((s) => s.classList.toggle("active", s.id === "step-" + name));
  document.querySelectorAll("#steps button").forEach((b) => b.classList.toggle("active", b.dataset.step === name));
  window.scrollTo(0, 0);
  if (name === "market" || name === "params") loadParams();
  if (name === "params") checkSetup(true);
  if (name === "run") renderCaseFile();
  if (name === "results" && S.results) Object.values(S.charts).forEach((c) => c.resize());
}
document.querySelectorAll("#steps button").forEach((b) => b.addEventListener("click", () => showStep(b.dataset.step)));
document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => showStep(b.dataset.goto)));

// -- step 1: system -------------------------------------------------------------------------------------------------
const has = (block) => S.system.blocks.has(block);
const RT = () => S.options.run_types[S.runType] || Object.values(S.options.run_types)[0];
// every run type that can run these blocks (the first is the default), or why none can
function runTypeFor(blocks) {
  const ids = [], reasons = [];
  for (const rt of Object.values(S.options.run_types)) {
    const missing = rt.blocks_required.filter((b) => !blocks.has(b));
    const extra = [...blocks].filter((b) => !rt.blocks_allowed.includes(b));
    if (!missing.length && !extra.length) { ids.push(rt.id); continue; }
    const name = (id) => (S.options.blocks.find((b) => b.id === id) || { name: id }).name;
    reasons.push(`${rt.name}: ${[missing.length && `needs ${missing.map(name).join(", ")}`,
      extra.length && `cannot run ${extra.map(name).join(", ")}`].filter(Boolean).join("; ")}`);
  }
  const id = ids.includes(S.runTypeWanted) ? S.runTypeWanted : ids[0] || null;
  return { id, ids, why: reasons };
}
$("runTypeSelect").addEventListener("change", () => { S.runTypeWanted = $("runTypeSelect").value; systemChanged(); });
function renderBlocks() {
  const preset = S.options.presets.find((p) => p.id === S.system.preset);
  const notes = (preset && preset.options) || {};
  $("blockGrid").innerHTML = S.options.blocks.map((b) => `
    <label class="block ${has(b.id) ? "on" : ""} ${b.status}">
      <input type="checkbox" data-block="${b.id}" ${has(b.id) ? "checked" : ""}>
      <span><b>${esc(b.name)}</b>
        <small>${esc(b.role)}</small>
        <small class="carriers">${b.in.length ? `in: ${esc(b.in.join(", "))}` : ""}${b.in.length && b.out.length ? " · " : ""}${b.out.length ? `out: ${esc(b.out.join(", "))}` : ""}</small>
        ${notes[b.id] ? `<small class="preset-note">${esc(notes[b.id])}</small>` : ""}
        <em class="status">${b.status === "model" ? "runs today" : "not built yet"}${b.status_note ? ` · ${esc(b.status_note)}` : ""}</em>
      </span></label>`).join("");
  $("blockGrid").querySelectorAll("input").forEach((i) => i.addEventListener("change", () => {
    if (i.checked) S.system.blocks.add(i.dataset.block); else S.system.blocks.delete(i.dataset.block);
    const preset = S.options.presets.find((p) => p.id === S.system.preset);
    if (preset && !sameSet(new Set(preset.blocks), S.system.blocks)) S.system.preset = null;
    S.preview = null;
    systemChanged();
    drawWorkbookWeek();
  }));
}
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
  $("presetInfo").textContent = preset ? `Preset: ${preset.name}. Change any block below; the system then becomes your own.`
    : "Your own system. A preset ticks the blocks of a thesis scenario (thesis.md, section 2.1).";
  renderBlocks();
  const fit = runTypeFor(S.system.blocks);
  const changed = fit.id !== S.runType;
  S.runType = fit.id;
  const planned = S.options.blocks.filter((b) => has(b.id) && b.status !== "model");
  $("systemCheck").innerHTML = fit.id
    ? `This system runs with <b>${esc(RT().name)}</b>.` + (fit.ids.length > 1 ? " Another model can run it too: choose below." : "")
    : `<b>No model can run this system yet.</b> ${fit.why.map(esc).join(" ")}` +
      (planned.length ? `<br>Not built yet: ${planned.map((b) => esc(b.name)).join(", ")}.` : "");
  $("runTypeRow").hidden = fit.ids.length < 2;
  fillSelect("runTypeSelect", fit.ids.map((id) => [id, S.options.run_types[id].name]));
  if (fit.id) $("runTypeSelect").value = fit.id;
  if (changed && fit.id && $("mUtility").value) loadParamsSoon();
  document.querySelectorAll(".sys-note").forEach((n) => {
    n.hidden = !!fit.id;
    n.innerHTML = `<b>No model can run the system of step 1 yet.</b> The steps below show what the battery study needs; go back to step 1 to choose a system that runs.`;
  });
  document.querySelectorAll(".block-card").forEach((c) => (c.hidden = !has(c.dataset.block)));
  $("plannedCard").hidden = !planned.length;
  $("plannedList").textContent = planned.map((b) => b.name).join(", ") + ": these blocks have no parameters yet and are left out of the run.";
  $("runBtn").disabled = !fit.id;
  $("runInfo").textContent = fit.id ? "" : "Choose a system that runs in step 1.";
  if (S.workbook) renderWorkbook();
  if (changed) S.preview = null;
  updateTop();
}
$("presetApply").addEventListener("click", () => {
  const preset = S.options.presets.find((p) => p.id === $("presetSelect").value);
  if (!preset) return toast("Choose a preset first.", true);
  setSystem(preset.blocks, preset.id);
  toast(`Preset ${preset.name}`);
});

// -- the case: form <-> JSON -----------------------------------------------------------------------------------------
function collectCase() {
  const market = { country: $("mCountry").value, region: $("mRegion").value };
  const [utility, year] = ($("mUtility").value || "|").split("|");
  Object.assign(market, { utility, year: Number(year) });
  const sizing = {
    objective: document.querySelector("input[name=objective]:checked").value,
    custom_kwh: Number($("zCustom").value) || 422,
    fine_grid_kwh: numbers($("zFine").value),
    fine_window_kwh: Number($("zWindow").value) || 0,
    cap_at_subsidy_size: $("zCap").checked,
  };
  const sweep = numbers($("zSweep").value);
  if (sweep.length) sizing.sweep_kwh = sweep;
  const manual = document.querySelector("input[name=regimeMode]:checked").value === "manual";
  const imp = $("sImport").value, exp = $("sExport").value;
  const c = {
    input_file: $("wbPath").value.trim().replace(/^"|"$/g, ""),
    year: Number($("dataYear").value),
    market,
    business_model: $("mBusiness").value,
    pv_modules: has("voltiris") ? Number($("sModules").value) || 0 : 0,
    use_existing_pv: has("existing_pv"),
    grid: { import_max_kw: imp === "" ? null : Number(imp), export_max_kw: exp === "" ? null : Number(exp) },
    regime: manual ? { auto: false, manual: $("sRegime").value } : { auto: true },
    sizing,
    overrides: $("sAncillary").checked ? currentOverrides() : deepMerge(currentOverrides(), ANCILLARY_OFF),
    tag: $("rTag").value.trim() || "study",
    system: { preset: S.system.preset, blocks: [...S.system.blocks], run_type: S.runType },
  };
  if (Object.keys(S.columns).length) c.columns = { ...S.columns };
  return c;
}

function applyCase(c) {
  const market = c.market || {};
  // a case without a system is an older battery case; use_existing_pv means the existing PV block
  const sys = c.system || { preset: null, blocks: S.options.presets.find((p) => p.id === "battery_study").blocks };
  S.runTypeWanted = sys.run_type || null;
  setSystem(c.use_existing_pv ? [...new Set(sys.blocks.concat("existing_pv"))] : sys.blocks, sys.preset);
  $("wbPath").value = c.input_file || "";
  const match = S.options.workbooks.find((w) => w.path === c.input_file || w.name === (c.input_file || "").split(/[\\/]/).pop());
  if (match) { $("wbSelect").value = match.path; if (!c.input_file || !/[\\/]/.test(c.input_file)) $("wbPath").value = match.path; }
  $("dataYear").value = c.year || market.year || 2026;
  S.columns = { ...(c.columns || {}) };
  setMarket(market.country, market.region || market.canton, market.utility, market.year);
  $("mBusiness").value = c.business_model || "direct_sales";
  // overrides: "ancillary off" first, then the key fields take what they know, the rest goes to the JSON box
  const rest = JSON.parse(JSON.stringify(c.overrides || {}));
  const anc = rest.ancillary || {};
  const off = anc.rate_per_kw_year === 0 && anc.reserve && anc.reserve.frac === 0 && (anc.reserve.mode || "percent") === "percent";
  if (off) { delPath(rest, "ancillary.rate_per_kw_year"); delPath(rest, "ancillary.reserve.frac"); delPath(rest, "ancillary.reserve.mode"); }
  S.fieldValues = {};
  KEY_FIELDS.forEach((f) => {
    const v = getPath(rest, f.path);
    if (v !== undefined && (typeof v !== "object" || Array.isArray(v))) { S.fieldValues[f.path] = v; delPath(rest, f.path); }
  });
  $("jsonOverrides").value = Object.keys(rest).length ? JSON.stringify(rest, null, 2) : "";
  $("sModules").value = c.pv_modules || 0;
  $("sAncillary").checked = !off;
  $("sImport").value = c.grid && c.grid.import_max_kw != null ? c.grid.import_max_kw : "";
  $("sExport").value = c.grid && c.grid.export_max_kw != null ? c.grid.export_max_kw : "";
  const regime = c.regime || { auto: true };
  document.querySelector(`input[name=regimeMode][value=${regime.auto === false ? "manual" : "auto"}]`).checked = true;
  S.manualRegime = regime.manual || null;
  const sz = c.sizing || {};
  document.querySelector(`input[name=objective][value=${sz.objective || "profit"}]`).checked = true;
  $("zCustom").value = sz.custom_kwh || 422;
  $("zSweep").value = (sz.sweep_kwh || []).join(", ");
  $("zFine").value = (sz.fine_grid_kwh || []).join(", ");
  $("zWindow").value = sz.fine_window_kwh != null ? sz.fine_window_kwh : 250;
  $("zCap").checked = sz.cap_at_subsidy_size !== false;
  $("rTag").value = c.tag || "study";
  $("rFolder").value = "";
  S.preview = null;
  $("previewSite").hidden = true;
  updateTop();
  if ($("wbPath").value) readWorkbook();
  loadParams();
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
function fillSelect(id, items, placeholder) {
  $(id).innerHTML = (placeholder ? `<option value="">${esc(placeholder)}</option>` : "") +
    items.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("");
}
$("caseLoad").addEventListener("click", async () => {
  if (!$("caseSelect").value) return toast("Choose a case file first.", true);
  try {
    const data = await api("/api/case", { path: $("caseSelect").value });
    applyCase(data.case);
    $("caseInfo").textContent = `Loaded ${data.path}`;
    toast("Case loaded");
  } catch (e) { toast(e.message, true); }
});
$("caseFile").addEventListener("change", async (ev) => {
  const file = ev.target.files[0]; if (!file) return;
  try {
    const c = JSON.parse(await file.text());
    if (c.market && c.market.canton && !c.market.region) c.market.region = c.market.canton;
    applyCase(c);
    $("caseInfo").textContent = `Loaded ${file.name}. Its workbook path was "${c.input_file}": if it is not found, pick or upload the workbook in step 2.`;
  } catch (e) { toast("Not a valid case file: " + e.message, true); }
  ev.target.value = "";
});
$("caseNew").addEventListener("click", () => {
  const m = RT().markets[0];
  applyCase({ input_file: $("wbSelect").value || "", market: m, year: m.year, tag: "study" });
  $("caseInfo").textContent = "Empty case with the battery study preset: change the blocks, pick the workbook, then go through the steps.";
});

// -- step 2: workbook ------------------------------------------------------------------------------------------------
$("wbSelect").addEventListener("change", () => { if ($("wbSelect").value) { $("wbPath").value = $("wbSelect").value; readWorkbook(); } });
$("wbUpload").addEventListener("change", async (ev) => {
  const file = ev.target.files[0]; if (!file) return;
  try {
    const res = await fetch(`/api/upload?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    $("wbPath").value = data.path;
    S.options.workbooks.push({ name: data.name, path: data.path });
    fillSelect("wbSelect", S.options.workbooks.map((w) => [w.path, w.name]), "— choose —");
    $("wbSelect").value = data.path;
    toast(`Uploaded ${data.name}`);
    readWorkbook();
  } catch (e) { toast(e.message, true); }
  ev.target.value = "";
});
$("wbRead").addEventListener("click", () => readWorkbook());
$("dataYear").addEventListener("change", () => readWorkbook());

async function readWorkbook() {
  const path = $("wbPath").value.trim().replace(/^"|"$/g, "");
  if (!path) return toast("Give the workbook first.", true);
  $("wbRead").disabled = true; $("wbRead").textContent = "Reading…";
  try {
    S.workbook = await api("/api/workbook", { path, year: Number($("dataYear").value), columns: S.columns, run_type: RT().id });
    // a coarser workbook comes back converted to 15 min: the run uses the converted file
    if (S.workbook.converted_from) $("wbPath").value = S.workbook.path;
    renderWorkbook();
    S.preview = null;
  } catch (e) { toast("Cannot read the workbook: " + e.message, true); }
  $("wbRead").disabled = false; $("wbRead").textContent = "Read workbook";
}

function renderWorkbook() {
  const w = S.workbook, defaults = RT().default_columns;
  $("wbColumnsCard").hidden = false;
  const opts = (sel) => `<option value="">— none —</option>` + w.columns.map((c) =>
    `<option ${c === sel ? "selected" : ""}>${esc(c)}</option>`).join("");
  const roles = w.roles.filter((r) => r.block === "time" || has(r.block));
  $("wbRoles").innerHTML = `<tr><th>Used for</th><th>Block</th><th>Unit</th><th>Coarser step</th><th>Needed</th><th>Column in the workbook</th><th>Status</th></tr>` +
    roles.map((r) => `<tr><td class="text"><b>${esc(r.about)}</b><br><small class="muted">${r.role}</small></td>
      <td class="text">${esc(r.block)}</td><td class="text">${esc(r.unit)}</td><td class="text">${CONVERSION[r.kind] || "–"}</td>
      <td class="text">${esc(r.needed)}</td>
      <td class="text"><select data-role="${r.role}">${opts(r.found ? r.column : "")}</select></td>
      <td class="text">${r.found ? '<span class="ok">found</span>' : r.needed === "always" ? '<span class="missing">missing</span>' : '<span class="optional">not found</span>'}</td></tr>`).join("");
  $("wbRoles").querySelectorAll("select").forEach((s) => s.addEventListener("change", () => {
    const role = s.dataset.role;
    if (s.value && s.value !== defaults[role]) S.columns[role] = s.value; else delete S.columns[role];
    if (S.workbook.converted_from) $("wbPath").value = S.workbook.converted_from.path;   // map on the original
    readWorkbook();
  }));
  renderStep();
  if (w.error) { $("wbContentCard").hidden = true; return toast(w.error, true); }
  $("wbContentCard").hidden = false;
  const t = w.totals;
  tiles("wbTiles", [
    ["Period", `${t.start.slice(0, 10)}`, `to ${t.end.slice(0, 16).replace("T", " ")}`],
    ["Rows", fmt(t.steps), `one per ${t.step_minutes} min${t.steps !== 35040 && t.steps !== 35136 ? " · not a full year" : ""}`],
    ["Load", `${fmt(t.load_mwh, 0)} MWh`, `peak ${fmt(t.load_peak_kw, 0)} kW · mean ${fmt(t.load_mean_kw, 0)} kW`],
    w.has.pv_w_per_module && ["Yield of one module", `${fmt(t.pv_kwh_per_module, 1)} kWh/yr`, `peak ${fmt(t.pv_peak_w_per_module, 0)} W`],
    w.has.existing_pv_kw && ["Existing PV", `${fmt(t.existing_pv_mwh, 1)} MWh`, `peak ${fmt(t.existing_pv_peak_kw, 0)} kW`],
    w.has.day_ahead_eur_kwh && ["Day-ahead price", `${fmt(t.day_ahead_mean, 4)} EUR/kWh`,
      `min ${fmt(t.day_ahead_min, 4)} · max ${fmt(t.day_ahead_max, 4)} · ${fmt(t.day_ahead_negative_h, 1)} h negative${t.day_ahead_missing ? ` · ${t.day_ahead_missing} missing` : ""}`],
  ]);
  const ds = [{ label: "Load, MWh", data: w.monthly.load.map((v) => v / 1000), backgroundColor: COLORS.load }];
  if (w.monthly.existing_pv) ds.push({ label: "Existing PV, MWh", data: w.monthly.existing_pv.map((v) => v / 1000), backgroundColor: COLORS.existing });
  chart("wbMonthly", { type: "bar", data: { labels: MONTHS, datasets: ds } });
  chart("wbMonthlyPv", { type: "bar", data: { labels: MONTHS, datasets: [{ label: "kWh per module", data: w.monthly.pv_module_kw || [], backgroundColor: COLORS.pv }] },
    options: { plugins: { legend: { display: false } } } });
  drawWorkbookWeek();
}
function renderStep() {
  const w = S.workbook, conv = w.converted_from, step = conv || w.step;
  $("wbStepCard").hidden = !step;
  if (!step) return;
  const model = S.options.model_step_min;
  tiles("wbStepTiles", [
    ["Step in the workbook", `${fmt(step.step_minutes)} min`, `${fmt(step.rows)} rows${step.irregular_steps ? ` · ${fmt(step.irregular_steps)} irregular steps` : ""}`, conv ? "accent" : ""],
    ["Step of the model", `${model} min`, conv ? `converted: ${fmt(w.rows)} rows` : "no conversion needed"],
  ]);
  $("wbStepNote").innerHTML = conv
    ? `The workbook was converted and the run uses the converted file: <code>${esc(w.path)}</code>. Kept columns: ${Object.entries(conv.kinds).map(([c, k]) => `<code>${esc(c)}</code> ${CONVERSION[k]}`).join(", ")}. Other columns are dropped. Original: <code>${esc(conv.path)}</code>.`
    : (step.irregular_steps ? "Some steps differ from the usual one (gaps, repeated or missing hours): check the workbook." : "");
}
function drawWorkbookWeek() {
  const w = S.workbook; if (!w || !w.hourly) return;
  const week = Number($("wbWeek").value), from = week * 168, h = w.hourly, n = Math.min(168, h.load.length - from);
  const labels = hourLabels(h.start, from, n);
  $("wbWeekLabel").textContent = `${labels[0].slice(0, 10)} to ${labels[n - 1].slice(0, 10)}`;
  const modules = has("voltiris") ? Number($("sModules").value) || 0 : 0;
  $("wbModulesNote").textContent = fmt(modules);
  const slice = (a) => (a || []).slice(from, from + n);
  const sets = [line("Load, kW", slice(h.load), COLORS.load)];
  if (h.pv_module_kw && modules) sets.push(line("Voltiris PV, kW", slice(h.pv_module_kw).map((v) => v * modules), COLORS.pv, { fill: false }));
  if (h.existing_pv && has("existing_pv")) sets.push(line("Existing PV, kW", slice(h.existing_pv), COLORS.existing));
  if (h.day_ahead) sets.push(line("Day-ahead, EUR/kWh", slice(h.day_ahead), COLORS.da, { yAxisID: "y1", borderDash: [4, 3], borderWidth: 1.2 }));
  chart("wbWeekChart", { type: "line", data: { labels, datasets: sets },
    options: { scales: { x: { ticks: dayTicks, grid: { display: false } }, y: { title: { display: true, text: "kW" } },
      y1: { display: !!h.day_ahead, position: "right", grid: { display: false }, title: { display: true, text: "EUR/kWh" } } } } });
}
$("wbWeek").addEventListener("input", drawWorkbookWeek);

// -- step 3: market --------------------------------------------------------------------------------------------------
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

// -- step 4: parameters ----------------------------------------------------------------------------------------------
// the parameters you can change without writing JSON (block, group, path in the parameter dict, label, unit, kind)
const KEY_FIELDS = [
  ["battery", "Technology", "tech.battery.c_rate", "C-rate", "kW per kWh bought", "num"],
  ["battery", "Technology", "tech.battery.soc_min", "Lowest state of charge", "% of the size", "pct"],
  ["battery", "Technology", "tech.battery.soc_max", "Highest state of charge", "% of the size", "pct"],
  ["battery", "Technology", "tech.battery.efficiency_store", "Charging efficiency", "%", "pct"],
  ["battery", "Technology", "tech.battery.efficiency_dispatch", "Discharging efficiency", "%", "pct"],
  ["battery", "Technology", "tech.battery.self_discharge_per_day", "Self-discharge", "% per day", "pct"],
  ["voltiris", "Technology", "tech.module_wp", "Module power", "Wp per module", "num"],
  ["battery", "Investment and subsidy", "capex.battery_tiers_per_kwh", "Battery price tiers", "kWh:price per kWh, …", "tiers"],
  ["battery", "Investment and subsidy", "capex.battery_replacement_frac", "Replacement cost", "% of the gross price", "pct"],
  ["voltiris", "Investment and subsidy", "capex.pv_per_wp", "PV price", "per Wp", "num"],
  ["battery", "Investment and subsidy", "subsidies.battery.mode", "Battery subsidy", "", "select:percent|fixed|threshold"],
  ["battery", "Investment and subsidy", "subsidies.battery.frac", "Battery subsidy share", "%", "pct"],
  ["battery", "Investment and subsidy", "subsidies.battery.amount", "Battery subsidy amount", "fixed mode", "num"],
  ["battery", "Investment and subsidy", "subsidies.battery.threshold_mode", "Threshold size from", "", "select:ocan|manual"],
  ["battery", "Investment and subsidy", "subsidies.battery.threshold_kwh", "Threshold size", "kWh (manual)", "num"],
  ["battery", "Investment and subsidy", "subsidies.battery.ocan_factor", "OCAN factor", "kWh per daily kWh of load", "num"],
  ["voltiris", "Investment and subsidy", "subsidies.pv.frac", "PV subsidy share", "%", "pct"],
  ["battery", "EMS", "ems.fixed_per_year", "Fixed cost", "per year", "num"],
  ["battery", "EMS", "ems.capex", "Hardware", "once, with the battery", "num"],
  ["battery", "EMS", "ems.savings_fee_pct.voltiris", "Fee on bill savings, Voltiris", "%", "pct"],
  ["battery", "EMS", "ems.savings_fee_pct.external", "Fee on bill savings, external", "%", "pct"],
  ["battery", "EMS", "ems.ancillary_fee_pct.voltiris", "Fee on ancillary revenue, Voltiris", "%", "pct"],
  ["battery", "EMS", "ems.ancillary_fee_pct.external", "Fee on ancillary revenue, external", "%", "pct"],
  ["battery", "Lifetimes", "finance.battery_life_yr", "Battery life", "years", "num"],
  ["voltiris", "Lifetimes", "finance.pv_life_yr", "PV life", "years", "num"],
  ["battery", "Ancillary services (used when switched on above)", "ancillary.rate_per_kw_year", "Revenue rate", "per reserved kW and year", "num"],
  ["battery", "Ancillary services (used when switched on above)", "ancillary.reserve.mode", "Reserve", "", "select:percent|fixed_kwh"],
  ["battery", "Ancillary services (used when switched on above)", "ancillary.reserve.frac", "Reserve share", "% of window and power", "pct"],
  ["battery", "Ancillary services (used when switched on above)", "ancillary.reserve.kwh", "Fixed reserve", "kWh (fixed_kwh mode)", "num"],
  ["voltiris", "Business model", "business_model.price_per_mwh", "EaaS price", "per MWh of Voltiris energy used on site", "num"],
].map(([block, group, path, label, unit, kind]) => ({ block, group, path, label, unit, kind }));

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
  if (text) { try { json = JSON.parse(text); $("jsonError").textContent = ""; } catch (e) { $("jsonError").textContent = "Not valid JSON: " + e.message; } }
  const fields = {};
  Object.entries(S.fieldValues).forEach(([p, v]) => setPath(fields, p, v));
  return deepMerge(json, fields);
}

function renderKeyParams() {
  const d = S.params.defaults;
  ["voltiris", "battery"].forEach((block) => {
    const box = $("kp-" + block), groups = {};
    KEY_FIELDS.filter((f) => f.block === block && getPath(d, f.path) !== undefined)
      .forEach((f) => (groups[f.group] = groups[f.group] || []).push(f));
    box.innerHTML = "";
    Object.entries(groups).forEach(([group, fields]) => {
      const g = el("div", { class: "pgroup" }, `<h3>${esc(group)} <span class="muted">${esc(cur())}</span></h3>`);
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

async function loadParams() {
  if (!$("mUtility").value) return;
  const c = collectCase();
  try {
    S.params = await api("/api/parameters", { run_type: RT().id, market: c.market, business_model: c.business_model, overrides: c.overrides });
  } catch (e) { $("paramsError").textContent = e.message; return; }
  $("paramsError").textContent = S.params.error ? "These overrides cannot be applied, the file values are shown: " + S.params.error : "";
  $("mCurrency").textContent = `Money is in ${S.params.currency}. Shared prices (battery, PV, EMS, EaaS) are converted from CHF/EUR with params/fx.json.`;
  renderKeyParams();
  renderParamBlocks(c.overrides);
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

// preview: the setup check, without solving
["sModules", "sImport", "sExport", "sRegime", "sAncillary", "zCustom", "zSweep", "zFine", "zWindow", "zCap"].forEach((id) =>
  $(id).addEventListener("change", () => { S.preview = null; updateTop(); if (id === "sModules") drawWorkbookWeek();
    if (id === "sAncillary") loadParamsSoon(); checkSetupSoon(); }));
document.querySelectorAll("input[name=regimeMode], input[name=objective]").forEach((r) => r.addEventListener("change", () => { S.preview = null; checkSetupSoon(); }));
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
  const l = r.list, show = l.length <= 8 ? l.map((x) => fmt(x)).join(", ") : `${l.slice(0, 4).map((x) => fmt(x)).join(", ")}, … ${fmt(l[l.length - 1])}`;
  $("gInfo").textContent = `${l.length} size${l.length > 1 ? "s" : ""}: ${show} kWh (about ${fmt(l.length * 6 / 60, 1)} min to solve)`;
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

async function checkSetup(quiet) {
  const visible = $("step-params").classList.contains("active");
  if (quiet && (!visible || S.preview)) return;
  if (!S.runType) { if (!quiet) toast("No model can run the system of step 1 yet.", true); return; }
  const c = collectCase();
  if (!c.input_file) { if (!quiet) toast("Choose the workbook in step 2 first.", true); return; }
  $("checkInfo").textContent = "Building the run context…";
  try {
    S.preview = await api("/api/preview", { case: c });
    $("checkInfo").textContent = "Setup checked: nothing has been solved yet.";
    renderPreview();
  } catch (e) {
    $("checkInfo").textContent = "";
    $("zPlan").textContent = "The setup has a problem: " + e.message;
    toast(e.message, true);
  }
}

function renderPreview() {
  const p = S.preview, s = p.site, b = p.battery, m = p.money, t = p.tariff, k = b.per_100_kwh;
  $("previewSite").hidden = false;
  tiles("pvSite", [
    ["Yearly load", `${fmt(s.load_mwh, 0)} MWh`, `peak ${fmt(s.load_peak_kw, 0)} kW`],
    ["Voltiris PV", `${fmt(s.voltiris_kwp, 1)} kWp`, `${fmt(s.modules)} modules · ${fmt(s.voltiris_mwh, 1)} MWh/yr`],
    ["Existing PV", `${fmt(s.existing_mwh, 1)} MWh`, has("existing_pv") ? "added to the Voltiris PV" : "not in the system"],
    ["PV surplus without battery", `${fmt(s.pv_surplus_mwh, 1)} MWh`, `of ${fmt(s.pv_mwh, 1)} MWh PV`],
    ["Grid import limit", `${fmt(p.grid.import_max_kw, 0)} kW`, p.grid.import_auto ? "automatic" : "from the case"],
    ["Grid export limit", `${fmt(p.grid.export_max_kw, 0)} kW`, p.grid.export_auto ? "automatic" : "from the case"],
  ]);
  const pct = (v, total) => `${Math.max(0, (v / total) * 100)}%`;
  const below = b.soc_min * 100, above = (1 - b.soc_max) * 100;
  $("pvBattery").innerHTML = `
    <div class="bbar"><div class="label">Energy: 100 kWh bought</div><div class="bar">
      <div class="seg-off" style="width:${pct(below, 100)}">${fmt(below, 0)} kWh</div>
      ${k.reserved_kwh > 0 ? `<div class="seg-res" style="width:${pct(k.reserved_kwh, 100)}">reserve ${fmt(k.reserved_kwh, 0)} kWh</div>` : ""}
      <div class="seg-use" style="width:${pct(k.dispatch_kwh, 100)}">optimiser ${fmt(k.dispatch_kwh, 0)} kWh</div>
      <div class="seg-off" style="width:${pct(above, 100)}">${fmt(above, 0)} kWh</div></div></div>
    <div class="bbar"><div class="label">Power: ${fmt(k.power_kw, 0)} kW (C-rate ${fmt(b.c_rate, 2)})</div><div class="bar">
      ${k.reserved_kw > 0 ? `<div class="seg-res" style="width:${pct(k.reserved_kw, k.power_kw)}">reserve ${fmt(k.reserved_kw, 1)} kW</div>` : ""}
      <div class="seg-use" style="width:${pct(k.dispatch_kw, k.power_kw)}">optimiser ${fmt(k.dispatch_kw, 1)} kW</div></div></div>`;
  tiles("pvBatteryTiles", [
    ["State-of-charge window", `${fmt(b.soc_min * 100, 0)}–${fmt(b.soc_max * 100, 0)} %`, "striped: never used"],
    ["Round trip", `${fmt(b.round_trip * 100, 1)} %`, `charge ${fmt(b.charge_efficiency * 100, 1)} % · discharge ${fmt(b.discharge_efficiency * 100, 1)} %`],
    ["Self-discharge", `${fmt(b.self_discharge_per_day * 100, 2)} %/day`],
    p.ancillary.enabled
      ? ["Ancillary revenue", `${money(k.ancillary_revenue)}/yr`, `per 100 kWh: ${fmt(k.reserved_kw, 1)} kW × ${fmt(p.ancillary.rate_per_kw_year, 1)}`, "accent"]
      : ["Ancillary services", "off", "whole window and power to the optimiser"],
  ]);
  tiles("pvMoney", [
    ["Battery price", `${money(m.price_per_kwh_at["100"])}/kWh`, `at 100 kWh · ${money(m.price_per_kwh_at["1000"])}/kWh at 1,000 kWh`],
    ["100 kWh after subsidy", money(m.price_after_subsidy_100), `subsidy: ${m.subsidy_mode}${m.subsidy_frac ? ` ${fmt(m.subsidy_frac * 100, 0)} %` : ""}`],
    m.subsidy_mode === "threshold" && ["Subsidised maximum", `${fmt(m.subsidy_threshold_kwh, 0)} kWh`, "OCAN: yearly load / 365 × factor"],
    ["EMS", `${money(m.ems_fixed_per_year)}/yr`, `hardware ${money(m.ems_hardware)} once`],
    ["Lifetimes", `${fmt(m.battery_life_yr)} / ${fmt(m.pv_life_yr)} yr`, "battery / PV"],
  ]);
  const r = p.regime;
  tiles("pvTariff", [
    ["Business model", t.business_model === "eaas" ? (t.eaas ? "EaaS" : "EaaS (inactive: 0 modules)") : "Direct sales"],
    ["Starting regime", r.start, r.dup_h != null ? `DUP ${fmt(r.dup_h, 0)} h without battery · threshold ${fmt(t.threshold_h, 0)} h` : (r.auto ? "the tariff has no regime rule" : "fixed by the case")],
    ["Regimes", t.regimes.join(" / "), t.has_rule ? "chosen by the DUP rule" : "chosen by the case"],
    ["Energy price", t.uses_day_ahead ? "day-ahead based" : "fixed by period", `export value ${fmt(t.export_value_mean, 4)} ${cur()}/kWh on average`],
    ["Capacity charges", t.capacity_charges.length ? t.capacity_charges.join(", ") : "none"],
    ["Battery export", t.battery_export === "pv_only" ? "PV energy only" : "any energy"],
    ["One-meter rules", `${fmt(p.meter.export_pays_more_h, 0)} h`, `exporting pays more · ${fmt(p.meter.negative_price_h, 1)} h negative price`],
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

// -- step 5: run ----------------------------------------------------------------------------------------------------
$("runBtn").addEventListener("click", async () => {
  if (!S.runType) return toast("No model can run the system of step 1 yet.", true);
  const c = collectCase();
  if (!c.input_file) return toast("Choose the workbook in step 2 first.", true);
  if ($("jsonError").textContent) return toast("Fix the JSON overrides in step 4 first.", true);
  try {
    const r = await api("/api/run", { case: c, output_dir: $("rFolder").value.trim() });
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
    document.querySelector('#steps button[data-step="results"]').classList.add("done");
    toast(`Done in ${fmt(st.elapsed, 0)} s`);
    showStep("results");
    renderResults();
  }
}

// -- step 6: results ------------------------------------------------------------------------------------------------
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
  $("resFiles").textContent = `Written to ${R.files.folder}`;
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
  else if (ch.objective !== "custom" && chosen.size === largest && rows.length > 1) notes.push(`The chosen size is the largest one tested: a larger battery might do better. Extend the list in step 4 to check.`);
  else if (ch.objective !== "custom" && chosen.size === smallest && rows.length > 1 && chosen.value > 0) notes.push(`The chosen size is the smallest one tested: a smaller battery might do better. Extend the list in step 4 to check.`);
  const fine = rows.filter((r) => !ch.first_stage.includes(r.size)).map((r) => fmt(r.size));
  if (fine.length) notes.push(`${fine.join(", ")} kWh came from the fine grid, solved after the first list.`);
  if (chosen.regime !== s.regime_no_battery) notes.push(`This size is billed under regime ${chosen.regime}, not the starting regime ${s.regime_no_battery}: its hours of use crossed the threshold${chosen.lock ? `, and the DUP was held in regime ${chosen.lock}` : ""}.`);
  $("resWhy").innerHTML = why + (notes.length ? "<br>" + notes.join(" ") : "");
  $("resWhyTable").innerHTML = `<tr><th>Size, kWh</th><th>Yearly value, ${c}</th><th>Investment, ${c}</th><th>Payback</th><th>Within ${fmt(life)} yr</th><th>Lifetime profit, ${c}</th><th>Regime</th><th></th></tr>` +
    rows.map((r) => `<tr${r === chosen ? ' class="hl"' : ""}><td>${fmt(r.size)}</td><td>${fmt(r.value)}</td><td>${fmt(r.inv)}</td>
      <td>${pbText(r)}</td><td class="${pays(r) ? "yes" : "no"}">${pays(r) ? "yes" : "no"}</td><td>${fmt(r.profit)}</td>
      <td>${esc(r.regime)}${r.lock ? ` (DUP held in ${esc(r.lock)})` : ""}</td><td>${r === chosen ? '<span class="tag">chosen</span>' : ""}</td></tr>`).join("");
  $("resWhyNote").textContent = `Payback and lifetime profit use the battery life of ${fmt(life)} years (step 4, battery, Lifetimes). Yearly value = bill saving + ancillary revenue − EMS costs; investment = battery after subsidy + EMS hardware.`;
}

function drawYear() {
  const d = S.results.daily, n = d.load.length;
  const t0 = new Date(d.start + "Z").getTime();
  const labels = Array.from({ length: n }, (_, i) => new Date(t0 + i * 864e5).toISOString().slice(0, 10));
  const monthTicks = { autoSkip: false, maxRotation: 0,
    callback(value) { const l = this.getLabelForValue(value); return l.endsWith("-01") ? MONTHS[Number(l.slice(5, 7)) - 1] : ""; } };
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
  fillSelect("caseSelect", S.options.cases.map((c) => [c.path, c.name]), "— choose —");
  fillSelect("wbSelect", S.options.workbooks.map((w) => [w.path, w.name]), "— choose —");
  fillSelect("presetSelect", S.options.presets.map((p) => [p.id, p.name]), "— your own system —");
  fillSelect("mBusiness", RT().business_models.map((b) => [b, b === "eaas" ? "EaaS (Voltiris owns the modules)" : "Direct sales (grower buys the modules)"]));
  setMarket();
  $("zSweep").placeholder = RT().sizing_defaults.sweep_kwh.join(", ");
  if (S.options.cases.length) {
    $("caseSelect").value = S.options.cases[0].path;
    $("caseLoad").click();
  } else {
    $("caseNew").click();
  }
})();

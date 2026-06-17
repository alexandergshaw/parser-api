// Parser API tester — external script (loaded via <script src="/app.js">).
// Lens-agnostic: it renders whatever lenses the API returns under `results`.

const $ = (id) => document.getElementById(id);
const out = $('out');
const aggOut = $('aggOut');
let lastResponse = null;
let lastAgg = null;
let taxLoaded = false;

const EXAMPLES = {
  de: `Senior Data Engineer
We are seeking a Data Engineer to design and build scalable data pipelines and ETL
workflows that power our analytics platform. You will own our data warehouse and data
lake, model data for downstream consumers, and optimize big data processing with Spark
and Airflow. Strong SQL and Python skills are required, along with experience in data
modeling and feature engineering for machine learning use cases. You'll work in an Agile
team with two-week sprints, participate in code review, and ship through our CI/CD
pipeline. Experience with Kafka, dbt, Snowflake, AWS, Docker, and Kubernetes is a plus.`,
  phys: `Today's lecture covers classical mechanics. We begin with Newton's laws and the
concept of momentum, then derive equations for velocity and acceleration. We'll connect
kinetic energy to work, discuss thermodynamics briefly, and preview how electromagnetism
and relativity reshape these ideas. Your homework from the textbook is due before the
next lecture; the exam will cover everything through this week's coursework.`,
};

// ---- settings (persisted) -------------------------------------------------
function getBase() { return $('baseUrl').value.trim().replace(/\/+$/, ''); }
function getKey() { return $('apiKey').value.trim(); }
function apiUrl(path) { return getBase() + path; }
function apiHeaders(json) {
  const h = json ? { 'Content-Type': 'application/json' } : {};
  const k = getKey();
  if (k) h['X-API-Key'] = k;
  return h;
}
function saveSettings() {
  try {
    localStorage.setItem('parserApi.baseUrl', $('baseUrl').value.trim());
    localStorage.setItem('parserApi.apiKey', $('apiKey').value);
  } catch (e) { /* storage unavailable */ }
}
function loadSettings() {
  let base = '', savedKey = null;
  try {
    base = localStorage.getItem('parserApi.baseUrl') || '';
    savedKey = localStorage.getItem('parserApi.apiKey');
  } catch (e) { /* storage unavailable */ }
  $('baseUrl').value = base;
  $('apiKey').value = savedKey !== null && savedKey !== undefined ? savedKey : '';
}

// ---- helpers --------------------------------------------------------------
function pct(x) { return Math.round((x || 0) * 100); }
function escapeHtml(s) { return String(s).replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function netError(e) {
  return `Couldn't reach the API. Check the base URL, that the server is running, and — for a
    cross-origin URL — that the API's ALLOWED_ORIGINS permits this page. (${escapeHtml(String(e))})`;
}
async function flash(btn, msg) {
  const old = btn.textContent; btn.textContent = msg;
  setTimeout(() => { btn.textContent = old; }, 1200);
}

// ---- health badge ---------------------------------------------------------
let healthTimer = null;
function scheduleRefresh() {
  clearTimeout(healthTimer);
  healthTimer = setTimeout(() => { loadHealth(); loadLenses(); }, 400);
}
async function loadHealth() {
  const badge = $('badge'), text = $('badgeText');
  badge.className = 'badge'; text.textContent = 'checking…';
  try {
    const res = await fetch(apiUrl('/api/health'), { headers: apiHeaders(false) });
    const d = await res.json();
    if (res.ok && d.status === 'ok') {
      badge.className = 'badge ok';
      text.textContent = `v${d.version} · ${d.categories} categories`;
    } else {
      badge.className = 'badge bad'; text.textContent = `HTTP ${res.status}`;
    }
  } catch (e) {
    badge.className = 'badge bad'; text.textContent = 'unreachable';
  }
}

// ---- targets (lens selector) ----------------------------------------------
async function loadLenses() {
  const box = $('targets');
  try {
    const res = await fetch(apiUrl('/api/lenses'), { headers: apiHeaders(false) });
    const d = await res.json();
    box.innerHTML = (d.lenses || []).map((l) =>
      `<label class="tgl"><input type="checkbox" value="${escapeHtml(l.name)}" ${l.default ? 'checked' : ''}/>` +
      `${escapeHtml(l.name)} <span class="kind">${escapeHtml(l.kind)}</span></label>`
    ).join('');
  } catch (e) {
    box.innerHTML = '<span class="err">couldn\'t load lenses</span>';
  }
}
function selectedTargets() {
  const checked = [...document.querySelectorAll('#targets input:checked')].map((i) => i.value);
  return checked.length ? checked : null; // null → server defaults
}

// ---- files (optional uploads) ---------------------------------------------
function selectedFiles() {
  const el = $('files');
  return el && el.files ? Array.from(el.files) : [];
}
function fmtBytes(n) {
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(0) + ' KB';
  return (n / (1024 * 1024)).toFixed(1) + ' MB';
}
function renderFileList() {
  $('filelist').innerHTML = selectedFiles().map((f) =>
    `<span class="fitem">${escapeHtml(f.name)} <span style="opacity:.6">${fmtBytes(f.size)}</span></span>`
  ).join('');
}
$('files').addEventListener('change', renderFileList);

// ---- parse ----------------------------------------------------------------
$('go').addEventListener('click', run);
function requestBody() {
  const body = { text: $('text').value.trim(), max_keywords: Number($('maxkw').value) || 15 };
  const targets = selectedTargets();
  if (targets) body.targets = targets;
  return body;
}
// Multipart when files are attached (browser sets the boundary — don't set Content-Type),
// else the existing JSON body. Both carry the same text/targets/max_keywords.
function buildRequest() {
  const files = selectedFiles();
  if (!files.length) {
    return { headers: apiHeaders(true), body: JSON.stringify(requestBody()) };
  }
  const fd = new FormData();
  const text = $('text').value.trim();
  if (text) fd.append('text', text);
  const targets = selectedTargets();
  if (targets) fd.append('targets', JSON.stringify(targets));
  fd.append('max_keywords', String(Number($('maxkw').value) || 15));
  files.forEach((f) => fd.append('files', f));
  return { headers: apiHeaders(false), body: fd };
}
async function run() {
  if (!$('text').value.trim() && !selectedFiles().length) {
    out.innerHTML = '<div class="err">Enter some text or attach a file first.</div>'; return;
  }
  $('go').disabled = true;
  out.innerHTML = '<div class="empty">Parsing…</div>';
  try {
    const req = buildRequest();
    const res = await fetch(apiUrl('/api/parse'), { method: 'POST', headers: req.headers, body: req.body });
    const data = await res.json();
    if (!res.ok) {
      out.innerHTML = `<div class="err">HTTP ${res.status}: ${escapeHtml(data.detail || 'error')}</div>`;
      return;
    }
    lastResponse = data;
    render(data);
  } catch (e) {
    out.innerHTML = `<div class="err">${netError(e)}</div>`;
  } finally {
    $('go').disabled = false;
  }
}

// ---- lens-agnostic rendering ----------------------------------------------
function render(d) {
  const results = d.results || {};
  let html = '<div class="rtools"><button class="ghost sm" id="copyjson">Copy JSON</button></div>';
  const names = Object.keys(results);
  if (!names.length) html += '<div class="empty">No lenses returned.</div>';
  for (const name of names) {
    const r = results[name];
    html += `<h3>${escapeHtml(name)} <span class="kind">${escapeHtml(r.kind || '')}</span></h3>`;
    html += renderLens(r);
  }
  const m = d.meta || {};
  if (Array.isArray(m.sources) && m.sources.length) html += renderSources(m.sources);
  html += `<div class="meta"><span>tokens: ${m.token_count}</span><span>v${escapeHtml(m.version || '')}</span></div>`;
  html += `<details><summary>Raw JSON</summary><pre>${escapeHtml(JSON.stringify(d, null, 2))}</pre></details>`;
  out.innerHTML = html;
  const cj = $('copyjson');
  if (cj) cj.addEventListener('click', (ev) => copyJson(ev.target));
}

function renderSources(sources) {
  const rows = sources.map((s) => {
    const detail = s.ok
      ? `<span>${escapeHtml(s.kind)} · ${(s.chars || 0).toLocaleString()} chars</span>`
      : `<span class="why">${escapeHtml(s.error || 'failed')}</span>`;
    return `<div class="src${s.ok ? '' : ' fail'}"><span class="nm">${escapeHtml(s.name)}</span>${detail}</div>`;
  }).join('');
  return `<h3>sources</h3><div class="sources">${rows}</div>`;
}

function renderLens(r) {
  if (r.kind === 'emphasis') return renderEmphasis(r);
  if (r.kind === 'lexicon') return renderLexicon(r);
  if (r.kind === 'keywords') return renderKeywords(r);
  if (r.kind === 'tone') return renderTone(r);
  return '';
}

function renderTone(r) {
  const dims = r.dimensions || [];
  if (!dims.length) return '<div class="empty">none</div>';
  const rows = dims.map((d) => {
    const ev = (d.evidence || []).map((e) => `<span class="chip">${escapeHtml(e)}</span>`).join('');
    return `<div class="item"><span class="nm">${escapeHtml(d.label)}
        <span class="kind">${escapeHtml(d.leaning || '')}</span></span>
      <span class="bar"><i style="width:${pct(d.score)}%"></i></span>
      <span class="pct">${pct(d.score)}%</span></div>` +
      (ev ? `<div class="chips" style="margin:-2px 0 8px 0">${ev}</div>` : '');
  }).join('');
  return `<div class="ranked">${rows}</div>`;
}

function renderEmphasis(r) {
  if (!r.top) return '<div class="empty">no match</div>';
  const t = r.top;
  const chips = (t.matched_terms || []).map((x) => `<span class="chip">${escapeHtml(x)}</span>`).join('');
  const warn = t.low_confidence ? ' <span class="warn">⚠ low confidence</span>' : '';
  let h = `<div class="emph primary">
    <div class="tag">top${warn}</div>
    <div class="label">${escapeHtml(t.label)} <span class="id">${escapeHtml(t.id)}</span></div>
    <div class="bar"><i style="width:${pct(t.score)}%"></i></div>
    <div class="chips">${chips}</div></div>`;
  h += '<div class="ranked">';
  (r.ranked || []).forEach((e) => {
    h += `<div class="item"><span class="nm">${escapeHtml(e.label)}</span>
      <span class="bar"><i style="width:${pct(e.score)}%"></i></span>
      <span class="pct">${pct(e.score)}%</span></div>`;
  });
  return h + '</div>';
}

function renderLexicon(r) {
  const m = r.matched || [];
  if (!m.length) return '<div class="empty">none detected</div>';
  return '<div class="chips">' + m.map((x) => {
    const rel = x.related ? x.related.label : '';
    return `<span class="chip" title="${escapeHtml(rel)}">${escapeHtml(x.display || x.term)}</span>`;
  }).join('') + '</div>';
}

function renderKeywords(r) {
  const items = r.items || [];
  if (!items.length) return '<div class="empty">none</div>';
  return '<div class="chips">' + items.map((k) => {
    const cls = k.source === 'lexicon' ? 'lex' : (k.source === 'rake+lexicon' ? 'both' : '');
    const rel = k.related ? ' · ' + k.related.label : '';
    return `<span class="chip ${cls}" title="${escapeHtml(k.source + rel)}">${escapeHtml(k.display || k.term)}<span class="s">${pct(k.score)}</span></span>`;
  }).join('') + '</div>';
}

// ---- copy helpers ---------------------------------------------------------
function shellQuote(s) { return "'" + s.replace(/'/g, "'\\''") + "'"; }
async function copyToClipboard(textVal, btn) {
  try { await navigator.clipboard.writeText(textVal); flash(btn, 'Copied!'); }
  catch (e) { flash(btn, 'Copy failed'); }
}
$('copycurl').addEventListener('click', (ev) => {
  const files = selectedFiles();
  if (!$('text').value.trim() && !files.length) { flash(ev.target, 'No input'); return; }
  const url = (getBase() || location.origin) + '/api/parse';
  const lines = [`curl -s ${shellQuote(url)}`];
  if (getKey()) lines.push(`-H ${shellQuote('X-API-Key: ' + getKey())}`);
  if (files.length) {
    const text = $('text').value.trim();
    if (text) lines.push(`-F ${shellQuote('text=' + text)}`);
    const targets = selectedTargets();
    if (targets) lines.push(`-F ${shellQuote('targets=' + JSON.stringify(targets))}`);
    lines.push(`-F ${shellQuote('max_keywords=' + (Number($('maxkw').value) || 15))}`);
    files.forEach((f) => lines.push(`-F ${shellQuote('files=@' + f.name)}`));
  } else {
    lines.splice(1, 0, `-H 'Content-Type: application/json'`);
    lines.push(`-d ${shellQuote(JSON.stringify(requestBody()))}`);
  }
  copyToClipboard(lines.join(' \\\n  '), ev.target);
});
function copyJson(btn) {
  if (!lastResponse) { flash(btn, 'No result'); return; }
  copyToClipboard(JSON.stringify(lastResponse, null, 2), btn);
}

// ---- taxonomy browser -----------------------------------------------------
async function loadTaxonomy() {
  const box = $('taxOut');
  box.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const res = await fetch(apiUrl('/api/taxonomy'), { headers: apiHeaders(false) });
    const d = await res.json();
    if (!res.ok) { box.innerHTML = `<div class="err">HTTP ${res.status}</div>`; return; }
    const groups = {};
    (d.categories || []).forEach((c) => (groups[c.type] || (groups[c.type] = [])).push(c));
    const col = (title, items) => `<div><h3>${title} (${items.length})</h3>` +
      items.map((c) => `<div class="cat">${escapeHtml(c.label)}<span class="id">${escapeHtml(c.id)}</span></div>`).join('') + '</div>';
    box.innerHTML = Object.keys(groups).sort().map((t) => col(t, groups[t])).join('');
    $('taxCount').textContent = `${d.count} categories · v${d.version}`;
    taxLoaded = true;
  } catch (e) {
    box.innerHTML = `<div class="err">${netError(e)}</div>`;
  }
}
$('taxBox').addEventListener('toggle', (e) => { if (e.target.open && !taxLoaded) loadTaxonomy(); });
$('taxRefresh').addEventListener('click', loadTaxonomy);

// ---- aggregate (records → statistics) -------------------------------------
const EXAMPLES_AGG = {
  // includes a lowercase "employed" so the case-insensitive toggle is demonstrable
  grads: JSON.stringify([
    { placement: 'Employed', salary: 85000, gpa: 3.6 },
    { placement: 'Employed', salary: 95000, gpa: 3.9 },
    { placement: 'Grad school', salary: null, gpa: 3.8 },
    { placement: 'Employed', salary: 72000, gpa: 3.1 },
    { placement: 'Seeking', salary: 'N/A', gpa: 2.9 },
    { placement: 'employed', salary: 88000, gpa: 3.4 },
  ], null, 2),
  jobs: JSON.stringify([
    { title: 'Data Engineer', salary: '$120,000', remote: true, level: 'Senior' },
    { title: 'Data Analyst', salary: '$85,000', remote: false, level: 'Mid' },
    { title: 'ML Engineer', salary: '$140,000', remote: true, level: 'Senior' },
    { title: 'BI Developer', salary: '95000', remote: true, level: 'Mid' },
  ], null, 2),
};

function selectedCsv() { const el = $('csv'); return el && el.files && el.files[0] ? el.files[0] : null; }
function renderCsvList() {
  const f = selectedCsv();
  $('csvlist').innerHTML = f
    ? `<span class="fitem">${escapeHtml(f.name)} <span style="opacity:.6">${fmtBytes(f.size)}</span></span>` : '';
}
$('csv').addEventListener('change', renderCsvList);

function aggFields() {
  const raw = $('fields').value.trim();
  if (!raw) return null;                       // null → all fields
  if (raw.startsWith('[')) { try { const v = JSON.parse(raw); if (Array.isArray(v)) return v; } catch (e) { /* fall through */ } }
  return raw.split(',').map((s) => s.trim()).filter(Boolean);
}

$('aggGo').addEventListener('click', runAgg);
async function runAgg() {
  const file = selectedCsv(), text = $('records').value.trim();
  if (!file && !text) { aggOut.innerHTML = '<div class="err">Paste records JSON or attach a CSV first.</div>'; return; }
  const fields = aggFields(), casefold = $('casefold').checked;
  $('aggGo').disabled = true;
  aggOut.innerHTML = '<div class="empty">Aggregating…</div>';
  try {
    let res;
    if (file) {
      const fd = new FormData();
      fd.append('file', file);
      if (fields) fd.append('fields', JSON.stringify(fields));
      if (casefold) fd.append('casefold', 'true');
      res = await fetch(apiUrl('/api/aggregate'), { method: 'POST', headers: apiHeaders(false), body: fd });
    } else {
      let records;
      try { records = JSON.parse(text); }
      catch (e) { aggOut.innerHTML = `<div class="err">Records must be valid JSON. (${escapeHtml(String(e))})</div>`; return; }
      const body = { records };
      if (fields) body.fields = fields;
      if (casefold) body.casefold = true;
      res = await fetch(apiUrl('/api/aggregate'), { method: 'POST', headers: apiHeaders(true), body: JSON.stringify(body) });
    }
    const data = await res.json();
    if (!res.ok) { aggOut.innerHTML = `<div class="err">HTTP ${res.status}: ${escapeHtml(data.detail || 'error')}</div>`; return; }
    lastAgg = data;
    renderAgg(data);
  } catch (e) {
    aggOut.innerHTML = `<div class="err">${netError(e)}</div>`;
  } finally {
    $('aggGo').disabled = false;
  }
}

function fmtNum(x) {
  if (x === null || x === undefined) return '—';
  if (typeof x === 'number') {
    return Number.isInteger(x) ? x.toLocaleString() : x.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return escapeHtml(String(x));
}
function renderAgg(d) {
  const results = d.results || {};
  let html = '<div class="rtools"><button class="ghost sm" id="copyaggjson">Copy JSON</button></div>';
  const names = Object.keys(results);
  if (!names.length) html += '<div class="empty">No fields returned.</div>';
  for (const name of names) {
    const r = results[name];
    html += `<h3>${escapeHtml(name)} <span class="kind">${escapeHtml(r.kind || '')}</span></h3>`;
    if (r.kind === 'numeric') html += renderNumeric(r);
    else if (r.kind === 'categorical') html += renderCategorical(r);
    else html += '<div class="empty">no values</div>';
  }
  const m = d.meta || {};
  html += `<div class="meta"><span>records: ${m.records}</span><span>fields: ${m.fields_analyzed}</span><span>v${escapeHtml(m.version || '')}</span></div>`;
  html += `<details><summary>Raw JSON</summary><pre>${escapeHtml(JSON.stringify(d, null, 2))}</pre></details>`;
  aggOut.innerHTML = html;
  const cj = $('copyaggjson');
  if (cj) cj.addEventListener('click', (ev) => {
    if (!lastAgg) { flash(ev.target, 'No result'); return; }
    copyToClipboard(JSON.stringify(lastAgg, null, 2), ev.target);
  });
}
function renderNumeric(r) {
  const cells = [['mean', r.mean], ['median', r.median], ['stdev', r.stdev], ['min', r.min],
                 ['max', r.max], ['p25', r.p25], ['p75', r.p75], ['sum', r.sum]];
  const stats = cells.map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${fmtNum(v)}</div></div>`).join('');
  return `<div class="stats">${stats}</div>
    <div class="counts"><span><b>${r.count}</b> values</span><span><b>${r.missing}</b> missing</span><span><b>${r.invalid}</b> invalid</span></div>`;
}
function renderCategorical(r) {
  const freqs = r.frequencies || [];
  const top = freqs.reduce((mx, f) => Math.max(mx, f.proportion || 0), 0) || 1; // scale bars to the mode
  const rows = freqs.map((f) => {
    const w = Math.round(((f.proportion || 0) / top) * 100);
    return `<div class="item"><span class="nm" title="${escapeHtml(f.value)}">${escapeHtml(f.value)}</span>
      <span class="bar"><i style="width:${w}%"></i></span>
      <span class="pct">${f.count} · ${pct(f.proportion)}%</span></div>`;
  }).join('');
  const trunc = r.truncated ? ` <span class="warn">(top ${freqs.length} of ${r.distinct})</span>` : '';
  return `<div class="counts"><span>mode <b>${escapeHtml(r.mode == null ? '—' : r.mode)}</b></span>
      <span><b>${r.distinct}</b> distinct${trunc}</span><span><b>${r.count}</b> values</span><span><b>${r.missing}</b> missing</span></div>
    <div class="ranked freq">${rows || '<div class="empty">no values</div>'}</div>`;
}

$('aggCurl').addEventListener('click', (ev) => {
  const file = selectedCsv(), text = $('records').value.trim();
  if (!file && !text) { flash(ev.target, 'No input'); return; }
  const url = (getBase() || location.origin) + '/api/aggregate';
  const lines = [`curl -s ${shellQuote(url)}`];
  if (getKey()) lines.push(`-H ${shellQuote('X-API-Key: ' + getKey())}`);
  const fields = aggFields(), casefold = $('casefold').checked;
  if (file) {
    lines.push(`-F ${shellQuote('file=@' + file.name)}`);
    if (fields) lines.push(`-F ${shellQuote('fields=' + JSON.stringify(fields))}`);
    if (casefold) lines.push(`-F ${shellQuote('casefold=true')}`);
  } else {
    lines.splice(1, 0, `-H 'Content-Type: application/json'`);
    const body = {};
    try { body.records = JSON.parse(text); } catch (e) { body.records = text; }
    if (fields) body.fields = fields;
    if (casefold) body.casefold = true;
    lines.push(`-d ${shellQuote(JSON.stringify(body))}`);
  }
  copyToClipboard(lines.join(' \\\n  '), ev.target);
});

// ---- mode tabs ------------------------------------------------------------
const SUBS = {
  parse: `Paste text and/or drop in files (pdf, pptx, docx, xlsx, txt), hit Parse. Returns broad
    <b>emphases</b> (taxonomy + lexicon) and specific <b>keywords</b> (RAKE) — no LLM.
    Endpoint: <code>POST /api/parse</code>.`,
  agg: `Paste a JSON array of records or attach a CSV, hit Aggregate. Returns per-field statistics —
    <b>mean / median / quartiles</b> for numbers, <b>frequencies</b> for categories — deterministically,
    no LLM. Endpoint: <code>POST /api/aggregate</code>.`,
};
function showTab(name) {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  $('parseMode').style.display = name === 'parse' ? '' : 'none';
  $('aggMode').style.display = name === 'agg' ? '' : 'none';
  $('sub').innerHTML = SUBS[name] || SUBS.parse;
}
document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => showTab(t.dataset.tab)));
document.querySelectorAll('[data-aggex]').forEach((b) => b.addEventListener('click', () => {
  const k = b.dataset.aggex;
  $('records').value = k === 'clear' ? '' : (EXAMPLES_AGG[k] || '');
}));

// ---- wire up presets + settings + init ------------------------------------
document.querySelectorAll('#parseMode .presets button').forEach((b) => {
  b.addEventListener('click', () => {
    const k = b.dataset.ex;
    $('text').value = k === 'clear' ? '' : (EXAMPLES[k] || '');
  });
});
['baseUrl', 'apiKey'].forEach((id) => $(id).addEventListener('input', () => {
  saveSettings(); taxLoaded = false; scheduleRefresh();
}));

loadSettings();
loadHealth();
loadLenses();

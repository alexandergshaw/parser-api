// Parser API tester — external script (loaded via <script src="/app.js">).
// Lens-agnostic: it renders whatever lenses the API returns under `results`.

const $ = (id) => document.getElementById(id);
const out = $('out');
let lastResponse = null;
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

// ---- parse ----------------------------------------------------------------
$('go').addEventListener('click', run);
function requestBody() {
  const body = { text: $('text').value.trim(), max_keywords: Number($('maxkw').value) || 15 };
  const targets = selectedTargets();
  if (targets) body.targets = targets;
  return body;
}
async function run() {
  if (!$('text').value.trim()) { out.innerHTML = '<div class="err">Enter some text first.</div>'; return; }
  $('go').disabled = true;
  out.innerHTML = '<div class="empty">Parsing…</div>';
  try {
    const res = await fetch(apiUrl('/api/parse'), {
      method: 'POST', headers: apiHeaders(true), body: JSON.stringify(requestBody()),
    });
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
  html += `<div class="meta"><span>tokens: ${m.token_count}</span><span>v${escapeHtml(m.version || '')}</span></div>`;
  html += `<details><summary>Raw JSON</summary><pre>${escapeHtml(JSON.stringify(d, null, 2))}</pre></details>`;
  out.innerHTML = html;
  const cj = $('copyjson');
  if (cj) cj.addEventListener('click', (ev) => copyJson(ev.target));
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
  return dims.map((d) => {
    const ev = (d.evidence || []).map((e) => `<span class="chip">${escapeHtml(e)}</span>`).join('');
    return `<div class="item"><span class="nm">${escapeHtml(d.label)}
        <span class="kind">${escapeHtml(d.leaning || '')}</span></span>
      <span class="bar"><i style="width:${pct(d.score)}%"></i></span>
      <span class="pct">${pct(d.score)}%</span></div>` +
      (ev ? `<div class="chips" style="margin:-2px 0 8px 0">${ev}</div>` : '');
  }).join('');
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
  if (!$('text').value.trim()) { flash(ev.target, 'No text'); return; }
  const url = (getBase() || location.origin) + '/api/parse';
  const lines = [`curl -s ${shellQuote(url)}`, `-H 'Content-Type: application/json'`];
  if (getKey()) lines.push(`-H ${shellQuote('X-API-Key: ' + getKey())}`);
  lines.push(`-d ${shellQuote(JSON.stringify(requestBody()))}`);
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

// ---- wire up presets + settings + init ------------------------------------
document.querySelectorAll('.presets button').forEach((b) => {
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

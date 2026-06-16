// Parser API tester — external script (loaded via <script src="/app.js">).
// Kept external so it is never subject to inline-script CSP or HTML templating.

const INJECTED_KEY = "";
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
pipeline to production. Experience with Kafka, dbt, and Snowflake is a plus.`,
  phys: `Today's lecture covers classical mechanics. We begin with Newton's laws and the
concept of momentum, then derive equations for velocity and acceleration under a constant
force. We'll connect kinetic energy to work, discuss thermodynamics briefly, and preview
how electromagnetism and relativity reshape these ideas. Your homework from the textbook
is due before the next lecture; the exam will cover everything through this week's
coursework.`,
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
  // Storage can throw in sandboxed/embedded contexts — never let it break the UI.
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
  $('apiKey').value = savedKey !== null && savedKey !== undefined ? savedKey : INJECTED_KEY;
}

// ---- helpers --------------------------------------------------------------
function pct(x) { return Math.round((x || 0) * 100); }
function escapeHtml(s) { return String(s).replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function netError(e) {
  // fetch() rejects (vs. an HTTP error response) on network / DNS / CORS failures.
  return `Couldn't reach the API. Check the base URL, that the server is running, and — for a
    cross-origin URL — that the API's ALLOWED_ORIGINS permits this page. (${escapeHtml(String(e))})`;
}
async function flash(btn, msg) {
  const old = btn.textContent; btn.textContent = msg;
  setTimeout(() => { btn.textContent = old; }, 1200);
}

// ---- health badge ---------------------------------------------------------
let healthTimer = null;
function scheduleHealth() { clearTimeout(healthTimer); healthTimer = setTimeout(loadHealth, 400); }
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

// ---- parse ----------------------------------------------------------------
$('go').addEventListener('click', run);
async function run() {
  const text = $('text').value.trim();
  if (!text) { out.innerHTML = '<div class="err">Enter some text first.</div>'; return; }
  $('go').disabled = true;
  out.innerHTML = '<div class="empty">Parsing…</div>';
  try {
    const res = await fetch(apiUrl('/api/parse'), {
      method: 'POST', headers: apiHeaders(true),
      body: JSON.stringify({ text, max_keywords: Number($('maxkw').value) || 15 }),
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

function emphCard(e, kind) {
  if (!e) return '';
  const chips = (e.matched_terms || []).map((t) => `<span class="chip">${escapeHtml(t)}</span>`).join('');
  return `<div class="emph ${kind}">
    <div class="tag">${kind} emphasis</div>
    <div class="label">${escapeHtml(e.label)}
      <span class="id">${escapeHtml(e.id || '')} · ${escapeHtml(e.type)}</span></div>
    <div class="bar"><i style="width:${pct(e.score)}%"></i></div>
    <div class="chips">${chips}</div>
  </div>`;
}

function render(d) {
  const m = d.meta || {};
  let html = '<div class="rtools"><button class="ghost sm" id="copyjson">Copy JSON</button></div>';
  html += emphCard(d.primary, 'primary') + emphCard(d.secondary, 'secondary');
  if (!d.primary) html += '<div class="err">No emphasis matched the taxonomy.</div>';

  html += '<h3>All ranked emphases</h3><div class="ranked">';
  (d.emphases || []).forEach((e) => {
    html += `<div class="item"><span class="nm">${escapeHtml(e.label)}</span>
      <span class="bar"><i style="width:${pct(e.score)}%"></i></span>
      <span class="pct">${pct(e.score)}%</span></div>`;
  });
  html += '</div>';

  html += '<h3>Specific keywords</h3><div class="chips">';
  (d.keywords || []).forEach((k) => {
    const cls = k.source === 'lexicon' ? 'lex' : (k.source === 'rake+lexicon' ? 'both' : '');
    const rel = k.related_emphasis ? ' · ' + k.related_emphasis : '';
    html += `<span class="chip ${cls}" title="${escapeHtml(k.source + rel)}">${escapeHtml(k.display || k.term)}<span class="s">${pct(k.score)}</span></span>`;
  });
  html += '</div>';

  const warn = m.low_confidence ? '<span class="warn">⚠ low confidence</span>' : '';
  html += `<div class="meta"><span>tokens: ${m.token_count}</span>
    <span>confidence: ${pct(m.confidence)}%</span> ${warn}
    <span>v${escapeHtml(m.version || '')}</span></div>`;
  html += `<details><summary>Raw JSON</summary><pre>${escapeHtml(JSON.stringify(d, null, 2))}</pre></details>`;
  out.innerHTML = html;
  $('copyjson').addEventListener('click', (ev) => copyJson(ev.target));
}

// ---- copy helpers ---------------------------------------------------------
function shellQuote(s) { return "'" + s.replace(/'/g, "'\\''") + "'"; }
async function copyToClipboard(textVal, btn) {
  try { await navigator.clipboard.writeText(textVal); flash(btn, 'Copied!'); }
  catch (e) { flash(btn, 'Copy failed'); }
}
$('copycurl').addEventListener('click', (ev) => {
  const text = $('text').value.trim();
  if (!text) { flash(ev.target, 'No text'); return; }
  const url = (getBase() || location.origin) + '/api/parse';
  const body = JSON.stringify({ text, max_keywords: Number($('maxkw').value) || 15 });
  const lines = [`curl -s ${shellQuote(url)}`, `-H 'Content-Type: application/json'`];
  if (getKey()) lines.push(`-H ${shellQuote('X-API-Key: ' + getKey())}`);
  lines.push(`-d ${shellQuote(body)}`);
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
    const groups = { field: [], sector: [] };
    (d.categories || []).forEach((c) => (groups[c.type] || (groups[c.type] = [])).push(c));
    const col = (title, items) => `<div><h3>${title} (${items.length})</h3>` +
      items.map((c) => `<div class="cat">${escapeHtml(c.label)}<span class="id">${escapeHtml(c.id)}</span></div>`).join('') + '</div>';
    box.innerHTML = col('Fields', groups.field || []) + col('Sectors', groups.sector || []);
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
  saveSettings(); taxLoaded = false; scheduleHealth();
}));

loadSettings();
loadHealth();

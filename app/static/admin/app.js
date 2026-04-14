// ── State ─────────────────────────────────────────────────────────────────────

let cfg = {};           // current config (includes computed fields from GET /api/config)
let statsLoaded = false;
let logsLoaded  = false;
let logsPage    = 1;

// ── API helpers ───────────────────────────────────────────────────────────────

async function apiGet(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || `${r.status} ${r.statusText}`);
  }
  return r.json();
}

async function apiDelete(path) {
  const r = await fetch(path, { method: 'DELETE' });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || `${r.status} ${r.statusText}`);
  }
  return r.json();
}

async function apiUpload(path, file) {
  const form = new FormData();
  form.append('file', file);
  const r = await fetch(path, { method: 'POST', body: form });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || `${r.status} ${r.statusText}`);
  }
  return r.json();
}

// Strip computed server-side fields before sending config to POST /api/config
function configPayload(overrides) {
  const { has_logo, has_favicon, has_disclaimer, ...base } = cfg;
  return { ...base, ...overrides };
}

// ── Config loading ────────────────────────────────────────────────────────────

async function reloadConfig() {
  cfg = await apiGet('/api/config');
  populateForms();
  renderDisclaimerBanner();
  renderLogoState();
  renderFaviconState();
}

function populateForms() {
  setVal('site_title',        cfg.site_title    ?? '');
  setVal('browser_title',     cfg.browser_title ?? '');
  setVal('subtitle',          cfg.subtitle      ?? '');
  setVal('accent_color',      cfg.accent_color  ?? '#3b82f6');
  setVal('accent_hex',        cfg.accent_color  ?? '#3b82f6');
  setRadio('header_mode',     cfg.header_mode   ?? 'title');
  setChecked('show_paste_button', cfg.show_paste_button ?? true);
  setChecked('kofi_enabled',  cfg.kofi_enabled  ?? false);
  setVal('kofi_username',     cfg.kofi_username ?? '');
  updateKofiFields();
  validateBranding();
  validateContent();
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

function setChecked(id, checked) {
  const el = document.getElementById(id);
  if (el) el.checked = checked;
}

function setRadio(name, value) {
  const el = document.querySelector(`input[name="${name}"][value="${value}"]`);
  if (el) el.checked = true;
}

// ── Navigation ────────────────────────────────────────────────────────────────

function showSection(name) {
  document.querySelectorAll('.section').forEach(s => s.hidden = true);
  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));

  const sec = document.getElementById(`section-${name}`);
  if (sec) sec.hidden = false;

  const btn = document.querySelector(`.nav-item[data-section="${name}"]`);
  if (btn) btn.classList.add('active');

  const saveBar      = document.getElementById('save-bar');
  const saveBranding = document.getElementById('save-branding');
  const saveContent  = document.getElementById('save-content');
  if (saveBranding) saveBranding.hidden = name !== 'branding';
  if (saveContent)  saveContent.hidden  = name !== 'content';
  if (saveBar)      saveBar.hidden      = !['branding', 'content'].includes(name);

  if (name === 'statistics' && !statsLoaded) loadStats();
  if (name === 'logs'       && !logsLoaded)  loadLogs(1);
}

document.querySelectorAll('.nav-item[data-section]').forEach(btn => {
  btn.addEventListener('click', () => showSection(btn.dataset.section));
});

// ── Disclaimer banner ─────────────────────────────────────────────────────────

function renderDisclaimerBanner() {
  const banner = document.getElementById('banner-disclaimer');
  if (!banner) return;
  banner.hidden = !(!cfg.has_disclaimer && cfg.show_disclaimer_warning);
}

document.getElementById('dismiss-disclaimer')?.addEventListener('click', async () => {
  try {
    await apiPost('/api/dismiss-disclaimer-warning');
    await reloadConfig();
  } catch (err) {
    console.error('dismiss-disclaimer failed:', err);
  }
});

// ── Validation ────────────────────────────────────────────────────────────────

function validateBranding() {
  const headerMode = document.querySelector('input[name="header_mode"]:checked')?.value ?? 'title';
  const errorEl    = document.getElementById('header-mode-error');
  const saveBtn    = document.getElementById('save-branding');
  const invalid    = headerMode === 'logo' && !cfg.has_logo;
  if (errorEl) errorEl.hidden = !invalid;
  if (saveBtn) saveBtn.disabled = invalid;
}

function validateContent() {
  const kofiEnabled  = document.getElementById('kofi_enabled')?.checked ?? false;
  const kofiUsername = document.getElementById('kofi_username')?.value.trim() ?? '';
  const row          = document.getElementById('kofi-username-row');
  const errorEl      = document.getElementById('kofi-username-error');
  const saveBtn      = document.getElementById('save-content');
  const invalid      = kofiEnabled && !kofiUsername;
  row?.classList.toggle('field--error', invalid);
  if (errorEl) errorEl.hidden = !invalid;
  if (saveBtn) saveBtn.disabled = invalid;
}

document.querySelectorAll('input[name="header_mode"]').forEach(r =>
  r.addEventListener('change', validateBranding)
);
document.getElementById('kofi_username')?.addEventListener('input', validateContent);

// ── Branding section ──────────────────────────────────────────────────────────

// Color picker <-> hex input sync
document.getElementById('accent_color')?.addEventListener('input', (e) => {
  setVal('accent_hex', e.target.value);
});

document.getElementById('accent_hex')?.addEventListener('input', (e) => {
  if (/^#[0-9a-fA-F]{6}$/.test(e.target.value)) {
    setVal('accent_color', e.target.value);
  }
});

document.getElementById('save-branding')?.addEventListener('click', async () => {
  const btn = document.getElementById('save-branding');
  btn.disabled = true;
  try {
    await apiPost('/api/config', configPayload({
      site_title:    document.getElementById('site_title').value.trim(),
      browser_title: document.getElementById('browser_title').value.trim(),
      subtitle:      document.getElementById('subtitle').value.trim(),
      accent_color:  document.getElementById('accent_color').value,
      header_mode:   document.querySelector('input[name="header_mode"]:checked')?.value ?? 'title',
    }));
    await reloadConfig();
    showToast('success', 'Branding saved');
  } catch (err) {
    showToast('error', err.message);
  } finally {
    validateBranding();
  }
});

// ── Logo state ────────────────────────────────────────────────────────────────

let logoPending = false;  // true after a successful upload, before confirm

function renderLogoState() {
  const el = document.getElementById('logo-state');
  if (!el) return;

  if (logoPending) {
    el.innerHTML = `
      <div class="asset-preview">
        <img src="/api/logo/pending?t=${Date.now()}" alt="Logo preview" class="asset-img" />
        <span class="asset-badge asset-badge--pending">Not yet live</span>
      </div>
      <div class="asset-actions">
        <button class="btn btn--primary" id="logo-confirm">Confirm</button>
        <button class="btn btn--ghost" id="logo-discard">Cancel</button>
      </div>`;
    document.getElementById('logo-confirm').onclick = confirmLogo;
    document.getElementById('logo-discard').onclick = discardLogo;
    return;
  }

  if (cfg.has_logo) {
    el.innerHTML = `
      <div class="asset-preview">
        <img src="/logo?t=${Date.now()}" alt="Logo" class="asset-img" />
      </div>
      <div class="asset-actions">
        <label for="logo-replace-input" class="btn btn--secondary">Replace</label>
        <button class="btn btn--danger" id="logo-delete">Delete</button>
      </div>
      <input type="file" id="logo-replace-input" class="hidden-file" accept="image/*" />`;
    document.getElementById('logo-delete').onclick = deleteLogo;
    document.getElementById('logo-replace-input').onchange = handleLogoUpload;
    return;
  }

  el.innerHTML = `
    <p class="asset-empty">No logo uploaded</p>
    <div class="asset-actions">
      <label for="logo-upload-input" class="btn btn--secondary">Upload image</label>
    </div>
    <input type="file" id="logo-upload-input" class="hidden-file" accept="image/*" />`;
  document.getElementById('logo-upload-input').onchange = handleLogoUpload;
}

async function handleLogoUpload(e) {
  const file = e.target.files[0];
  if (!file) return;
  const el = document.getElementById('logo-state');
  el.innerHTML = '<p class="asset-empty">Uploading...</p>';
  try {
    await apiUpload('/api/logo/upload', file);
    logoPending = true;
    renderLogoState();
  } catch (err) {
    showToast('error', `Logo upload failed: ${err.message}`);
    renderLogoState();
  }
}

async function confirmLogo() {
  try {
    await apiPost('/api/logo/confirm');
    logoPending = false;
    await reloadConfig();
    showToast('success', 'Logo saved');
  } catch (err) {
    showToast('error', err.message);
  }
}

async function discardLogo() {
  try {
    await apiPost('/api/logo/discard');
  } catch { /* ignore */ }
  logoPending = false;
  renderLogoState();
}

async function deleteLogo() {
  if (!confirm('Delete the logo? This cannot be undone.')) return;
  try {
    await apiDelete('/api/logo');
    await reloadConfig();
    showToast('success', 'Logo deleted');
  } catch (err) {
    showToast('error', err.message);
  }
}

// ── Favicon state ─────────────────────────────────────────────────────────────

let faviconPending = false;

function renderFaviconState() {
  const el = document.getElementById('favicon-state');
  if (!el) return;

  if (faviconPending) {
    el.innerHTML = `
      <div class="asset-preview">
        <img src="/api/favicon/pending?t=${Date.now()}" alt="Favicon preview" class="asset-favicon-img" />
        <span class="asset-badge asset-badge--pending">Not yet live</span>
      </div>
      <div class="asset-actions">
        <button class="btn btn--primary" id="fav-confirm">Confirm</button>
        <button class="btn btn--ghost" id="fav-discard">Cancel</button>
      </div>`;
    document.getElementById('fav-confirm').onclick = confirmFavicon;
    document.getElementById('fav-discard').onclick = discardFavicon;
    return;
  }

  if (cfg.has_favicon) {
    el.innerHTML = `
      <div class="asset-preview">
        <img src="/favicon.ico?t=${Date.now()}" alt="Favicon" class="asset-favicon-img" />
        <span class="asset-badge asset-badge--enabled">Active</span>
      </div>
      <div class="asset-actions">
        <label for="fav-replace-input" class="btn btn--secondary">Replace</label>
        <button class="btn btn--danger" id="fav-delete">Delete</button>
      </div>
      <input type="file" id="fav-replace-input" class="hidden-file" accept="image/*" />`;
    document.getElementById('fav-delete').onclick = deleteFavicon;
    document.getElementById('fav-replace-input').onchange = handleFaviconUpload;
    return;
  }

  el.innerHTML = `
    <p class="asset-empty">No favicon uploaded</p>
    <div class="asset-actions">
      <label for="fav-upload-input" class="btn btn--secondary">Upload image</label>
    </div>
    <input type="file" id="fav-upload-input" class="hidden-file" accept="image/*" />`;
  document.getElementById('fav-upload-input').onchange = handleFaviconUpload;
}

async function handleFaviconUpload(e) {
  const file = e.target.files[0];
  if (!file) return;
  const el = document.getElementById('favicon-state');
  el.innerHTML = '<p class="asset-empty">Uploading...</p>';
  try {
    await apiUpload('/api/favicon/upload', file);
    faviconPending = true;
    renderFaviconState();
  } catch (err) {
    showToast('error', `Favicon upload failed: ${err.message}`);
    renderFaviconState();
  }
}

async function confirmFavicon() {
  try {
    await apiPost('/api/favicon/confirm');
    faviconPending = false;
    await reloadConfig();
    showToast('success', 'Favicon saved');
  } catch (err) {
    showToast('error', err.message);
  }
}

async function discardFavicon() {
  try {
    await apiPost('/api/favicon/discard');
  } catch { /* ignore */ }
  faviconPending = false;
  renderFaviconState();
}

async function deleteFavicon() {
  if (!confirm('Delete the favicon?')) return;
  try {
    await apiDelete('/api/favicon');
    await reloadConfig();
    showToast('success', 'Favicon deleted');
  } catch (err) {
    showToast('error', err.message);
  }
}

// ── Content section ───────────────────────────────────────────────────────────

function updateKofiFields() {
  const enabled = document.getElementById('kofi_enabled')?.checked;
  const row = document.getElementById('kofi-username-row');
  if (row) row.hidden = !enabled;
  validateContent();
}

document.getElementById('kofi_enabled')?.addEventListener('change', updateKofiFields);

document.getElementById('save-content')?.addEventListener('click', async () => {
  const btn = document.getElementById('save-content');
  btn.disabled = true;
  try {
    await apiPost('/api/config', configPayload({
      show_paste_button: document.getElementById('show_paste_button').checked,
      kofi_enabled:      document.getElementById('kofi_enabled').checked,
      kofi_username:     document.getElementById('kofi_username').value.trim(),
    }));
    await reloadConfig();
    showToast('success', 'Content settings saved');
  } catch (err) {
    showToast('error', err.message);
  } finally {
    validateContent();
  }
});

// ── Statistics section ────────────────────────────────────────────────────────

const SERVICE_COLORS = [
  '#3b82f6', '#22c55e', '#f59e0b', '#ef4444',
  '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16',
];

async function loadStats() {
  statsLoaded = true;
  const el = document.getElementById('stats-body');
  if (!el) return;

  let data;
  try {
    data = await apiGet('/api/stats');
  } catch (err) {
    el.innerHTML = `<div class="stats-unavailable"><h3>Failed to load statistics</h3><p>${err.message}</p></div>`;
    return;
  }

  if (!data.available) {
    el.innerHTML = `
      <div class="stats-unavailable">
        <h3>Request logging not yet configured</h3>
        <p>Add <code>aiosqlite</code>, <code>ua-parser</code>, and <code>geoip2</code> to requirements.txt
        and implement <code>app/db.py</code> to enable statistics tracking.</p>
        <p>See the Planned section in <code>CLAUDE.md</code> for the full design.</p>
      </div>`;
    return;
  }

  const tilesHtml = (data.totals || []).map(t => `
    <div class="stats-tile">
      <div class="stats-tile-value">${t.value.toLocaleString()}</div>
      <div class="stats-tile-label">${t.label}</div>
    </div>`).join('');

  el.innerHTML = `
    <div class="stats-tiles">${tilesHtml}</div>
    <div class="charts-row">
      <div class="chart-card">
        <h3>By platform</h3>
        <div class="chart-canvas-wrap"><canvas id="chart-pie" class="chart"></canvas></div>
        <div id="chart-pie-legend" class="chart-legend"></div>
      </div>
      <div class="chart-card">
        <h3>Downloads per day</h3>
        <div class="chart-canvas-wrap"><canvas id="chart-bar" class="chart"></canvas></div>
      </div>
    </div>`;

  drawDonut('chart-pie', 'chart-pie-legend', data.services || []);
  drawBars('chart-bar', data.daily || []);
}

function drawDonut(canvasId, legendId, segments) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width  = rect.width  * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const w = rect.width, h = rect.height;
  const cx = w / 2, cy = h / 2;
  const r = Math.min(w, h) / 2 - 8;
  const inner = r * 0.58;

  const colored = segments.map((s, i) => ({ ...s, color: SERVICE_COLORS[i % SERVICE_COLORS.length] }));
  const total = colored.reduce((acc, s) => acc + s.count, 0);

  if (total === 0) {
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.arc(cx, cy, inner, 0, Math.PI * 2, true);
    ctx.fillStyle = '#252525';
    ctx.fill('evenodd');
    ctx.fillStyle = '#555';
    ctx.font = `bold 14px -apple-system, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('No data', cx, cy);
    return;
  }

  let angle = -Math.PI / 2;
  for (const seg of colored) {
    const slice = (seg.count / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, angle, angle + slice);
    ctx.arc(cx, cy, inner, angle + slice, angle, true);
    ctx.closePath();
    ctx.fillStyle = seg.color;
    ctx.fill();
    angle += slice;
  }

  ctx.fillStyle = '#e5e5e5';
  ctx.font = `bold ${Math.round(r * 0.28)}px -apple-system, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(total.toLocaleString(), cx, cy);

  const legendEl = document.getElementById(legendId);
  if (legendEl) {
    legendEl.innerHTML = colored.map(s => `
      <span class="legend-item">
        <span class="legend-dot" style="background:${s.color}"></span>
        ${s.name} (${s.count})
      </span>`).join('');
  }
}

function drawBars(canvasId, daily) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width  = rect.width  * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const w = rect.width, h = rect.height;
  const padL = 8, padR = 8, padT = 8, padB = 24;
  const chartW = w - padL - padR;
  const chartH = h - padT - padB;

  if (!daily.length) {
    ctx.fillStyle = '#555';
    ctx.font = '13px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('No data', w / 2, h / 2);
    return;
  }

  const maxVal = Math.max(...daily.map(d => d.count), 1);
  const barW = Math.max(2, chartW / daily.length - 2);
  const gap  = chartW / daily.length;

  daily.forEach((d, i) => {
    const barH = (d.count / maxVal) * chartH;
    const x = padL + i * gap;
    const y = padT + chartH - barH;
    ctx.fillStyle = '#3b82f6';
    ctx.fillRect(x, y, barW, barH);
  });

  ctx.fillStyle = '#555';
  ctx.font = `${10 * dpr / dpr}px -apple-system, sans-serif`;
  ctx.textAlign = 'center';
  const step = Math.max(1, Math.ceil(daily.length / 8));
  daily.forEach((d, i) => {
    if (i % step === 0) {
      const x = padL + i * gap + barW / 2;
      const label = d.date ? d.date.slice(5) : '';  // MM-DD from YYYY-MM-DD
      ctx.fillText(label, x, h - padB + 14);
    }
  });
}

// ── Logs section ──────────────────────────────────────────────────────────────

async function loadLogs(page) {
  logsLoaded = true;
  logsPage = page;
  const el = document.getElementById('logs-body');
  if (!el) return;

  let data;
  try {
    data = await apiGet(`/api/logs?page=${page}&per_page=50`);
  } catch (err) {
    el.innerHTML = `<div class="logs-unavailable"><p>${err.message}</p></div>`;
    return;
  }

  if (!data.available) {
    el.innerHTML = `
      <div class="logs-unavailable">
        <h3>Request logging not yet configured</h3>
        <p>Once request logging is implemented, each <code>/api/info</code> and
        <code>/api/download</code> call will be recorded here with IP, country,
        platform, URL, and outcome.</p>
      </div>`;
    return;
  }

  if (!data.items.length) {
    el.innerHTML = `<div class="logs-unavailable"><p>No log entries yet.</p></div>`;
    return;
  }

  const rows = data.items.map(row => `
    <tr>
      <td title="${row.ts}">${formatTs(row.ts)}</td>
      <td>${row.ip ?? '-'}</td>
      <td>${row.country ?? '-'}</td>
      <td>${row.endpoint ?? '-'}</td>
      <td>${row.platform ?? '-'}</td>
      <td class="log-cell-url" title="${row.url ?? ''}">${row.url ? truncate(row.url, 48) : '-'}</td>
      <td class="${row.success ? 'log-status-ok' : 'log-status-err'}">${row.success ? 'OK' : 'Fail'}</td>
      <td>${row.duration_ms != null ? `${row.duration_ms}ms` : '-'}</td>
    </tr>`).join('');

  const prevDisabled = page <= 1 ? 'disabled' : '';
  const nextDisabled = page >= data.pages ? 'disabled' : '';

  el.innerHTML = `
    <div class="log-table-wrap">
      <table class="log-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>IP</th>
            <th>Country</th>
            <th>Endpoint</th>
            <th>Platform</th>
            <th>URL</th>
            <th>Status</th>
            <th>Duration</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="log-pagination">
        <span class="log-pagination-info">
          Page ${page} of ${data.pages} (${data.total} entries)
        </span>
        <button class="btn btn--ghost" id="logs-prev" ${prevDisabled}>Previous</button>
        <button class="btn btn--ghost" id="logs-next" ${nextDisabled}>Next</button>
      </div>
    </div>`;

  document.getElementById('logs-prev')?.addEventListener('click', () => loadLogs(page - 1));
  document.getElementById('logs-next')?.addEventListener('click', () => loadLogs(page + 1));
}

function formatTs(ts) {
  if (!ts) return '-';
  try {
    return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return ts; }
}

function truncate(str, max) {
  return str.length > max ? str.slice(0, max) + '...' : str;
}

// ── Danger section ────────────────────────────────────────────────────────────

document.getElementById('reset-btn')?.addEventListener('click', async () => {
  if (!confirm('Reset all settings to defaults?')) return;
  const btn = document.getElementById('reset-btn');
  btn.disabled = true;
  try {
    await apiPost('/api/config/reset');
    await reloadConfig();
    showToast('success', 'Settings reset to defaults');
  } catch (err) {
    showToast('error', err.message);
  } finally {
    btn.disabled = false;
  }
});

// ── Toast notifications ───────────────────────────────────────────────────────

function showToast(type, msg) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast toast--${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('toast--out');
    setTimeout(() => toast.remove(), 180);
  }, 3000);
}

// ── Init ──────────────────────────────────────────────────────────────────────

reloadConfig().catch(err => console.error('init failed:', err));

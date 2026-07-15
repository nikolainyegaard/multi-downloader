// ── Theme ─────────────────────────────────────────────────────────────────────

const THEME_ICONS = {
  system: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>',
  light:  '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><line x1="12" y1="2" x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="4.22" y1="4.22" x2="6.34" y2="6.34"/><line x1="17.66" y1="17.66" x2="19.78" y2="19.78"/><line x1="2" y1="12" x2="5" y2="12"/><line x1="19" y1="12" x2="22" y2="12"/><line x1="4.22" y1="19.78" x2="6.34" y2="17.66"/><line x1="17.66" y1="6.34" x2="19.78" y2="4.22"/></svg>',
  dark:   '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>',
};

function getStoredTheme() {
  return localStorage.getItem('theme') || 'system';
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('theme', theme);
  redrawCharts();
}

function hexToHue(hex) {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16) / 255;
  const g = parseInt(h.slice(2, 4), 16) / 255;
  const b = parseInt(h.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  if (max === min) return 0;
  const d = max - min;
  let hue;
  if (max === r) hue = (g - b) / d + (g < b ? 6 : 0);
  else if (max === g) hue = (b - r) / d + 2;
  else hue = (r - g) / d + 4;
  return Math.round(hue / 6 * 360);
}

function applyAccentVars(hex) {
  const hue = hexToHue(hex);
  const root = document.documentElement;
  root.style.setProperty('--accent', `hsl(${hue}, 78%, 60%)`);
  root.style.setProperty('--accent-hover', `hsl(${hue}, 78%, 68%)`);
  root.style.setProperty('--accent-subtle', `hsla(${hue}, 78%, 60%, 0.10)`);
}

function syncThemeButton() {
  const theme = getStoredTheme();
  const icon  = document.getElementById('theme-icon');
  const label = document.getElementById('theme-label');
  if (icon)  icon.innerHTML = THEME_ICONS[theme];
  if (label) label.textContent = theme.charAt(0).toUpperCase() + theme.slice(1);
  document.querySelectorAll('.theme-option').forEach((opt) => {
    opt.classList.toggle('active', opt.dataset.theme === theme);
  });
}

(function initThemeToggle() {
  syncThemeButton();

  const btn  = document.getElementById('theme-btn');
  const menu = document.getElementById('theme-menu');
  if (!btn || !menu) return;

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const opening = menu.hidden;
    menu.hidden = !menu.hidden;
    btn.setAttribute('aria-expanded', String(opening));
  });

  menu.addEventListener('click', (e) => {
    const opt = e.target.closest('.theme-option');
    if (!opt) return;
    applyTheme(opt.dataset.theme);
    syncThemeButton();
    menu.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
  });

  document.addEventListener('click', () => {
    menu.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
  });
})();

// ── State ─────────────────────────────────────────────────────────────────────

let currentSection = 'branding';
let cfg = {};           // current config (includes computed fields from GET /api/config)
let statsLoaded = false;
let logsLoaded  = false;
let logsPage    = 1;

// ── Field defaults (mirrors config.py Config dataclass) ───────────────────────

const FIELD_DEFAULTS = {
  browser_title:     '',
  subtitle:          'Paste a link, download the video',
  site_title:        'multi-downloader',
  accent_color:      '#3b82f6',
  header_mode:       'title',
  show_paste_button: true,
  kofi_enabled:      false,
  kofi_username:     '',
};

// ── Confirm dialog ────────────────────────────────────────────────────────────

function showConfirm(message) {
  return new Promise(resolve => {
    const overlay  = document.getElementById('confirm-overlay');
    const msgEl    = document.getElementById('confirm-message');
    const okBtn    = document.getElementById('confirm-ok');
    const cancelBtn = document.getElementById('confirm-cancel');
    if (!overlay) { resolve(false); return; }

    msgEl.textContent = message;
    overlay.hidden = false;
    okBtn.focus();

    function finish(result) {
      overlay.hidden = true;
      okBtn.removeEventListener('click', onOk);
      cancelBtn.removeEventListener('click', onCancel);
      overlay.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      resolve(result);
    }

    function onOk()      { finish(true);  }
    function onCancel()  { finish(false); }
    function onBackdrop(e) { if (e.target === overlay) finish(false); }
    function onKey(e)    { if (e.key === 'Escape') finish(false); }

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    overlay.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);
  });
}

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
  updateHeaderModeView();
  validateBranding();
  validateContent();
  updateResetBtns();
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

// ── Per-field reset ───────────────────────────────────────────────────────────

function getFormValue(field) {
  switch (field) {
    case 'header_mode':
      return document.querySelector('input[name="header_mode"]:checked')?.value ?? 'title';
    case 'show_paste_button':
    case 'kofi_enabled':
      return document.getElementById(field)?.checked ?? FIELD_DEFAULTS[field];
    case 'accent_color':
      return (document.getElementById(field)?.value ?? FIELD_DEFAULTS[field]).toLowerCase();
    default:
      return document.getElementById(field)?.value ?? FIELD_DEFAULTS[field];
  }
}

const BRANDING_FIELDS = new Set(['browser_title', 'subtitle', 'header_mode', 'site_title', 'accent_color']);
const CONTENT_FIELDS  = new Set(['show_paste_button', 'kofi_enabled', 'kofi_username']);

function isSectionDirty(fields) {
  for (const field of fields) {
    if (!(field in cfg)) continue;
    const saved   = cfg[field];
    const current = getFormValue(field);
    if (String(current) !== String(saved)) return true;
  }
  return false;
}

function updateResetBtns() {
  document.querySelectorAll('[data-reset-field]').forEach(btn => {
    const field = btn.dataset.resetField;
    if (!(field in FIELD_DEFAULTS)) return;
    const def     = FIELD_DEFAULTS[field];
    const current = getFormValue(field);
    btn.disabled = String(current) === String(def);
  });
  updateSaveBar();
}

function updateSaveBar() {
  const btn = document.getElementById('save-btn');
  if (!btn) return;
  const sectionFields = currentSection === 'branding' ? BRANDING_FIELDS
                      : currentSection === 'content'  ? CONTENT_FIELDS
                      : null;
  btn.hidden = !sectionFields || !isSectionDirty(sectionFields);
}

function resetField(field) {
  const def = FIELD_DEFAULTS[field];
  switch (field) {
    case 'header_mode':
      setRadio('header_mode', def);
      updateHeaderModeView();
      break;
    case 'show_paste_button':
    case 'kofi_enabled':
      setChecked(field, def);
      if (field === 'kofi_enabled') updateKofiFields();
      break;
    case 'accent_color':
      setVal('accent_color', def);
      setVal('accent_hex', def);
      break;
    default:
      setVal(field, def);
  }
  updateResetBtns();
  validateBranding();
  validateContent();
}

// ── Navigation ────────────────────────────────────────────────────────────────

function showSection(name) {
  currentSection = name;
  document.querySelectorAll('.section').forEach(s => s.hidden = true);
  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));

  const sec = document.getElementById(`section-${name}`);
  if (sec) sec.hidden = false;

  const btn = document.querySelector(`.nav-item[data-section="${name}"]`);
  if (btn) btn.classList.add('active');

  updateSaveBar();

  if (name === 'statistics' && !statsLoaded) loadStats();
  if (name === 'logs'       && !logsLoaded)  loadLogs(1);
}

document.querySelectorAll('.nav-item[data-section]').forEach(btn => {
  btn.addEventListener('click', () => showSection(btn.dataset.section));
});

// Sync reset button states whenever any form field changes
document.querySelector('.main')?.addEventListener('input',  updateResetBtns);
document.querySelector('.main')?.addEventListener('change', updateResetBtns);

// Reset button clicks (event delegation)
document.querySelector('.main')?.addEventListener('click', e => {
  const btn = e.target.closest('[data-reset-field]');
  if (!btn || btn.disabled) return;
  resetField(btn.dataset.resetField);
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
  const invalid    = headerMode === 'logo' && !cfg.has_logo;
  if (errorEl) errorEl.hidden = !invalid;
  const saveBtn = document.getElementById('save-btn');
  if (saveBtn && currentSection === 'branding') saveBtn.disabled = invalid;
  updateSaveBar();
}

function validateContent() {
  const kofiEnabled  = document.getElementById('kofi_enabled')?.checked ?? false;
  const kofiUsername = document.getElementById('kofi_username')?.value.trim() ?? '';
  const row          = document.getElementById('kofi-username-row');
  const errorEl      = document.getElementById('kofi-username-error');
  const invalid      = kofiEnabled && !kofiUsername;
  row?.classList.toggle('field--error', invalid);
  if (errorEl) errorEl.hidden = !invalid;
  const saveBtn = document.getElementById('save-btn');
  if (saveBtn && currentSection === 'content') saveBtn.disabled = invalid;
  updateSaveBar();
}

function updateHeaderModeView() {
  const mode = document.querySelector('input[name="header_mode"]:checked')?.value ?? 'title';
  const titleRow = document.getElementById('header-title-row');
  const logoRow  = document.getElementById('header-logo-row');
  if (titleRow) titleRow.hidden = mode !== 'title';
  if (logoRow)  logoRow.hidden  = mode !== 'logo';
}

document.querySelectorAll('input[name="header_mode"]').forEach(r =>
  r.addEventListener('change', () => { validateBranding(); updateHeaderModeView(); })
);
document.getElementById('kofi_username')?.addEventListener('input', validateContent);

// ── Branding section ──────────────────────────────────────────────────────────

// Color picker <-> hex input sync
document.getElementById('accent_color')?.addEventListener('input', (e) => {
  setVal('accent_hex', e.target.value);
  applyAccentVars(e.target.value);
});

document.getElementById('accent_hex')?.addEventListener('input', (e) => {
  if (/^#[0-9a-fA-F]{6}$/.test(e.target.value)) {
    setVal('accent_color', e.target.value);
    applyAccentVars(e.target.value);
  }
});

document.getElementById('save-btn')?.addEventListener('click', async () => {
  const btn = document.getElementById('save-btn');
  btn.disabled = true;
  try {
    if (currentSection === 'branding') {
      // lowercase so the saved value always matches getFormValue's dirty check
      const accent = document.getElementById('accent_color').value.toLowerCase();
      await apiPost('/api/config', configPayload({
        site_title:    document.getElementById('site_title').value.trim(),
        browser_title: document.getElementById('browser_title').value.trim(),
        subtitle:      document.getElementById('subtitle').value.trim(),
        accent_color:  accent,
        header_mode:   document.querySelector('input[name="header_mode"]:checked')?.value ?? 'title',
      }));
      applyAccentVars(accent);
      await reloadConfig();
      showToast('success', 'Branding saved');
    } else if (currentSection === 'content') {
      await apiPost('/api/config', configPayload({
        show_paste_button: document.getElementById('show_paste_button').checked,
        kofi_enabled:      document.getElementById('kofi_enabled').checked,
        kofi_username:     document.getElementById('kofi_username').value.trim(),
      }));
      await reloadConfig();
      showToast('success', 'Content settings saved');
    }
  } catch (err) {
    showToast('error', err.message);
  } finally {
    if (currentSection === 'branding') validateBranding();
    else validateContent();
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
        <img src="/api/logo?t=${Date.now()}" alt="Logo" class="asset-img" />
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
  if (!await showConfirm('Delete the logo? This cannot be undone.')) return;
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
  if (!await showConfirm('Delete the favicon? This cannot be undone.')) return;
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

  // store data on canvas elements so redrawCharts() can replay them
  const pie = document.getElementById('chart-pie');
  const bar = document.getElementById('chart-bar');
  if (pie) pie._chartData = { segments: data.services || [] };
  if (bar) bar._chartData = { daily: data.daily || [] };
}

function redrawCharts() {
  const pie = document.getElementById('chart-pie');
  const bar = document.getElementById('chart-bar');
  if (pie?._chartData) drawDonut('chart-pie', 'chart-pie-legend', pie._chartData.segments);
  if (bar?._chartData) drawBars('chart-bar', bar._chartData.daily);
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

  const style = getComputedStyle(document.documentElement);
  const colorText     = style.getPropertyValue('--text').trim();
  const colorMuted    = style.getPropertyValue('--text-muted').trim();
  const colorSurface3 = style.getPropertyValue('--surface-3').trim();

  if (total === 0) {
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.arc(cx, cy, inner, 0, Math.PI * 2, true);
    ctx.fillStyle = colorSurface3;
    ctx.fill('evenodd');
    ctx.fillStyle = colorMuted;
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

  ctx.fillStyle = colorText;
  ctx.font = `bold ${Math.round(r * 0.28)}px -apple-system, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(total.toLocaleString(), cx, cy);

  const legendEl = document.getElementById(legendId);
  if (legendEl) {
    legendEl.innerHTML = colored.map(s => `
      <span class="legend-item">
        <span class="legend-dot" style="background:${s.color}"></span>
        ${esc(s.name)} (${s.count})
      </span>`).join('');
  }

  // build pie hitmap: array of {startAngle, endAngle, name, count}
  canvas._pieHitmap = [];
  let a = -Math.PI / 2;
  for (const seg of colored) {
    const slice = (seg.count / total) * Math.PI * 2;
    canvas._pieHitmap.push({ startAngle: a, endAngle: a + slice, name: seg.name, count: seg.count, cx, cy, r, inner });
    a += slice;
  }

  initCanvasTooltip(canvas, (mx, my) => {
    const hm = canvas._pieHitmap;
    if (!hm) return null;
    for (const seg of hm) {
      const dx = mx - seg.cx, dy = my - seg.cy;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < seg.inner || dist > seg.r) continue;
      let angle = Math.atan2(dy, dx);
      // normalise so both angle and segment range share the same -π/2 origin
      if (angle < -Math.PI / 2) angle += Math.PI * 2;
      if (angle >= seg.startAngle && angle < seg.endAngle) {
        return `${seg.name}: ${seg.count}`;
      }
    }
    return null;
  });
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

  const colorMuted = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim();

  if (!daily.length) {
    ctx.fillStyle = colorMuted;
    ctx.font = '13px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('No data', w / 2, h / 2);
    canvas._barHitmap = null;
    return;
  }

  const maxVal = Math.max(...daily.map(d => (d.ok || 0) + (d.err || 0)), 1);
  const groupW = chartW / daily.length;
  const barW   = Math.max(2, groupW - 4);
  const barX0  = padL + (groupW - barW) / 2;

  // hitmap: array of {x, okY, okH, errY, errH, ok, err, date} in CSS px
  const hitmap = [];

  daily.forEach((d, i) => {
    const ok  = d.ok  || 0;
    const err = d.err || 0;
    const total = ok + err;
    const x = barX0 + i * groupW;

    const totalH = (total / maxVal) * chartH;
    const okH    = total > 0 ? (ok  / total) * totalH : 0;
    const errH   = total > 0 ? (err / total) * totalH : 0;
    const baseY  = padT + chartH;

    // error segment on top, download segment on bottom
    if (err > 0) {
      ctx.fillStyle = '#ef4444';
      ctx.fillRect(x, baseY - totalH, barW, errH);
    }
    if (ok > 0) {
      ctx.fillStyle = '#3b82f6';
      ctx.fillRect(x, baseY - okH, barW, okH);
    }

    hitmap.push({
      x, barW,
      errY: baseY - totalH, errH,
      okY:  baseY - okH,    okH,
      ok, err, date: d.date,
    });
  });

  ctx.fillStyle = colorMuted;
  ctx.font = '10px -apple-system, sans-serif';
  ctx.textAlign = 'center';
  const step = Math.max(1, Math.ceil(daily.length / 7));
  daily.forEach((d, i) => {
    if (i % step === 0) {
      const x = barX0 + i * groupW + barW / 2;
      const label = d.date ? d.date.slice(5) : '';
      ctx.fillText(label, x, h - padB + 14);
    }
  });

  canvas._barHitmap = hitmap;
  initCanvasTooltip(canvas, (mx, my) => {
    const hm = canvas._barHitmap;
    if (!hm) return null;
    for (const seg of hm) {
      if (mx < seg.x || mx > seg.x + seg.barW) continue;
      if (seg.errH > 0 && my >= seg.errY && my <= seg.errY + seg.errH) return `Errors: ${seg.err}`;
      if (seg.okH  > 0 && my >= seg.okY  && my <= seg.okY  + seg.okH)  return `Downloads: ${seg.ok}`;
    }
    return null;
  });
}

function getTooltipEl() {
  let tip = document.getElementById('chart-tooltip');
  if (!tip) {
    tip = document.createElement('div');
    tip.id = 'chart-tooltip';
    tip.className = 'bar-tooltip';
    tip.hidden = true;
    document.body.appendChild(tip);
  }
  return tip;
}

function showTooltipAt(tip, text, e) {
  tip.textContent = text;
  tip.hidden = false;
  const offset = 10;
  tip.style.left = `${e.clientX + offset}px`;
  tip.style.top  = `${e.clientY - tip.offsetHeight - offset}px`;
}

// Generic canvas tooltip — hitFn(mx, my) returns a label string or null.
function initCanvasTooltip(canvas, hitFn) {
  if (canvas._tooltipInit) return;
  canvas._tooltipInit = true;

  const tip = getTooltipEl();

  canvas.addEventListener('mousemove', (e) => {
    const rect = canvas.getBoundingClientRect();
    const label = hitFn(e.clientX - rect.left, e.clientY - rect.top);
    if (label) {
      showTooltipAt(tip, label, e);
    } else {
      tip.hidden = true;
    }
  });

  canvas.addEventListener('mouseleave', () => { tip.hidden = true; });
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
      <td>${row.ip ? esc(row.ip) : '-'}</td>
      <td>${row.country ?? '-'}</td>
      <td>${row.endpoint ?? '-'}</td>
      <td>${row.platform ? esc(row.platform) : '-'}</td>
      <td class="log-cell-url" title="${esc(row.url ?? '')}">${row.url ? esc(truncate(row.url, 48)) : '-'}</td>
      <td class="${row.success ? 'log-status-ok' : 'log-status-err'}">${row.success ? 'OK' : 'Fail'}</td>
      <td>${row.duration_ms != null ? `${row.duration_ms}ms` : '-'}</td>
    </tr>`).join('');

  const prevDisabled = page <= 1 ? 'disabled' : '';
  const nextDisabled = page >= data.pages ? 'disabled' : '';

  el.innerHTML = `
    <div class="log-block">
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
      </div>
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

// Escape untrusted values (visitor-submitted URLs, spoofable IPs) before innerHTML
function esc(str) {
  return String(str).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
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
  if (!await showConfirm('Reset all settings to defaults? This cannot be undone.')) return;
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

let _resizeRafPending = false;
window.addEventListener('resize', () => {
  if (_resizeRafPending) return;
  _resizeRafPending = true;
  requestAnimationFrame(() => {
    redrawCharts();
    _resizeRafPending = false;
  });
});

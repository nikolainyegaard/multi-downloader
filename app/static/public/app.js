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
  syncThemeMeta();
}

function syncThemeMeta() {
  const theme = getStoredTheme();
  const dark = theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = dark ? '#0f0f0f' : '#f8f9fa';
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
  syncThemeMeta();

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

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
    }
  });

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (getStoredTheme() === 'system') syncThemeMeta();
  });
})();

// ── Download UI ───────────────────────────────────────────────────────────────

const urlInput       = document.getElementById('url-input');
const pasteBtn       = document.getElementById('paste-btn');
const downloadBtn    = document.getElementById('download-btn');
const downloadWrap   = document.getElementById('download-wrap');
const dlSpinner      = downloadBtn.querySelector('.dl-spinner');
const dlLabel        = document.getElementById('dl-label');
const qualityToggle  = document.getElementById('quality-toggle');
const qualityLabel   = document.getElementById('quality-label');
const qualityMenu    = document.getElementById('quality-menu');
const statusEl       = document.getElementById('status');
const previewEl      = document.getElementById('preview');
const previewLoading = document.getElementById('preview-loading');
const previewContent = document.getElementById('preview-content');
const previewThumb   = document.getElementById('preview-thumb');
const previewTitle   = document.getElementById('preview-title');
const previewMeta    = document.getElementById('preview-meta');

let previewController    = null; // AbortController for in-flight /api/info requests
let previewDebounceTimer = null;

// ── Quality state ─────────────────────────────────────────────────────────────

let currentQualities   = []; // [{label, height}, ...]
let selectedQualityIdx = 0;

function buildDlLabelText() {
  const q = currentQualities[selectedQualityIdx];
  return q ? `\u2193 Download \u2022 ${q.label}` : '\u2193 Download';
}

function renderQualities(qualities) {
  currentQualities   = qualities || [];
  selectedQualityIdx = 0;

  qualityMenu.innerHTML = '';
  currentQualities.forEach((q, i) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'quality-option' + (i === 0 ? ' active' : '');
    btn.setAttribute('role', 'option');
    btn.setAttribute('aria-selected', i === 0 ? 'true' : 'false');
    btn.dataset.idx = String(i);
    btn.textContent = q.label;
    qualityMenu.appendChild(btn);
  });

  const multi = currentQualities.length > 1;
  qualityToggle.hidden = !multi;
  downloadWrap.classList.toggle('has-quality', multi);

  dlLabel.textContent = buildDlLabelText();
  qualityLabel.textContent = currentQualities[0]?.label ?? 'HD';
}

function selectQuality(idx) {
  selectedQualityIdx = idx;
  qualityMenu.querySelectorAll('.quality-option').forEach((btn, i) => {
    btn.classList.toggle('active', i === idx);
    btn.setAttribute('aria-selected', String(i === idx));
  });
  dlLabel.textContent = buildDlLabelText();
  qualityLabel.textContent = currentQualities[idx]?.label ?? 'HD';
  closeQualityMenu();
}

// ── Quality menu ──────────────────────────────────────────────────────────────

function openQualityMenu() {
  qualityMenu.classList.add('open');
  qualityToggle.setAttribute('aria-expanded', 'true');
  qualityMenu.setAttribute('aria-hidden', 'false');
}

function closeQualityMenu() {
  qualityMenu.classList.remove('open');
  qualityToggle.setAttribute('aria-expanded', 'false');
  qualityMenu.setAttribute('aria-hidden', 'true');
}

qualityToggle.addEventListener('click', (e) => {
  e.stopPropagation();
  qualityMenu.classList.contains('open') ? closeQualityMenu() : openQualityMenu();
});

qualityMenu.addEventListener('click', (e) => {
  const btn = e.target.closest('.quality-option');
  if (btn) selectQuality(Number(btn.dataset.idx));
});

document.addEventListener('click', () => closeQualityMenu());
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeQualityMenu(); });

// ── Paste ─────────────────────────────────────────────────────────────────────

pasteBtn?.addEventListener('click', async () => {
  if (!navigator.clipboard?.readText) {
    urlInput.focus();
    showStatus('error', 'Clipboard not available; paste manually');
    return;
  }
  try {
    const text = await navigator.clipboard.readText();
    urlInput.value = text.trim();
    clearStatus();
    urlInput.focus();
    if (urlInput.value) triggerPreview(urlInput.value);
  } catch {
    urlInput.focus();
    showStatus('error', 'Could not read clipboard; paste manually');
  }
});

// Debounced preview on every input event (typing, native paste, cut, etc.)
urlInput.addEventListener('input', () => {
  const url = urlInput.value.trim();
  clearPreviewDebounce();
  if (!url) {
    hidePreview();
    return;
  }
  previewDebounceTimer = setTimeout(() => triggerPreview(url), 600);
});

// ── Download ──────────────────────────────────────────────────────────────────

downloadBtn.addEventListener('click', async () => {
  const url = urlInput.value.trim();
  if (!url) {
    showStatus('error', 'Enter a URL first');
    urlInput.focus();
    return;
  }

  setLoading(true);
  clearStatus();

  const height = currentQualities[selectedQualityIdx]?.height ?? null;

  try {
    const response = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, height }),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || `Server error (${response.status})`);
    }

    // Server confirmed; clear the input immediately, keep the preview visible
    urlInput.value = '';

    const filename = filenameFromResponse(response) || 'video.mp4';
    const blob = await readWithProgress(response);

    triggerDownload(blob, filename);
    showStatus('success', 'Download started!');
    setTimeout(resetAll, 3000);
  } catch (err) {
    showStatus('error', err.message);
  } finally {
    setLoading(false);
  }
});

// Also trigger on Enter key in the input
urlInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') downloadBtn.click();
});

// ── Preview ───────────────────────────────────────────────────────────────────

function triggerPreview(url) {
  abortPreview();
  closeQualityMenu();
  previewController = new AbortController();

  fetch('/api/info', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
    signal: previewController.signal,
  })
    .then((r) => (r.ok ? r.json() : Promise.reject()))
    .then((data) => {
      previewTitle.textContent = data.title || '';

      const parts = [];
      if (data.duration != null) parts.push(formatDuration(data.duration));
      if (data.uploader)         parts.push(data.uploader);
      previewMeta.textContent = parts.join(' \u00b7 ');

      renderQualities(data.qualities || []);

      if (data.thumbnail) {
        previewThumb.hidden = false;
        previewThumb.src = data.thumbnail;
        previewThumb.onerror = () => { previewThumb.hidden = true; };
      } else {
        previewThumb.hidden = true;
      }

      previewLoading.hidden = true;
      previewContent.hidden = false;
      previewEl.hidden = false;
    })
    .catch((err) => {
      if (err?.name !== 'AbortError') hidePreview();
    });
}

function abortPreview() {
  previewController?.abort();
  previewController = null;
}

function clearPreviewDebounce() {
  if (previewDebounceTimer) {
    clearTimeout(previewDebounceTimer);
    previewDebounceTimer = null;
  }
}

function hidePreview() {
  clearPreviewDebounce();
  abortPreview();
  previewEl.hidden = true;
  previewLoading.hidden = true;
  previewContent.hidden = true;
  previewThumb.src = '';
}

function resetAll() {
  clearStatus();
  hidePreview();
  renderQualities([]);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function setLoading(on) {
  downloadBtn.disabled = on;
  qualityToggle.disabled = on;
  dlSpinner.hidden = !on;
  dlLabel.textContent = on ? 'Downloading\u2026' : buildDlLabelText();
}

function showLoadingProgress(pct) {
  dlLabel.textContent = `Downloading\u2026 ${pct}%`;
}

async function readWithProgress(response) {
  const total  = parseInt(response.headers.get('Content-Length') || '0', 10);
  const reader = response.body.getReader();
  const chunks = [];
  let received = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.length;
    if (total > 0) showLoadingProgress(Math.round((received / total) * 100));
  }

  return new Blob(chunks);
}

function showStatus(type, msg) {
  statusEl.className = type;
  statusEl.textContent = msg;
}

function clearStatus() {
  statusEl.className = '';
  statusEl.textContent = '';
}

function filenameFromResponse(response) {
  const cd = response.headers.get('Content-Disposition') || '';
  const rfc5987 = cd.match(/filename\*=UTF-8''([^;\n]+)/i);
  if (rfc5987) return decodeURIComponent(rfc5987[1].trim());
  const plain = cd.match(/filename="?([^";\n]+)"?/i);
  if (plain) return plain[1].trim();
  return null;
}

function triggerDownload(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000);
}

function formatDuration(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

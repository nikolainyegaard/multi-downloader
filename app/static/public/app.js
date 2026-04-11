const urlInput       = document.getElementById('url-input');
const pasteBtn       = document.getElementById('paste-btn');
const downloadBtn    = document.getElementById('download-btn');
const statusEl       = document.getElementById('status');
const previewEl      = document.getElementById('preview');
const previewLoading = document.getElementById('preview-loading');
const previewContent = document.getElementById('preview-content');
const previewThumb   = document.getElementById('preview-thumb');
const previewTitle   = document.getElementById('preview-title');
const previewMeta    = document.getElementById('preview-meta');

let previewController = null; // AbortController for in-flight /api/info requests

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

// Native paste (keyboard shortcut / right-click)
urlInput.addEventListener('paste', () => {
  // Let the paste event settle before reading the value
  setTimeout(() => {
    const url = urlInput.value.trim();
    if (url) triggerPreview(url);
  }, 0);
});

// Clear preview when the field is emptied manually
urlInput.addEventListener('input', () => {
  if (!urlInput.value.trim()) hidePreview();
});

// ── Download ──────────────────────────────────────────────────────────────────

downloadBtn.addEventListener('click', async () => {
  const url = urlInput.value.trim();
  if (!url) {
    showStatus('error', 'Enter a URL first');
    urlInput.focus();
    return;
  }

  abortPreview();
  setLoading(true);
  clearStatus();

  try {
    const response = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || `Server error (${response.status})`);
    }

    // Server confirmed; clear the input immediately, keep the preview visible
    urlInput.value = '';

    const filename = filenameFromResponse(response) || 'video.mp4';
    const blob = await response.blob();

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
  previewController = new AbortController();

  previewEl.hidden = false;
  previewLoading.hidden = false;
  previewContent.hidden = true;

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
      previewMeta.textContent = parts.join(' · ');

      if (data.thumbnail) {
        previewThumb.hidden = false;
        previewThumb.src = data.thumbnail;
        previewThumb.onerror = () => { previewThumb.hidden = true; };
      } else {
        previewThumb.hidden = true;
      }

      previewLoading.hidden = true;
      previewContent.hidden = false;
    })
    .catch((err) => {
      if (err?.name !== 'AbortError') hidePreview();
    });
}

function abortPreview() {
  previewController?.abort();
  previewController = null;
}

function hidePreview() {
  abortPreview();
  previewEl.hidden = true;
  previewLoading.hidden = true;
  previewContent.hidden = true;
  previewThumb.src = '';
}

function resetAll() {
  clearStatus();
  hidePreview();
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function setLoading(on) {
  downloadBtn.disabled = on;
  downloadBtn.innerHTML = on
    ? '<span class="spinner"></span> Downloading…'
    : '↓ Download';
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

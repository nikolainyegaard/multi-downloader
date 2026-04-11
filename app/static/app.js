const urlInput    = document.getElementById('url-input');
const pasteBtn    = document.getElementById('paste-btn');
const downloadBtn = document.getElementById('download-btn');
const statusEl    = document.getElementById('status');

// ── Paste ────────────────────────────────────────────────────────────────────

pasteBtn.addEventListener('click', async () => {
  if (!navigator.clipboard?.readText) {
    urlInput.focus();
    showStatus('error', 'Clipboard not available — paste manually');
    return;
  }
  try {
    const text = await navigator.clipboard.readText();
    urlInput.value = text.trim();
    clearStatus();
    urlInput.focus();
  } catch {
    urlInput.focus();
    showStatus('error', 'Could not read clipboard — paste manually');
  }
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

    const filename = filenameFromResponse(response) || 'video.mp4';
    const blob = await response.blob();

    triggerDownload(blob, filename);
    showStatus('success', 'Download started!');
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
  // Try filename*=UTF-8'' (RFC 5987) first, then plain filename=
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
  // Delay revoke so the browser has time to start the download
  setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000);
}

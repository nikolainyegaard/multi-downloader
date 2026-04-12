const form     = document.getElementById('config-form');
const saveBtn  = document.getElementById('save-btn');
const resetBtn = document.getElementById('reset-btn');
const statusEl = document.getElementById('save-status');

async function loadConfig() {
  try {
    const r = await fetch('/api/config');
    if (!r.ok) throw new Error('Failed to load config');
    const cfg = await r.json();
    document.getElementById('site_title').value          = cfg.site_title   ?? '';
    document.getElementById('subtitle').value            = cfg.subtitle     ?? '';
    document.getElementById('accent_color').value        = cfg.accent_color ?? '#3b82f6';
    document.getElementById('show_paste_button').checked = cfg.show_paste_button ?? true;
    document.getElementById('kofi_username').value        = cfg.kofi_username   ?? '';
  } catch (err) {
    showStatus('error', 'Could not load config: ' + err.message);
  }
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  saveBtn.disabled = true;
  clearStatus();

  const cfg = {
    site_title:        document.getElementById('site_title').value,
    subtitle:          document.getElementById('subtitle').value,
    accent_color:      document.getElementById('accent_color').value,
    show_paste_button: document.getElementById('show_paste_button').checked,
    custom_logo:       false,
    kofi_username:     document.getElementById('kofi_username').value.trim(),
  };

  try {
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    });
    if (!r.ok) throw new Error(`Server error (${r.status})`);
    showStatus('success', 'Saved');
  } catch (err) {
    showStatus('error', err.message);
  } finally {
    saveBtn.disabled = false;
  }
});

resetBtn.addEventListener('click', async () => {
  if (!confirm('Reset all settings to defaults?')) return;
  resetBtn.disabled = true;
  clearStatus();

  try {
    const r = await fetch('/api/config/reset', { method: 'POST' });
    if (!r.ok) throw new Error(`Server error (${r.status})`);
    await loadConfig();
    showStatus('success', 'Reset to defaults');
  } catch (err) {
    showStatus('error', err.message);
  } finally {
    resetBtn.disabled = false;
  }
});

function showStatus(type, msg) {
  statusEl.className = type;
  statusEl.textContent = msg;
}

function clearStatus() {
  statusEl.className = '';
  statusEl.textContent = '';
}

loadConfig();

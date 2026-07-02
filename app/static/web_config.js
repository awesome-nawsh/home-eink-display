function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]').content;
}

// Populate the "Display Service" and "Web Panel" status cells from one
// /api/status fetch. main.py rewrites its status file every loop tick (30s
// awake, 300s asleep), so a report older than ~11 minutes means the display
// service is down or hung. The web panel has no such file — if this request
// got a response at all, the panel that served it is up — so its cell is
// just its own uptime, no staleness check needed.
function loadStatusBar() {
    const displayEl = document.getElementById('display-status');
    const webConfigEl = document.getElementById('web-config-status');
    if (!displayEl && !webConfigEl) return;
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            if (displayEl) {
                const d = data.display;
                if (!d || !d.written_at) {
                    displayEl.textContent = 'No status reported yet';
                    displayEl.style.color = '#f59e0b';
                } else {
                    const ageSeconds = (Date.now() - new Date(d.written_at).getTime()) / 1000;
                    if (ageSeconds > 660) {
                        displayEl.textContent = '✗ Stale — service down?';
                        displayEl.style.color = '#ef4444';
                    } else {
                        let text = '✓ Up ' + d.uptime_formatted;
                        if (d.active_screen) text += ' — ' + d.active_screen;
                        displayEl.textContent = text;
                        displayEl.title = 'MQTT ' + (d.mqtt_connected ? 'connected' : 'not connected')
                            + (d.day_type ? ' · day type: ' + d.day_type : '')
                            + ' · ' + d.metrics.display_updates + ' display updates';
                        displayEl.style.color = '#10b981';
                    }
                }
            }
            if (webConfigEl) {
                webConfigEl.textContent = '✓ Up ' + data.web_config.uptime_formatted;
                webConfigEl.style.color = '#10b981';
            }
        })
        .catch(() => {
            if (displayEl) { displayEl.textContent = 'Status unavailable'; displayEl.style.color = '#f59e0b'; }
            if (webConfigEl) { webConfigEl.textContent = 'Status unavailable'; webConfigEl.style.color = '#f59e0b'; }
        });
}

document.addEventListener('DOMContentLoaded', loadStatusBar);

// Live font-sample preview: any select with a "<name>-sample" image below it
// (rendered by the font_sample flag in CONFIG_SCHEMA) re-fetches the
// server-rendered sample when the selection changes.
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.font-sample-img').forEach(img => {
        const select = document.getElementById(img.id.replace(/-sample$/, ''));
        if (!select) return;
        select.addEventListener('change', () => {
            if (select.value) {
                img.src = '/api/font_sample/' + encodeURIComponent(select.value);
                img.parentElement.style.display = '';
            } else {
                img.parentElement.style.display = 'none';
            }
        });
    });
});

// Screen Preview tab: re-fetches /api/preview_image whenever the screen
// choice or a scenario toggle changes. Only 'combined' (bus_train_screen)
// uses all four toggles; 'daytime' only honors weather; 'sleep'/'boot'/
// 'debug' ignore all of them (mirrors tools/preview_render.py's toggles).
const TOGGLE_RELEVANCE = {
    combined: ['disruption', 'no-weather', 'no-journey', 'manual-refresh'],
    daytime: ['no-weather'],
    sleep: [], boot: [], debug: [],
};

function updatePreviewImage() {
    const screenEl = document.getElementById('preview-screen');
    const img = document.getElementById('preview-image');
    if (!screenEl || !img) return;

    const screen = screenEl.value;
    const relevant = TOGGLE_RELEVANCE[screen] || [];
    const params = new URLSearchParams({ screen });
    ['disruption', 'no-weather', 'no-journey', 'manual-refresh'].forEach(name => {
        const el = document.getElementById('preview-' + name);
        if (el) {
            el.disabled = !relevant.includes(name);
            if (el.checked && relevant.includes(name)) params.set(name.replace(/-/g, '_'), '1');
        }
    });
    img.src = '/api/preview_image?' + params.toString();

    const note = document.getElementById('preview-toggle-note');
    if (note) {
        note.textContent = relevant.length
            ? ''
            : 'This screen doesn’t use the toggles above — it always renders the same fixed sample.';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const screenEl = document.getElementById('preview-screen');
    if (!screenEl) return;
    ['preview-screen', 'preview-disruption', 'preview-no-weather', 'preview-no-journey', 'preview-manual-refresh']
        .forEach(id => document.getElementById(id)?.addEventListener('change', updatePreviewImage));
    updatePreviewImage();
});

function triggerRefresh() {
    fetch('/api/refresh', {
        method: 'POST',
        headers: { 'X-CSRF-Token': csrfToken() },
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert('✓ Display refresh triggered!');
            } else {
                alert('✗ Failed to trigger refresh: ' + data.error);
            }
        })
        .catch(error => {
            alert('✗ Error: ' + error);
        });
}

function triggerRestart() {
    if (!confirm('Restart the bus_display service now? This applies any saved .env/schedule changes.')) {
        return;
    }
    fetch('/api/restart', {
        method: 'POST',
        headers: { 'X-CSRF-Token': csrfToken() },
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert('✓ Restart queued — check the status bar in a few seconds to confirm it came back up.');
            } else {
                alert('✗ Failed to restart: ' + data.error);
            }
        })
        .catch(error => {
            alert('✗ Error: ' + error);
        });
}

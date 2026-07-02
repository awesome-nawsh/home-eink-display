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

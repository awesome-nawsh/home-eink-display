function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]').content;
}

// Populate the "Display Service" status cell from /api/status. main.py
// rewrites its status file every loop tick (30s awake, 300s asleep), so a
// report older than ~11 minutes means the display service is down or hung.
function loadDisplayStatus() {
    const el = document.getElementById('display-status');
    if (!el) return;
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            const d = data.display;
            if (!d || !d.written_at) {
                el.textContent = 'No status reported yet';
                el.style.color = '#f59e0b';
                return;
            }
            const ageSeconds = (Date.now() - new Date(d.written_at).getTime()) / 1000;
            if (ageSeconds > 660) {
                el.textContent = '✗ Stale — service down?';
                el.style.color = '#ef4444';
                return;
            }
            let text = '✓ Up ' + d.uptime_formatted;
            if (d.active_screen) text += ' — ' + d.active_screen;
            el.textContent = text;
            el.title = 'MQTT ' + (d.mqtt_connected ? 'connected' : 'not connected')
                + (d.day_type ? ' · day type: ' + d.day_type : '')
                + ' · ' + d.metrics.display_updates + ' display updates';
            el.style.color = '#10b981';
        })
        .catch(() => {
            el.textContent = 'Status unavailable';
            el.style.color = '#f59e0b';
        });
}

document.addEventListener('DOMContentLoaded', loadDisplayStatus);

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
                alert('✓ Service restart triggered!');
            } else {
                alert('✗ Failed to restart: ' + data.error);
            }
        })
        .catch(error => {
            alert('✗ Error: ' + error);
        });
}

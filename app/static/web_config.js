function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]').content;
}

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

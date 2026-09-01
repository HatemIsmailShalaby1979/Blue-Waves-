async function loadDashboard() {
    const response = await fetch('/api/dashboard');
    const data = await response.json();
    document.getElementById('health-status').innerHTML = `
        <div class="stat"><span class="stat-label">Version:</span><span class="stat-value">${data.health.version}</span></div>
        <div class="stat"><span class="stat-label">Ledger:</span><span class="stat-value">${data.health.ledger_intact ? 'Intact' : 'Broken'}</span></div>
        <div class="stat"><span class="stat-label">Queue:</span><span class="stat-value">${data.queue.total}</span></div>
    `;
    document.getElementById('queue-status').innerHTML = `
        <div class="stat"><span class="stat-label">Pending:</span><span class="stat-value">${data.queue.pending}</span></div>
        <div class="stat"><span class="stat-label">Ready:</span><span class="stat-value">${data.queue.ready_to_publish}</span></div>
        <div class="stat"><span class="stat-label">Published:</span><span class="stat-value">${data.queue.published}</span></div>
    `;
    document.getElementById('finance-status').innerHTML = `
        <div class="stat"><span class="stat-label">Weekly:</span><span class="stat-value">$${(data.finance.weekly_costs / 100).toFixed(2)}</span></div>
        <div class="stat"><span class="stat-label">Music:</span><span class="stat-value">$${(data.finance.music_costs / 100).toFixed(2)}</span></div>
        <div class="stat"><span class="stat-label">Podcast:</span><span class="stat-value">$${(data.finance.podcast_costs / 100).toFixed(2)}</span></div>
    `;
}

async function loadApprovals() {
    const response = await fetch('/api/approvals');
    const approvals = await response.json();
    let html = '';
    approvals.forEach(a => {
        html += `<div class="approval-item">
            <h3>${a.type.toUpperCase()}: ${a.title}</h3>
            <button class="btn" onclick="approve('${a.type}', '${a.asset_id}')">Approve</button>
            <button class="btn btn-danger" onclick="reject('${a.type}', '${a.asset_id}')">Reject</button>
        </div>`;
    });
    document.getElementById('approvals').innerHTML = html || '<p>No pending approvals</p>';
}

async function approve(type, assetId) {
    const response = await fetch(`/api/approve/${type}/${assetId}`, { method: 'POST' });
    const result = await response.json();
    document.getElementById('status').innerHTML = `<p>Approved: ${JSON.stringify(result)}</p>`;
    loadApprovals();
}

async function addRequest() {
    const contentType = document.getElementById('content-type').value;
    const topic = document.getElementById('topic').value;
    const priority = document.getElementById('priority').value;
    const quality = document.getElementById('quality').value;
    const response = await fetch('/api/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content_type: contentType, topic, priority, quality })
    });
    const result = await response.json();
    document.getElementById('status').innerHTML = `<p>Request added: ${JSON.stringify(result)}</p>`;
}

loadDashboard();
loadApprovals();
setInterval(loadDashboard, 30000);

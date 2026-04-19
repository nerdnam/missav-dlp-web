let currentVideoInfo = null;

function formatSize(bytes) {
    if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + ' GB';
    if (bytes >= 1e6) return (bytes / 1e6).toFixed(1) + ' MB';
    if (bytes >= 1e3) return (bytes / 1e3).toFixed(1) + ' KB';
    return bytes + ' B';
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

async function fetchTasks() {
    try {
        const res = await fetch('/api/tasks');
        const tasks = await res.json();
        const statsRes = await fetch('/api/queue/stats');
        const stats = await statsRes.json();
        
        document.getElementById('stats').innerHTML = `
            <span class="stat">⏳ Waiting: ${stats.waiting}</span>
            <span class="stat">⬇ Downloading: ${stats.downloading}</span>
            <span class="stat">✅ Completed: ${stats.completed}</span>
            <span class="stat">❌ Failed: ${stats.failed}</span>
        `;
        
        const listEl = document.getElementById('taskList');
        const entries = Object.entries(tasks);
        if (entries.length === 0) {
            listEl.innerHTML = '<div style="text-align:center; padding:20px;">No downloads</div>';
            return;
        }
        
        listEl.innerHTML = entries.reverse().map(([id, t]) => {
            let cls = '';
            if (t.status === 'Completed') cls = 'completed';
            else if (t.status && t.status.startsWith('Error')) cls = 'error';
            else if (t.status === 'Downloading') cls = 'downloading';
            
            const progress = t.progress || 0;
            const stage = t.stage || '';
            const title = t.filename || (t.url ? t.url.substring(0, 50) : 'Unknown');
            
            return `
                <div class="task-card ${cls}">
                    <div class="task-top">
                        <div style="flex:1">
                            <strong>${escapeHtml(title)}</strong>
                            <div style="font-size:12px; opacity:0.8">${t.status} ${stage ? `- ${stage}` : ''}</div>
                        </div>
                        <button onclick="deleteTask('${id}')" class="btn-danger" style="padding:5px 10px">✕</button>
                    </div>
                    ${t.status === 'Downloading' ? `
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${progress}%"></div>
                        </div>
                        <div style="font-size:12px; margin-top:5px">${progress}%</div>
                    ` : ''}
                </div>
            `;
        }).join('');
    } catch(e) { console.error(e); }
}

async function deleteTask(id) {
    await fetch(`/api/tasks/${id}`, { method: 'DELETE' });
    fetchTasks();
}

async function fetchFiles() {
    try {
        const res = await fetch('/api/files');
        const files = await res.json();
        const search = document.getElementById('fileSearch').value.toLowerCase();
        const filtered = files.filter(f => f.name.toLowerCase().includes(search));
        
        const listEl = document.getElementById('fileList');
        if (filtered.length === 0) {
            listEl.innerHTML = '<div style="text-align:center; padding:20px;">No files</div>';
            return;
        }
        
        listEl.innerHTML = filtered.map(f => `
            <div class="file-card">
                <span>🎬 ${escapeHtml(f.name)}</span>
                <div>
                    <span style="margin-right:15px">${formatSize(f.size)}</span>
                    <a href="/api/files/${encodeURIComponent(f.name)}/download" download style="color:#00d9ff; margin-right:10px">⬇ Download</a>
                    <button onclick="deleteFile('${encodeURIComponent(f.name)}')" class="btn-danger" style="padding:5px 10px">Delete</button>
                </div>
            </div>
        `).join('');
    } catch(e) { console.error(e); }
}

async function deleteFile(name) {
    if (confirm('Delete this file?')) {
        await fetch(`/api/files/${name}`, { method: 'DELETE' });
        fetchFiles();
    }
}

// Get Info
document.getElementById('getInfoBtn').onclick = async () => {
    const url = document.getElementById('urlInput').value.trim();
    if (!url) { alert('Enter URL or JAV code'); return; }
    
    document.getElementById('getInfoBtn').disabled = true;
    document.getElementById('getInfoBtn').textContent = 'Loading...';
    
    try {
        const res = await fetch('/api/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        const data = await res.json();
        if (data.status !== 'success') {
            alert('Failed: ' + (data.message || 'Unknown error'));
            return;
        }
        
        currentVideoInfo = data.info;
        document.getElementById('videoTitle').innerText = currentVideoInfo.title || '-';
        document.getElementById('videoCode').innerText = currentVideoInfo.id || '-';
        document.getElementById('videoDuration').innerText = currentVideoInfo.duration_string || '-';
        
        const warning = document.getElementById('previewWarning');
        if (currentVideoInfo.is_preview) {
            warning.classList.remove('hidden');
        } else {
            warning.classList.add('hidden');
        }
        
        const qualitySelect = document.getElementById('qualitySelect');
        qualitySelect.innerHTML = '';
        if (currentVideoInfo.formats && currentVideoInfo.formats.length > 0) {
            currentVideoInfo.formats.forEach(f => {
                const option = document.createElement('option');
                option.value = f.format_id;
                option.textContent = `${f.resolution}${f.filesize ? ` (${formatSize(f.filesize)})` : ''}`;
                qualitySelect.appendChild(option);
            });
        } else {
            qualitySelect.innerHTML = '<option value="best">Best Quality</option>';
        }
        
        document.getElementById('infoCard').style.display = 'block';
    } catch(e) { alert('Error: ' + e.message); }
    finally {
        document.getElementById('getInfoBtn').disabled = false;
        document.getElementById('getInfoBtn').textContent = '🔍 Get Info';
    }
};

// Download Now
document.getElementById('downloadBtn').onclick = async () => {
    if (!currentVideoInfo) return;
    const format = document.getElementById('qualitySelect').value;
    await fetch('/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: currentVideoInfo.url, format })
    });
    fetchTasks();
    alert('Added to queue');
};

// Add to Queue
document.getElementById('addQueueBtn').onclick = async () => {
    if (!currentVideoInfo) return;
    const format = document.getElementById('qualitySelect').value;
    await fetch('/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: currentVideoInfo.url, format })
    });
    fetchTasks();
    alert('Added to queue');
};

// Batch
document.getElementById('batchBtn').onclick = () => {
    document.getElementById('batchPanel').classList.toggle('hidden');
};

document.getElementById('cancelBatchBtn').onclick = () => {
    document.getElementById('batchPanel').classList.add('hidden');
    document.getElementById('batchUrls').value = '';
};

document.getElementById('addBatchBtn').onclick = async () => {
    const text = document.getElementById('batchUrls').value;
    const urls = text.split('\n').filter(l => l.trim());
    if (urls.length === 0) return;
    
    const res = await fetch('/api/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ urls })
    });
    const data = await res.json();
    alert(`Added ${data.count} videos to queue`);
    document.getElementById('batchPanel').classList.add('hidden');
    document.getElementById('batchUrls').value = '';
    fetchTasks();
};

// Queue controls
document.getElementById('cleanBtn').onclick = async () => {
    await fetch('/api/queue/clean', { method: 'POST' });
    fetchTasks();
};

document.getElementById('clearBtn').onclick = async () => {
    if (confirm('Clear all waiting tasks?')) {
        await fetch('/api/queue/clear', { method: 'POST' });
        fetchTasks();
    }
};

// Settings Modal
const modal = document.getElementById('settingsModal');

document.getElementById('settingsBtn').onclick = async () => {
    try {
        const res = await fetch('/api/settings');
        if (!res.ok) throw new Error('Failed to load settings');
        const settings = await res.json();
        
        document.getElementById('settingsDownloadDir').value = settings.download_dir || './downloads';
        document.getElementById('settingsSequentialMode').checked = settings.sequential_mode !== false;
        document.getElementById('settingsDelay').value = settings.delay_between_downloads || 3;
        document.getElementById('settingsQuality').value = settings.video_quality || 'best';
        
        const mirrors = settings.mirrors || ['missav.ai', 'missav.net', 'missav123.com', 'missav.com', 'missav.ws'];
        document.getElementById('settingsMirrors').value = mirrors.join('\n');
        
        modal.style.display = 'flex';
    } catch(e) {
        console.error('Settings load error:', e);
        // Load defaults if API fails
        document.getElementById('settingsDownloadDir').value = './downloads';
        document.getElementById('settingsSequentialMode').checked = true;
        document.getElementById('settingsDelay').value = 3;
        document.getElementById('settingsQuality').value = 'best';
        document.getElementById('settingsMirrors').value = 'missav.ai\nmissav.net\nmissav123.com\nmissav.com\nmissav.ws';
        modal.style.display = 'flex';
    }
};

document.getElementById('closeSettingsBtn').onclick = () => {
    modal.style.display = 'none';
};

document.getElementById('saveSettingsBtn').onclick = async () => {
    try {
        const settings = {
            download_dir: document.getElementById('settingsDownloadDir').value,
            sequential_mode: document.getElementById('settingsSequentialMode').checked,
            delay_between_downloads: parseInt(document.getElementById('settingsDelay').value),
            video_quality: document.getElementById('settingsQuality').value,
            mirrors: document.getElementById('settingsMirrors').value.split('\n').filter(l => l.trim())
        };
        await fetch('/api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        modal.style.display = 'none';
        alert('Settings saved');
    } catch(e) {
        alert('Failed to save settings: ' + e.message);
    }
};

// Close modal when clicking outside
window.onclick = function(event) {
    if (event.target === modal) {
        modal.style.display = 'none';
    }
};

// Search
document.getElementById('fileSearch').addEventListener('input', fetchFiles);

// Auto refresh
setInterval(fetchTasks, 1500);
setInterval(fetchFiles, 5000);

// Initial load
fetchTasks();
fetchFiles();
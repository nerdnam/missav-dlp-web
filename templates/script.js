let currentVideoInfo = null;
let cachedSettings = null;
let currentTranslations = {};

// Translation function
function _(key, params = {}) {
    let text = currentTranslations[key] || key;
    // Replace parameters like {count}
    Object.keys(params).forEach(param => {
        text = text.replace(`{${param}}`, params[param]);
    });
    return text;
}

// Update all i18n elements on the page
function updatePageLanguage() {
    // Update elements with data-i18n attribute
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        el.textContent = _(key);
    });
    
    // Update placeholders
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        const key = el.getAttribute('data-i18n-placeholder');
        el.placeholder = _(key);
    });
    
    // Update document title
    document.title = _('app_title');
}

// Load language
async function loadLanguage(lang) {
    try {
        const res = await fetch('/api/language', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ language: lang })
        });
        const data = await res.json();
        
        if (data.status === 'success') {
            // Get translations
            const transRes = await fetch('/api/language');
            const transData = await transRes.json();
            currentTranslations = transData.translations;
            updatePageLanguage();
            
            // Refresh UI text that might have been dynamically generated
            fetchTasks();
            fetchFiles();
            
            // Update stats labels
            updateStatsLabels();
        }
    } catch(e) {
        console.error('Failed to load language:', e);
    }
}

// Format functions
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

function updateStatsLabels() {
    // This will be called when stats are refreshed
}

async function fetchTasks() {
    try {
        const res = await fetch('/api/tasks');
        const tasks = await res.json();
        const statsRes = await fetch('/api/queue/stats');
        const stats = await statsRes.json();
        
        document.getElementById('stats').innerHTML = `
            <span class="stat">⏳ ${_('waiting')}: ${stats.waiting}</span>
            <span class="stat">⬇ ${_('downloading')}: ${stats.downloading}</span>
            <span class="stat">✅ ${_('completed')}: ${stats.completed}</span>
            <span class="stat">❌ ${_('failed')}: ${stats.failed}</span>
        `;
        
        const listEl = document.getElementById('taskList');
        const entries = Object.entries(tasks);
        if (entries.length === 0) {
            listEl.innerHTML = `<div style="text-align:center; padding:20px;">${_('no_downloads')}</div>`;
            return;
        }
        
        listEl.innerHTML = entries.reverse().map(([id, t]) => {
            let cls = '';
            let statusText = '';
            if (t.status === 'Completed') {
                cls = 'completed';
                statusText = _('completed');
            } else if (t.status && t.status.startsWith('Error')) {
                cls = 'error';
                statusText = _('failed');
            } else if (t.status === 'Downloading') {
                cls = 'downloading';
                statusText = _('downloading');
            } else {
                statusText = t.status;
            }
            
            const progress = t.progress || 0;
            const stage = t.stage || '';
            const title = t.filename || (t.url ? t.url.substring(0, 50) : 'Unknown');
            
            return `
                <div class="task-card ${cls}">
                    <div class="task-top">
                        <div style="flex:1">
                            <strong>${escapeHtml(title)}</strong>
                            <div style="font-size:12px; opacity:0.8">${statusText} ${stage ? `- ${stage}` : ''}</div>
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
    if (confirm(_('task_cancelled'))) {
        await fetch(`/api/tasks/${id}`, { method: 'DELETE' });
        fetchTasks();
    }
}

async function fetchFiles() {
    try {
        const res = await fetch('/api/files');
        const files = await res.json();
        const search = document.getElementById('fileSearch').value.toLowerCase();
        const filtered = files.filter(f => f.name.toLowerCase().includes(search));
        
        const listEl = document.getElementById('fileList');
        if (filtered.length === 0) {
            listEl.innerHTML = `<div style="text-align:center; padding:20px;">${_('no_files')}</div>`;
            return;
        }
        
        listEl.innerHTML = filtered.map(f => `
            <div class="file-card">
                <span>🎬 ${escapeHtml(f.name)}</span>
                <div>
                    <span style="margin-right:15px">${formatSize(f.size)}</span>
                    <a href="/api/files/${encodeURIComponent(f.name)}/download" download style="color:#00d9ff; margin-right:10px">⬇ ${_('downloads')}</a>
                    <button onclick="deleteFile('${encodeURIComponent(f.name)}')" class="btn-danger" style="padding:5px 10px">${_('delete')}</button>
                </div>
            </div>
        `).join('');
    } catch(e) { console.error(e); }
}

async function deleteFile(name) {
    if (confirm(_('delete_file_confirm'))) {
        await fetch(`/api/files/${name}`, { method: 'DELETE' });
        fetchFiles();
    }
}

// Get Info
document.getElementById('getInfoBtn').onclick = async () => {
    const url = document.getElementById('urlInput').value.trim();
    if (!url) { alert(_('enter_url_or_code')); return; }
    
    document.getElementById('getInfoBtn').disabled = true;
    document.getElementById('getInfoBtn').innerHTML = `🔍 ${_('loading')}`;
    
    try {
        const res = await fetch('/api/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        const data = await res.json();
        if (data.status !== 'success') {
            alert(_('failed_get_info') + ': ' + (data.message || 'Unknown error'));
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
        document.getElementById('getInfoBtn').innerHTML = `🔍 ${_('get_info')}`;
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
    alert(_('added_to_queue'));
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
    alert(_('added_to_queue'));
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
    alert(_('batch_added', { count: data.count }));
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
    if (confirm(_('clear_waiting_confirm'))) {
        await fetch('/api/queue/clear', { method: 'POST' });
        fetchTasks();
    }
};

// Settings Modal
const modal = document.getElementById('settingsModal');

function populateSettingsForm(settings) {
    document.getElementById('settingsDownloadDir').value = settings.download_dir || './downloads';
    document.getElementById('settingsSequentialMode').checked = settings.sequential_mode !== false;
    document.getElementById('settingsDelay').value = settings.delay_between_downloads || 3;
    document.getElementById('settingsQuality').value = settings.video_quality || 'best';
    
    const mirrors = settings.mirrors || ['missav.ai', 'missav.net', 'missav123.com', 'missav.com', 'missav.ws'];
    document.getElementById('settingsMirrors').value = mirrors.join('\n');
}

// Pre-load settings in background
async function preloadSettings() {
    try {
        const res = await fetch('/api/settings');
        if (res.ok) {
            cachedSettings = await res.json();
        }
    } catch(e) {
        console.error('Failed to preload settings:', e);
    }
}

// Get current language and load translations
async function initLanguage() {
    try {
        const res = await fetch('/api/language');
        const data = await res.json();
        currentTranslations = data.translations;
        updatePageLanguage();
        
        // Set language select to current
        const langSelect = document.getElementById('languageSelect');
        langSelect.value = data.current;
    } catch(e) {
        console.error('Failed to load initial language:', e);
    }
}

// Language selector
document.getElementById('languageSelect').onchange = async (e) => {
    const lang = e.target.value;
    await loadLanguage(lang);
};

// Settings button handler
document.getElementById('settingsBtn').onclick = async () => {
    modal.style.display = 'flex';
    
    if (cachedSettings) {
        populateSettingsForm(cachedSettings);
    } else {
        const saveBtn = document.getElementById('saveSettingsBtn');
        const originalText = saveBtn.innerHTML;
        saveBtn.innerHTML = _('loading');
        saveBtn.disabled = true;
        
        try {
            const res = await fetch('/api/settings');
            if (!res.ok) throw new Error('Failed to load settings');
            const settings = await res.json();
            cachedSettings = settings;
            populateSettingsForm(settings);
        } catch(e) {
            console.error('Settings load error:', e);
            const defaultSettings = {
                download_dir: './downloads',
                sequential_mode: true,
                delay_between_downloads: 3,
                video_quality: 'best',
                mirrors: ['missav.ai', 'missav.net', 'missav123.com', 'missav.com', 'missav.ws']
            };
            populateSettingsForm(defaultSettings);
        } finally {
            saveBtn.innerHTML = originalText;
            saveBtn.disabled = false;
        }
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
        
        const res = await fetch('/api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        
        if (res.ok) {
            cachedSettings = settings;
            modal.style.display = 'none';
            alert(_('settings_saved'));
        } else {
            throw new Error('Failed to save');
        }
    } catch(e) {
        alert(_('error') + ': ' + e.message);
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
initLanguage();
preloadSettings();
fetchTasks();
fetchFiles();
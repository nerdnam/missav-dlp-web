import os
import json
import subprocess
import time
import threading
import queue
import uuid
import re
import logging
from datetime import datetime
from urllib.parse import urlparse
from flask import Flask, request, render_template, jsonify, send_file, Response
import yt_dlp
from yt_dlp.extractor.common import InfoExtractor
from curl_cffi import requests as cffi_requests

# ============================================================
# CONFIGURATION MANAGEMENT (No hardcoded paths)
# ============================================================

# Get the directory where app.py is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Settings file is now in the SAME folder as app.py (not inside downloads)
SETTINGS_FILE = os.path.join(BASE_DIR, '.settings.json')

# Default settings (download_dir can be changed by user)
DEFAULT_SETTINGS = {
    'max_concurrent': 1,  # Changed to 1 for sequential by default
    'filename_template': '[%(id)s] %(title).60s.%(ext)s',
    'spoofdpi_enabled': True,
    'video_quality': 'best',
    'mirrors': ['missav.ai', 'missav.net', 'missav123.com', 'missav.com', 'missav.ws'],
    'download_dir': os.path.join(BASE_DIR, 'downloads'),  # Configurable!
    'delay_between_downloads': 3,
    'max_retries': 3,
    'sequential_mode': True
}

def load_settings():
    """Load settings from .settings.json in project root"""
    global DOWNLOAD_DIR
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
                merged = {**DEFAULT_SETTINGS, **saved}
        else:
            merged = DEFAULT_SETTINGS.copy()
        
        # Set DOWNLOAD_DIR from settings
        DOWNLOAD_DIR = merged.get('download_dir', DEFAULT_SETTINGS['download_dir'])
        
        # Create download directory if it doesn't exist
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        
        return merged
    except Exception as e:
        print(f"Error loading settings: {e}")
        DOWNLOAD_DIR = DEFAULT_SETTINGS['download_dir']
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    """Save settings to .settings.json in project root"""
    global DOWNLOAD_DIR
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    # Update DOWNLOAD_DIR after saving
    DOWNLOAD_DIR = settings.get('download_dir', DEFAULT_SETTINGS['download_dir'])
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Load settings at startup
settings = load_settings()

# ============================================================
# FFMPEG SETUP (for local ffmpeg/bin folder)
# ============================================================

def get_ffmpeg_path():
    """Find ffmpeg in local ffmpeg/bin folder or system PATH"""
    local_ffmpeg = os.path.join(BASE_DIR, 'ffmpeg', 'bin', 'ffmpeg.exe')
    if os.path.exists(local_ffmpeg):
        return local_ffmpeg
    return 'ffmpeg'

FFMPEG_PATH = get_ffmpeg_path()
print(f"[FFmpeg] Using: {FFMPEG_PATH}")

# ============================================================
# SPOOFDPI SETUP
# ============================================================

SPOOFDPI_PORT = 8080
SPOOFDPI_PROXY = f"http://127.0.0.1:{SPOOFDPI_PORT}"

def start_spoofdpi():
    base_dir = BASE_DIR
    if os.path.exists(os.path.join(base_dir, 'spoofdpi.exe')):
        default_bin = os.path.join(base_dir, 'spoofdpi.exe')
    elif os.path.exists(os.path.join(base_dir, 'spoofdpi')):
        default_bin = os.path.join(base_dir, 'spoofdpi')
    else:
        default_bin = 'spoofdpi'
    
    spoofdpi_bin = os.environ.get('SPOOFDPI_PATH', default_bin)
    try:
        proc = subprocess.Popen(
            [spoofdpi_bin],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        time.sleep(2)
        if proc.poll() is None:
            print(f"[System] SpoofDPI started (Port: {SPOOFDPI_PORT})", flush=True)
        else:
            print(f"[System] SpoofDPI failed to start", flush=True)
    except FileNotFoundError:
        print(f"[System] SpoofDPI not found at '{spoofdpi_bin}'", flush=True)

start_spoofdpi()

# ============================================================
# FLASK APP SETUP
# ============================================================

app = Flask(__name__, static_folder='templates', static_url_path='/static')

# Queue and task management
download_queue = queue.Queue()
tasks = {}
active_downloads = 0
queue_lock = threading.Lock()

# Create logs directory
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

class DownloadCancelled(Exception):
    pass

# ============================================================
# JAV CODE HELPERS
# ============================================================

def jav_code_to_url(code):
    """Convert JAV code to full URL"""
    code = code.strip().upper()
    jav_pattern = re.compile(r'^([A-Z]{2,5})-(\d{3,5})$')
    if jav_pattern.match(code):
        mirror = settings.get('mirrors', ['missav.ws'])[0]
        return f"https://{mirror}/ko/{code}"
    return None

def is_jav_code(text):
    """Check if text looks like a JAV code"""
    return bool(re.match(r'^([A-Z]{2,5})-(\d{3,5})$', text.strip().upper()))

# ============================================================
# VIDEO INFO (Get resolution + duration without downloading)
# ============================================================

def get_video_info(url):
    """Fetch video information (resolutions, duration) without downloading"""
    try:
        # Convert JAV code to URL if needed
        if is_jav_code(url):
            url = jav_code_to_url(url)
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.add_info_extractor(MyCustomMissAV())
            ydl.add_default_info_extractors()
            info = ydl.extract_info(url, download=False)
            
            formats = []
            for f in info.get('formats', []):
                height = f.get('height')
                if height:
                    formats.append({
                        'format_id': f.get('format_id'),
                        'resolution': f"{height}p",
                        'height': height,
                        'ext': f.get('ext'),
                        'filesize': f.get('filesize'),
                        'vcodec': f.get('vcodec'),
                        'acodec': f.get('acodec')
                    })
            
            # Remove duplicates, keep highest quality per resolution
            unique_formats = {}
            for f in formats:
                height = f['height']
                if height not in unique_formats:
                    unique_formats[height] = f
            
            duration = info.get('duration')
            is_preview = duration and duration < 600  # Less than 10 minutes = preview
            
            return {
                'id': info.get('id'),
                'title': info.get('title'),
                'duration': duration,
                'duration_string': format_duration(duration),
                'thumbnail': info.get('thumbnail'),
                'formats': sorted(unique_formats.values(), key=lambda x: x['height'], reverse=True),
                'is_preview': is_preview,
                'url': url
            }
    except Exception as e:
        print(f"Error getting video info: {e}")
        return None

def format_duration(seconds):
    if not seconds:
        return "Unknown"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

# ============================================================
# CUSTOM MISS AV EXTRACTOR (Your existing code)
# ============================================================

class MyCustomMissAV(InfoExtractor):
    IE_NAME = 'custom_missav'
    _VALID_URL = r'https?://(?:[^/]+\.)?missav\.[^/]+/(?:[^/]+/)?(?P<id>[^/?#]+)'

    def _real_extract(self, url):
        video_id = self._match_id(url)
        print(f'🔥 [Logic Start] Target: {url}', flush=True)

        parsed_url = urlparse(url)
        path = parsed_url.path
        mirrors = [parsed_url.netloc] + settings.get('mirrors', DEFAULT_SETTINGS['mirrors'])
        mirrors = list(dict.fromkeys(mirrors))

        webpage = None
        used_url = url

        for mirror in mirrors:
            test_url = f"https://{mirror}{path}"
            proxy_list = [SPOOFDPI_PROXY, None] if settings.get('spoofdpi_enabled', True) else [None]
            for proxy in proxy_list:
                try:
                    proxies = {"https": proxy, "http": proxy} if proxy else None
                    res = cffi_requests.get(
                        test_url,
                        impersonate="chrome110",
                        timeout=20,
                        proxies=proxies
                    )
                    if res.status_code == 200 and ('seek' in res.text or 'm3u8' in res.text):
                        webpage = res.text
                        used_url = test_url
                        print(f'✅ Page connected: {mirror} (proxy={proxy})', flush=True)
                        break
                except Exception as e:
                    print(f'⚠️ Failed: {mirror} (proxy={proxy}): {e}', flush=True)
                    continue
            if webpage:
                break

        if not webpage:
            raise ValueError("Failed to load page source (Cloudflare block suspected)")

        video_uuid = None
        script_contents = re.findall(r'<script[^>]*>(.*?)</script>', webpage, re.DOTALL)
        print(f'[UUID] Script tags: {len(script_contents)}', flush=True)

        for idx, script_content in enumerate(script_contents):
            seek_index = script_content.find('seek')
            if seek_index != -1 and seek_index >= 38:
                candidate = script_content[seek_index - 38: seek_index - 2]
                if re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', candidate):
                    video_uuid = candidate
                    print(f'✅ UUID found (script #{idx+1}): {video_uuid}', flush=True)
                    break

        if not video_uuid:
            seek_idx = webpage.find('seek')
            while seek_idx != -1:
                if seek_idx >= 38:
                    candidate = webpage[seek_idx - 38: seek_idx - 2]
                    if re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', candidate):
                        video_uuid = candidate
                        print(f'✅ UUID fallback: {video_uuid}', flush=True)
                        break
                seek_idx = webpage.find('seek', seek_idx + 1)

        if not video_uuid:
            uuid_match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', webpage)
            if uuid_match:
                video_uuid = uuid_match.group(1)
                print(f'✅ UUID regex: {video_uuid}', flush=True)

        if not video_uuid:
            raise ValueError("Video UUID not found")

        master_url = f"https://surrit.com/{video_uuid}/playlist.m3u8"
        print(f'🔗 Master m3u8: {master_url}', flush=True)

        final_formats = []
        try:
            m_res = cffi_requests.get(
                master_url,
                impersonate="chrome110",
                timeout=15,
                headers={
                    'Referer': used_url,
                    'Origin': f"https://{urlparse(used_url).netloc}",
                }
            )
            lines = m_res.text.split('\n')
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                quality_label = line.split('/')[0]
                quality_url = f"https://surrit.com/{video_uuid}/{line}"
                height = None
                try:
                    height = int(re.search(r'(\d+)', quality_label).group(1))
                except:
                    pass
                final_formats.append({
                    'url': quality_url,
                    'ext': 'mp4',
                    'format_id': f'hls-{quality_label}',
                    'height': height,
                    'quality': height or 0,
                    'protocol': 'm3u8_native',
                    'http_headers': {
                        'Referer': used_url,
                        'Origin': f"https://{urlparse(used_url).netloc}",
                    }
                })
        except Exception as e:
            print(f"⚠️ Failed to extract quality list: {e}", flush=True)

        if not final_formats:
            final_formats = self._extract_m3u8_formats(
                master_url, video_id, 'mp4', m3u8_id='hls',
                headers={
                    'Referer': used_url,
                    'Origin': f"https://{urlparse(used_url).netloc}",
                }
            )

        final_formats.sort(key=lambda x: x.get('quality', 0) or x.get('height', 0) or 0, reverse=True)
        title = self._og_search_title(webpage, default=video_id)

        return {
            'id': video_id,
            'title': title,
            'formats': final_formats,
            'age_limit': 18,
        }

# ============================================================
# DOWNLOAD FUNCTION (with per-task logging)
# ============================================================

def setup_task_logger(task_id):
    """Create a logger for a specific download task"""
    log_file = os.path.join(LOGS_DIR, f'task_{task_id}.log')
    logger = logging.getLogger(f'task_{task_id}')
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # File handler
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    
    return logger, log_file

def download_video(task_id, url, selected_format=None):
    """Download video with progress tracking and per-task logging"""
    task_logger, log_file = setup_task_logger(task_id)
    task_logger.info(f"Starting download for: {url}")
    
    # Update task with log file path
    if task_id in tasks:
        tasks[task_id]['log_file'] = log_file
        tasks[task_id]['stage'] = 'Starting'
    
    def progress_hook(d):
        if task_id not in tasks:
            raise DownloadCancelled("Cancelled")
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%')
            p_clean = re.sub(r'\x1b[^m]*m', '', p).strip()
            tasks[task_id]['progress'] = p_clean
            tasks[task_id]['stage'] = 'Downloading'
            task_logger.info(f"Progress: {p_clean}")
        elif d['status'] == 'finished':
            tasks[task_id]['progress'] = '100%'
            tasks[task_id]['stage'] = 'Merging'
            task_logger.info("Download finished, merging...")

    tmpl = settings.get('filename_template', DEFAULT_SETTINGS['filename_template'])
    
    # Use selected format or default quality
    if selected_format:
        format_selector = selected_format
    else:
        quality = settings.get('video_quality', 'best')
        if quality == 'best':
            format_selector = 'bestvideo+bestaudio/best'
        elif quality == '1080p':
            format_selector = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'
        elif quality == '720p':
            format_selector = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
        else:
            format_selector = 'bestvideo+bestaudio/best'
    
    task_logger.info(f"Format selector: {format_selector}")
    
    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_DIR, tmpl),
        'format': format_selector,
        'merge_output_format': 'mp4',
        'proxy': None,
        'quiet': False,
        'noprogress': True,
        'progress_hooks': [progress_hook],
        'ffmpeg_location': FFMPEG_PATH,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://missav.ws/',
            'Origin': 'https://missav.ws',
        },
        'extractor_args': {'generic': ['impersonate']},
        'hls_prefer_native': True,
        'concurrent_fragment_downloads': 5,
    }
    
    try:
        task_logger.info(f"Starting yt-dlp download")
        with yt_dlp.YoutubeDL(ydl_opts, auto_init=False) as ydl:
            ydl.add_info_extractor(MyCustomMissAV())
            ydl.add_default_info_extractors()
            ydl.download([url])
        
        if task_id in tasks:
            tasks[task_id]['status'] = 'Completed'
            tasks[task_id]['stage'] = 'Complete'
            task_logger.info("Download completed successfully")
            
            # Find the downloaded file to get size
            for f in os.listdir(DOWNLOAD_DIR):
                if task_id in f or (tasks[task_id].get('url') and tasks[task_id]['url'].split('/')[-1] in f):
                    fp = os.path.join(DOWNLOAD_DIR, f)
                    tasks[task_id]['filename'] = f
                    tasks[task_id]['filesize'] = os.path.getsize(fp)
                    break
                    
    except DownloadCancelled:
        if task_id in tasks:
            tasks[task_id]['status'] = 'Cancelled'
            tasks[task_id]['stage'] = 'Cancelled'
        task_logger.warning("Download cancelled by user")
    except Exception as e:
        error_msg = str(e)[:200]
        task_logger.error(f"Download failed: {error_msg}")
        if task_id in tasks:
            tasks[task_id]['status'] = f'Error: {error_msg}'
            tasks[task_id]['stage'] = 'Failed'

# ============================================================
# WORKER (Sequential mode support)
# ============================================================

def worker():
    """Worker thread that processes downloads from queue"""
    global active_downloads
    
    while True:
        task_id = download_queue.get()
        if task_id is None:
            break
        
        with queue_lock:
            active_downloads += 1
        
        if task_id in tasks:
            tasks[task_id]['status'] = 'Downloading'
            tasks[task_id]['stage'] = 'Initializing'
            download_video(task_id, tasks[task_id]['url'], tasks[task_id].get('selected_format'))
        
        with queue_lock:
            active_downloads -= 1
        
        # Delay between downloads if sequential mode is on
        if settings.get('sequential_mode', True):
            delay = settings.get('delay_between_downloads', 3)
            time.sleep(delay)
        
        download_queue.task_done()

# Start workers (respects max_concurrent setting)
def start_workers():
    for _ in range(settings.get('max_concurrent', 1)):
        t = threading.Thread(target=worker, daemon=True)
        t.start()

start_workers()

# ============================================================
# API ROUTES
# ============================================================

@app.route('/')
def index():
    return render_template('index.html')

# --- Download endpoints ---
@app.route('/download', methods=['POST'])
def handle_download():
    """Add a single download to queue"""
    url = request.form.get('url', '').strip()
    selected_format = request.form.get('format', None)
    
    if not url:
        return jsonify({"status": "error", "message": "URL required"}), 400
    
    # Convert JAV code to URL if needed
    if is_jav_code(url):
        url = jav_code_to_url(url)
    
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        'url': url,
        'status': 'Waiting',
        'progress': '0%',
        'stage': 'Queued',
        'selected_format': selected_format,
        'created_at': time.time()
    }
    download_queue.put(task_id)
    
    return jsonify({"status": "success", "task_id": task_id, "message": "Added to queue"})

@app.route('/batch-download', methods=['POST'])
def handle_batch_download():
    """Add multiple downloads to queue"""
    data = request.json
    urls = data.get('urls', [])
    
    if not urls:
        return jsonify({"status": "error", "message": "No URLs provided"}), 400
    
    task_ids = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        
        if is_jav_code(url):
            url = jav_code_to_url(url)
        
        task_id = str(uuid.uuid4())
        tasks[task_id] = {
            'url': url,
            'status': 'Waiting',
            'progress': '0%',
            'stage': 'Queued',
            'created_at': time.time()
        }
        download_queue.put(task_id)
        task_ids.append(task_id)
    
    return jsonify({"status": "success", "task_ids": task_ids, "count": len(task_ids)})

@app.route('/api/info', methods=['POST'])
def get_info():
    """Get video information (resolutions, duration) without downloading"""
    data = request.json
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({"status": "error", "message": "URL required"}), 400
    
    info = get_video_info(url)
    if info:
        return jsonify({"status": "success", "info": info})
    else:
        return jsonify({"status": "error", "message": "Failed to get video info"}), 500

# --- Queue management endpoints ---
@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    return jsonify(tasks)

@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    if task_id in tasks:
        del tasks[task_id]
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404

@app.route('/api/queue/clear', methods=['DELETE'])
def clear_queue():
    """Clear all waiting tasks (not active downloads)"""
    global download_queue
    cleared = []
    
    # Create new queue
    new_queue = queue.Queue()
    
    # Keep only active downloads
    for task_id, task in list(tasks.items()):
        if task['status'] == 'Downloading':
            new_queue.put(task_id)
        else:
            cleared.append(task_id)
            del tasks[task_id]
    
    download_queue = new_queue
    return jsonify({"status": "success", "cleared": len(cleared)})

@app.route('/api/queue/clean', methods=['DELETE'])
def clean_queue():
    """Remove completed and failed tasks"""
    cleaned = []
    for task_id, task in list(tasks.items()):
        if task['status'] in ['Completed', 'Cancelled'] or task['status'].startswith('Error'):
            cleaned.append(task_id)
            del tasks[task_id]
    return jsonify({"status": "success", "cleaned": len(cleaned)})

@app.route('/api/queue/stats', methods=['GET'])
def queue_stats():
    """Get queue statistics"""
    waiting = sum(1 for t in tasks.values() if t['status'] == 'Waiting')
    downloading = sum(1 for t in tasks.values() if t['status'] == 'Downloading')
    completed = sum(1 for t in tasks.values() if t['status'] == 'Completed')
    failed = sum(1 for t in tasks.values() if t['status'].startswith('Error'))
    
    return jsonify({
        'waiting': waiting,
        'downloading': downloading,
        'completed': completed,
        'failed': failed,
        'total': len(tasks),
        'active_downloads': active_downloads,
        'max_concurrent': settings.get('max_concurrent', 1),
        'sequential_mode': settings.get('sequential_mode', True)
    })

# --- File management endpoints ---
@app.route('/api/files', methods=['GET'])
def list_files():
    files = []
    if os.path.exists(DOWNLOAD_DIR):
        for f in os.listdir(DOWNLOAD_DIR):
            fp = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(fp) and not f.startswith('.'):
                s = os.stat(fp)
                files.append({'name': f, 'size': s.st_size, 'modified': s.st_mtime})
    files.sort(key=lambda x: x['modified'], reverse=True)
    return jsonify(files)

@app.route('/api/files/<path:filename>/download', methods=['GET'])
def download_file(filename):
    fp = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(fp):
        return send_file(fp, as_attachment=True)
    return jsonify({"status": "error"}), 404

@app.route('/api/files/<path:filename>/stream', methods=['GET'])
def stream_file(filename):
    fp = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(fp):
        return send_file(fp)
    return jsonify({"status": "error"}), 404

@app.route('/api/files/<path:filename>', methods=['DELETE'])
def delete_file(filename):
    fp = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(fp):
        os.remove(fp)
        return jsonify({"status": "success", "message": "File deleted"})
    return jsonify({"status": "error"}), 404

@app.route('/api/logs/<task_id>', methods=['GET'])
def get_task_log(task_id):
    """Get log file for a specific task"""
    log_file = os.path.join(LOGS_DIR, f'task_{task_id}.log')
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            return jsonify({"status": "success", "log": f.read()})
    return jsonify({"status": "error", "message": "Log not found"}), 404

# --- Settings endpoints ---
@app.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(settings)

@app.route('/api/settings', methods=['PUT'])
def update_settings():
    global settings
    new_settings = request.json
    
    # Update settings
    settings.update(new_settings)
    save_settings(settings)
    
    return jsonify({"status": "success", "message": "Settings saved"})

# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    print(f"\n{'='*50}")
    print(f"MissAV Downloader Started")
    print(f"Download directory: {DOWNLOAD_DIR}")
    print(f"Settings file: {SETTINGS_FILE}")
    print(f"Logs directory: {LOGS_DIR}")
    print(f"FFmpeg: {FFMPEG_PATH}")
    print(f"Sequential mode: {settings.get('sequential_mode', True)}")
    print(f"Max concurrent: {settings.get('max_concurrent', 1)}")
    print(f"{'='*50}\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
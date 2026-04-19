import os
import time
import threading
import queue
import uuid
import re
import logging
from pathlib import Path
import yt_dlp
from extractor import MyCustomMissAV
from config_manager import load_settings
from utils import is_jav_code, jav_code_to_url

settings = load_settings()
DOWNLOAD_DIR = settings.get('download_dir', './downloads')
LOGS_DIR = Path(__file__).parent / 'logs'
LOGS_DIR.mkdir(exist_ok=True)

download_queue = queue.Queue()
tasks = {}
active_downloads = 0
queue_lock = threading.Lock()

SPOOFDPI_PROXY = "http://127.0.0.1:8080"

class DownloadCancelled(Exception):
    pass

def setup_task_logger(task_id):
    log_file = LOGS_DIR / f'task_{task_id}.log'
    logger = logging.getLogger(f'task_{task_id}')
    logger.setLevel(logging.INFO)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return logger, str(log_file)

def format_duration(seconds):
    if not seconds:
        return "Unknown"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def get_video_info(url):
    try:
        if is_jav_code(url):
            mirrors = settings.get('mirrors', [])
            url = jav_code_to_url(url, mirrors[0] if mirrors else 'missav.ws')
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.add_info_extractor(MyCustomMissAV(settings=settings))
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
                        'filesize': f.get('filesize'),
                    })
            
            unique_formats = {}
            for f in formats:
                if f['height'] not in unique_formats:
                    unique_formats[f['height']] = f
            
            duration = info.get('duration')
            is_preview = duration and duration < 600
            
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

def add_download(url, selected_format=None):
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        'id': task_id,
        'url': url,
        'status': 'Waiting',
        'progress': 0,
        'stage': 'Queued',
        'selected_format': selected_format,
        'filename': None,
        'filesize': None,
        'created_at': time.time()
    }
    download_queue.put(task_id)
    return task_id

def add_batch(urls):
    task_ids = []
    for url in urls:
        if url.strip():
            task_ids.append(add_download(url.strip()))
    return task_ids

def download_video(task_id, url, selected_format=None):
    task = tasks.get(task_id)
    if not task:
        return
    
    task_logger, log_file = setup_task_logger(task_id)
    task['log_file'] = log_file
    task['status'] = 'Downloading'
    task['stage'] = 'Starting'
    
    task_logger.info(f"Starting download: {url}")
    
    def progress_hook(d):
        if task_id not in tasks:
            return
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%')
            p_clean = re.sub(r'\x1b[^m]*m', '', p).strip().replace('%', '')
            try:
                task['progress'] = float(p_clean)
                task['stage'] = 'Downloading'
                task_logger.info(f"Progress: {p_clean}%")
            except:
                task['progress'] = 0
        elif d['status'] == 'finished':
            task['stage'] = 'Merging'
            task_logger.info("Download finished, merging...")
    
    tmpl = settings.get('filename_template', '[%(id)s] %(title).60s.%(ext)s')
    
    # Map resolution to height filter
    resolution_map = {
        '2160p': 2160,
        '1440p': 1440,
        '1080p': 1080,
        '720p': 720,
        '480p': 480,
        '360p': 360,
        '240p': 240,
    }
    
    if selected_format:
        # Extract resolution from format_id (e.g., 'hls-1080p' -> 1080)
        selected_resolution = None
        for res in resolution_map:
            if res in selected_format:
                selected_resolution = resolution_map[res]
                break
        
        if selected_resolution:
            # Download same or HIGHER quality (>=)
            format_selector = f'bestvideo[height>={selected_resolution}]+bestaudio/best[height>={selected_resolution}]/best'
        else:
            format_selector = 'bestvideo+bestaudio/best'
    else:
        quality = settings.get('video_quality', 'best')
        if quality == 'best':
            format_selector = 'bestvideo+bestaudio/best'
        elif quality in resolution_map:
            target_height = resolution_map[quality]
            format_selector = f'bestvideo[height>={target_height}]+bestaudio/best[height>={target_height}]/best'
        else:
            format_selector = 'bestvideo+bestaudio/best'
    
    base_dir = Path(__file__).parent
    ffmpeg_path = base_dir / 'ffmpeg' / 'bin' / 'ffmpeg.exe'
    if not ffmpeg_path.exists():
        ffmpeg_path = 'ffmpeg'
    
    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_DIR, tmpl),
        'format': format_selector,
        'merge_output_format': 'mp4',
        'proxy': None,
        'quiet': False,
        'noprogress': True,
        'progress_hooks': [progress_hook],
        'ffmpeg_location': str(ffmpeg_path),
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
        if is_jav_code(url):
            mirrors = settings.get('mirrors', [])
            url = jav_code_to_url(url, mirrors[0] if mirrors else 'missav.ws')
        
        task_logger.info(f"Format selector: {format_selector}")
        
        with yt_dlp.YoutubeDL(ydl_opts, auto_init=False) as ydl:
            ydl.add_info_extractor(MyCustomMissAV(settings=settings))
            ydl.add_default_info_extractors()
            ydl.download([url])
        
        download_path = Path(DOWNLOAD_DIR)
        for f in download_path.iterdir():
            if f.is_file() and (task_id in f.name or url.split('/')[-1] in f.name):
                task['filename'] = f.name
                task['filesize'] = f.stat().st_size
                break
        
        task['status'] = 'Completed'
        task['stage'] = 'Complete'
        task['progress'] = 100
        task_logger.info("Download completed successfully")
        
    except Exception as e:
        error_msg = str(e)[:200]
        task_logger.error(f"Download failed: {error_msg}")
        task['status'] = f'Error: {error_msg}'
        task['stage'] = 'Failed'
        task['progress'] = 0

def worker():
    global active_downloads
    while True:
        task_id = download_queue.get()
        if task_id is None:
            break
        
        with queue_lock:
            active_downloads += 1
        
        if task_id in tasks:
            task = tasks[task_id]
            task['status'] = 'Downloading'
            task['stage'] = 'Initializing'
            download_video(task_id, task['url'], task.get('selected_format'))
        
        with queue_lock:
            active_downloads -= 1
        
        if settings.get('sequential_mode', True):
            time.sleep(settings.get('delay_between_downloads', 3))
        
        download_queue.task_done()

def start_workers():
    for _ in range(settings.get('max_concurrent', 1)):
        t = threading.Thread(target=worker, daemon=True)
        t.start()

start_workers()

def clear_queue():
    global download_queue
    cleared = []
    new_queue = queue.Queue()
    for task_id, task in list(tasks.items()):
        if task['status'] == 'Downloading':
            new_queue.put(task_id)
        else:
            cleared.append(task_id)
            del tasks[task_id]
    download_queue = new_queue
    return cleared

def clean_completed():
    cleaned = []
    for task_id, task in list(tasks.items()):
        if task['status'] in ['Completed', 'Cancelled'] or task['status'].startswith('Error'):
            cleaned.append(task_id)
            del tasks[task_id]
    return cleaned

def get_queue_stats():
    waiting = sum(1 for t in tasks.values() if t['status'] == 'Waiting')
    downloading = sum(1 for t in tasks.values() if t['status'] == 'Downloading')
    completed = sum(1 for t in tasks.values() if t['status'] == 'Completed')
    failed = sum(1 for t in tasks.values() if t['status'].startswith('Error'))
    return {
        'waiting': waiting,
        'downloading': downloading,
        'completed': completed,
        'failed': failed,
        'total': len(tasks),
        'active_downloads': active_downloads
    }
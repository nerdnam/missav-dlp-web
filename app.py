# app.py

import sys
import platform
import shutil
import os
import json
import subprocess
import time
import uuid
from pathlib import Path
from flask import Flask, request, render_template, jsonify, send_file, session, make_response
from app_files.download_manager import (
    get_video_info, add_download, add_batch, tasks, get_queue_stats,
    clear_queue, clean_completed
)
from app_files.config_manager import load_settings, save_settings
from app_files.utils import is_jav_code, jav_code_to_url
from app_files.paths import ROOT_DIR, DOWNLOADS_DIR, SETTINGS_FILE
from app_files.language import lang_manager

BASE_DIR = ROOT_DIR
settings = load_settings()
DOWNLOAD_DIR = Path(settings.get('download_dir', str(DOWNLOADS_DIR)))
DOWNLOAD_DIR.mkdir(exist_ok=True)

SPOOFDPI_PORT = 8080
SPOOFDPI_PROXY = f"http://127.0.0.1:{SPOOFDPI_PORT}"

def start_spoofdpi():
    system = platform.system().lower()
    
    # Windows
    if system == 'windows':
        spoofdpi_bin = BASE_DIR / 'spoofdpi.exe'
        if not spoofdpi_bin.exists():
            spoofdpi_bin = 'spoofdpi'
        try:
            proc = subprocess.Popen([str(spoofdpi_bin)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            time.sleep(2)
            if proc.poll() is None:
                print(f"[System] SpoofDPI started on Windows (Port: {SPOOFDPI_PORT})", flush=True)
        except FileNotFoundError:
            print(f"[System] spoofdpi.exe not found in {BASE_DIR}", flush=True)
    
    # Linux / macOS
    else:
        import shutil
        spoofdpi_cmd = shutil.which('spoof-dpi') or shutil.which('spoofdpi')
        
        if not spoofdpi_cmd:
            print("\n" + "="*60)
            print(f"⚠️  SpoofDPI not found on {system}!")
            print("="*60)
            if system == 'linux':
                print("\nInstall: curl -fsSL https://raw.githubusercontent.com/xvzc/SpoofDPI/main/install.sh | bash")
            elif system == 'darwin':
                print("\nInstall: brew install spoofdpi")
            print("\n🔗 https://github.com/xvzc/spoofdpi/releases")
            print("="*60 + "\n")
            return
        
        try:
            proc = subprocess.Popen([spoofdpi_cmd, '-port', str(SPOOFDPI_PORT)], 
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True)
            time.sleep(2)
            if proc.poll() is None:
                print(f"[System] SpoofDPI started on {system} (Port: {SPOOFDPI_PORT})", flush=True)
        except Exception as e:
            print(f"[System] Error starting SpoofDPI: {e}", flush=True)
            
start_spoofdpi()

app = Flask(__name__, static_folder='templates', static_url_path='/static')
app.secret_key = os.urandom(24)  # Required for session

# Initialize language manager
lang_manager.init_app(app)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/language', methods=['GET'])
def get_language():
    """Get current language"""
    lang = session.get('language', 'en')
    translations = lang_manager.get_all_translations(lang)
    return jsonify({
        'current': lang,
        'translations': translations,
        'supported': lang_manager.supported_langs
    })

@app.route('/api/language', methods=['POST'])
def set_language():
    """Set language"""
    data = request.json
    lang = data.get('language', 'en')
    
    if lang in lang_manager.supported_langs:
        session['language'] = lang
        response = make_response(jsonify({'status': 'success', 'language': lang}))
        response.set_cookie('language', lang, max_age=365*24*60*60)  # 1 year
        return response
    
    return jsonify({'status': 'error', 'message': 'Unsupported language'}), 400

@app.route('/api/languages', methods=['GET'])
def get_languages():
    """Get list of supported languages"""
    return jsonify({
        'supported': lang_manager.supported_langs,
        'names': {
            'en': 'English',
            'ko': '한국어',
            'ja': '日本語',
            'zh': '中文'
        }
    })

# Rest of your routes remain the same...
@app.route('/api/info', methods=['POST'])
def info():
    data = request.json
    url = data.get('url', '').strip()
    if not url:
        return jsonify({"status": "error", "message": "URL required"}), 400
    info = get_video_info(url)
    if info:
        return jsonify({"status": "success", "info": info})
    return jsonify({"status": "error", "message": "Failed to get video info"}), 500

@app.route('/api/download', methods=['POST'])
def download():
    data = request.json
    url = data.get('url', '').strip()
    selected_format = data.get('format', None)
    if not url:
        return jsonify({"status": "error", "message": "URL required"}), 400
    task_id = add_download(url, selected_format)
    return jsonify({"status": "success", "task_id": task_id})

@app.route('/api/batch', methods=['POST'])
def batch():
    data = request.json
    urls = data.get('urls', [])
    if not urls:
        return jsonify({"status": "error", "message": "No URLs provided"}), 400
    task_ids = add_batch(urls)
    return jsonify({"status": "success", "task_ids": task_ids, "count": len(task_ids)})

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    return jsonify(tasks)

@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    if task_id in tasks:
        del tasks[task_id]
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404

@app.route('/api/queue/clear', methods=['POST'])
def queue_clear():
    cleared = clear_queue()
    return jsonify({"status": "success", "cleared": len(cleared)})

@app.route('/api/queue/clean', methods=['POST'])
def queue_clean():
    cleaned = clean_completed()
    return jsonify({"status": "success", "cleaned": len(cleaned)})

@app.route('/api/queue/stats', methods=['GET'])
def queue_stats():
    return jsonify(get_queue_stats())

@app.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(settings)

@app.route('/api/settings', methods=['PUT'])
def update_settings():
    global settings, DOWNLOAD_DIR
    new_settings = request.json
    settings.update(new_settings)
    save_settings(settings)
    DOWNLOAD_DIR = Path(settings.get('download_dir', str(DOWNLOADS_DIR)))
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    return jsonify({"status": "success"})

@app.route('/api/files', methods=['GET'])
def list_files():
    files = []
    if DOWNLOAD_DIR.exists():
        for f in DOWNLOAD_DIR.iterdir():
            if f.is_file() and not f.name.startswith('.'):
                s = f.stat()
                files.append({'name': f.name, 'size': s.st_size, 'modified': s.st_mtime})
    files.sort(key=lambda x: x['modified'], reverse=True)
    return jsonify(files)

@app.route('/api/files/<path:filename>/download', methods=['GET'])
def download_file(filename):
    fp = DOWNLOAD_DIR / filename
    if fp.exists():
        return send_file(fp, as_attachment=True)
    return jsonify({"status": "error"}), 404

@app.route('/api/files/<path:filename>', methods=['DELETE'])
def delete_file(filename):
    fp = DOWNLOAD_DIR / filename
    if fp.exists():
        fp.unlink()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404

@app.route('/api/logs/<task_id>', methods=['GET'])
def get_log(task_id):
    log_file = ROOT_DIR / 'logs' / f'task_{task_id}.log'
    if log_file.exists():
        with open(log_file, 'r', encoding='utf-8') as f:
            return jsonify({"status": "success", "log": f.read()})
    return jsonify({"status": "error"}), 404

if __name__ == '__main__':
    import webbrowser
    import threading

    def open_browser():
        webbrowser.open('http://localhost:5000')

    print(f"\n{'='*50}")
    print(f"MissAV Downloader Started")
    print(f"Download directory: {DOWNLOAD_DIR}")
    print(f"Logs directory: {ROOT_DIR / 'logs'}")
    print(f"Open: http://localhost:5000")
    print(f"{'='*50}\n")
    threading.Timer(1.5, open_browser).start()
    #app.run(host='0.0.0.0', port=5000, debug=False)
    app.run(host='127.0.0.1', port=5000, debug=False)
    
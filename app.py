import os
import json
import subprocess
import time
import uuid
from pathlib import Path
from flask import Flask, request, render_template, jsonify, send_file
from download_manager import (
    get_video_info, add_download, add_batch, tasks, get_queue_stats,
    clear_queue, clean_completed
)
from config_manager import load_settings, save_settings
from utils import is_jav_code, jav_code_to_url

BASE_DIR = Path(__file__).parent
SETTINGS_FILE = BASE_DIR / '.settings.json'
settings = load_settings()
DOWNLOAD_DIR = settings.get('download_dir', './downloads')
if not DOWNLOAD_DIR:
    DOWNLOAD_DIR = './downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

SPOOFDPI_PORT = 8080
SPOOFDPI_PROXY = f"http://127.0.0.1:{SPOOFDPI_PORT}"

def start_spoofdpi():
    spoofdpi_bin = BASE_DIR / 'spoofdpi.exe'
    if not spoofdpi_bin.exists():
        spoofdpi_bin = 'spoofdpi'
    try:
        proc = subprocess.Popen([str(spoofdpi_bin)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        time.sleep(2)
        if proc.poll() is None:
            print(f"[System] SpoofDPI started (Port: {SPOOFDPI_PORT})", flush=True)
    except FileNotFoundError:
        print(f"[System] SpoofDPI not found", flush=True)

start_spoofdpi()

app = Flask(__name__, static_folder='templates', static_url_path='/static')

@app.route('/')
def index():
    return render_template('index.html')

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
    DOWNLOAD_DIR = settings.get('download_dir', './downloads')
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    return jsonify({"status": "success"})

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

@app.route('/api/files/<path:filename>', methods=['DELETE'])
def delete_file(filename):
    fp = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(fp):
        os.remove(fp)
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404

@app.route('/api/logs/<task_id>', methods=['GET'])
def get_log(task_id):
    log_file = Path(__file__).parent / 'logs' / f'task_{task_id}.log'
    if log_file.exists():
        with open(log_file, 'r', encoding='utf-8') as f:
            return jsonify({"status": "success", "log": f.read()})
    return jsonify({"status": "error"}), 404

if __name__ == '__main__':
    print(f"\n{'='*50}")
    print(f"MissAV Downloader Started")
    print(f"Download directory: {DOWNLOAD_DIR}")
    print(f"Open: http://localhost:5000")
    print(f"{'='*50}\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
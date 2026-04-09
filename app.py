import os
import json
import subprocess
import time
import threading
import queue
import uuid
import re
from urllib.parse import urlparse
from flask import Flask, request, render_template, jsonify, send_file, Response
import yt_dlp
from yt_dlp.extractor.common import InfoExtractor
from curl_cffi import requests as cffi_requests

# --- 설정 관리 ---
DOWNLOAD_DIR = '/downloads'
SETTINGS_FILE = os.path.join(DOWNLOAD_DIR, '.settings.json')

DEFAULT_SETTINGS = {
    'max_concurrent': 4,
    'filename_template': '[%(id)s] %(title).60s.%(ext)s',
    'spoofdpi_enabled': True,
    'video_quality': 'best',
    'mirrors': ['missav.ai', 'missav.net', 'missav123.com', 'missav.com', 'missav.ws'],
}

def load_settings():
    try:
        with open(SETTINGS_FILE, 'r') as f:
            saved = json.load(f)
            merged = {**DEFAULT_SETTINGS, **saved}
            return merged
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

settings = load_settings()

# --- SpoofDPI 프록시 자동 기동 ---
SPOOFDPI_PORT = 8080
SPOOFDPI_PROXY = f"http://127.0.0.1:{SPOOFDPI_PORT}"

def start_spoofdpi():
    """SpoofDPI를 백그라운드 HTTP 프록시로 기동 (SNI 차단 우회)"""
    try:
        proc = subprocess.Popen(
            ["spoofdpi", "--listen-addr", f"127.0.0.1:{SPOOFDPI_PORT}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        time.sleep(2)
        if proc.poll() is None:
            print(f"[SpoofDPI] 프록시 기동 성공 (port {SPOOFDPI_PORT})", flush=True)
        else:
            out = proc.stdout.read().decode() if proc.stdout else ""
            print(f"[SpoofDPI] 기동 실패: {out}", flush=True)
    except FileNotFoundError:
        print("[SpoofDPI] 바이너리 없음 — 프록시 없이 직접 연결", flush=True)

start_spoofdpi()

app = Flask(__name__)

download_queue = queue.Queue()
tasks = {}

class DownloadCancelled(Exception):
    pass

# --- 커스텀 추출기 (VPN 전용 & CF 완벽 우회 탑재) ---
class MyCustomMissAV(InfoExtractor):
    IE_NAME = 'custom_missav'
    _VALID_URL = r'https?://(?:[^/]+\.)?missav\.[^/]+/(?:[^/]+/)?(?P<id>[^/?#]+)'

    def _real_extract(self, url):
        video_id = self._match_id(url)
        self.to_screen(f'🔥 웹페이지 파싱 시도 (VPN 네트워크 사용): {url}')

        parsed_url = urlparse(url)
        path = parsed_url.path

        mirrors = [parsed_url.netloc] + settings.get('mirrors', DEFAULT_SETTINGS['mirrors'])
        mirrors = list(dict.fromkeys(mirrors))

        webpage = None
        for mirror in mirrors:
            test_url = f"https://{mirror}{path}"
            self.to_screen(f'🔥 HTML 추출 시도 중: {test_url}')
            # SpoofDPI 프록시 경유 → 프록시 없이 순서로 시도
            proxy_list = [SPOOFDPI_PROXY, None] if settings.get('spoofdpi_enabled', True) else [None]
            for proxy in proxy_list:
                try:
                    proxies = {"https": proxy, "http": proxy} if proxy else None
                    res = cffi_requests.get(
                        test_url,
                        impersonate="chrome",
                        timeout=20,
                        proxies=proxies,
                    )
                    if res.status_code == 200 and ('seek' in res.text or 'm3u8' in res.text):
                        webpage = res.text
                        proxy_label = "via SpoofDPI" if proxy else "direct"
                        self.to_screen(f'✅ 접속 성공 도메인: {mirror} ({proxy_label})')
                        break
                except Exception as e:
                    proxy_label = "SpoofDPI" if proxy else "direct"
                    self.to_screen(f'⚠️ {mirror} ({proxy_label}) 접속 실패: {e}')
            if webpage:
                break

        if not webpage:
            raise ValueError("Cloudflare 봇 방어를 뚫지 못했습니다. VPN IP가 강력하게 차단되었을 수 있습니다.")

        video_uuid = None
        seek_index = webpage.find('seek')
        if seek_index != -1 and seek_index >= 38:
            video_uuid = webpage[seek_index - 38 : seek_index - 2]
        
        if not video_uuid:
            uuid_match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', webpage)
            if uuid_match:
                video_uuid = uuid_match.group(1)

        if not video_uuid:
            title_match = re.search(r'<title>(.*?)</title>', webpage, re.IGNORECASE)
            page_title = title_match.group(1) if title_match else "Unknown"
            raise ValueError(f"고유 UUID를 찾을 수 없습니다. (현재 긁어온 페이지 제목: '{page_title}')")

        formatted_url = f"https://surrit.com/{video_uuid}/playlist.m3u8"
        self.to_screen(f'🔥 m3u8 마스터 주소 획득 성공: {formatted_url}')

        formats = self._extract_m3u8_formats(formatted_url, video_id, 'mp4', m3u8_id='hls')
        
        return {
            'id': video_id,
            'title': self._og_search_title(webpage, default=video_id),
            'formats': formats,
            'age_limit': 18,
        }

# --- 다운로드 처리 ---
def download_video(task_id, url):
    def progress_hook(d):
        if task_id not in tasks:
            raise DownloadCancelled("사용자에 의해 다운로드가 취소되었습니다.")
        
        if d['status'] == 'downloading':
            percent_str = d.get('_percent_str', '0%').strip()
            percent_clean = re.sub(r'\x1b[^m]*m', '', percent_str)
            tasks[task_id]['progress'] = percent_clean
        elif d['status'] == 'finished':
            tasks[task_id]['progress'] = '100%'
            filepath = d.get('filename', '')
            if filepath and os.path.isfile(filepath):
                tasks[task_id]['filename'] = os.path.basename(filepath)
                tasks[task_id]['filesize'] = os.path.getsize(filepath)

    parsed_url = urlparse(url)
    base_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"

    tmpl = settings.get('filename_template', DEFAULT_SETTINGS['filename_template'])
    quality = settings.get('video_quality', 'best')
    fmt = f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/bestvideo+bestaudio/best' if quality.isdigit() else 'bestvideo+bestaudio/best'

    ydl_opts = {
        'outtmpl': f'/downloads/{tmpl}',
        'format': fmt,
        'merge_output_format': 'mp4',
        'proxy': SPOOFDPI_PROXY if settings.get('spoofdpi_enabled', True) else None,

        # 🎯 로그 최적화: 콘솔 출력을 최소화합니다.
        'quiet': True,             # 기본 로그 숨김
        'noprogress': True,        # 터미널 진행률 출력 완벽 차단 (웹 UI로는 정상 전송됨)

        'progress_hooks': [progress_hook],
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': url,
            'Origin': base_origin,
        }
    }
    
    with yt_dlp.YoutubeDL(ydl_opts, auto_init=False) as ydl:
        ydl.add_info_extractor(MyCustomMissAV())
        ydl.add_default_info_extractors()
        
        try:
            print(f"[다운로드 시작] {url}", flush=True)
            ydl.download([url])
            if task_id in tasks:
                tasks[task_id]['status'] = '완료'
            print(f"[다운로드 완료] {url}", flush=True)
        except DownloadCancelled:
            print(f"[다운로드 취소 및 강제 종료됨] {url}", flush=True)
        except Exception as e:
            print(f"[다운로드 에러] {url} - {e}", flush=True)
            if task_id in tasks:
                tasks[task_id]['status'] = '에러'

# --- 워커 스레드 ---
def worker():
    while True:
        task_id = download_queue.get()
        if task_id is None:
            break
        
        if task_id not in tasks:
            download_queue.task_done()
            continue
            
        url = tasks[task_id]['url']
        tasks[task_id]['status'] = '다운로드 중'
        
        try:
            download_video(task_id, url)
        finally:
            download_queue.task_done()

for _ in range(settings.get('max_concurrent', 4)):
    threading.Thread(target=worker, daemon=True).start()

# --- API 및 라우팅 ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def handle_download():
    url = request.form.get('url', '').strip()
    if not url:
        return jsonify({"status": "error", "message": "URL을 입력해주세요."}), 400
    
    task_id = str(uuid.uuid4())
    tasks[task_id] = {'url': url, 'status': '대기 중', 'progress': '0%'}
    download_queue.put(task_id)
    
    return jsonify({"status": "success", "message": "목록에 추가되었습니다."})

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    return jsonify(tasks)

@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    if task_id in tasks:
        del tasks[task_id]
        return jsonify({"status": "success", "message": "삭제되었습니다."})
    return jsonify({"status": "error", "message": "찾을 수 없습니다."}), 404

def safe_filepath(filename):
    """경로 조작 방지 — DOWNLOAD_DIR 내부 파일만 허용"""
    filepath = os.path.realpath(os.path.join(DOWNLOAD_DIR, filename))
    if not filepath.startswith(os.path.realpath(DOWNLOAD_DIR) + os.sep):
        return None
    return filepath

@app.route('/api/files', methods=['GET'])
def list_files():
    files = []
    for f in os.listdir(DOWNLOAD_DIR):
        filepath = os.path.join(DOWNLOAD_DIR, f)
        if os.path.isfile(filepath):
            stat = os.stat(filepath)
            files.append({
                'name': f,
                'size': stat.st_size,
                'modified': stat.st_mtime,
            })
    files.sort(key=lambda x: x['modified'], reverse=True)
    return jsonify(files)

@app.route('/api/files/<path:filename>/download', methods=['GET'])
def download_file(filename):
    filepath = safe_filepath(filename)
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"status": "error", "message": "파일을 찾을 수 없습니다."}), 404
    return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))

@app.route('/api/files/<path:filename>/stream', methods=['GET'])
def stream_file(filename):
    filepath = safe_filepath(filename)
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"status": "error", "message": "파일을 찾을 수 없습니다."}), 404

    file_size = os.path.getsize(filepath)
    range_header = request.headers.get('Range')

    if range_header:
        byte_start = 0
        byte_end = file_size - 1
        match = re.match(r'bytes=(\d+)-(\d*)', range_header)
        if match:
            byte_start = int(match.group(1))
            if match.group(2):
                byte_end = int(match.group(2))
        length = byte_end - byte_start + 1

        def generate():
            with open(filepath, 'rb') as f:
                f.seek(byte_start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(8192, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return Response(
            generate(),
            status=206,
            mimetype='video/mp4',
            headers={
                'Content-Range': f'bytes {byte_start}-{byte_end}/{file_size}',
                'Accept-Ranges': 'bytes',
                'Content-Length': str(length),
            }
        )

    def generate_full():
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                yield chunk

    return Response(
        generate_full(),
        mimetype='video/mp4',
        headers={
            'Accept-Ranges': 'bytes',
            'Content-Length': str(file_size),
        }
    )

@app.route('/api/files/<path:filename>', methods=['DELETE'])
def delete_file(filename):
    filepath = safe_filepath(filename)
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"status": "error", "message": "파일을 찾을 수 없습니다."}), 404
    os.remove(filepath)
    return jsonify({"status": "success", "message": "삭제되었습니다."})

@app.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(settings)

@app.route('/api/settings', methods=['PUT'])
def update_settings():
    global settings
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "잘못된 요청입니다."}), 400

    allowed_keys = set(DEFAULT_SETTINGS.keys())
    for key in data:
        if key in allowed_keys:
            settings[key] = data[key]

    save_settings(settings)
    return jsonify({"status": "success", "message": "설정이 저장되었습니다.", "settings": settings})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
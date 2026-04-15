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
        if not os.path.exists(DOWNLOAD_DIR):
            os.makedirs(DOWNLOAD_DIR)
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

# --- SpoofDPI 프록시 자동 기동 (기본 포트 8080) ---
SPOOFDPI_PORT = 8080
SPOOFDPI_PROXY = f"http://127.0.0.1:{SPOOFDPI_PORT}"

def start_spoofdpi():
    """SpoofDPI를 백그라운드에서 실행 (SNI 차단 우회)"""
    try:
        # 최신 SpoofDPI 구조에 맞게 옵션 없이 실행하거나 필요 시 수정
        proc = subprocess.Popen(
            ["spoofdpi"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        time.sleep(2)
        if proc.poll() is None:
            print(f"[System] SpoofDPI 엔진 가동 성공 (Port: {SPOOFDPI_PORT})", flush=True)
        else:
            print(f"[System] SpoofDPI 가동 실패", flush=True)
    except FileNotFoundError:
        print("[System] SpoofDPI 바이너리를 찾을 수 없습니다.", flush=True)

start_spoofdpi()

app = Flask(__name__)

# 다운로드 큐 및 작업 상태 저장소
download_queue = queue.Queue()
tasks = {}

class DownloadCancelled(Exception):
    pass

# --- [패치] 유저스크립트 로직을 이식한 커스텀 추출기 ---
class MyCustomMissAV(InfoExtractor):
    IE_NAME = 'custom_missav'
    _VALID_URL = r'https?://(?:[^/]+\.)?missav\.[^/]+/(?:[^/]+/)?(?P<id>[^/?#]+)'

    def _real_extract(self, url):
        video_id = self._match_id(url)
        print(f'🔥 [로직 시작] 파싱 대상: {url}', flush=True)

        parsed_url = urlparse(url)
        path = parsed_url.path
        mirrors = [parsed_url.netloc] + settings.get('mirrors', DEFAULT_SETTINGS['mirrors'])
        mirrors = list(dict.fromkeys(mirrors))

        webpage = None
        # 1. 페이지 HTML 소스 가져오기 (Cloudflare 통과용 chrome110 위장)
        for mirror in mirrors:
            test_url = f"https://{mirror}{path}"
            proxy_list = [SPOOFDPI_PROXY, None] if settings.get('spoofdpi_enabled', True) else [None]
            for proxy in proxy_list:
                try:
                    proxies = {"https": proxy, "http": proxy} if proxy else None
                    res = cffi_requests.get(test_url, impersonate="chrome110", timeout=20, proxies=proxies)
                    if res.status_code == 200 and ('seek' in res.text or 'm3u8' in res.text):
                        webpage = res.text
                        print(f'✅ 페이지 접속 성공: {mirror}', flush=True)
                        break
                except Exception as e:
                    continue
            if webpage: break

        if not webpage:
            raise ValueError("페이지 소스를 불러오는 데 실패했습니다. (Cloudflare 차단 의심)")

        # 2. [유저스크립트 로직] UUID 추출
        video_uuid = None
        seek_index = webpage.find('seek')
        if seek_index != -1 and seek_index >= 38:
            # 유저스크립트의 substring(index - 38, index - 2) 로직 적용
            video_uuid = webpage[seek_index - 38 : seek_index - 2]
        
        if not video_uuid:
            uuid_match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', webpage)
            if uuid_match: video_uuid = uuid_match.group(1)

        if not video_uuid:
            raise ValueError("영상 고유 ID(UUID)를 찾을 수 없습니다.")

        # 3. 마스터 m3u8 주소 구성
        master_url = f"https://surrit.com/{video_uuid}/playlist.m3u8"
        print(f'🔗 마스터 m3u8 확인: {master_url}', flush=True)
        
        # 4. [유저스크립트 로직] 마스터를 읽어서 화질별 절대 경로 m3u8 생성
        final_formats = []
        try:
            m_res = cffi_requests.get(master_url, impersonate="chrome110", timeout=10)
            lines = m_res.text.split('\n')
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    # 유저스크립트: prefix + UUID + '/' + line
                    # 예: 1080p/video.m3u8 -> https://surrit.com/UUID/1080p/video.m3u8
                    quality_url = f"https://surrit.com/{video_uuid}/{line}"
                    quality_label = line.split('/')[0]
                    
                    final_formats.append({
                        'url': quality_url,
                        'ext': 'mp4',
                        'format_id': f'hls-{quality_label}',
                        'quality': 1 if '1080' in quality_label else 0,
                        'protocol': 'm3u8_native',
                    })
        except Exception as e:
            print(f"⚠️ 화질별 목록 추출 실패, 기본 분석 시도: {e}", flush=True)

        # 화질 목록이 비었으면 yt-dlp 기본 m3u8 분석기로 대체
        if not final_formats:
            final_formats = self._extract_m3u8_formats(master_url, video_id, 'mp4', m3u8_id='hls')
        
        return {
            'id': video_id,
            'title': self._og_search_title(webpage, default=video_id),
            'formats': final_formats,
            'age_limit': 18,
        }

# --- 실제 다운로드 수행 함수 ---
def download_video(task_id, url):
    def progress_hook(d):
        if task_id not in tasks:
            raise DownloadCancelled("취소됨")
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%')
            # 특수문자 제거
            tasks[task_id]['progress'] = re.sub(r'\x1b[^m]*m', '', p).strip()
        elif d['status'] == 'finished':
            tasks[task_id]['progress'] = '100%'

    tmpl = settings.get('filename_template', DEFAULT_SETTINGS['filename_template'])
    ydl_opts = {
        'outtmpl': f'{DOWNLOAD_DIR}/{tmpl}',
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'proxy': SPOOFDPI_PROXY if settings.get('spoofdpi_enabled', True) else None,
        'quiet': True,
        'noprogress': True,
        'progress_hooks': [progress_hook],
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
            'Referer': 'https://missav.ws/',
            'Origin': 'https://missav.ws',
        }
    }
    
    with yt_dlp.YoutubeDL(ydl_opts, auto_init=False) as ydl:
        ydl.add_info_extractor(MyCustomMissAV())
        ydl.add_default_info_extractors()
        try:
            print(f"[Download] 시작: {url}", flush=True)
            ydl.download([url])
            if task_id in tasks: tasks[task_id]['status'] = '완료'
        except Exception as e:
            print(f"[Error] {url}: {e}", flush=True)
            if task_id in tasks: tasks[task_id]['status'] = '에러'

# --- 워커 및 라우팅 ---
def worker():
    while True:
        task_id = download_queue.get()
        if task_id is None: break
        if task_id in tasks:
            tasks[task_id]['status'] = '다운로드 중'
            download_video(task_id, tasks[task_id]['url'])
        download_queue.task_done()

for _ in range(settings.get('max_concurrent', 4)):
    threading.Thread(target=worker, daemon=True).start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def handle_download():
    url = request.form.get('url', '').strip()
    if not url: return jsonify({"status": "error", "message": "URL 입력"}), 400
    task_id = str(uuid.uuid4())
    tasks[task_id] = {'url': url, 'status': '대기 중', 'progress': '0%'}
    download_queue.put(task_id)
    return jsonify({"status": "success"})

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    return jsonify(tasks)

@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    if task_id in tasks:
        del tasks[task_id]
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404

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

@app.route('/api/files/<path:filename>', methods=['DELETE'])
def delete_file(filename):
    fp = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(fp):
        os.remove(fp)
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
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
        if not os.path.exists(SETTINGS_FILE):
            save_settings(DEFAULT_SETTINGS.copy())
            return DEFAULT_SETTINGS.copy()
        with open(SETTINGS_FILE, 'r') as f:
            saved = json.load(f)
            merged = {**DEFAULT_SETTINGS, **saved}
            return merged
    except (FileNotFoundError, json.JSONDecodeError):
        save_settings(DEFAULT_SETTINGS.copy())
        return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

settings = load_settings()

# --- SpoofDPI 프록시 자동 기동 ---
SPOOFDPI_PORT = 8080
SPOOFDPI_PROXY = f"http://127.0.0.1:{SPOOFDPI_PORT}"

def start_spoofdpi():
    try:
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

# static_folder 설정 추가
app = Flask(__name__, static_folder='templates', static_url_path='/static')

download_queue = queue.Queue()
tasks = {}

class DownloadCancelled(Exception):
    pass

# --- 커스텀 MissAV 추출기 ---
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
        used_url = url

        # 1. 페이지 HTML 소스 가져오기
        for mirror in mirrors:
            test_url = f"https://{mirror}{path}"
            proxy_list = [SPOOFDPI_PROXY, None] if settings.get('spoofdpi_enabled', True) else [None]
            for proxy in proxy_list:
                try:
                    proxies = {"https": proxy, "http": proxy} if proxy else None
                    res = cffi_requests.get(test_url, impersonate="chrome110", timeout=20, proxies=proxies)
                    if res.status_code == 200 and ('seek' in res.text or 'm3u8' in res.text):
                        webpage = res.text
                        used_url = test_url
                        print(f'✅ 페이지 접속 성공: {mirror} (proxy={proxy})', flush=True)
                        break
                except Exception as e:
                    print(f'⚠️ {mirror} 접속 실패: {e}', flush=True)
                    continue
            if webpage:
                break

        if not webpage:
            raise ValueError("페이지 소스를 불러오는 데 실패했습니다. (Cloudflare 차단 의심)")

        # 2. UUID 추출 - script 태그별로 검사 + UUID 형식 검증
        video_uuid = None
        script_contents = re.findall(r'<script[^>]*>(.*?)</script>', webpage, re.DOTALL)
        print(f'[UUID] script 태그 수: {len(script_contents)}', flush=True)

        for idx, script_content in enumerate(script_contents):
            seek_index = script_content.find('seek')
            if seek_index != -1 and seek_index >= 38:
                candidate = script_content[seek_index - 38: seek_index - 2]
                if re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', candidate):
                    video_uuid = candidate
                    print(f'✅ UUID 발견 (script #{idx+1}): {video_uuid}', flush=True)
                    break

        # fallback1: 전체 HTML에서 seek 주변 검색
        if not video_uuid:
            seek_idx = webpage.find('seek')
            while seek_idx != -1:
                if seek_idx >= 38:
                    candidate = webpage[seek_idx - 38: seek_idx - 2]
                    if re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', candidate):
                        video_uuid = candidate
                        print(f'✅ UUID fallback1: {video_uuid}', flush=True)
                        break
                seek_idx = webpage.find('seek', seek_idx + 1)

        # fallback2: 정규식으로 UUID 패턴 검색
        if not video_uuid:
            uuid_match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', webpage)
            if uuid_match:
                video_uuid = uuid_match.group(1)
                print(f'✅ UUID fallback2: {video_uuid}', flush=True)

        if not video_uuid:
            raise ValueError("영상 고유 ID(UUID)를 찾을 수 없습니다.")

        # 3. 마스터 m3u8 주소 구성
        master_url = f"https://surrit.com/{video_uuid}/playlist.m3u8"
        print(f'🔗 마스터 m3u8: {master_url}', flush=True)

        # 4. 화질별 m3u8 URL 생성
        final_formats = []
        try:
            m_res = cffi_requests.get(
                master_url,
                impersonate="chrome110",
                timeout=10,
                headers={
                    'Referer': used_url,
                    'Origin': f"https://{urlparse(used_url).netloc}",
                }
            )
            print(f'[m3u8] 응답코드: {m_res.status_code}', flush=True)
            lines = m_res.text.split('\n')
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    quality_url = f"https://surrit.com/{video_uuid}/{line}"
                    quality_label = line.split('/')[0]
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
                    print(f'[포맷] {quality_label} -> {quality_url}', flush=True)
        except Exception as e:
            print(f"⚠️ 화질별 목록 추출 실패: {e}", flush=True)

        if not final_formats:
            final_formats = self._extract_m3u8_formats(master_url, video_id, 'mp4', m3u8_id='hls')

        final_formats.sort(key=lambda x: x.get('quality', 0) or x.get('height', 0) or 0, reverse=True)

        return {
            'id': video_id,
            'title': self._og_search_title(webpage, default=video_id),
            'formats': final_formats,
            'age_limit': 18,
        }


# --- 다운로드 함수 ---
def download_video(task_id, url):
    def progress_hook(d):
        if task_id not in tasks:
            raise DownloadCancelled("취소됨")
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%')
            tasks[task_id]['progress'] = re.sub(r'\x1b[^m]*m', '', p).strip()
        elif d['status'] == 'finished':
            tasks[task_id]['progress'] = '100%'

    tmpl = settings.get('filename_template', DEFAULT_SETTINGS['filename_template'])
    ydl_opts = {
        'outtmpl': f'{DOWNLOAD_DIR}/{tmpl}',
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'proxy': None,  # surrit.com CDN은 프록시 없이 직접 접근
        'quiet': True,
        'noprogress': True,
        'progress_hooks': [progress_hook],
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
            'Referer': 'https://missav.ws/',
            'Origin': 'https://missav.ws',
        },
        'hls_prefer_native': True,
        'concurrent_fragment_downloads': 5,
    }

    with yt_dlp.YoutubeDL(ydl_opts, auto_init=False) as ydl:
        ydl.add_info_extractor(MyCustomMissAV())
        ydl.add_default_info_extractors()
        try:
            print(f"[Download] 시작: {url}", flush=True)
            ydl.download([url])
            if task_id in tasks:
                tasks[task_id]['status'] = '완료'
        except DownloadCancelled:
            if task_id in tasks:
                tasks[task_id]['status'] = '취소됨'
        except Exception as e:
            print(f"[Error] {url}: {e}", flush=True)
            if task_id in tasks:
                tasks[task_id]['status'] = f'에러: {str(e)[:100]}'


# --- 워커 ---
def worker():
    while True:
        task_id = download_queue.get()
        if task_id is None:
            break
        if task_id in tasks:
            tasks[task_id]['status'] = '다운로드 중'
            download_video(task_id, tasks[task_id]['url'])
        download_queue.task_done()

for _ in range(settings.get('max_concurrent', 4)):
    threading.Thread(target=worker, daemon=True).start()


# --- 라우팅 ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def handle_download():
    url = request.form.get('url', '').strip()
    if not url:
        return jsonify({"status": "error", "message": "URL 입력"}), 400
    task_id = str(uuid.uuid4())
    tasks[task_id] = {'url': url, 'status': '대기 중', 'progress': '0%'}
    download_queue.put(task_id)
    return jsonify({"status": "success", "task_id": task_id})

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

@app.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(settings)

@app.route('/api/settings', methods=['PUT'])
def update_settings():
    global settings
    new_settings = request.json
    settings.update(new_settings)
    save_settings(settings)
    return jsonify({"status": "success"})

if __name__ == '__main__':
    print(f"\n{'='*50}")
    print(f"MissAV Downloader Started")
    print(f"Download directory: {DOWNLOAD_DIR}")
    print(f"Open: http://localhost:5000")
    print(f"{'='*50}\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
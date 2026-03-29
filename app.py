import os
import threading
import queue
import uuid
import re
from urllib.parse import urlparse
from flask import Flask, request, render_template, jsonify
import yt_dlp
from yt_dlp.extractor.common import InfoExtractor
from curl_cffi import requests as cffi_requests

app = Flask(__name__)

MAX_CONCURRENT_DOWNLOADS = 4
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

        mirrors = [
            parsed_url.netloc,
            "missav.ai",
            "missav.net",
            "missav123.com",
            "missav.com",
            "missav.ws"
        ]
        mirrors = list(dict.fromkeys(mirrors))

        webpage = None
        for mirror in mirrors:
            test_url = f"https://{mirror}{path}"
            self.to_screen(f'🔥 HTML 추출 시도 중: {test_url}')
            try:
                res = cffi_requests.get(test_url, impersonate="chrome110", timeout=15)
                if res.status_code == 200 and ('seek' in res.text or 'm3u8' in res.text):
                    webpage = res.text
                    self.to_screen(f'✅ 접속 성공 도메인: {mirror}')
                    break
            except Exception as e:
                self.to_screen(f'⚠️ {mirror} 접속 실패: {e}')

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

    parsed_url = urlparse(url)
    base_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"

    ydl_opts = {
        'outtmpl': '/downloads/[%(id)s] %(title).60s.%(ext)s', 
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        
        # 🎯 로그 최적화: 콘솔 출력을 최소화합니다.
        'quiet': True,             # 기본 로그 숨김
        'noprogress': True,        # 터미널 진행률 출력 완벽 차단 (웹 UI로는 정상 전송됨)
        
        'progress_hooks': [progress_hook],
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
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

for _ in range(MAX_CONCURRENT_DOWNLOADS):
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
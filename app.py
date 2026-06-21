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

# surrit.com CDN의 Cloudflare 봇 차단 통과용 브라우저 TLS 지문 후보.
# cf_clearance 쿠키(FlareSolverr)는 Chromium에서 발급되므로 Chrome UA와 맞춰 Chrome 지문을 우선 시도.
IMPERSONATE_TARGETS = ["chrome131", "chrome124", "chrome120", "firefox135"]

# --- FlareSolverr (Cloudflare 봇 차단 우회: 헤드리스 브라우저로 cf_clearance 쿠키 획득) ---
# 다운로더와 같은 Gluetun 망에 FlareSolverr 컨테이너를 띄우면 서버 자신의 IP로 쿠키가 발급된다.
FLARESOLVERR_URL = os.environ.get('FLARESOLVERR_URL', 'http://localhost:8191/v1')
_cf_cache = {'cookie': None, 'ua': None, 'ts': 0.0}
_CF_CACHE_TTL = 900  # cf_clearance 쿠키 재사용 시간(초)

def get_cf_clearance(probe_url, force=False):
    """FlareSolverr로 surrit.com의 cf_clearance 쿠키와 User-Agent를 얻는다(캐시 사용).
    반환: (cookie_header, user_agent) 또는 (None, None)."""
    now = time.time()
    if not force and _cf_cache['cookie'] and now - _cf_cache['ts'] < _CF_CACHE_TTL:
        return _cf_cache['cookie'], _cf_cache['ua']
    try:
        resp = cffi_requests.post(
            FLARESOLVERR_URL,
            json={'cmd': 'request.get', 'url': probe_url, 'maxTimeout': 60000},
            timeout=90,
        )
        data = resp.json()
        if data.get('status') != 'ok':
            print(f"[FlareSolverr] 실패: {data.get('message')}", flush=True)
            return None, None
        sol = data.get('solution', {})
        ua = sol.get('userAgent')
        cookies = sol.get('cookies', [])
        cookie_header = '; '.join(f"{c['name']}={c['value']}" for c in cookies if c.get('name'))
        if cookie_header:
            _cf_cache.update(cookie=cookie_header, ua=ua, ts=now)
            print(f"[FlareSolverr] cf_clearance 획득 (쿠키 {len(cookies)}개, UA={ua})", flush=True)
            return cookie_header, ua
        print("[FlareSolverr] 쿠키가 비어있음", flush=True)
        return None, None
    except Exception as e:
        print(f"[FlareSolverr] 호출 실패(컨테이너 미기동/주소 확인): {e}", flush=True)
        return None, None

# --- 설정 관리 ---
DOWNLOAD_DIR = '/downloads'
SETTINGS_FILE = os.path.join(DOWNLOAD_DIR, '.settings.json')

# 설정 스키마 버전. 미러 목록 등 기본값이 바뀔 때 올려서 기존 설정 파일을 자동 마이그레이션한다.
SETTINGS_VERSION = 3

DEFAULT_SETTINGS = {
    'max_concurrent': 4,
    'filename_template': '[%(id)s] %(title).60s.%(ext)s',
    'spoofdpi_enabled': True,
    'video_quality': 'best',
    # 유저스크립트 @match 기준 현재 활성 도메인 (2026.3 기준). 죽은 미러(missav.net/com) 제거.
    'mirrors': ['missav.ai', 'missav.ws', 'missav.live', 'missav.fans', 'missav.media', 'missav123.com', 'missav01.com'],
    'settings_version': SETTINGS_VERSION,
}

# 버전 업그레이드 시 자동으로 제거할, 더 이상 동작하지 않는 옛 미러 도메인
DEPRECATED_MIRRORS = {'missav.net', 'missav.com'}

def migrate_settings(saved):
    """저장된 설정에 새 기본 키를 채우고, 버전 업그레이드 시 미러 목록을 갱신한다.
    사용자가 추가한 커스텀 미러는 보존하고, 죽은 기본 미러(DEPRECATED_MIRRORS)만 교체한다.
    반환: (마이그레이션된 설정 dict, 변경 여부 bool)
    """
    merged = {**DEFAULT_SETTINGS, **saved}
    changed = False

    # 1. 새로 추가된 기본 키가 저장본에 없으면 채워 넣고 재저장 표시
    if any(k not in saved for k in DEFAULT_SETTINGS):
        changed = True

    # 2. 버전 업그레이드 시 미러 목록 마이그레이션 (죽은 미러 제거 + 신규 공식 미러 추가)
    if saved.get('settings_version', 1) < SETTINGS_VERSION:
        mirrors = [m for m in merged.get('mirrors', []) if m not in DEPRECATED_MIRRORS]
        for m in DEFAULT_SETTINGS['mirrors']:
            if m not in mirrors:
                mirrors.append(m)
        merged['mirrors'] = mirrors
        merged['settings_version'] = SETTINGS_VERSION
        changed = True

    return merged, changed


def load_settings():
    try:
        if not os.path.exists(DOWNLOAD_DIR):
            os.makedirs(DOWNLOAD_DIR)
        if not os.path.exists(SETTINGS_FILE):
            save_settings(DEFAULT_SETTINGS.copy())
            return DEFAULT_SETTINGS.copy()
        with open(SETTINGS_FILE, 'r') as f:
            saved = json.load(f)
        merged, changed = migrate_settings(saved)
        if changed:
            save_settings(merged)
            print(f"[System] 설정을 v{SETTINGS_VERSION}로 마이그레이션했습니다. 미러: {merged.get('mirrors')}", flush=True)
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
    # missav.ws / missav.live 외에 missav123.com 처럼 숫자가 붙은 도메인도 매칭 (\d*)
    # 로케일 접두사(/en/, /ja/, /dm22/en/ 등)는 모두 건너뛰고 마지막 세그먼트를 영상 코드로 사용
    _VALID_URL = r'https?://(?:[^/]+\.)?missav\d*\.[^/]+/(?:[^/?#]+/)*(?P<id>[^/?#]+)'

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
        # 브라우저 referrer-policy(strict-origin-when-cross-origin)와 동일하게 Referer는 오리진만 전송
        netloc = urlparse(used_url).netloc
        referer = f"https://{netloc}/"
        origin = f"https://{netloc}"
        final_formats = []
        cf_cookie, cf_ua = None, None  # FlareSolverr로 받은 cf_clearance 쿠키 / User-Agent

        def fetch_m3u8(cookie=None, ua=None):
            """여러 TLS 지문으로 마스터 m3u8을 받아 실제 m3u8(#EXTM3U)인지 검증. 본문 반환 or None."""
            for tgt in IMPERSONATE_TARGETS:
                try:
                    h = {'Referer': referer, 'Origin': origin, 'Accept': '*/*'}
                    if cookie:
                        h['Cookie'] = cookie
                    if ua:
                        h['User-Agent'] = ua
                    r = cffi_requests.get(master_url, impersonate=tgt, timeout=15, headers=h)
                    tag = 'm3u8+cf' if cookie else 'm3u8'
                    print(f'[{tag}] {tgt} 응답코드: {r.status_code}', flush=True)
                    if r.status_code == 200 and '#EXTM3U' in r.text:
                        return r.text
                except Exception as e:
                    print(f'⚠️ m3u8 fetch ({tgt}) 실패: {e}', flush=True)
            return None

        # 1차: 쿠키 없이 직접 시도
        m_text = fetch_m3u8()

        # 2차: 차단되면 FlareSolverr로 cf_clearance 쿠키를 받아 재시도 (서버 자신의 IP로 발급)
        if not m_text:
            print('⚠️ 직접 m3u8 차단 → FlareSolverr로 cf_clearance 시도', flush=True)
            cf_cookie, cf_ua = get_cf_clearance(master_url)
            if cf_cookie:
                m_text = fetch_m3u8(cookie=cf_cookie, ua=cf_ua)

        # 세그먼트 다운로드까지 쿠키·UA가 전달되도록 포맷 헤더 구성
        fmt_headers = {'Referer': referer, 'Origin': origin}
        if cf_cookie:
            fmt_headers['Cookie'] = cf_cookie
        if cf_ua:
            fmt_headers['User-Agent'] = cf_ua

        if m_text:
            for line in m_text.split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    quality_url = f"https://surrit.com/{video_uuid}/{line}"
                    quality_label = line.split('/')[0]
                    height = None
                    try:
                        height = int(re.search(r'(\d+)', quality_label).group(1))
                    except Exception:
                        pass
                    final_formats.append({
                        'url': quality_url,
                        'ext': 'mp4',
                        'format_id': f'hls-{quality_label}',
                        'height': height,
                        'quality': height or 0,
                        'protocol': 'm3u8_native',
                        'http_headers': dict(fmt_headers),
                    })
                    print(f'[포맷] {quality_label} -> {quality_url}', flush=True)

        # 그래도 결과가 없으면 yt-dlp 네트워킹(impersonate + 쿠키)으로 폴백
        if not final_formats:
            print('⚠️ 직접 m3u8 추출 실패 → yt-dlp 폴백', flush=True)
            final_formats = self._extract_m3u8_formats(
                master_url, video_id, 'mp4', m3u8_id='hls', headers=fmt_headers,
            )

        final_formats.sort(key=lambda x: x.get('quality', 0) or x.get('height', 0) or 0, reverse=True)

        return {
            'id': video_id,
            'title': self._og_search_title(webpage, default=video_id),
            'formats': final_formats,
            'age_limit': 18,
        }


def select_impersonate_target(ydl):
    """yt-dlp 다운로드용 impersonate 타깃 선택.
    surrit.com이 Firefox는 통과시키고 Chrome 지문은 차단하는 정황이 있어 Firefox를 우선 선택하고,
    백엔드(curl_cffi)에 Firefox 타깃이 없으면 Chrome으로 폴백한다. 사용 불가 시 None 반환."""
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget
    except Exception:
        return None
    # 백엔드가 실제로 지원하는 타깃 목록 조회 (버전에 따라 (target, handler) 튜플 또는 target)
    available = []
    try:
        for item in ydl._get_available_impersonate_targets():
            available.append(item[0] if isinstance(item, (list, tuple)) else item)
    except Exception:
        available = []
    for client in ('chrome', 'firefox'):
        want = ImpersonateTarget(client=client)
        if not available:
            return want  # 조회 실패 시 일반 타깃으로 시도 (요청 시점에 매칭)
        for a in available:
            try:
                if a in want:  # 사용 가능한 구체 타깃 a가 want(일반) 사양을 만족
                    return a
            except Exception:
                continue
    return None


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
        # User-Agent는 지정하지 않음: impersonate가 TLS 지문과 일치하는 헤더를 자동 설정한다
        # (UA를 수동 고정하면 TLS 지문과 불일치해 Cloudflare가 오히려 봇으로 탐지함).
        # Referer/Origin은 추출기에서 포맷별 http_headers로 다시 덮어쓴다.
        'http_headers': {
            'Referer': 'https://missav.ws/',
            'Origin': 'https://missav.ws',
        },
        'hls_prefer_native': True,
        'concurrent_fragment_downloads': 5,
    }

    with yt_dlp.YoutubeDL(ydl_opts, auto_init=False) as ydl:
        ydl.add_info_extractor(MyCustomMissAV())
        ydl.add_default_info_extractors()
        # surrit.com CDN의 Cloudflare 차단 우회: yt-dlp의 모든 요청(.ts 세그먼트 포함)을 브라우저로 위장.
        # 실사용 Firefox로는 통과되므로 Firefox 지문을 우선 선택하고, 없으면 Chrome으로 폴백.
        target = select_impersonate_target(ydl)
        if target is not None:
            ydl.params['impersonate'] = target
            print(f'[System] yt-dlp impersonate 타깃: {target}', flush=True)
        else:
            print('[System] yt-dlp impersonate 사용 불가 — yt-dlp/curl_cffi 업데이트 필요', flush=True)
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
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
# 실사용상 Firefox 지문이 가장 잘 통과되어 Firefox 전용으로 시도한다.
IMPERSONATE_TARGETS = ["firefox135", "firefox133"]

# surrit.com은 m3u8/세그먼트에 대한 "직접 접근"(Sec-Fetch-Site: none/navigate)은 WAF로 차단하고,
# 미러 페이지의 영상 플레이어가 보내는 "크로스사이트 서브리소스 요청"은 허용한다.
# 그래서 요청을 플레이어의 fetch처럼 보이게 하는 헤더를 함께 보낸다.
CROSS_SITE_HEADERS = {
    'Accept': '*/*',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'cross-site',
}

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
    # (선택·대개 불필요) surrit.com이 쿠키를 요구하는 경우에만: 브라우저에서 복사한 cf_clearance 쿠키/UA.
    # 서버가 브라우저와 같은 출구 IP일 때만 유효하고 수시간 뒤 만료된다.
    'cf_cookie': '',
    'cf_user_agent': '',
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
        cf_cookie, cf_ua = None, None  # (선택) 수동 cf_clearance 쿠키 / User-Agent

        def fetch_m3u8(cookie=None, ua=None):
            """여러 TLS 지문으로 마스터 m3u8을 받아 실제 m3u8(#EXTM3U)인지 검증. 본문 반환 or None."""
            for tgt in IMPERSONATE_TARGETS:
                try:
                    h = {'Referer': referer, 'Origin': origin, **CROSS_SITE_HEADERS}
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

        # 1차: 쿠키 없이 마스터 m3u8 직접 시도
        m_text = fetch_m3u8()

        # 세그먼트는 쿠키 없이 헤더(Sec-Fetch cross-site)만으로 통과한다(브라우저 실측 확인).
        # 설정에 수동 cf_clearance가 있으면 선택적으로 함께 보낸다.
        manual_cookie = (settings.get('cf_cookie') or '').strip()
        manual_ua = (settings.get('cf_user_agent') or '').strip()
        if manual_cookie:
            cf_cookie = manual_cookie if '=' in manual_cookie else f'cf_clearance={manual_cookie}'
            cf_ua = manual_ua or None
            print('[cf] 수동 cf_clearance 쿠키 사용', flush=True)

        # 마스터도 막혔으면 확보한 쿠키로 재시도
        if not m_text and cf_cookie:
            print('⚠️ 직접 m3u8 차단 → cf_clearance 쿠키로 재시도', flush=True)
            m_text = fetch_m3u8(cookie=cf_cookie, ua=cf_ua)

        # 세그먼트 다운로드도 플레이어처럼(크로스사이트) 보이도록 헤더 구성 + 쿠키·UA 전달
        fmt_headers = {'Referer': referer, 'Origin': origin, **CROSS_SITE_HEADERS}
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


# --- surrit.com 세그먼트 직접 다운로드 ---
# yt-dlp는 세그먼트 요청에 Sec-Fetch 헤더를 싣지 않아 403이 난다. 마스터가 통과하는 방식
# (curl_cffi + 크로스사이트 헤더) 그대로 변형 m3u8과 세그먼트를 직접 받아 합친다 (쿠키 불필요).
from concurrent.futures import ThreadPoolExecutor


def _fetch_segment(seg_url, headers):
    last = None
    for _ in range(2):
        for tgt in IMPERSONATE_TARGETS:
            try:
                r = cffi_requests.get(seg_url, impersonate=tgt, headers=headers, timeout=30)
                if r.status_code == 200:
                    return r.content
                last = f'HTTP {r.status_code}'
            except Exception as e:
                last = str(e)
    raise ValueError(f'세그먼트 실패({last}): {seg_url}')


def _download_hls_direct(task_id, variant_url, headers, ts_path):
    """변형 m3u8을 받아 세그먼트를 curl_cffi로 직접 내려받아 ts_path에 순서대로 이어붙인다."""
    r = None
    for tgt in IMPERSONATE_TARGETS:
        r = cffi_requests.get(variant_url, impersonate=tgt, headers=headers, timeout=20)
        if r.status_code == 200 and '#EXT' in r.text:
            break
    if not r or r.status_code != 200 or '#EXT' not in r.text:
        raise ValueError(f'변형 m3u8 응답 이상: {r.status_code if r else "?"}')
    base = variant_url.rsplit('/', 1)[0] + '/'
    seg_urls = [
        (s if s.startswith('http') else base + s)
        for s in (ln.strip() for ln in r.text.splitlines())
        if s and not s.startswith('#')
    ]
    total = len(seg_urls)
    if total == 0:
        raise ValueError('세그먼트가 없습니다')
    print(f'[직접 다운로드] 세그먼트 {total}개', flush=True)
    with open(ts_path, 'wb') as f, ThreadPoolExecutor(max_workers=8) as ex:
        BATCH = 16
        for start in range(0, total, BATCH):
            if task_id not in tasks:
                raise DownloadCancelled()
            batch = seg_urls[start:start + BATCH]
            for data in ex.map(lambda u: _fetch_segment(u, headers), batch):
                f.write(data)
            tasks[task_id]['progress'] = f'{int(min(start + BATCH, total) * 100 / total)}%'


def _pick_format(formats, quality):
    fmts = sorted([f for f in formats if f.get('url')], key=lambda f: f.get('height') or 0)
    if not fmts:
        return None
    if not quality or quality == 'best':
        return fmts[-1]
    try:
        target = int(quality)
        under = [f for f in fmts if (f.get('height') or 0) <= target]
        return under[-1] if under else fmts[0]
    except Exception:
        return fmts[-1]


def _safe_filename(info, ext='mp4'):
    vid = info.get('id') or 'video'
    title = re.sub(r'[\\/:*?"<>|\n\r\t]', '', (info.get('title') or vid)).strip()[:60]
    return f'[{vid}] {title}.{ext}'


def _cleanup_temp_files():
    """이전 실행에서 중간에 끊긴 숨김 임시파일(.*.part.ts)을 정리한다."""
    try:
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith('.') and f.endswith('.part.ts'):
                try:
                    os.remove(os.path.join(DOWNLOAD_DIR, f))
                    print(f'[System] 미완료 임시파일 제거: {f}', flush=True)
                except OSError:
                    pass
    except OSError:
        pass


# --- 다운로드 함수 ---
def download_video(task_id, url):
    try:
        # 1. 추출만 (다운로드는 직접 처리) — MyCustomMissAV가 변형 m3u8 URL + 헤더를 준다
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'proxy': None},
                              auto_init=False) as ydl:
            ydl.add_info_extractor(MyCustomMissAV())
            print(f"[Download] 시작: {url}", flush=True)
            info = ydl.extract_info(url, download=False)

        fmt = _pick_format(info.get('formats', []), settings.get('video_quality', 'best'))
        if not fmt:
            raise ValueError('사용 가능한 화질이 없습니다')
        variant_url = fmt['url']
        headers = dict(fmt.get('http_headers') or {})
        for k, v in CROSS_SITE_HEADERS.items():
            headers.setdefault(k, v)
        print(f"[선택] {fmt.get('height')}p -> {variant_url}", flush=True)

        out_name = _safe_filename(info)
        out_path = os.path.join(DOWNLOAD_DIR, out_name)
        # 숨김 임시파일(다운로드 목록에 안 보임). 세그먼트를 다 받은 뒤 mp4로 리먹스한다.
        ts_path = os.path.join(DOWNLOAD_DIR, f'.{info.get("id") or "video"}.part.ts')

        # 2. 세그먼트 직접 다운로드
        _download_hls_direct(task_id, variant_url, headers, ts_path)
        if task_id not in tasks:
            if os.path.exists(ts_path):
                os.remove(ts_path)
            return

        # 3. mp4로 리먹스 (실패하면 원본 ts로 폴백)
        tasks[task_id]['progress'] = '99%'
        print('[ffmpeg] mp4 리먹스 중...', flush=True)
        proc = subprocess.run(
            ['ffmpeg', '-y', '-loglevel', 'error', '-i', ts_path, '-c', 'copy', out_path],
            capture_output=True, text=True,
        )
        if proc.returncode == 0 and os.path.exists(out_path):
            if os.path.exists(ts_path):
                os.remove(ts_path)
        else:
            print(f'[ffmpeg] 리먹스 실패(코드 {proc.returncode}) → ts로 저장: {(proc.stderr or "")[:300]}', flush=True)
            out_name = _safe_filename(info, ext='ts')
            out_path = os.path.join(DOWNLOAD_DIR, out_name)
            os.replace(ts_path, out_path)

        if task_id in tasks:
            tasks[task_id]['status'] = '완료'
            tasks[task_id]['progress'] = '100%'
            tasks[task_id]['filename'] = out_name
            try:
                tasks[task_id]['filesize'] = os.path.getsize(out_path)
            except OSError:
                pass
        print(f"[완료] {out_name}", flush=True)
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

_cleanup_temp_files()
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

@app.route('/api/tasks/<task_id>/retry', methods=['POST'])
def retry_task(task_id):
    """실패/취소된 작업을 같은 URL로 다시 큐에 넣어 재시도한다."""
    if task_id not in tasks:
        return jsonify({"status": "error", "message": "작업 없음"}), 404
    cur = tasks[task_id].get('status', '')
    if cur in ('다운로드 중', '대기 중'):
        return jsonify({"status": "error", "message": "이미 진행 중인 작업"}), 400
    tasks[task_id]['status'] = '대기 중'
    tasks[task_id]['progress'] = '0%'
    download_queue.put(task_id)
    print(f"[Retry] 재시도 큐 추가: {tasks[task_id].get('url')}", flush=True)
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
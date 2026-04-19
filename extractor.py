import re
from urllib.parse import urlparse
from yt_dlp.extractor.common import InfoExtractor
from curl_cffi import requests as cffi_requests

# Default settings for extractor (fallback if not provided)
DEFAULT_MIRRORS = ['missav.ai', 'missav.net', 'missav123.com', 'missav.com', 'missav.ws']
SPOOFDPI_PROXY = "http://127.0.0.1:8080"

class MyCustomMissAV(InfoExtractor):
    IE_NAME = 'custom_missav'
    _VALID_URL = r'https?://(?:[^/]+\.)?missav\.[^/]+/(?:[^/]+/)?(?P<id>[^/?#]+)'

    def __init__(self, settings=None):
        super().__init__()
        self._settings = settings or {}
        self._spoofdpi_proxy = SPOOFDPI_PROXY

    def _real_extract(self, url):
        video_id = self._match_id(url)
        print(f'🔥 [Logic Start] Target: {url}', flush=True)

        parsed_url = urlparse(url)
        path = parsed_url.path
        mirrors = [parsed_url.netloc] + self._settings.get('mirrors', DEFAULT_MIRRORS)
        mirrors = list(dict.fromkeys(mirrors))

        webpage = None
        used_url = url

        for mirror in mirrors:
            test_url = f"https://{mirror}{path}"
            proxy_list = [self._spoofdpi_proxy, None] if self._settings.get('spoofdpi_enabled', True) else [None]
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
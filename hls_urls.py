"""Extract the player's CDN URLs without executing page JavaScript."""

import re
from html import unescape
from urllib.parse import urljoin, urlsplit

from yt_dlp.utils import decode_packed_codes


def playlist_candidates(webpage, page_url):
    scripts = re.findall(r'<script\b[^>]*>(.*?)</script>', webpage, re.S | re.I)
    decoded = []
    for script in scripts:
        if 'eval(function(p,a,c,k,e,' in script:
            try:
                decoded.append(decode_packed_codes(script))
            except (AttributeError, IndexError, KeyError, ValueError):
                # A broken/unrelated packed script must not hide plain player URLs.
                continue

    text = unescape('\n'.join(decoded + [webpage]))
    text = text.replace(r'\/', '/').replace(r"\'", "'").replace(r'\"', '"')
    urls = re.findall(r'''(?:https?:)?//[^\s"'<>\\]+\.m3u8(?:\?[^\s"'<>\\]*)?''', text)
    urls = list(dict.fromkeys(urljoin(page_url, url) for url in urls))
    masters = [url for url in urls if urlsplit(url).path.endswith('/playlist.m3u8')]
    if masters:
        urls = masters
    elif not urls:
        # Older pages expose only thumbnail URLs. Preserve their CDN host and UUID.
        bases = re.findall(
            r'(?:https?:)?//[^\s"\'<>\\/]+/'
            r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}/seek/', text)
        urls = [urljoin(page_url, base[:-len('seek/')] + 'playlist.m3u8') for base in bases]

    candidates = []
    for url in urls:
        candidates.append(url)
        parsed = urlsplit(url)
        if parsed.hostname == 'surrit.com':
            # Some mirrors still serve the old host after the CDN migration.
            candidates.append(parsed._replace(netloc='c.surrit.com').geturl())
    return list(dict.fromkeys(candidates))


def playlist_entries(playlist, playlist_url):
    """Resolve relative, root-relative and absolute HLS URIs against the final URL."""
    return [urljoin(playlist_url, line)
            for line in map(str.strip, playlist.splitlines())
            if line and not line.startswith('#')]

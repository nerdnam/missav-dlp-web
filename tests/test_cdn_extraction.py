import importlib
import builtins
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import mock_open, patch

import yt_dlp


class CDNExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import without starting workers, SpoofDPI, or accessing saved user tasks.
        real_open, real_exists, real_listdir = builtins.open, os.path.exists, os.listdir
        runtime_paths = {os.path.normpath('/downloads'),
                         os.path.normpath('/downloads/.settings.json'),
                         os.path.normpath('/downloads/.tasks.json')}
        fake_open = mock_open(read_data='{}')

        def isolated_open(path, *args, **kwargs):
            if isinstance(path, (str, os.PathLike)) and os.path.normpath(path) in runtime_paths:
                return fake_open(path, *args, **kwargs)
            return real_open(path, *args, **kwargs)

        with patch('builtins.open', side_effect=isolated_open), \
                patch('os.path.exists', side_effect=lambda p: os.path.normpath(p) in runtime_paths or real_exists(p)), \
                patch('os.listdir', side_effect=lambda p='.': [] if os.path.normpath(p) in runtime_paths else real_listdir(p)), \
                patch('subprocess.Popen', side_effect=FileNotFoundError), \
                patch('threading.Thread.start'):
            cls.app = importlib.import_module('app')

    def setUp(self):
        self.config = patch.dict(self.app.settings, {'spoofdpi_enabled': False, 'mirrors': [],
                                                    'cf_cookie': '', 'cf_user_agent': ''})
        self.config.start()
        self.addCleanup(self.config.stop)

    @staticmethod
    def response(url, body, status=200):
        return SimpleNamespace(url=url, text=body, status_code=status)

    def extract(self, source, manifest_url, body, legacy_error=False):
        page_url = 'https://missav01.com/ko/example'
        responses = [self.response(page_url, f'<script>source="{source}"</script>')]
        if legacy_error:
            responses.append(self.response(source, '<Error><Code>BucketPunish</Code></Error>', 403))
        responses.append(self.response(manifest_url, body))
        with patch.object(self.app.cffi_requests, 'get', side_effect=responses) as get, \
                yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}, auto_init=False) as ydl:
            extractor = self.app.MyCustomMissAV(ydl)
            info = extractor._real_extract(page_url)
        return info, get

    def test_legacy_403_retries_current_cdn_and_keeps_it_for_variants(self):
        old = 'https://surrit.com/id/playlist.m3u8'
        current = 'https://c.surrit.com/id/playlist.m3u8'
        body = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1280x720\n720p/video.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1920x1080\n/id/1080p/video.m3u8\n'
        info, get = self.extract(old, current, body, legacy_error=True)
        self.assertEqual([c.args[0] for c in get.call_args_list[1:]], [old, current])
        self.assertEqual([f['url'] for f in info['formats']], [
            'https://c.surrit.com/id/1080p/video.m3u8',
            'https://c.surrit.com/id/720p/video.m3u8'])
        self.assertEqual(self.app._pick_format(info['formats'], '720')['height'], 720)
        self.assertEqual(info['formats'][0]['http_headers']['Referer'], 'https://missav01.com/')

    def test_redirected_manifest_resolves_variants_against_final_url(self):
        source = 'https://c.surrit.com/id/playlist.m3u8'
        final = 'https://edge.example/redirected/id/playlist.m3u8'
        info, get = self.extract(source, final,
                                '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1920x1080\n1080p/video.m3u8\n')
        self.assertEqual(get.call_args_list[1].args[0], source)
        self.assertEqual(info['formats'][0]['url'], 'https://edge.example/redirected/id/1080p/video.m3u8')

    def test_media_playlist_is_not_mistaken_for_a_master(self):
        source = 'https://c.surrit.com/id/1080p/video.m3u8'
        info, _ = self.extract(source, source, '#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\nvideo0.jpeg\n#EXT-X-ENDLIST\n')
        self.assertEqual([f['url'] for f in info['formats']], [source])

    def test_failed_cdn_reports_storage_error_without_yt_dlp_network_fallback(self):
        page_url = 'https://missav01.com/ko/example'
        page = self.response(page_url, '<script>source="https://surrit.com/id/playlist.m3u8"</script>')
        error = self.response('https://c.surrit.com/id/playlist.m3u8', '<Code>BucketPunish</Code>', 403)
        with patch.object(self.app.cffi_requests, 'get', side_effect=[page, error, error]), \
                yt_dlp.YoutubeDL({'quiet': True}, auto_init=False) as ydl:
            with self.assertRaisesRegex(ValueError, 'c.surrit.com: HTTP 403 .*BucketPunish'):
                self.app.MyCustomMissAV(ydl)._real_extract(page_url)

    def test_downloader_uses_redirected_variant_base_for_segments(self):
        body = '#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\nvideo0.jpeg\n#EXTINF:6,\n/id/video1.jpeg\n#EXT-X-ENDLIST\n'
        response = self.response('https://edge.example/id/1080p/video.m3u8', body)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(self.app, 'DOWNLOAD_DIR', directory), \
                patch.dict(self.app.tasks, {'test': {'progress': '0%'}}, clear=True), \
                patch.object(self.app.cffi_requests, 'get', return_value=response), \
                patch.object(self.app, '_fetch_segment', return_value=b'test-segment') as fetch, \
                patch.object(self.app.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr='test')):
            output = self.app._download_hls_resumable('test', 'https://c.surrit.com/id/1080p/video.m3u8', {},
                                                    os.path.join(directory, 'video.mp4'))
            self.assertEqual({c.args[0] for c in fetch.call_args_list}, {
                'https://edge.example/id/1080p/video0.jpeg', 'https://edge.example/id/video1.jpeg'})
            with open(output, 'rb') as file:
                self.assertEqual(file.read(), b'test-segment' * 2)


if __name__ == '__main__':
    unittest.main()

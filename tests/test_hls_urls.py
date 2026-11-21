import unittest

from hls_urls import playlist_candidates, playlist_entries


class PlaylistURLTests(unittest.TestCase):
    PAGE = 'https://missav.example/ko/example'
    UUID = '11111111-2222-3333-4444-555555555555'

    def test_current_cdn_preserved(self):
        url = f'https://c.surrit.com/{self.UUID}/playlist.m3u8?token=abc&x=1'
        page = '<script>source="' + url.replace('&', '&amp;').replace('/', r'\/') + '";</script>'
        self.assertEqual(playlist_candidates(page, self.PAGE), [url])

    def test_legacy_host_has_migration_fallback(self):
        old = f'https://surrit.com/{self.UUID}/playlist.m3u8?token=abc'
        self.assertEqual(playlist_candidates(f'<script>source="{old}"</script>', self.PAGE),
                         [old, old.replace('//surrit.com/', '//c.surrit.com/')])

    def test_packed_player_source_wins_over_thumbnail_uuid(self):
        packed = r"""<script>eval(function(p,a,c,k,e,d){return p;}('0=\'1://2.3/4/5.6\';',7,7,'source|https|c.surrit|com|correct-video|playlist|m3u8'.split('|'),0,{}))</script>"""
        page = packed + f'<script>thumb="https://surrit.com/{self.UUID}/seek/_0.jpg"</script>'
        self.assertEqual(playlist_candidates(page, self.PAGE),
                         ['https://c.surrit.com/correct-video/playlist.m3u8'])

    def test_thumbnail_fallback_keeps_host(self):
        page = f'<script>thumb="https://c.surrit.com/{self.UUID}/seek/_0.jpg"</script>'
        self.assertEqual(playlist_candidates(page, self.PAGE),
                         [f'https://c.surrit.com/{self.UUID}/playlist.m3u8'])

    def test_unrelated_uuid_does_not_generate_a_video_url(self):
        self.assertEqual(playlist_candidates(f'<script>tracking_id="{self.UUID}"</script>', self.PAGE), [])

    def test_master_preferred_over_variant(self):
        page = '<script>source="https://cdn.example/id/playlist.m3u8"; source720="https://cdn.example/id/720p/video.m3u8"</script>'
        self.assertEqual(playlist_candidates(page, self.PAGE), ['https://cdn.example/id/playlist.m3u8'])

    def test_non_surrit_cdn_not_rewritten(self):
        url = 'https://cdn.example/id/playlist.m3u8'
        self.assertEqual(playlist_candidates(f'<script>source="{url}"</script>', self.PAGE), [url])

    def test_segment_url_forms_and_query_strings(self):
        playlist = '#EXTM3U\n#EXTINF:6,\nvideo0.jpeg?token=abc\n../video1.jpeg\n/id/video2.jpeg\n//other.example/video3.jpeg\nhttps://other.example/video4.jpeg\n'
        self.assertEqual(playlist_entries(playlist, 'https://c.surrit.com/id/1080p/video.m3u8'), [
            'https://c.surrit.com/id/1080p/video0.jpeg?token=abc',
            'https://c.surrit.com/id/video1.jpeg',
            'https://c.surrit.com/id/video2.jpeg',
            'https://other.example/video3.jpeg',
            'https://other.example/video4.jpeg',
        ])


if __name__ == '__main__':
    unittest.main()

import json
import logging

import httpretty
import mock

from hathor.exc import HathorException, FunctionUndefined
from hathor.podcast import urls
from hathor.podcast.archive import ArchiveInterface, RSSManager, SoundcloudManager, YoutubeManager
from hathor import utils

from tests import utils as test_utils
from tests.podcasts.data import rss_feed
from tests.podcasts.data import soundcloud_one_track_cant_download
from tests.podcasts.data import soundcloud_one_track
from tests.podcasts.data import youtube_archive1
from tests.podcasts.data import youtube_one_item_not_video

class TestArchive(test_utils.TestHelper):
    def test_archive_interface(self):
        manager = ArchiveInterface(logging, None, None)
        with self.assertRaises(FunctionUndefined) as error:
            manager.broadcast_update('foo')
        self.check_error_message('No broadcast update for class', error)
        with self.assertRaises(FunctionUndefined) as error:
            manager.episode_download('foo', 'bar')
        self.check_error_message('No episode download for class', error)

    @httpretty.activate
    def test_soundcloud_error_status_not_200(self):
        sound_id = '123'
        broadcast = 'foo'
        manager = SoundcloudManager(logging, sound_id, None)
        url = urls.soundcloud_track_list(broadcast, sound_id)
        code = 400
        httpretty.register_uri(httpretty.GET, url, body=json.dumps(soundcloud_one_track.DATA), status=code)
        with self.assertRaises(HathorException) as error:
            manager.broadcast_update(broadcast)
        self.assertTrue('Error getting soundcloud track list, request error:%s' % code, error)

    @httpretty.activate
    def test_youtube_error_is_400(self):
        google_key = '123'
        broadcast = 'foo'
        manager = YoutubeManager(logging, None, google_key)
        url = urls.youtube_channel_get(broadcast, google_key)
        code = 400
        httpretty.register_uri(httpretty.GET, url, body=json.dumps(youtube_archive1.DATA), status=code)
        with self.assertRaises(HathorException) as error:
            manager.broadcast_update(broadcast)
        self.check_error_message('Invalid status code:%s' % code, error)

    @httpretty.activate
    def test_rss_feed(self):
        url = 'http://example.%s.com' % utils.random_string()
        manager = RSSManager(logging, None, None)
        httpretty.register_uri(httpretty.GET, url, body=rss_feed.DATA)
        episodes = manager.broadcast_update(url)
        self.assert_length(episodes, 12)
        for ep in episodes:
            self.assert_dictionary(ep)

    @httpretty.activate
    def test_rss_feed_non_200(self):
        url = 'http://example1.%s.com' % utils.random_string()
        manager = RSSManager(logging, None, None)
        httpretty.register_uri(httpretty.GET, url, body=rss_feed.DATA, status=400)
        with self.assertRaises(HathorException) as error:
            manager.broadcast_update(url)
        self.check_error_message('Getting invalid status code:400 for rss feed', error)

    @httpretty.activate
    def test_soundcloud_broadcast_update_skip_cant_download(self):
        sound_id = '123'
        broadcast = 'foo'
        manager = SoundcloudManager(logging, sound_id, None)
        url = urls.soundcloud_track_list(broadcast, sound_id)
        httpretty.register_uri(httpretty.GET, url, body=json.dumps(soundcloud_one_track_cant_download.DATA))
        episodes = manager.broadcast_update(broadcast)
        self.assert_length(episodes, 0)

    @httpretty.activate
    def test_youtube_do_not_download_non_videos(self):
        broadcast = utils.random_string()
        google_key = utils.random_string()
        manager = YoutubeManager(logging, None, google_key)
        url = urls.youtube_channel_get(broadcast,
                                       google_key)
        httpretty.register_uri(httpretty.GET, url, body=json.dumps(youtube_one_item_not_video.DATA),
                               content_type='application/json')
        with mock.patch('youtube_dl.YoutubeDL', side_effect=test_utils.youtube_mock):
            episodes = manager.broadcast_update(broadcast)
            self.assert_length(episodes, 0)

import json
import logging
from tempfile import TemporaryDirectory
from time import time

from pathlib import Path
import pytest

from hathor.client import HathorClient
from hathor.exc import HathorException, FunctionUndefined
from hathor.podcast.archive import ArchiveInterface, RSSManager, YoutubeManager
from hathor.podcast.archive import curl_download, verify_title_filters
from hathor import utils

from tests import utils as test_utils
from tests.podcasts.data import rss_feed
from tests.podcasts.data import youtube_archive1
from tests.podcasts.data import youtube_one_item_not_video

class RequestsMockObject():
    def __init__(self, headers, audio_file):
        self.headers = headers
        self.audio_file = audio_file

    def iter_content(self, chunk_size: int = None):
        return [Path(self.audio_file).read_bytes()]


def requests_get_mock(url, audio_file, **kwargs):
    def func(url, **kwargs):
        print('Requests mock', url, kwargs)
        return RequestsMockObject({
            'content-type': 'audio/mpeg',
        },
        audio_file)
    return func

def test_curl_download(mocker):
    client = HathorClient()
    with TemporaryDirectory() as tmp_dir:
        parse_mock = mocker.patch('hathor.podcast.archive.parse')
        parse_mock.return_value = {
            'feed': {
                'link': 'https://example.foo'
            },
            'entries': [
                {
                    'link': 'https://example.foo/download1',
                    'title': 'Episode 0',
                    'published_parsed': time(),
                },
            ]
        }
        client.podcast_create('rss', 'https://example.foo', 'temp', file_location=tmp_dir)
        client.episode_sync()
        episode_list = client.episode_list(only_files=False)
        with test_utils.temp_audio_file() as temp_audio_file:
            requests_mock = mocker.patch('hathor.podcast.archive.get', side_effect=requests_get_mock('https://example.foo/download1', temp_audio_file))
            client.episode_download([episode_list[0]['id']])
            episode_list = client.episode_list()
            assert 'Episode 0.mp3' in episode_list[0]['file_path']
            path = Path(episode_list[0]['file_path'])
            assert path.exists()

def test_title_filters():
    no_filters = verify_title_filters([], 'foo')
    assert no_filters == True
    good_filter = verify_title_filters([r'^foo$'], 'foo')
    assert good_filter == True
    bad_filter = verify_title_filters([r'^foo$'], 'bar')
    assert bad_filter == False

def test_archive_interface():
    manager = ArchiveInterface(logging)
    with pytest.raises(FunctionUndefined) as error:
        manager.broadcast_update('foo')
    assert 'No broadcast update for class' in str(error.value)
    with pytest.raises(FunctionUndefined) as error:
        manager.episode_download('foo')
    assert 'No episode download for class' in str(error.value)

def test_rss_interface_broadcast_update(mocker):
    manager = RSSManager(logging)
    parse_mock = mocker.patch('hathor.podcast.archive.parse')
    parse_mock.return_value = {
        'feed': {
            'link': 'https://example.foo'
        },
        'entries': [
            {
                'link': 'https://example.foo/download1',
                'title': 'Episode 0',
                'published_parsed': time(),
            },
        ]
    }
    episode_list = manager.broadcast_update('https://example.foo')
    assert episode_list[0]['title'] == 'Episode 0'

def test_rss_interface_broadcast_update_max_results(mocker):
    manager = RSSManager(logging)
    parse_mock = mocker.patch('hathor.podcast.archive.parse')
    parse_mock.return_value = {
        'feed': {
            'link': 'https://example.foo'
        },
        'entries': [
            {
                'link': 'https://example.foo/download1',
                'title': 'Episode 0',
                'published_parsed': time(),
            },
            {
                'link': 'https://example.foo/download2',
                'title': 'Episode 1',
                'published_parsed': time(),
            },
        ]
    }
    episode_list = manager.broadcast_update('https://example.foo', max_results=1)
    assert episode_list[0]['title'] == 'Episode 0'
    assert len(episode_list) == 1

def test_rss_interface_broadcast_update_filters(mocker):
    manager = RSSManager(logging)
    parse_mock = mocker.patch('hathor.podcast.archive.parse')
    parse_mock.return_value = {
        'feed': {
            'link': 'https://example.foo'
        },
        'entries': [
            {
                'link': 'https://example.foo/download1',
                'title': 'Episode 0',
                'published_parsed': time(),
            },
            {
                'link': 'https://example.foo/download2',
                'title': 'Episode 1',
                'published_parsed': time(),
            },
        ]
    }
    episode_list = manager.broadcast_update('https://example.foo', filters=[r'^Episode 1'])
    assert episode_list[0]['title'] == 'Episode 1'
    assert len(episode_list) == 1

def test_rss_invalid_feed(mocker):
    manager = RSSManager(logging)
    parse_mock = mocker.patch('hathor.podcast.archive.parse')
    parse_mock.return_value = {
        'entries': [
            {
                'link': 'https://example.foo/download1',
                'title': 'Episode 0',
                'published_parsed': time(),
            },
            {
                'link': 'https://example.foo/download2',
                'title': 'Episode 1',
                'published_parsed': time(),
            },
        ]
    }
    with pytest.raises(HathorException) as error:
        manager.broadcast_update('https://example.foo')
    assert 'Invalid data from rss feed' in str(error.value)

def test_rss_invalid_link(mocker):
    manager = RSSManager(logging)
    parse_mock = mocker.patch('hathor.podcast.archive.parse')
    parse_mock.return_value = {
        'feed': {
            'link': 'https://example.foo'
        },
        'entries': [
            {
                'title': 'Episode 0',
                'published_parsed': time(),
            },
            {
                'link': 'https://example.foo/download2',
                'title': 'Episode 1',
                'published_parsed': time(),
            },
        ]
    }
    episode_list = manager.broadcast_update('https://example.foo')
    assert episode_list[0]['title'] == 'Episode 1'
    assert len(episode_list) == 1

def test_ress_interface_episode_download(mocker):
    manager = RSSManager(logging)
    with test_utils.temp_audio_file() as temp_audio_file:
        requests_mock = mocker.patch('hathor.podcast.archive.get', side_effect=requests_get_mock('https://example.foo/download1', temp_audio_file))
        with TemporaryDirectory() as temp_dir:
            path, size = manager.episode_download('https://example.foo/download1', f'{temp_dir}/episode0')
            assert size == Path(path).stat().st_size
            assert 'episode0.mp3' in str(path)

def test_youtube_no_google_key_given():
    with pytest.raises(HathorException) as error:
        YoutubeManager(logging)
    assert 'Google API Key not passed' in str(error.value)

class MockYoutubeRequest():
    def __init__(self):
        pass
    
    def execute(self):
        return {
            'items': [
                'foo'
            ]
        }

class MockYoutubeSearch():
    def __init__(self):
        pass
    
    def list(self, **kwargs):
        return MockYoutubeRequest()

class MockYoutube():
    def __init__(self):
        self.search = MockYoutubeSearch()

def google_api_build(typer, version, developerKey=None):
    return MockYoutube()

def test_youtube_brodcast_update(mocker):
    manager = YoutubeManager(logging, google_api_key='derp')
    mocker.patch('hathor.podcast.archive.build', side_effect=google_api_build)
    manager.broadcast_update('foo')

'''
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
        self.assert_length(episodes, 6)
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
    def test_youtube_do_not_download_non_videos(self):
        broadcast = utils.random_string()
        google_key = utils.random_string()
        manager = YoutubeManager(logging, None, google_key)
        url = urls.youtube_channel_get(broadcast,
                                       google_key)
        httpretty.register_uri(httpretty.GET, url, body=json.dumps(youtube_one_item_not_video.DATA),
                               content_type='application/json')
        episodes = manager.broadcast_update(broadcast)
        self.assert_length(episodes, 0)
'''
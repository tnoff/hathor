from contextlib import contextmanager
from datetime import datetime, timezone
import logging
from tempfile import TemporaryDirectory
from time import struct_time

from pathlib import Path
import pytest
from yt_dlp.utils import DownloadError

from hathor.client import HathorClient
from hathor.exc import HathorException, FunctionUndefined
from hathor.podcast.archive import ArchiveInterface, RSSManager, YoutubeManager
from hathor.podcast.archive import verify_title_filters

from tests import utils as test_utils
from tests.data.rss_feed import SIMPLE_RSS_FEED

RSS_FEED_INVALID_URL = {
    'feed': {
        'link': 'https://example.foo'
    },
    'entries': [
        {
            'links': [
                {
                    'href': 'https://example.foo/download1-no-extension',
                    'type': 'audio/mpeg',
                }
            ],
            'title': 'Episode 0',
            'published_parsed': struct_time((2024, 12, 11, 22, 40, 1, 2, 346, -1)),
            'id': '123456'
        },
    ]
}

class RequestsMockObject():
    def __init__(self, headers, audio_file):
        self.headers = headers
        self.audio_file = audio_file

    def iter_content(self, chunk_size: None): #pylint:disable=unused-argument
        return [Path(self.audio_file).read_bytes()]


def requests_get_mock(_url, audio_file, **_):
    def func(_url, **_):
        return RequestsMockObject({
            'content-type': 'audio/mpeg',
        },
        audio_file)
    return func

def requests_get_mock_no_content(_url, audio_file, **_):
    def func(_url, **_):
        return RequestsMockObject({}, audio_file)
    return func

def test_curl_download(mocker):
    client = HathorClient()
    with TemporaryDirectory() as tmp_dir:
        parse_mock = mocker.patch('hathor.podcast.archive.parse')
        parse_mock.return_value = SIMPLE_RSS_FEED
        client.podcast_create('rss', 'https://example.foo', 'temp', file_location=tmp_dir)
        client.episode_sync()
        episode_list = client.episode_list(only_files=False)
        with test_utils.temp_audio_file() as temp_audio_file:
            mocker.patch('hathor.podcast.archive.get', side_effect=requests_get_mock('https://example.foo/download1', temp_audio_file))
            client.episode_download([episode_list[0]['id']])
            episode_list = client.episode_list()
            assert 'Episode_1.mp3' in episode_list[0]['file_path']
            path = Path(episode_list[0]['file_path'])
            assert path.exists()

def test_curl_download_no_content_type(mocker):
    client = HathorClient()
    with TemporaryDirectory() as tmp_dir:
        parse_mock = mocker.patch('hathor.podcast.archive.parse')
        parse_mock.return_value = SIMPLE_RSS_FEED
        client.podcast_create('rss', 'https://example.foo', 'temp', file_location=tmp_dir)
        client.episode_sync()
        episode_list = client.episode_list(only_files=False)
        with test_utils.temp_audio_file() as temp_audio_file:
            mocker.patch('hathor.podcast.archive.get', side_effect=requests_get_mock_no_content('https://example.foo/download1', temp_audio_file))
            client.episode_download([episode_list[0]['id']])
            episode_list = client.episode_list()
            assert 'Episode_1.mp3' in episode_list[0]['file_path']
            path = Path(episode_list[0]['file_path'])
            assert path.exists()

def test_curl_download_invalid_type(mocker):
    client = HathorClient()
    with TemporaryDirectory() as tmp_dir:
        parse_mock = mocker.patch('hathor.podcast.archive.parse')
        parse_mock.return_value = RSS_FEED_INVALID_URL
        client.podcast_create('rss', 'https://example.foo', 'temp', file_location=tmp_dir)
        client.episode_sync()
        episode_list = client.episode_list(only_files=False)
        with test_utils.temp_audio_file() as temp_audio_file:
            mocker.patch('hathor.podcast.archive.get', side_effect=requests_get_mock_no_content('https://example.foo/download1-no-extension', temp_audio_file))
            with pytest.raises(HathorException) as error:
                client.episode_download([episode_list[0]['id']])
            assert 'Unable to determine extension type for url' in str(error.value)

def test_title_filters():
    no_filters = verify_title_filters([], 'foo')
    assert no_filters is True
    good_filter = verify_title_filters([r'^foo$'], 'foo')
    assert good_filter is True
    bad_filter = verify_title_filters([r'^foo$'], 'bar')
    assert bad_filter is False

def test_archive_interface():
    manager = ArchiveInterface(logging)
    with pytest.raises(FunctionUndefined) as error:
        manager.broadcast_update('foo')
    assert 'No broadcast update for class' in str(error.value)
    with pytest.raises(FunctionUndefined) as error:
        manager.episode_download('foo', 'bar')
    assert 'No episode download for class' in str(error.value)

def test_rss_interface_broadcast_update(mocker):
    manager = RSSManager(logging)
    parse_mock = mocker.patch('hathor.podcast.archive.parse')
    parse_mock.return_value = SIMPLE_RSS_FEED
    episode_list = manager.broadcast_update('https://example.foo')
    assert episode_list[0]['title'] == 'Episode 0'

def test_rss_interface_broadcast_update_max_results(mocker):
    manager = RSSManager(logging)
    parse_mock = mocker.patch('hathor.podcast.archive.parse')
    parse_mock.return_value = SIMPLE_RSS_FEED
    episode_list = manager.broadcast_update('https://example.foo', max_results=1)
    assert episode_list[0]['title'] == 'Episode 0'
    assert len(episode_list) == 1

def test_rss_interface_broadcast_update_filters(mocker):
    manager = RSSManager(logging)
    parse_mock = mocker.patch('hathor.podcast.archive.parse')
    parse_mock.return_value = SIMPLE_RSS_FEED
    episode_list = manager.broadcast_update('https://example.foo', filters=[r'^Episode 1'])
    assert episode_list[0]['title'] == 'Episode 1'
    assert len(episode_list) == 1

def test_rss_valid_id(mocker):
    rss_feed_with_id = {
        'feed': {
            'link': 'https://example.foo'
        },
        'entries': [
            {
                'title': 'Episode 0',
                'published_parsed': struct_time((2024, 12, 11, 22, 40, 1, 2, 346, -1)),
                'id': 'https://example.foo/download1.mp3'
            },
        ]
    }
    manager = RSSManager(logging)
    parse_mock = mocker.patch('hathor.podcast.archive.parse')
    parse_mock.return_value = rss_feed_with_id
    episode_list = manager.broadcast_update('https://example.foo')
    assert episode_list[0]['title'] == 'Episode 0'
    assert len(episode_list) == 1

def test_rss_invalid_feed(mocker):
    manager = RSSManager(logging)
    parse_mock = mocker.patch('hathor.podcast.archive.parse')
    parse_mock.return_value = {
        'entries': [
            {
                'link': 'https://example.foo/download1',
                'title': 'Episode 0',
                'published_parsed': struct_time((2024, 12, 11, 22, 40, 1, 2, 346, -1)),
            },
            {
                'link': 'https://example.foo/download2',
                'title': 'Episode 1',
                'published_parsed': struct_time((2024, 12, 11, 23, 40, 1, 2, 346, -1)),
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
                'published_parsed': struct_time((2024, 12, 11, 22, 40, 1, 2, 346, -1)),
            },
            {
                'link': 'https://example.foo/download2',
                'title': 'Episode 1',
                'published_parsed': struct_time((2024, 12, 11, 23, 40, 1, 2, 346, -1)),
            },
        ]
    }
    with pytest.raises(HathorException) as error:
        manager.broadcast_update('https://example.foo')
    assert 'Cannot find valid url for episode' in str(error.value)

def test_ress_interface_episode_download(mocker):
    manager = RSSManager(logging)
    with test_utils.temp_audio_file() as temp_audio_file:
        mocker.patch('hathor.podcast.archive.get', side_effect=requests_get_mock('https://example.foo/download1', temp_audio_file))
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
                {
                    'snippet': {
                        'title': 'Episode 0',
                        'publishedAt': datetime.now(timezone.utc).isoformat(),
                        'description': 'foo bar'
                    },
                    'id': {
                        'videoId': '1234ABC',
                    }
                },
                {
                    'snippet': {
                        'title': 'Episode 1',
                        'publishedAt': datetime.now(timezone.utc).isoformat(),
                        'description': 'foo bar 2'
                    },
                    'id': {
                        'videoId': '1234ABCDEFG',
                    }
                },
            ]
        }

class MockYoutubeSearch():
    def __init__(self):
        pass

    def list(self, **_):
        return MockYoutubeRequest()

    def list_next(self, *_, **__):
        return None


class MockYoutube():
    def __init__(self):
        pass

    def search(self):
        return MockYoutubeSearch()

def google_api_build(_typer, _version, developerKey=None): #pylint:disable=invalid-name,unused-argument
    return MockYoutube()

def test_youtube_brodcast_update(mocker):
    manager = YoutubeManager(logging, google_api_key='derp')
    mocker.patch('hathor.podcast.archive.build', side_effect=google_api_build)
    episode_list = manager.broadcast_update('foo')
    assert len(episode_list) == 2

def test_youtube_brodcast_update_max_results(mocker):
    manager = YoutubeManager(logging, google_api_key='derp')
    mocker.patch('hathor.podcast.archive.build', side_effect=google_api_build)
    episode_list = manager.broadcast_update('foo', max_results=1)
    assert len(episode_list) == 1
    assert episode_list[0]['title'] == 'Episode 0'

def test_youtube_brodcast_update_filters(mocker):
    manager = YoutubeManager(logging, google_api_key='derp')
    mocker.patch('hathor.podcast.archive.build', side_effect=google_api_build)
    episode_list = manager.broadcast_update('foo', filters=[r'^Episode 1'])
    assert len(episode_list) == 1
    assert episode_list[0]['title'] == 'Episode 1'

class MockYoutubeDL():
    def __init__(self, temp_audio_file):
        self.temp_audio_file = temp_audio_file

    def extract_info(self, _download_url, download=True): #pylint:disable=unused-argument
        return {
            'requested_downloads': [
                {
                    'filepath': Path(self.temp_audio_file),
                },
            ],
        }

def generate_mock_youtube(temp_audio_file):
    @contextmanager
    def mock_youtube_client(_options):
        yield MockYoutubeDL(temp_audio_file)
    return mock_youtube_client

class MockYoutubeError():
    def __init__(self):
        pass

    def extract_info(self, *args, **kwargs):
        raise DownloadError('issue downloading file')

@contextmanager
def mock_youtube_error(_options):
    yield MockYoutubeError()

def test_youtube_broadcast_download(mocker):
    manager = YoutubeManager(logging, google_api_key='foo123')
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio_file:
        mocker.patch('hathor.podcast.archive.YoutubeDL', side_effect=generate_mock_youtube(temp_audio_file))
        _file_path, size = manager.episode_download('foo', 'bar')
        assert size == Path(temp_audio_file).stat().st_size

def test_youtube_broadcast_download_error(mocker):
    manager = YoutubeManager(logging, google_api_key='foo123')
    mocker.patch('hathor.podcast.archive.YoutubeDL', side_effect=mock_youtube_error)
    file_path, size = manager.episode_download('foo', 'bar')
    assert file_path is None
    assert size is None

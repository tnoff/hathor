from contextlib import contextmanager
from datetime import datetime, timezone
import logging
from pathlib import Path
import random
from tempfile import TemporaryDirectory
from time import struct_time

import pytest
from yt_dlp.utils import DownloadError

from hathor.client import HathorClient
from hathor.exc import EpisodeNotReady, HathorException, FunctionUndefined
from hathor.podcast.archive import ArchiveInterface, RSSManager, TwitchManager
from hathor.podcast.archive import extract_twitch_video_id
from hathor.podcast.archive import twitch_timestamp, verify_title_filters

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

# Keep test function names off exactly 40 characters. Trufflehog's Lob detector
# matches `test_` followed by 35 word characters, so a 40 character test name is
# picked up as a verified Lob key and fails the pr-check:secrets scan.
TWITCH_PUBLISHED_AT = '2026-08-11T17:55:36Z'


class TwitchResponseMock():
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def twitch_video(video_id=None, title='Stream 0', description='a description',
                 thumbnail='https://static.twitch.tv/thumb.jpg',
                 stream_id=None, user_id='555'):
    vid = video_id or str(random.randint(100000, 999999))
    return {
        'id': vid,
        'user_id': user_id,
        'stream_id': stream_id,
        'title': title,
        'description': description,
        'published_at': TWITCH_PUBLISHED_AT,
        'url': f'https://www.twitch.tv/videos/{vid}',
        'thumbnail_url': thumbnail,
    }


def twitch_post_mock(token='token123'):
    def func(_url, params=None, timeout=None): #pylint:disable=unused-argument
        return TwitchResponseMock({'access_token': token, 'expires_in': 5000})
    return func


def twitch_get_mock(routes, calls=None):
    def func(url, params=None, headers=None, timeout=None): #pylint:disable=unused-argument
        endpoint = url.rsplit('/', 1)[-1]
        if calls is not None:
            calls.append((endpoint, dict(params or {}), dict(headers or {})))
        payload = routes[endpoint]
        if callable(payload):
            payload = payload(params or {})
        return TwitchResponseMock(payload)
    return func


def build_twitch_manager(mocker, routes, calls=None, post_mock=None, **kwargs):
    mocker.patch('hathor.podcast.archive.post', side_effect=post_mock or twitch_post_mock())
    mocker.patch('hathor.podcast.archive.get', side_effect=twitch_get_mock(routes, calls))
    return TwitchManager(logging, twitch_client_id='id123',
                         twitch_client_secret='secret123', **kwargs)


def users_route(user_id='555'):
    return {'data': [{'id': user_id, 'login': 'somechannel'}]}


def test_twitch_manager_requires_client_secret():
    with pytest.raises(HathorException) as error:
        TwitchManager(logging, twitch_client_id='id123')
    assert 'Twitch client id and client secret not passed' in str(error.value)


def test_twitch_manager_requires_client_id():
    with pytest.raises(HathorException) as error:
        TwitchManager(logging, twitch_client_secret='secret123')
    assert 'Twitch client id and client secret not passed' in str(error.value)


def test_twitch_manager_ytdlp_options_default_empty(mocker):
    manager = build_twitch_manager(mocker, {})
    assert manager.ytdlp_options == {}


def test_twitch_timestamp_parses_rfc3339():
    parsed = twitch_timestamp(TWITCH_PUBLISHED_AT)
    assert parsed == datetime(2026, 8, 11, 17, 55, 36, tzinfo=timezone.utc)


@pytest.mark.parametrize('url_template,should_match', [
    ('https://www.twitch.tv/videos/{vid}', True),
    ('https://twitch.tv/videos/{vid}', True),
    ('https://www.twitch.tv/videos/{vid}?t=1h2m3s', True),
    ('https://www.twitch.tv/somechannel', False),
    ('https://example.com/videos/{vid}', False),
])
def test_extract_twitch_video_id_from_url_shapes(url_template, should_match):
    vid = str(random.randint(100000, 999999))
    result = extract_twitch_video_id(url_template.format(vid=vid))
    assert result == (vid if should_match else None)


@pytest.mark.parametrize('input_url', ['foo', ''])
def test_extract_twitch_video_id_unparseable_url(input_url):
    assert extract_twitch_video_id(input_url) is None


def test_twitch_broadcast_update(mocker):
    calls = []
    manager = build_twitch_manager(mocker, {
        'users': users_route(),
        'videos': {'data': [twitch_video(title='Stream 0'), twitch_video(title='Stream 1')]},
    }, calls=calls)
    episode_list = manager.broadcast_update('somechannel')
    assert len(episode_list) == 2
    assert episode_list[0]['title'] == 'Stream 0'
    assert episode_list[0]['description'] == 'a description'
    assert episode_list[0]['download_link'].startswith('https://www.twitch.tv/videos/')
    assert episode_list[0]['date'] == datetime(2026, 8, 11, 17, 55, 36, tzinfo=timezone.utc)
    # Past broadcasts only, highlights and uploads are not fetched
    videos_call = [c for c in calls if c[0] == 'videos'][0]
    assert videos_call[1]['type'] == 'archive'
    assert videos_call[1]['user_id'] == '555'
    assert videos_call[2]['Authorization'] == 'Bearer token123'
    assert videos_call[2]['Client-Id'] == 'id123'


def test_twitch_broadcast_update_honors_max_results(mocker):
    manager = build_twitch_manager(mocker, {
        'users': users_route(),
        'videos': {'data': [twitch_video(title='Stream 0'), twitch_video(title='Stream 1')]},
    })
    episode_list = manager.broadcast_update('somechannel', max_results=1)
    assert len(episode_list) == 1
    assert episode_list[0]['title'] == 'Stream 0'


def test_twitch_broadcast_update_filters(mocker):
    manager = build_twitch_manager(mocker, {
        'users': users_route(),
        'videos': {'data': [twitch_video(title='Stream 0'), twitch_video(title='Stream 1')]},
    })
    episode_list = manager.broadcast_update('somechannel', filters=[r'^Stream 1'])
    assert len(episode_list) == 1
    assert episode_list[0]['title'] == 'Stream 1'


def test_twitch_broadcast_update_paginates(mocker):
    def videos(params):
        if not params.get('after'):
            return {
                'data': [twitch_video(title='Stream 0')],
                'pagination': {'cursor': 'cursor123'},
            }
        return {'data': [twitch_video(title='Stream 1')], 'pagination': {}}

    calls = []
    manager = build_twitch_manager(mocker, {
        'users': users_route(),
        'videos': videos,
    }, calls=calls)
    episode_list = manager.broadcast_update('somechannel')
    assert len(episode_list) == 2
    assert [e['title'] for e in episode_list] == ['Stream 0', 'Stream 1']
    videos_calls = [c for c in calls if c[0] == 'videos']
    assert videos_calls[1][1]['after'] == 'cursor123'


def test_twitch_broadcast_update_empty_description(mocker):
    manager = build_twitch_manager(mocker, {
        'users': users_route(),
        'videos': {'data': [twitch_video(description='')]},
    })
    episode_list = manager.broadcast_update('somechannel')
    assert episode_list[0]['description'] is None


def test_twitch_broadcast_update_unknown_channel(mocker):
    manager = build_twitch_manager(mocker, {'users': {'data': []}})
    with pytest.raises(HathorException) as error:
        manager.broadcast_update('nosuchchannel')
    assert 'No twitch channel found for: nosuchchannel' in str(error.value)


def test_twitch_token_is_reused(mocker):
    post_calls = []
    def counting_post(_url, params=None, timeout=None): #pylint:disable=unused-argument
        post_calls.append(params)
        return TwitchResponseMock({'access_token': 'token123'})
    manager = build_twitch_manager(mocker, {
        'users': users_route(),
        'videos': {'data': [twitch_video()]},
    }, post_mock=counting_post)
    manager.broadcast_update('somechannel')
    manager.broadcast_update('somechannel')
    assert len(post_calls) == 1
    assert post_calls[0]['grant_type'] == 'client_credentials'
    assert post_calls[0]['client_secret'] == 'secret123'


class MockTwitchDLError():
    def extract_info(self, *args, **kwargs):
        raise DownloadError('issue downloading file')


@contextmanager
def mock_ytdlp_error(_options):
    yield MockTwitchDLError()


class MockTwitchDL():
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


def generate_mock_twitch(temp_audio_file, captured=None):
    @contextmanager
    def mock_twitch_client(options):
        if captured is not None:
            captured.update(options)
        yield MockTwitchDL(temp_audio_file)
    return mock_twitch_client


def _twitch_url(video_id='123456') -> str:
    return f'https://www.twitch.tv/videos/{video_id}'


def test_twitch_broadcast_download(mocker):
    manager = build_twitch_manager(mocker, {
        'videos': {'data': [twitch_video(video_id='123456')]},
        'streams': {'data': []},
    })
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio_file:
        mocker.patch('hathor.podcast.archive.YoutubeDL',
                     side_effect=generate_mock_twitch(temp_audio_file))
        _file_path, size = manager.episode_download(_twitch_url(), 'bar')
        assert size == Path(temp_audio_file).stat().st_size


def test_twitch_broadcast_download_error(mocker):
    manager = build_twitch_manager(mocker, {
        'videos': {'data': [twitch_video(video_id='123456')]},
    })
    mocker.patch('hathor.podcast.archive.YoutubeDL', side_effect=mock_ytdlp_error)
    file_path, size = manager.episode_download(_twitch_url(), 'bar')
    assert file_path is None
    assert size is None


def test_twitch_download_skips_live_broadcast(mocker):
    manager = build_twitch_manager(mocker, {
        'videos': {'data': [twitch_video(video_id='123456', stream_id='stream999')]},
        'streams': {'data': [{'id': 'stream999'}]},
    })
    yt_mock = mocker.patch('hathor.podcast.archive.YoutubeDL')
    with pytest.raises(EpisodeNotReady) as error:
        manager.episode_download(_twitch_url(), 'bar')
    assert 'Episode not ready for download' in str(error.value)
    yt_mock.assert_not_called()


def test_twitch_download_proceeds_when_other_stream_live(mocker):
    manager = build_twitch_manager(mocker, {
        'videos': {'data': [twitch_video(video_id='123456', stream_id='stream999')]},
        'streams': {'data': [{'id': 'a-newer-stream'}]},
    })
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio_file:
        mocker.patch('hathor.podcast.archive.YoutubeDL',
                     side_effect=generate_mock_twitch(temp_audio_file))
        _file_path, size = manager.episode_download(_twitch_url(), 'bar')
        assert size == Path(temp_audio_file).stat().st_size


def test_twitch_download_skips_vod_still_processing(mocker):
    manager = build_twitch_manager(mocker, {
        'videos': {'data': [twitch_video(
            video_id='123456',
            thumbnail='https://vod-secure.twitch.tv/_404/404_processing_320x180.png')]},
    })
    yt_mock = mocker.patch('hathor.podcast.archive.YoutubeDL')
    with pytest.raises(EpisodeNotReady) as error:
        manager.episode_download(_twitch_url(), 'bar')
    assert 'Episode not ready for download' in str(error.value)
    yt_mock.assert_not_called()


def test_twitch_download_proceeds_when_video_not_found(mocker):
    manager = build_twitch_manager(mocker, {'videos': {'data': []}})
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio_file:
        mocker.patch('hathor.podcast.archive.YoutubeDL',
                     side_effect=generate_mock_twitch(temp_audio_file))
        _file_path, size = manager.episode_download(_twitch_url(), 'bar')
        assert size == Path(temp_audio_file).stat().st_size


def test_twitch_download_proceeds_for_unparseable_url(mocker):
    manager = build_twitch_manager(mocker, {})
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio_file:
        mocker.patch('hathor.podcast.archive.YoutubeDL',
                     side_effect=generate_mock_twitch(temp_audio_file))
        _file_path, size = manager.episode_download('https://example.com/not-a-vod', 'bar')
        assert size == Path(temp_audio_file).stat().st_size


def test_twitch_download_proceeds_when_liveness_check_errors(mocker):
    def boom(*_args, **_kwargs):
        raise RuntimeError('api unreachable')
    mocker.patch('hathor.podcast.archive.post', side_effect=twitch_post_mock())
    mocker.patch('hathor.podcast.archive.get', side_effect=boom)
    manager = TwitchManager(logging, twitch_client_id='id123', twitch_client_secret='secret123')
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio_file:
        mocker.patch('hathor.podcast.archive.YoutubeDL',
                     side_effect=generate_mock_twitch(temp_audio_file))
        _file_path, size = manager.episode_download(_twitch_url(), 'bar')
        assert size == Path(temp_audio_file).stat().st_size


def test_twitch_download_ytdlp_options_override_format(mocker):
    manager = build_twitch_manager(mocker, {
        'videos': {'data': []},
    }, ytdlp_options={'format': 'worst', 'proxy': 'socks5://localhost:1080'})
    captured = {}
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio_file:
        mocker.patch('hathor.podcast.archive.YoutubeDL',
                     side_effect=generate_mock_twitch(temp_audio_file, captured))
        manager.episode_download(_twitch_url(), 'bar')
    assert captured['format'] == 'worst'
    assert captured['proxy'] == 'socks5://localhost:1080'


def test_twitch_download_ytdlp_options_cannot_override_output(mocker):
    manager = build_twitch_manager(mocker, {
        'videos': {'data': []},
    }, ytdlp_options={'outtmpl': 'nope', 'logger': None})
    captured = {}
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio_file:
        mocker.patch('hathor.podcast.archive.YoutubeDL',
                     side_effect=generate_mock_twitch(temp_audio_file, captured))
        manager.episode_download(_twitch_url(), 'bar')
    assert captured['outtmpl'] == 'bar.%(ext)s'
    assert captured['logger'] is logging

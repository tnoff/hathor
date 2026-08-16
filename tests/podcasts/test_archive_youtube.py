from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from json import dumps
import logging
from pathlib import Path
import random
import string

from googleapiclient.errors import HttpError
import pytest
from yt_dlp.utils import DownloadError

from hathor.exc import EpisodeNotReady, HathorException
from hathor.podcast.archive import YoutubeManager, extract_youtube_video_id
from hathor.podcast.archive import youtube_quota_exhausted
from hathor.podcast.archive import YOUTUBE_MAX_PAGES, YOUTUBE_NUM_RETRIES

from tests import utils as test_utils


def test_youtube_no_google_key_given():
    with pytest.raises(HathorException) as error:
        YoutubeManager(logging)
    assert 'Google API Key not passed' in str(error.value)

# A channel id, so YoutubeManager takes the cheap uploads-playlist path
YOUTUBE_CHANNEL = 'UCabcdefghijklmnopqrstuv'


class MockApiRequest():
    def __init__(self, response):
        self._response = response
        self.execute_calls = []

    def execute(self, num_retries=0):
        self.execute_calls.append(num_retries)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class MockApiCollection():
    '''A collection with a single canned response, such as videos() or channels()'''
    def __init__(self, response):
        self._response = response
        self.list_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return MockApiRequest(self._response)


class MockPlaylistItems():
    '''
    Serves the given pages in order. list_next returns None once they run out,
    which is how the google client signals the end of a playlist.
    '''
    def __init__(self, pages):
        self._pages = pages
        self.list_calls = []
        self.requests = []
        self.pages_served = 0

    def _next_request(self):
        page = self._pages[self.pages_served]
        self.pages_served += 1
        request = MockApiRequest(page)
        self.requests.append(request)
        return request

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return self._next_request()

    def list_next(self, _request, _response):
        if self.pages_served >= len(self._pages):
            return None
        return self._next_request()


class MockYoutubeClient():
    '''Stands in for the google api client, with only the collections hathor uses'''
    def __init__(self, pages=None, videos_response=None, channels_response=None):
        self.playlist_items_mock = MockPlaylistItems(pages if pages is not None else [{'items': []}])
        self.videos_mock = MockApiCollection(videos_response if videos_response is not None else {'items': []})
        self.channels_mock = MockApiCollection(channels_response if channels_response is not None else {'items': []})

    def playlistItems(self): #pylint:disable=invalid-name
        return self.playlist_items_mock

    def videos(self):
        return self.videos_mock

    def channels(self):
        return self.channels_mock


def youtube_manager(mocker, client=None, **kwargs):
    '''
    Build a YoutubeManager against a mocked google api client. The patch has to
    land before construction, the manager builds its api client in __init__
    '''
    client = client if client is not None else MockYoutubeClient()
    mocker.patch('hathor.podcast.archive.build', return_value=client)
    kwargs.setdefault('google_api_key', 'derp')
    return YoutubeManager(logging, **kwargs)


def playlist_item(video_id=None, title='Episode 0', description='foo bar', published_at=None):
    return {
        'snippet': {
            'title': title,
            'description': description,
            'resourceId': {'videoId': video_id or random_video_id()},
        },
        'contentDetails': {'videoPublishedAt': published_at or random_past_iso_timestamp()},
    }


def playlist_page(*items):
    return {'items': list(items)}


def watch_url(video_id):
    return f'https://www.youtube.com/watch?v={video_id}'


def test_youtube_broadcast_update(mocker):
    client = MockYoutubeClient(pages=[playlist_page(playlist_item(title='Episode 0'),
                                                    playlist_item(title='Episode 1'))])
    manager = youtube_manager(mocker, client)
    episode_list = manager.broadcast_update(YOUTUBE_CHANNEL)
    assert len(episode_list) == 2


def test_youtube_broadcast_update_max_results(mocker):
    client = MockYoutubeClient(pages=[playlist_page(playlist_item(title='Episode 0'),
                                                    playlist_item(title='Episode 1'))])
    manager = youtube_manager(mocker, client)
    episode_list = manager.broadcast_update(YOUTUBE_CHANNEL, max_results=1)
    assert len(episode_list) == 1
    assert episode_list[0]['title'] == 'Episode 0'


def test_youtube_broadcast_update_filters(mocker):
    client = MockYoutubeClient(pages=[playlist_page(playlist_item(title='Episode 0'),
                                                    playlist_item(title='Episode 1'))])
    manager = youtube_manager(mocker, client)
    episode_list = manager.broadcast_update(YOUTUBE_CHANNEL, filters=[r'^Episode 1'])
    assert len(episode_list) == 1
    assert episode_list[0]['title'] == 'Episode 1'


def test_youtube_broadcast_update_episode_fields(mocker):
    video_id = random_video_id()
    published_at = random_past_iso_timestamp()
    client = MockYoutubeClient(pages=[playlist_page(
        playlist_item(video_id=video_id, title='Episode 0',
                      description='a description', published_at=published_at))])
    manager = youtube_manager(mocker, client)
    episode = manager.broadcast_update(YOUTUBE_CHANNEL)[0]
    assert episode['title'] == 'Episode 0'
    assert episode['description'] == 'a description'
    assert episode['download_link'] == watch_url(video_id)
    # the date is the video's own publish time, not when it joined the playlist
    assert episode['date'] == datetime.fromisoformat(published_at)


def test_youtube_broadcast_update_reads_uploads_playlist(mocker):
    client = MockYoutubeClient(pages=[playlist_page(playlist_item())])
    manager = youtube_manager(mocker, client)
    manager.broadcast_update(YOUTUBE_CHANNEL)
    call = client.playlist_items_mock.list_calls[0]
    # search.list costs 100 units a call, playlistItems.list costs 1
    assert call['playlistId'] == f'UU{YOUTUBE_CHANNEL[2:]}'
    # the api default is 5 per page, which spends a call every fifth video
    assert call['maxResults'] == 50


def test_youtube_broadcast_update_pages_through(mocker):
    client = MockYoutubeClient(pages=[
        playlist_page(playlist_item(), playlist_item()),
        playlist_page(playlist_item(), playlist_item()),
    ])
    manager = youtube_manager(mocker, client)
    assert len(manager.broadcast_update(YOUTUBE_CHANNEL)) == 4
    assert client.playlist_items_mock.pages_served == 2


def test_youtube_broadcast_update_stops_at_known(mocker):
    known = [random_video_id() for _ in range(3)]
    client = MockYoutubeClient(pages=[
        playlist_page(playlist_item(title='new one'),
                      *(playlist_item(video_id=vid) for vid in known)),
        playlist_page(playlist_item(title='should never be read')),
    ])
    manager = youtube_manager(mocker, client)
    episode_list = manager.broadcast_update(
        YOUTUBE_CHANNEL, known_urls=[watch_url(vid) for vid in known])
    assert [e['title'] for e in episode_list] == ['new one']
    # caught up inside the first page, so the second is never fetched
    assert client.playlist_items_mock.pages_served == 1


def test_youtube_broadcast_update_known_streak_resets(mocker):
    known = [random_video_id() for _ in range(2)]
    client = MockYoutubeClient(pages=[
        playlist_page(playlist_item(video_id=known[0]),
                      playlist_item(video_id=known[1]),
                      playlist_item(title='still new'))])
    manager = youtube_manager(mocker, client)
    episode_list = manager.broadcast_update(
        YOUTUBE_CHANNEL, known_urls=[watch_url(vid) for vid in known])
    # two known in a row is under the stop streak, so the walk carries on
    assert [e['title'] for e in episode_list] == ['still new']


def test_youtube_broadcast_update_known_beats_filters(mocker):
    known = [random_video_id() for _ in range(3)]
    client = MockYoutubeClient(pages=[
        playlist_page(*(playlist_item(video_id=vid, title='filtered out') for vid in known)),
        playlist_page(playlist_item(title='should never be read')),
    ])
    manager = youtube_manager(mocker, client)
    episode_list = manager.broadcast_update(
        YOUTUBE_CHANNEL, filters=[r'^Episode'],
        known_urls=[watch_url(vid) for vid in known])
    # a filter that matches nothing must not keep the walk going
    assert not episode_list
    assert client.playlist_items_mock.pages_served == 1


def test_youtube_broadcast_update_ignores_unparseable_known(mocker):
    client = MockYoutubeClient(pages=[playlist_page(playlist_item())])
    manager = youtube_manager(mocker, client)
    assert len(manager.broadcast_update(YOUTUBE_CHANNEL, known_urls=['not-a-youtube-url', ''])) == 1


def test_youtube_broadcast_update_page_ceiling(mocker):
    pages = [playlist_page(playlist_item()) for _ in range(YOUTUBE_MAX_PAGES + 5)]
    client = MockYoutubeClient(pages=pages)
    manager = youtube_manager(mocker, client)
    episode_list = manager.broadcast_update(YOUTUBE_CHANNEL)
    assert len(episode_list) == YOUTUBE_MAX_PAGES
    assert client.playlist_items_mock.pages_served == YOUTUBE_MAX_PAGES


def test_youtube_broadcast_update_legacy_channel_id(mocker):
    client = MockYoutubeClient(
        pages=[playlist_page(playlist_item())],
        channels_response={'items': [{'contentDetails': {'relatedPlaylists': {'uploads': 'UUlegacy'}}}]})
    manager = youtube_manager(mocker, client)
    manager.broadcast_update('legacy-channel-name')
    assert client.channels_mock.list_calls[0]['id'] == 'legacy-channel-name'
    assert client.playlist_items_mock.list_calls[0]['playlistId'] == 'UUlegacy'


def test_youtube_broadcast_update_channel_not_found(mocker):
    client = MockYoutubeClient(channels_response={'items': []})
    manager = youtube_manager(mocker, client)
    with pytest.raises(HathorException) as error:
        manager.broadcast_update('legacy-channel-name')
    assert 'No youtube channel found for: legacy-channel-name' in str(error.value)


def http_error(status, reason):
    content = dumps({'error': {'code': status, 'message': 'nope',
                               'errors': [{'reason': reason}]}}).encode('utf-8')
    return HttpError(HttpResponseMock(status), content, uri='https://example.foo')


class HttpResponseMock(dict):
    def __init__(self, status):
        super().__init__(status=status)
        self.status = status
        self.reason = 'error'


def test_youtube_broadcast_update_asks_for_retries(mocker):
    client = MockYoutubeClient(pages=[playlist_page(playlist_item())])
    manager = youtube_manager(mocker, client)
    manager.broadcast_update(YOUTUBE_CHANNEL)
    # the google client backs off on 429, 5xx and the rate limit 403s by itself,
    # but only when asked for retries
    assert client.playlist_items_mock.requests[0].execute_calls == [YOUTUBE_NUM_RETRIES]


def test_youtube_broadcast_update_quota_exceeded(mocker):
    client = MockYoutubeClient(pages=[http_error(403, 'quotaExceeded')])
    manager = youtube_manager(mocker, client)
    with pytest.raises(HathorException) as error:
        manager.broadcast_update(YOUTUBE_CHANNEL)
    assert 'Youtube api daily quota exceeded' in str(error.value)


def test_youtube_broadcast_update_other_http_error(mocker):
    client = MockYoutubeClient(pages=[http_error(404, 'notFound')])
    manager = youtube_manager(mocker, client)
    with pytest.raises(HttpError):
        manager.broadcast_update(YOUTUBE_CHANNEL)


@pytest.mark.parametrize('details,expected', [
    ([{'reason': 'quotaExceeded'}], True),
    ([{'reason': 'dailyLimitExceeded'}], True),
    ([{'reason': 'rateLimitExceeded'}], False),
    ({'reason': 'quotaExceeded'}, True),
    ('a string body', False),
    ([], False),
])
def test_youtube_quota_exhausted_shapes(details, expected):
    error = http_error(403, 'quotaExceeded')
    error.error_details = details
    assert youtube_quota_exhausted(error) is expected

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
    manager = youtube_manager(mocker)
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio_file:
        mocker.patch('hathor.podcast.archive.YoutubeDL', side_effect=generate_mock_youtube(temp_audio_file))
        _file_path, size = manager.episode_download('foo', 'bar')
        assert size == Path(temp_audio_file).stat().st_size

def test_youtube_broadcast_download_error(mocker):
    manager = youtube_manager(mocker)
    mocker.patch('hathor.podcast.archive.YoutubeDL', side_effect=mock_youtube_error)
    file_path, size = manager.episode_download('foo', 'bar')
    assert file_path is None
    assert size is None

def capture_ytdlp_options(temp_audio_file, captured):
    @contextmanager
    def mock_youtube_client(options):
        captured.update(options)
        yield MockYoutubeDL(temp_audio_file)
    return mock_youtube_client

def download_with_options(mocker, manager, captured):
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio_file:
        mocker.patch('hathor.podcast.archive.YoutubeDL',
                     side_effect=capture_ytdlp_options(temp_audio_file, captured))
        manager.episode_download('foo', 'bar')

def test_youtube_download_paces_requests_by_default(mocker):
    manager = youtube_manager(mocker)
    captured = {}
    download_with_options(mocker, manager, captured)
    assert captured['sleep_requests'] == 1
    assert captured['sleep_interval'] == 2
    assert captured['max_sleep_interval'] == 6

def test_youtube_download_ytdlp_options_override_pacing(mocker):
    manager = youtube_manager(mocker,
                              ytdlp_options={'sleep_requests': 5, 'proxy': 'socks5://localhost:1080'})
    captured = {}
    download_with_options(mocker, manager, captured)
    assert captured['sleep_requests'] == 5
    assert captured['proxy'] == 'socks5://localhost:1080'
    # untouched keys keep their defaults
    assert captured['max_sleep_interval'] == 6

def test_youtube_download_ytdlp_options_cannot_override_output(mocker):
    manager = youtube_manager(mocker,
                              ytdlp_options={'outtmpl': 'nope', 'logger': None})
    captured = {}
    download_with_options(mocker, manager, captured)
    assert captured['outtmpl'] == 'bar.%(ext)s'
    assert captured['logger'] is logging

def test_youtube_manager_ytdlp_options_default_empty(mocker):
    manager = youtube_manager(mocker)
    assert manager.ytdlp_options == {}


_VIDEO_ID_ALPHABET = string.ascii_letters + string.digits + '-_'


def random_video_id() -> str:
    return ''.join(random.choices(_VIDEO_ID_ALPHABET, k=11))


def random_past_iso_timestamp() -> str:
    minutes_ago = random.randint(1, 60 * 24 * 30)
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def random_duration() -> str:
    hours = random.randint(0, 4)
    minutes = random.randint(1, 59)
    seconds = random.randint(1, 59)
    return f'PT{hours}H{minutes}M{seconds}S'


@pytest.mark.parametrize('url_template,should_match', [
    ('https://www.youtube.com/watch?v={vid}', True),
    ('https://youtube.com/watch?v={vid}&t=10s', True),
    ('https://www.youtube.com/live/{vid}', True),
    ('https://youtu.be/{vid}', True),
    ('https://www.youtube.com/embed/{vid}', True),
    ('https://www.youtube.com/shorts/{vid}', True),
    ('https://example.com/watch?v={vid}', False),
])
def test_extract_youtube_video_id_from_url_shapes(url_template, should_match):
    vid = random_video_id()
    result = extract_youtube_video_id(url_template.format(vid=vid))
    assert result == (vid if should_match else None)


@pytest.mark.parametrize('input_url', ['foo', ''])
def test_extract_youtube_video_id_unparseable(input_url):
    assert extract_youtube_video_id(input_url) is None


def _live_url() -> str:
    return f'https://www.youtube.com/live/{random_video_id()}'


def test_youtube_download_skips_live_broadcast(mocker):
    manager = youtube_manager(mocker, MockYoutubeClient(videos_response={
        'items': [{
            'snippet': {'liveBroadcastContent': 'live'},
            'liveStreamingDetails': {},
            'contentDetails': {'duration': 'PT0S'},
        }]
    }))
    yt_mock = mocker.patch('hathor.podcast.archive.YoutubeDL')
    with pytest.raises(EpisodeNotReady) as error:
        manager.episode_download(_live_url(), 'bar')
    assert 'Episode not ready for download' in str(error.value)
    yt_mock.assert_not_called()


def test_youtube_download_skips_upcoming_broadcast(mocker):
    manager = youtube_manager(mocker, MockYoutubeClient(videos_response={
        'items': [{
            'snippet': {'liveBroadcastContent': 'upcoming'},
            'liveStreamingDetails': {},
            'contentDetails': {},
        }]
    }))
    yt_mock = mocker.patch('hathor.podcast.archive.YoutubeDL')
    with pytest.raises(EpisodeNotReady) as error:
        manager.episode_download(_live_url(), 'bar')
    assert 'Episode not ready for download' in str(error.value)
    yt_mock.assert_not_called()


def test_youtube_download_skips_live_still_processing(mocker):
    manager = youtube_manager(mocker, MockYoutubeClient(videos_response={
        'items': [{
            'snippet': {'liveBroadcastContent': 'none'},
            'liveStreamingDetails': {'actualEndTime': random_past_iso_timestamp()},
            'contentDetails': {'duration': 'PT0S'},
        }]
    }))
    yt_mock = mocker.patch('hathor.podcast.archive.YoutubeDL')
    with pytest.raises(EpisodeNotReady) as error:
        manager.episode_download(_live_url(), 'bar')
    assert 'Episode not ready for download' in str(error.value)
    yt_mock.assert_not_called()


def test_youtube_download_proceeds_for_processed_live_vod(mocker):
    manager = youtube_manager(mocker, MockYoutubeClient(videos_response={
        'items': [{
            'snippet': {'liveBroadcastContent': 'none'},
            'liveStreamingDetails': {'actualEndTime': random_past_iso_timestamp()},
            'contentDetails': {'duration': random_duration()},
        }]
    }))
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio_file:
        mocker.patch('hathor.podcast.archive.YoutubeDL',
                     side_effect=generate_mock_youtube(temp_audio_file))
        _file_path, size = manager.episode_download(_live_url(), 'bar')
        assert size == Path(temp_audio_file).stat().st_size


def test_youtube_download_proceeds_for_regular_vod(mocker):
    manager = youtube_manager(mocker, MockYoutubeClient(videos_response={
        'items': [{
            'snippet': {'liveBroadcastContent': 'none'},
            'contentDetails': {'duration': random_duration()},
        }]
    }))
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio_file:
        mocker.patch('hathor.podcast.archive.YoutubeDL',
                     side_effect=generate_mock_youtube(temp_audio_file))
        _file_path, size = manager.episode_download(
            f'https://www.youtube.com/watch?v={random_video_id()}', 'bar')
        assert size == Path(temp_audio_file).stat().st_size


def test_youtube_download_proceeds_when_api_check_fails(mocker):
    manager = youtube_manager(mocker, MockYoutubeClient(
        videos_response=RuntimeError('api unreachable')))
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio_file:
        mocker.patch('hathor.podcast.archive.YoutubeDL',
                     side_effect=generate_mock_youtube(temp_audio_file))
        _file_path, size = manager.episode_download(_live_url(), 'bar')
        assert size == Path(temp_audio_file).stat().st_size


def test_youtube_download_proceeds_when_video_not_found(mocker):
    manager = youtube_manager(mocker, MockYoutubeClient(videos_response={'items': []}))
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio_file:
        mocker.patch('hathor.podcast.archive.YoutubeDL',
                     side_effect=generate_mock_youtube(temp_audio_file))
        _file_path, size = manager.episode_download(_live_url(), 'bar')
        assert size == Path(temp_audio_file).stat().st_size

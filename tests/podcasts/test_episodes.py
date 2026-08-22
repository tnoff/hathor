from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory, NamedTemporaryFile
import pytest

from hathor.client import HathorClient
from hathor.exc import AudioFileException, EpisodeNotReady, HathorException
from hathor.podcast.archive import RSSManager, YoutubeManager

from tests.utils import temp_audio_file

mock_episode_data = [
    {
        'download_link': 'https://foo.com/example1',
        'title': 'Episode 0',
        'date': datetime(2024, 12, 7, 14, 00, 00),
        'description': 'Episode 0 description',
    },
    {
        'download_link': 'https://foo.com/example2',
        'title': 'Episode 1',
        'date': datetime(2024, 12, 8, 14, 00, 00),
        'description': 'Episode 1 description',
    },
]

mock_duplicate_episode = [
    {
        'download_link': 'https://foo.com/example1',
        'title': 'Episode 0',
        'date': datetime(2024, 12, 7, 14, 00, 00),
        'description': 'Episode 0 description',
    },
    {
        'download_link': 'https://foo.com/example1',
        'title': 'Episode 1',
        'date': datetime(2024, 12, 8, 14, 00, 00),
        'description': 'Episode 1 description',
    },
]

mock_episode_data_two = [
    {
        'download_link': 'https://bar.com/example1',
        'title': 'Youtube Episode 0',
        'date': datetime(2024, 12, 7, 14, 00, 00),
        'description': 'Episode 0 description',
    },
    {
        'download_link': 'https://bar.com/example2',
        'title': 'Youtube Episode 1',
        'date': datetime(2024, 12, 8, 14, 00, 00),
        'description': 'Episode 1 description',
    },
]

mock_patreon = [
    {
        'download_link': 'https://test.patreonusercontent.com/example1?token-time=123&token-hash=abcd',
        'title': 'Youtube Episode 0',
        'date': datetime(2024, 12, 7, 14, 00, 00),
        'description': 'Episode 0 description',
    },
    {
        'download_link': 'https://test.patreonusercontent.com/example2?token-time=123&token-hash=abcd',
        'title': 'Youtube Episode 1',
        'date': datetime(2024, 12, 8, 14, 00, 00),
        'description': 'Episode 1 description',
    },
]

mock_patreon_two = [
    {
        'download_link': 'https://test.patreonusercontent.com/example1?token-time=456&token-hash=defg',
        'title': 'Youtube Episode 0',
        'date': datetime(2024, 12, 7, 14, 00, 00),
        'description': 'Episode 0 description',
    },
    {
        'download_link': 'https://test.patreonusercontent.com/example2?token-time=456&token-hash=defg',
        'title': 'Youtube Episode 1',
        'date': datetime(2024, 12, 8, 14, 00, 00),
        'description': 'Episode 1 description',
    },
]


def test_episode_sync(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo')
        new_pod2 = client.podcast_create('youtube', '1234', 'bar')
        mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        mocker.patch.object(YoutubeManager, 'broadcast_update', return_value=mock_episode_data_two)
        client.episode_sync(include_podcasts=[new_pod1['id'], new_pod2['id']])

        episode_list = client.episode_list(only_files=False)
        assert len(episode_list) == 4

def test_episode_sync_exclude(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo')
        new_pod2 = client.podcast_create('youtube', '1234', 'bar')
        mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        mocker.patch.object(YoutubeManager, 'broadcast_update', return_value=mock_episode_data_two)
        client.episode_sync(include_podcasts=[new_pod1['id'], new_pod2['id']],
                            exclude_podcasts=[new_pod2['id']])

        episode_list = client.episode_list(only_files=False)
        assert len(episode_list) == 2

def test_episode_sync_max_allowed(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo', max_allowed=1)
        mocked_rss = mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        client.episode_sync(include_podcasts=[new_pod1['id']])
        _, kwargs = mocked_rss.call_args
        assert kwargs.get('max_results') == 1

def test_episode_sync_max_allowed_unlimited(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo', max_allowed=1)
        mocked_rss = mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        client.episode_sync(include_podcasts=[new_pod1['id']], max_episode_sync=0)
        _, kwargs = mocked_rss.call_args
        assert kwargs.get('max_results') is None

def test_episode_sync_max_allowed_set(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo', max_allowed=1)
        mocked_rss = mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        client.episode_sync(include_podcasts=[new_pod1['id']], max_episode_sync=3)
        _, kwargs = mocked_rss.call_args
        assert kwargs.get('max_results') == 3

def test_episode_sync_backfills_under_max_allowed(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo', max_allowed=5)
        mocked_rss = mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        client.episode_sync(include_podcasts=[new_pod1['id']])
        _, kwargs = mocked_rss.call_args
        # nothing stored yet, so the whole max allowed is the gap
        assert kwargs.get('backfill') is True
        assert kwargs.get('max_results') == 5

        client.episode_sync(include_podcasts=[new_pod1['id']])
        _, kwargs = mocked_rss.call_args
        # two of five stored, so only the remaining three are asked for
        assert kwargs.get('backfill') is True
        assert kwargs.get('max_results') == 3

def test_episode_sync_no_backfill_when_full(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo', max_allowed=2)
        mocked_rss = mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        client.episode_sync(include_podcasts=[new_pod1['id']])
        client.episode_sync(include_podcasts=[new_pod1['id']])
        _, kwargs = mocked_rss.call_args
        # at its max allowed, so a sync stays the cheap caught up walk
        assert kwargs.get('backfill') is False
        assert kwargs.get('max_results') == 2

def test_episode_sync_no_backfill_without_max_allowed(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo')
        mocked_rss = mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        client.episode_sync(include_podcasts=[new_pod1['id']])
        _, kwargs = mocked_rss.call_args
        # no max allowed means no gap to measure, so nothing to backfill toward
        assert kwargs.get('backfill') is False
        assert kwargs.get('max_results') is None

def test_episode_sync_max_episode_sync_overrides_backfill(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo', max_allowed=5)
        mocked_rss = mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        client.episode_sync(include_podcasts=[new_pod1['id']], max_episode_sync=1)
        _, kwargs = mocked_rss.call_args
        # an explicit count is the caller's call, but the walk still gets to go deep
        assert kwargs.get('backfill') is True
        assert kwargs.get('max_results') == 1

def test_episode_sync_passes_known_urls(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo')
        mocked_rss = mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        client.episode_sync(include_podcasts=[new_pod1['id']])
        _, kwargs = mocked_rss.call_args
        # nothing stored yet on the first pass
        assert kwargs.get('known_urls') == set()

        client.episode_sync(include_podcasts=[new_pod1['id']])
        _, kwargs = mocked_rss.call_args
        assert kwargs.get('known_urls') == {e['download_link'] for e in mock_episode_data}

def test_episode_sync_known_urls_scoped(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo')
        new_pod2 = client.podcast_create('youtube', '1234', 'bar')
        mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        mocked_youtube = mocker.patch.object(YoutubeManager, 'broadcast_update',
                                             return_value=mock_episode_data_two)
        client.episode_sync(include_podcasts=[new_pod1['id'], new_pod2['id']])
        client.episode_sync(include_podcasts=[new_pod1['id'], new_pod2['id']])
        _, kwargs = mocked_youtube.call_args
        # one podcast's episodes must never stop another podcast's paging
        assert kwargs.get('known_urls') == {e['download_link'] for e in mock_episode_data_two}

def test_archive_manager_is_reused():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')
        # rebuilt per episode this would throw away the google api client and,
        # for twitch, the access token
        assert client._archive_manager('rss') is client._archive_manager('rss') #pylint:disable=protected-access

def test_episode_sync_duplicate_podcast(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo')
        mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_duplicate_episode)
        client.episode_sync(include_podcasts=[new_pod1['id']])
        episode_list = client.episode_list(only_files=False)
        assert len(episode_list) == 1

def test_episode_list(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo')
        new_pod2 = client.podcast_create('youtube', '1234', 'bar')
        mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        mocker.patch.object(YoutubeManager, 'broadcast_update', return_value=mock_episode_data_two)
        client.episode_sync(include_podcasts=[new_pod1['id'], new_pod2['id']])

        episode_list = client.episode_list(only_files=False,
                                           include_podcasts=[new_pod1['id']])
        assert len(episode_list) == 2
        episode_list = client.episode_list(only_files=False,
                                           exclude_podcasts=[new_pod1['id']])
        assert len(episode_list) == 2

def test_episode_show(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo')
        new_pod2 = client.podcast_create('youtube', '1234', 'bar')
        mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        mocker.patch.object(YoutubeManager, 'broadcast_update', return_value=mock_episode_data_two)
        client.episode_sync(include_podcasts=[new_pod1['id'], new_pod2['id']])

        episode_list = client.episode_list(only_files=False)
        ep = client.episode_show([episode_list[0]['id']])
        assert len(ep) == 1

def test_episode_update(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo')
        new_pod2 = client.podcast_create('youtube', '1234', 'bar')
        mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        mocker.patch.object(YoutubeManager, 'broadcast_update', return_value=mock_episode_data_two)
        client.episode_sync(include_podcasts=[new_pod1['id'], new_pod2['id']])

        episode_list = client.episode_list(only_files=False)
        ep = client.episode_update(episode_list[0]['id'], prevent_delete=True)
        assert ep['prevent_deletion'] is True

def test_episode_update_non_existing():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        with pytest.raises(HathorException) as error:
            client.episode_update(1, prevent_delete=False)
        assert 'Podcast Episode not found for ID' in str(error.value)

def test_episode_download(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

            new_pod1 = client.podcast_create('rss', '1234', 'foo')
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            client.episode_sync(include_podcasts=[new_pod1['id']])
            episode_list = client.episode_list(only_files=False)
            client.episode_download([episode_list[0]['id']])
            episode_list = client.episode_list()
            assert len(episode_list) == 1

def test_episode_update_file(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

            new_pod1 = client.podcast_create('rss', '1234', 'foo')
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            client.episode_sync(include_podcasts=[new_pod1['id']])
            episode_list = client.episode_list(only_files=False)
            client.episode_download([episode_list[0]['id']])
            episode_list = client.episode_list()
            with NamedTemporaryFile(dir=tmp_dir, suffix='.mp3') as temp_file:
                client.episode_update_file_path(episode_list[0]['id'], Path(temp_file.name))
                ep = client.episode_show(episode_list[0]['id'])
                assert ep[0]['file_path'] == temp_file.name

def test_episode_update_file_outside_location(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

            new_pod1 = client.podcast_create('rss', '1234', 'foo')
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            client.episode_sync(include_podcasts=[new_pod1['id']])
            episode_list = client.episode_list(only_files=False)
            client.episode_download([episode_list[0]['id']])
            episode_list = client.episode_list()
            with NamedTemporaryFile() as temp_file:
                with pytest.raises(HathorException) as error:
                    client.episode_update_file_path(episode_list[0]['id'], Path(temp_file.name))
                assert 'Podcast Episode cannot be moved out of podcast file location' in str(error.value)

def test_episode_update_file_bad_path(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

            new_pod1 = client.podcast_create('rss', '1234', 'foo')
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            client.episode_sync(include_podcasts=[new_pod1['id']])
            episode_list = client.episode_list(only_files=False)
            client.episode_download([episode_list[0]['id']])
            episode_list = client.episode_list()
            with NamedTemporaryFile(dir=tmp_dir, suffix='.mp4') as temp_file:
                with pytest.raises(HathorException) as error:
                    client.episode_update_file_path(episode_list[0]['id'], Path(temp_file.name))
                assert 'suffix must match original suffix' in str(error.value)

def test_episode_update_file_non_exists():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')
        with pytest.raises(HathorException) as error:
            client.episode_update_file_path(1, 'foo.mp3')
        assert 'Podcast Episode not found for ID' in str(error.value)

def test_episode_delete_file(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

            new_pod1 = client.podcast_create('rss', '1234', 'foo')
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            client.episode_sync(include_podcasts=[new_pod1['id']])
            episode_list = client.episode_list(only_files=False)
            client.episode_download([episode_list[0]['id']])
            episode_list = client.episode_list()
            client.episode_delete_file(episode_list[0]['id'])
            episode_list = client.episode_list()
            assert len(episode_list) == 0

def test_episode_delete(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

            new_pod1 = client.podcast_create('rss', '1234', 'foo')
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            client.episode_sync(include_podcasts=[new_pod1['id']])
            episode_list = client.episode_list(only_files=False)
            client.episode_download([episode_list[0]['id']])
            client.episode_delete([episode_list[0]['id']])
            episode_list = client.episode_list()
            assert len(episode_list) == 0
            episode_list = client.episode_list(only_files=False)
            assert len(episode_list) == 1

def test_episode_delete_no_delete(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

            new_pod1 = client.podcast_create('rss', '1234', 'foo')
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            client.episode_sync(include_podcasts=[new_pod1['id']])
            episode_list = client.episode_list(only_files=False)
            client.episode_download([episode_list[0]['id']])
            client.episode_delete([episode_list[0]['id']], delete_files=False)
            episode_list = client.episode_list()
            assert len(episode_list) == 0
            assert Path(temp_audio).exists()

def test_episode_cleanup(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo')
        new_pod2 = client.podcast_create('youtube', '1234', 'bar')
        mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        mocker.patch.object(YoutubeManager, 'broadcast_update', return_value=mock_episode_data_two)
        client.episode_sync(include_podcasts=[new_pod1['id'], new_pod2['id']])

        client.episode_cleanup()
        episode_list = client.episode_list(only_files=False)
        assert len(episode_list) == 0

def test_episode_download_no_return(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

        new_pod1 = client.podcast_create('rss', '1234', 'foo')
        mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        mocker.patch.object(RSSManager, 'episode_download', return_value=(None, None))
        client.episode_sync(include_podcasts=[new_pod1['id']])
        episode_list = client.episode_list(only_files=False)
        client.episode_download([episode_list[0]['id']])
        episode_list = client.episode_list()
        assert len(episode_list) == 0

def test_episode_download_not_ready(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

            new_pod1 = client.podcast_create('rss', '1234', 'foo')
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            client.episode_sync(include_podcasts=[new_pod1['id']])
            episode_list = client.episode_list(only_files=False)

            # First episode isnt downloadable yet, the second one is
            def download(download_url, _output_prefix, **_):
                if download_url == episode_list[0]['download_url']:
                    raise EpisodeNotReady(f'Episode not ready for download: {download_url}')
                return Path(temp_audio), 123
            mocker.patch.object(RSSManager, 'episode_download', side_effect=download)

            downloaded = client.episode_download([ep['id'] for ep in episode_list])
            assert [ep['id'] for ep in downloaded] == [episode_list[1]['id']]
            # Not ready episodes keep no file, so a later sync picks them up again
            assert client.episode_show(episode_list[0]['id'])[0]['file_path'] is None

class MockYoutubeDLOptions():
    def __init__(self, audio_file):
        self.audio_file = audio_file

    def extract_info(self, _download_url, **_):
        return {
            'requested_downloads': [
                {
                    'filepath': Path(self.audio_file),
                },
            ],
        }

def test_episode_download_uses_client_ytdlp_options(mocker):
    captured = {}
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo',
                              ytdlp_options={'sleep_requests': 7})

        new_pod = client.podcast_create('youtube', '1234', 'bar')
        mocker.patch.object(YoutubeManager, 'broadcast_update', return_value=mock_episode_data_two)
        client.episode_sync(include_podcasts=[new_pod['id']])
        episode_list = client.episode_list(only_files=False)

        with temp_audio_file(suffix='.mp4') as temp_audio:
            @contextmanager
            def mock_youtube_client(options):
                captured.update(options)
                yield MockYoutubeDLOptions(temp_audio)

            mocker.patch('hathor.podcast.archive.YoutubeDL', side_effect=mock_youtube_client)
            client.episode_download([episode_list[0]['id']])

    assert captured['sleep_requests'] == 7

def test_episode_download_update_tags(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

            new_pod1 = client.podcast_create('rss', '1234', 'foo')
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            mocker.patch('hathor.client.tags_update', side_effect=AudioFileException('unable to update tags'))
            client.episode_sync(include_podcasts=[new_pod1['id']])
            episode_list = client.episode_list(only_files=False)
            client.episode_download([episode_list[0]['id']])
            episode_list = client.episode_list()
            assert len(episode_list) == 1

def test_episode_download_patreon(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')
        client.podcast_create('rss', '1234', 'foo')
        mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_patreon)
        client.episode_sync()
        episode_list = client.episode_list(only_files=False)
        assert len(episode_list) == 2
        mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_patreon_two)
        client.episode_sync()
        episode_list = client.episode_list(only_files=False)
        assert len(episode_list) == 2

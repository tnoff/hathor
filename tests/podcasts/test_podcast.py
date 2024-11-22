from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from hathor.client import HathorClient
from hathor.exc import HathorException
from hathor.podcast.archive import RSSManager

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

mock_episode_data_second_run = [
    {
        'download_link': 'https://foo.com/example3',
        'title': 'Episode 2',
        'date': datetime(2024, 12, 9, 14, 00, 00),
        'description': 'Episode 2 description',
    },
    {
        'download_link': 'https://foo.com/example4',
        'title': 'Episode 3',
        'date': datetime(2024, 12, 10, 14, 00, 00),
        'description': 'Episode 3 description',
    },
]

def test_podcast_create():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)
        client.podcast_create('rss', 'foo1234', 'temp pod name')
        podcast_list = client.podcast_list()
        assert len(podcast_list) == 1
        assert podcast_list[0]['name'] == 'temp pod name'

def test_podcast_create_invalid_max_allowed():
    client = HathorClient()
    with pytest.raises(HathorException) as error:
        client.podcast_create('rss', 'foo1234', 'temp pod name', max_allowed=0)
    assert 'Max allowed must be positive integer' in str(error.value)

def test_podcast_create_with_no_file_location():
    client = HathorClient()
    with pytest.raises(HathorException) as error:
        client.podcast_create('rss', 'foo1234', 'temp pod name')
    assert 'No default podcast directory specified' in str(error.value)

def test_podcast_create_with_specific_file_location():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient()
        client.podcast_create('rss', 'foo1234', 'temp pod name', file_location=tmp_dir)
        podcast_list = client.podcast_list()
        assert len(podcast_list) == 1
        assert podcast_list[0]['name'] == 'temp pod name'

def test_podcast_show():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)
        client.podcast_create('rss', 'foo1234', 'temp pod name')
        podcast_list = client.podcast_list()
        pod_info = client.podcast_show(podcast_list[0]['id'])
        assert 'temp_pod_name' in pod_info[0]['file_location']

def test_podcast_show_no_input():
    client = HathorClient()
    podcast_list = client.podcast_show([])
    assert len(podcast_list) == 0

def test_podcast_update_non_existing():
    client = HathorClient()
    with pytest.raises(HathorException) as error:
        client.podcast_update(1)
    assert 'Podcast not found' in str(error.value)

def test_podcast_update():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)
        client.podcast_create('rss', 'foo1234', 'temp pod name')
        podcast_list = client.podcast_list()
        client.podcast_update(podcast_list[0]['id'],
                              podcast_name='test',
                              broadcast_id='bar1234',
                              archive_type='youtube',
                              max_allowed=5,
                              artist_name='foobar1234',
                              automatic_download=False)

def test_podcast_update_invalid_max_download():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)
        client.podcast_create('rss', 'foo1234', 'temp pod name')
        podcast_list = client.podcast_list()
        with pytest.raises(HathorException) as error:
            client.podcast_update(podcast_list[0]['id'],
                                max_allowed=-1)
        assert 'Max allowed must be positive integer or 0' in str(error.value)

def test_podcast_update_max_allowed_zero():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)
        client.podcast_create('rss', 'foo1234', 'temp pod name')
        podcast_list = client.podcast_list()
        client.podcast_update(podcast_list[0]['id'],
                              max_allowed=0)
        podcast_list = client.podcast_list()
        assert podcast_list[0]['max_allowed'] is None

def test_podcast_update_file_location(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

            new_pod1 = client.podcast_create('rss', '1234', 'foo')
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            client.episode_sync(include_podcasts=[new_pod1['id']])
            episode_list = client.episode_list(only_files=False)
            client.episode_download([episode_list[0]['id']])
            with TemporaryDirectory() as new_dir:
                client.podcast_update_file_location(new_pod1['id'], Path(new_dir))
                episode_list = client.episode_list()
                assert new_dir in str(episode_list[0]['file_path'])

def test_podcast_update_file_no_move(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')

            new_pod1 = client.podcast_create('rss', '1234', 'foo')
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            client.episode_sync(include_podcasts=[new_pod1['id']])
            episode_list = client.episode_list(only_files=False)
            client.episode_download([episode_list[0]['id']])
            with TemporaryDirectory() as new_dir:
                client.podcast_update_file_location(new_pod1['id'], Path(new_dir), move_files=False)
                episode_list = client.episode_list()
                assert new_dir not in str(episode_list[0]['file_path'])

def test_podcast_update_no_exists():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')
        with pytest.raises(HathorException) as error:
            client.podcast_update_file_location(1, 'foo')
        assert 'Podcast not found for ID' in str(error.value)

def test_podcast_delete(mocker):
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
            client.filter_create(new_pod1['id'], 'foo')

            client.podcast_delete([new_pod1['id']])

        pod_list = client.podcast_list()
        assert len(pod_list) == 0
        filters = client.filter_list()
        assert len(filters) == 0
        episodes = client.episode_list(only_files=False)
        assert len(episodes) == 0

def test_podcast_delete_keep_files(mocker):
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
            client.filter_create(new_pod1['id'], 'foo')

            client.podcast_delete([new_pod1['id']], delete_files=False)

            pod_list = client.podcast_list()
            assert len(pod_list) == 0
            filters = client.filter_list()
            assert len(filters) == 0
            episodes = client.episode_list(only_files=False)
            assert len(episodes) == 0
            assert Path(temp_audio).exists()

def test_podcast_sync_automatic_off():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')
        client.podcast_create('rss', 'foo', 'foo', automatic_download=False)
        client.podcast_sync()
        episode_list = client.episode_list(only_files=False)
        assert len(episode_list) == 0

def test_podcast_sync_download_episodes(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')
            client.podcast_create('rss', 'foo', 'foo')
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            client.podcast_sync()
            episode_list = client.episode_list()
            assert len(episode_list) == 2

def test_podcast_sync_max_allowed(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')
            client.podcast_create('rss', 'foo', 'foo', max_allowed=1)
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            client.podcast_sync()
            episode_list = client.episode_list()
            assert len(episode_list) == 1

def test_podcast_sync_run_twice(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')
            client.podcast_create('rss', 'foo', 'foo', max_allowed=1)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            client.podcast_sync()
            episode_list = client.episode_list()
            assert episode_list[0]['title'] == 'Episode 1'
            client.podcast_sync()
            episode_list = client.episode_list()
            assert len(episode_list) == 1
            assert episode_list[0]['title'] == 'Episode 1'

def test_podcast_sync_new_data(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')
            client.podcast_create('rss', 'foo', 'foo', max_allowed=1)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            client.podcast_sync()
            episode_list = client.episode_list()
            assert episode_list[0]['title'] == 'Episode 1'

            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data_second_run)
            client.podcast_sync()
            episode_list = client.episode_list()
            assert len(episode_list) == 1
            assert episode_list[0]['title'] == 'Episode 3'

def test_podcast_sync_new_data_with_prevent_delete(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')
            client.podcast_create('rss', 'foo', 'foo', max_allowed=1)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            client.podcast_sync()
            episode_list = client.episode_list()
            assert episode_list[0]['title'] == 'Episode 1'
            client.episode_update(episode_list[0]['id'], prevent_delete=True)
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data_second_run)
            client.podcast_sync()
            episode_list = client.episode_list()
            assert len(episode_list) == 2

def test_podcast_sync_exclude():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')
        new_pod = client.podcast_create('rss', 'foo', 'foo')
        client.podcast_sync(exclude_podcasts=[new_pod['id']])
        episode_list = client.episode_list(only_files=False)
        assert len(episode_list) == 0

def test_podcast_sync_include(mocker):
    with TemporaryDirectory() as tmp_dir:
        with temp_audio_file() as temp_audio:
            client = HathorClient(podcast_directory=tmp_dir, google_api_key='foo')
            new_pod = client.podcast_create('rss', 'foo', 'foo')
            client.podcast_create('youtube', 'bar', 'bar')
            mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
            mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
            client.podcast_sync(include_podcasts=[new_pod['id']])
            episode_list = client.episode_list()
            assert len(episode_list) == 2

from datetime import datetime
from json import loads
from pathlib import Path
from shutil import copyfile

from botocore.exceptions import ClientError
from moto import mock_aws
import pytest
import requests

from hathor.audio.metadata import tags_show
from hathor.client import HathorClient
from hathor.exc import HathorException
from hathor.podcast.archive import RSSManager

from tests.utils import FIXTURES_DIR

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

def fake_download(_url, output_prefix):
    '''
    Stand in for an archive download, which writes the file next to the prefix it is given
    '''
    output_path = Path(f'{output_prefix}.mp3')
    copyfile(FIXTURES_DIR / 'test_audio.mp3', output_path)
    return output_path, output_path.stat().st_size

@pytest.fixture(name='client')
def client_fixture(tmp_path):
    with mock_aws():
        client = HathorClient(podcast_directory='podcasts', storage_options={
            'type': 's3', 'bucket_name': 'bucket', 'region_name': 'us-east-1',
            'scratch_directory': str(tmp_path),
        })
        client.storage.client.create_bucket(Bucket='bucket')
        yield client

def bucket_keys(client, prefix=''):
    response = client.storage.client.list_objects_v2(Bucket='bucket', Prefix=prefix)
    return sorted(obj['Key'] for obj in response.get('Contents', []))

def synced_podcast(client, mocker, name='foo', **kwargs):
    podcast = client.podcast_create('rss', '1234', name, **kwargs)
    mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
    mocker.patch.object(RSSManager, 'episode_download', side_effect=fake_download)
    client.podcast_sync()
    return podcast

def test_podcast_create_uses_prefix(client):
    podcast = client.podcast_create('rss', '1234', 'My Podcast')
    assert podcast['file_location'] == 'podcasts/My_Podcast'
    assert client.podcast_create('rss', '5678', 'other', file_location='//a//b/')['file_location'] == 'a/b'

def test_sync_stores_episodes_in_bucket(client, mocker, tmp_path):
    podcast = synced_podcast(client, mocker)
    assert bucket_keys(client) == ['podcasts/foo/2024-12-07.Episode_0.mp3', 'podcasts/foo/2024-12-08.Episode_1.mp3']
    episodes = client.episode_list()
    assert sorted(e['file_path'] for e in episodes) == bucket_keys(client)
    assert all(e['file_size'] > 0 and e['podcast_id'] == podcast['id'] for e in episodes)

    head = client.storage.client.head_object(Bucket='bucket', Key='podcasts/foo/2024-12-07.Episode_0.mp3')
    assert head['ContentType'] == 'audio/mpeg'
    assert head['ContentDisposition'].startswith('attachment; filename="foo - 2024-12-07 - Episode 0.mp3"')
    # Downloads were written to scratch and cleaned up
    assert not list(tmp_path.iterdir())

def test_uploaded_file_is_tagged(client, mocker, tmp_path):
    synced_podcast(client, mocker, artist_name='Some Artist')
    path = tmp_path / 'check.mp3'
    client.storage.client.download_file('bucket', 'podcasts/foo/2024-12-07.Episode_0.mp3', str(path))
    assert tags_show(path)['artist'] == 'Some Artist'

def test_failed_upload_leaves_episode_for_next_sync(client, mocker):
    client.podcast_create('rss', '1234', 'foo')
    mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
    mocker.patch.object(RSSManager, 'episode_download', side_effect=fake_download)
    upload = mocker.patch.object(client.storage.client, 'upload_file',
                                 side_effect=ClientError({'Error': {'Code': '500', 'Message': 'boom'}}, 'Put'))
    assert client.podcast_sync() is True
    assert bucket_keys(client) == []
    assert all(e['file_path'] is None for e in client.episode_list(only_files=False))

    upload.side_effect = None
    mocker.stopall()
    mocker.patch.object(RSSManager, 'episode_download', side_effect=fake_download)
    client.podcast_sync(sync_web_episodes=False)
    assert len(bucket_keys(client)) == 2

def test_max_allowed_trims_bucket(client, mocker):
    synced_podcast(client, mocker, max_allowed=1)
    assert bucket_keys(client) == ['podcasts/foo/2024-12-08.Episode_1.mp3']

def test_delete_episode_file(client, mocker):
    synced_podcast(client, mocker)
    episode = client.episode_list()[0]
    assert client.episode_delete_file([episode['id']]) == [episode['id']]
    assert len(bucket_keys(client)) == 1
    assert client.episode_show([episode['id']])[0]['file_path'] is None

def test_delete_podcast_removes_only_its_prefix(client, mocker):
    synced_podcast(client, mocker)
    client.storage.client.put_object(Bucket='bucket', Key='podcasts/foobar/keep.mp3', Body=b'x')
    client.podcast_delete([1])
    assert bucket_keys(client) == ['podcasts/foobar/keep.mp3']

def test_update_file_location_moves_objects(client, mocker):
    podcast = synced_podcast(client, mocker)
    result = client.podcast_update_file_location(podcast['id'], 'archive/foo')
    assert result['file_location'] == 'archive/foo'
    assert bucket_keys(client) == ['archive/foo/2024-12-07.Episode_0.mp3', 'archive/foo/2024-12-08.Episode_1.mp3']
    assert sorted(e['file_path'] for e in client.episode_list()) == bucket_keys(client)

def test_update_file_location_to_same_prefix_keeps_objects(client, mocker):
    podcast = synced_podcast(client, mocker)
    client.podcast_update_file_location(podcast['id'], '/podcasts/foo/')
    assert len(bucket_keys(client, 'podcasts/foo/')) == 2

def test_update_file_location_without_moving(client, mocker):
    podcast = synced_podcast(client, mocker)
    client.podcast_update_file_location(podcast['id'], 'archive/foo', move_files=False)
    assert len(bucket_keys(client, 'podcasts/foo/')) == 2

def test_update_episode_file_path_unsupported(client, mocker):
    synced_podcast(client, mocker)
    with pytest.raises(HathorException, match='not supported with s3 storage'):
        client.episode_update_file_path(1, 'podcasts/foo/new.mp3')

def test_index_dry_run(client, mocker):
    synced_podcast(client, mocker)
    synced_podcast_two = client.podcast_create('rss', '9999', 'aaa')
    assert synced_podcast_two
    index = client.episode_index(dry_run=True)
    assert 'index.json' not in bucket_keys(client)
    assert index['url_expires_at'] > index['generated_at']
    # Podcasts with no stored episodes are left out, the rest sorted by name
    assert [p['name'] for p in index['podcasts']] == ['foo']
    episodes = index['podcasts'][0]['episodes']
    # Newest first
    assert [e['title'] for e in episodes] == ['Episode 1', 'Episode 0']
    first = episodes[0]
    assert first['date'] == '2024-12-08'
    assert first['key'] == 'podcasts/foo/2024-12-08.Episode_1.mp3'
    assert first['filename'] == 'foo - 2024-12-08 - Episode 1.mp3'
    assert first['content_type'] == 'audio/mpeg'
    assert first['size'] > 0
    # The link really downloads the file
    response = requests.get(first['url'], timeout=10)
    assert response.status_code == 200
    assert len(response.content) == first['size']

def test_index_write(client, mocker):
    synced_podcast(client, mocker)
    summary = client.episode_index()
    assert summary['index_object'] == 'index.json'
    assert (summary['podcasts'], summary['episodes']) == (1, 2)
    written = loads(client.storage.client.get_object(Bucket='bucket', Key='index.json')['Body'].read())
    assert written['url_expires_at'] == summary['url_expires_at']
    assert len(written['podcasts'][0]['episodes']) == 2

def test_index_requires_s3_storage():
    with pytest.raises(HathorException, match='requires s3 storage_options'):
        HathorClient().episode_index()

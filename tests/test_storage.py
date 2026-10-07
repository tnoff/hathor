from pathlib import Path

from botocore.exceptions import ClientError
from moto import mock_aws
import pytest

from hathor import storage
from hathor.exc import HathorException
from hathor.storage import LocalStorage, S3Storage

from tests.utils import temp_audio_file

def client_error(operation='Op'):
    return ClientError({'Error': {'Code': '500', 'Message': 'boom'}}, operation)

@pytest.fixture(name='s3')
def s3_fixture():
    with mock_aws():
        s3_storage = storage.storage_from_options({'type': 's3', 'bucket_name': 'bucket', 'region_name': 'us-east-1'})
        s3_storage.client.create_bucket(Bucket='bucket')
        yield s3_storage

def keys(s3, prefix=''):
    response = s3.client.list_objects_v2(Bucket='bucket', Prefix=prefix)
    return sorted(obj['Key'] for obj in response.get('Contents', []))

def test_sanitize_filename():
    assert storage.sanitize_filename('a/b\\c: d?*') == 'abc d'
    assert storage.sanitize_filename('  ...Why? Because   it is... ') == 'Why Because it is'
    assert storage.sanitize_filename('Café ünïcode') == 'Café ünïcode'
    assert storage.sanitize_filename('///') == 'episode'
    assert len(storage.sanitize_filename('a' * 500)) == storage.FILENAME_MAX_LENGTH

def test_content_disposition():
    header = storage.content_disposition('Pod - 2024 - Café "quoted".mp3')
    assert header.startswith('attachment; filename="Pod - 2024 - Caf quoted.mp3"')
    assert "filename*=UTF-8''Pod%20-%202024%20-%20Caf%C3%A9%20%22quoted%22.mp3" in header
    assert storage.content_disposition('日本語').startswith('attachment; filename="download"')

def test_display_filename():
    assert storage.display_filename('Pod', '2024-12-07', 'Big/Title', '.MP4') == 'Pod - 2024-12-07 - BigTitle.mp4'
    assert storage.display_filename('Pod', None, None, '.mp3') == 'Pod.mp3'

def test_guess_content_type():
    assert storage.guess_content_type('a.mp3') == 'audio/mpeg'
    assert storage.guess_content_type('a.mp4') == 'video/mp4'
    assert storage.guess_content_type('a.zzz') == 'application/octet-stream'

def test_local_storage(tmp_path):
    local = LocalStorage()
    location = local.normalize_location(tmp_path / 'a' / '..' / 'pod')
    assert location == str((tmp_path / 'pod').resolve())
    assert local.join(tmp_path, 'pod') == tmp_path / 'pod'
    assert local.same_location(tmp_path / 'pod', location)
    assert not local.same_location(tmp_path / 'pod', tmp_path / 'other')
    local.prepare_location(location)
    with local.working_directory(location) as work_dir:
        assert work_dir == Path(location)
    episode = Path(location) / 'one.mp3'
    episode.write_bytes(b'abc')
    assert local.store(episode, location, 'ignored') == str(episode.resolve())
    local.prepare_location(tmp_path / 'new')
    moved = local.move(episode, tmp_path / 'new')
    assert moved == str((tmp_path / 'new' / 'one.mp3').resolve())
    assert local.delete(moved) is True
    assert local.delete(moved) is False
    local.delete_location(location)
    assert not Path(location).exists()

def test_s3_url_expiry_validation():
    for hours in (0, 169):
        with pytest.raises(HathorException, match='url_expiry_hours'):
            S3Storage(None, 'bucket', url_expiry_hours=hours)

def test_s3_locations():
    assert S3Storage.join('/podcasts/', 'pod') == 'podcasts/pod'
    assert S3Storage.normalize_location('//a///b/') == 'a/b'
    assert S3Storage.same_location('a/b/', '/a/b')
    assert not S3Storage.same_location('a/b', 'a/c')
    assert S3Storage.prepare_location('a/b') is None
    with pytest.raises(HathorException, match='non empty key prefix'):
        S3Storage.normalize_location('/')

def test_s3_working_directory_is_removed(s3, tmp_path):
    s3.scratch_directory = str(tmp_path)
    with s3.working_directory('a/b') as work_dir:
        assert work_dir.parent == tmp_path
        (work_dir / 'file').write_text('x', encoding='utf-8')
    assert not work_dir.exists()

def test_s3_store(s3):
    with temp_audio_file() as audio:
        key = s3.store(Path(audio), 'podcasts/pod', 'Pod - 2024 - Title.mp3')
    assert key == f'podcasts/pod/{Path(audio).name}'
    head = s3.client.head_object(Bucket='bucket', Key=key)
    assert head['ContentType'] == 'audio/mpeg'
    assert head['ContentDisposition'].startswith('attachment; filename="Pod - 2024 - Title.mp3"')

def test_s3_store_defaults_display_name_and_wraps_errors(s3, mocker):
    with temp_audio_file() as audio:
        key = s3.store(Path(audio), 'p')
        assert Path(audio).name in s3.client.head_object(Bucket='bucket', Key=key)['ContentDisposition']
        mocker.patch.object(s3.client, 'upload_file', side_effect=client_error())
        with pytest.raises(HathorException, match='Unable to upload'):
            s3.store(Path(audio), 'p')
    with pytest.raises(HathorException, match='Unable to upload'):
        s3.store(Path('/does/not/exist.mp3'), 'p')

def test_s3_move_and_delete(s3):
    s3.client.put_object(Bucket='bucket', Key='a/one.mp3', Body=b'abc')
    assert s3.move('a/one.mp3', 'b') == 'b/one.mp3'
    assert keys(s3) == ['b/one.mp3']
    # Moving onto itself leaves the object alone
    assert s3.move('b/one.mp3', 'b') == 'b/one.mp3'
    assert keys(s3) == ['b/one.mp3']
    assert s3.delete('b/one.mp3') is True
    # Already gone is fine
    assert s3.delete('b/one.mp3') is True
    assert keys(s3) == []

def test_s3_delete_location_only_touches_prefix(s3, mocker):
    mocker.patch.object(storage, 'DELETE_BATCH_SIZE', 2)
    for key in ('pod/1', 'pod/2', 'pod/3', 'pod/sub/4', 'podcast/5', 'other/6'):
        s3.client.put_object(Bucket='bucket', Key=key, Body=b'x')
    s3.delete_location('pod')
    assert keys(s3) == ['other/6', 'podcast/5']
    # Nothing there is not an error
    s3.delete_location('pod')

def test_s3_presign(s3):
    s3.client.put_object(Bucket='bucket', Key='a/one.mp3', Body=b'abc')
    url = s3.presign('a/one.mp3')
    assert 'a/one.mp3' in url
    assert 'X-Amz-Expires=86400' in url
    assert 'X-Amz-Signature' in url

def test_s3_write_index(s3):
    s3.write_index({'podcasts': []})
    response = s3.client.get_object(Bucket='bucket', Key='index.json')
    assert response['ContentType'] == 'application/json'
    assert response['Body'].read() == b'{\n  "podcasts": []\n}'

@pytest.mark.parametrize('method,args,message', [
    ('move', ('a', 'b'), 'Unable to move'),
    ('delete', ('a',), 'Unable to delete a'),
    ('delete_location', ('a',), 'Unable to delete prefix'),
    ('presign', ('a',), 'Unable to presign'),
    ('write_index', ({},), 'Unable to write index'),
])
def test_s3_errors_become_hathor_exceptions(s3, mocker, method, args, message):
    for name in ('copy', 'delete_object', 'get_paginator', 'generate_presigned_url', 'put_object'):
        mocker.patch.object(s3.client, name, side_effect=client_error())
    with pytest.raises(HathorException, match=message):
        getattr(s3, method)(*args)

def test_storage_from_options_local():
    assert isinstance(storage.storage_from_options(None), LocalStorage)
    assert isinstance(storage.storage_from_options({'type': 'local'}), LocalStorage)

def test_storage_from_options_invalid():
    with pytest.raises(HathorException, match='Invalid storage type "nope"'):
        storage.storage_from_options({'type': 'nope'})
    with pytest.raises(HathorException, match='requires a bucket_name'):
        storage.storage_from_options({'type': 's3'})

def test_storage_from_options_aws():
    result = storage.storage_from_options({'type': 's3', 'bucket_name': 'b', 'region_name': 'us-east-1',
                                           'access_key_id': 'id', 'secret_access_key': 'secret',
                                           'scratch_directory': '/scratch', 'index_object': 'i.json',
                                           'url_expiry_hours': 6})
    assert (result.bucket_name, result.scratch_directory, result.index_object) == ('b', '/scratch', 'i.json')
    assert result.url_expiry_hours == 6
    assert result.client.meta.config.s3['addressing_style'] == 'auto'
    assert result.client.meta.config.request_checksum_calculation == 'when_required'
    assert result.client.meta.config.signature_version == 's3v4'

def test_storage_from_options_custom_endpoint_is_path_style():
    result = storage.storage_from_options({
        'type': 's3', 'bucket_name': 'b', 'region_name': 'us-ashburn-1',
        'endpoint_url': 'https://ns.compat.objectstorage.us-ashburn-1.oraclecloud.com',
        'access_key_id': 'id', 'secret_access_key': 'secret'})
    assert result.client.meta.config.s3['addressing_style'] == 'path'
    assert result.client.meta.endpoint_url == 'https://ns.compat.objectstorage.us-ashburn-1.oraclecloud.com'

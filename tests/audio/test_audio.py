from tempfile import NamedTemporaryFile
from unittest.mock import patch, MagicMock

import pytest

from mutagen.id3._util import ID3NoHeaderError
from mutagen.mp3 import HeaderNotFoundError

from hathor.audio import metadata
from hathor.exc import AudioFileException

from tests import utils as test_utils

def test_audio_tags():
    with test_utils.temp_audio_file(suffix='.mp3') as temp_audio:
        print('temp audio', temp_audio)
        args = {
            'title' : test_utils.random_string(),
            'album' : test_utils.random_string(),
            'performer'  : test_utils.random_string(),
            'tracknumber' : '1/2',
            'discnumber' : '1/1',
            'genre' : test_utils.random_string(),
            'date' : '2015',
            'copyright' : test_utils.random_string(),
            'albumartist' : test_utils.random_string(),
        }
        metadata.tags_update(temp_audio, args)
        new_tags = metadata.tags_show(temp_audio)
        assert new_tags['title'] == args['title']
        metadata.tags_delete(temp_audio, list(args.keys()))
        new_tags = metadata.tags_show(temp_audio)
        assert not new_tags

def test_audio_tags_none_not_set():
    with test_utils.temp_audio_file(suffix='.mp3') as temp_audio:
        args = {
            'title' : test_utils.random_string(),
            'album' : None,
        }
        metadata.tags_update(temp_audio, args)
        new_tags = metadata.tags_show(temp_audio)
        assert new_tags['title'] == args['title']
        assert 'album' not in new_tags

def test_audio_tags_delete_args_not_there():
    with test_utils.temp_audio_file(suffix='.mp3') as temp_audio:
        args = {
            'title' : test_utils.random_string(),
            'album' : test_utils.random_string(),
            'artist' : test_utils.random_string(),
            'albumartist' : test_utils.random_string(),
        }
        metadata.tags_update(temp_audio, args)
        metadata.tags_delete(temp_audio, ['foo'])
        new_tags = metadata.tags_show(temp_audio)
        assert new_tags == args

def test_audio_tags_reset_mp4():
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio:
        args = {
            'title' : test_utils.random_string(),
        }
        metadata.tags_update(temp_audio, args)
        metadata.tags_delete(temp_audio, ['foo', 'bar'])
        new_tags = metadata.tags_show(temp_audio)
        assert new_tags == args

def test_audio_picture_extract_data_jpg():
    with test_utils.temp_audio_file(suffix='.mp3') as temp_audio:
        # test with jpg
        with test_utils.temp_image_file() as temp_pic:
            with open(temp_pic, 'rb') as reader:
                temp_pic_data = reader.read()
            metadata.picture_update(temp_audio, temp_pic)
            with NamedTemporaryFile(suffix='.jpg') as new_temp_pic:
                metadata.picture_extract(temp_audio, new_temp_pic.name)
                with open(new_temp_pic.name, 'rb') as reader:
                    new_temp_data = reader.read()
                assert new_temp_data == temp_pic_data

def test_audio_picture_update_invalid_type():
    with test_utils.temp_audio_file(suffix='.mp3') as temp_audio:
        with NamedTemporaryFile(suffix='.foo') as temp_file:
            with pytest.raises(AudioFileException) as error:
                metadata.picture_update(temp_audio, temp_file.name)
            assert 'Unsupported image type:' in str(error.value)

def test_audio_picture_update_replaces_existing():
    with test_utils.temp_audio_file(suffix='.mp3') as temp_audio:
        with test_utils.temp_image_file() as temp_pic:
            metadata.picture_update(temp_audio, temp_pic)
            # second call should delete the existing APIC tag and set a new one
            metadata.picture_update(temp_audio, temp_pic)
            with NamedTemporaryFile(suffix='.jpg') as new_temp_pic:
                result = metadata.picture_extract(temp_audio, new_temp_pic.name)
                assert result['mime'] == 'image/jpeg'

def test_audio_picture_extract_no_picture():
    with test_utils.temp_audio_file(suffix='.mp3') as temp_audio:
        with NamedTemporaryFile(suffix='.jpg') as output:
            with pytest.raises(AudioFileException) as error:
                metadata.picture_extract(temp_audio, output.name)
            assert 'Unable to find picture' in str(error.value)

def test_audio_picture_extract_wrong_suffix():
    with test_utils.temp_audio_file(suffix='.mp3') as temp_audio:
        with test_utils.temp_image_file() as temp_pic:
            metadata.picture_update(temp_audio, temp_pic)
            with NamedTemporaryFile(suffix='.png') as output:
                with pytest.raises(AudioFileException) as error:
                    metadata.picture_extract(temp_audio, output.name)
                assert 'Invalid suffix' in str(error.value)

def test_generate_metadata_header_not_found():
    with patch('hathor.audio.metadata.mutagen_file', side_effect=HeaderNotFoundError('bad file')):
        with pytest.raises(AudioFileException):
            metadata.tags_show('/fake/file.mp3')

def test_generate_metadata_unsupported_type():
    with patch('hathor.audio.metadata.mutagen_file', return_value=None):
        with pytest.raises(AudioFileException) as error:
            metadata.tags_show('/fake/file.xyz')
        assert 'Unsupported type' in str(error.value)

def test_generate_id3_no_header():
    with patch('hathor.audio.metadata.ID3', side_effect=ID3NoHeaderError('no id3')):
        with pytest.raises(AudioFileException) as error:
            metadata.picture_extract('/fake/file.mp3', '/fake/out.jpg')
        assert 'Invalid file' in str(error.value)

def test_audio_picture_extract_unknown_mime():
    mock_picture = MagicMock()
    mock_picture.mime = 'application/octet-stream'
    mock_id3 = MagicMock()
    mock_id3.__iter__ = MagicMock(return_value=iter(['APIC']))
    mock_id3.__getitem__ = MagicMock(return_value=mock_picture)
    with patch('hathor.audio.metadata.ID3', return_value=mock_id3):
        with patch('hathor.audio.metadata.guess_extension', return_value=None):
            with pytest.raises(AudioFileException) as error:
                metadata.picture_extract('/fake/file.mp3', '/fake/out.bin')
            assert 'Unrecognised picture mimetype' in str(error.value)

def test_tags_update_type_error():
    mock_audio = MagicMock()
    mock_audio.__iter__ = MagicMock(return_value=iter([]))
    mock_audio.__setitem__ = MagicMock(side_effect=TypeError('bad type'))
    mock_audio.__delitem__ = MagicMock(side_effect=KeyError)
    with patch('hathor.audio.metadata.mutagen_file', return_value=mock_audio):
        with pytest.raises(AudioFileException) as error:
            metadata.tags_update('/fake/file.mp3', {'title': 'test'})
        assert 'Unable to add key value' in str(error.value)

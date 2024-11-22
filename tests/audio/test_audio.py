from tempfile import NamedTemporaryFile

import pytest


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

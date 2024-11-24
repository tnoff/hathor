import os
from tempfile import NamedTemporaryFile

from mutagen.id3._util import ID3NoHeaderError

from hathor.audio import metadata
from hathor import utils
from hathor.exc import AudioFileException

from tests import utils as test_utils

def mutagen_mock(_, **__):
    return None

def id3_mock(_, **__):
    raise ID3NoHeaderError('')

def test_audio_tags():
    with test_utils.temp_audio_file(suffix='.mp3') as temp_audio:
        print('temp audio', temp_audio)
        args = {
            'title' : utils.random_string(),
            'album' : utils.random_string(),
            'performer'  : utils.random_string(),
            'tracknumber' : '1/2',
            'discnumber' : '1/1',
            'genre' : utils.random_string(),
            'date' : '2015',
            'copyright' : utils.random_string(),
            'albumartist' : utils.random_string(),
        }
        metadata.tags_update(temp_audio, args)
        new_tags = metadata.tags_show(temp_audio)
        assert new_tags['title'] == args['title']
        metadata.tags_delete(temp_audio, list(args.keys()))
        new_tags = metadata.tags_show(temp_audio)
        assert new_tags == {}

def test_audio_tags_none_not_set():
    with test_utils.temp_audio_file(suffix='.mp3') as temp_audio:
        print('temp audio', temp_audio)
        args = {
            'title' : utils.random_string(),
            'album' : None,
        }
        metadata.tags_update(temp_audio, args)
        new_tags = metadata.tags_show(temp_audio)
        assert new_tags['title'] == args['title']
        assert 'album' not in list(new_tags.keys())

def test_audio_tags_delete_args_not_there():
    with test_utils.temp_audio_file(suffix='.mp3') as temp_audio:
        args = {
            'title' : utils.random_string(),
            'album' : utils.random_string(),
            'artist' : utils.random_string(),
            'albumartist' : utils.random_string(),
        }
        metadata.tags_update(temp_audio, args)
        metadata.tags_delete(temp_audio, ['foo'])
        new_tags = metadata.tags_show(temp_audio)
        assert new_tags == args

def test_audio_tags_reset_mp4():
    with test_utils.temp_audio_file(suffix='.mp4') as temp_audio:
        args = {
            'title' : utils.random_string(),
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

'''

class TestAudio(test_utils.TestHelper):

    def test_audio_picture_update_invalid_type(self):
        # foo is a bad file to load from
        with utils.temp_file(suffix='.foo') as test_file:
            with test_utils.temp_audio_file(open_data=False) as temp_audio:
                with self.assertRaises(AudioFileException) as error:
                    metadata.picture_update(temp_audio, test_file)
                self.check_error_message('Unsupported image type:%s' % test_file, error)

        # test the ones that work
        with test_utils.temp_image_file(suffix='.jpg') as test_file:
            with test_utils.temp_audio_file(open_data=False) as temp_audio:
                metadata.picture_update(temp_audio, test_file)
        with test_utils.temp_image_file(suffix='.png') as test_file:
            with test_utils.temp_audio_file(open_data=False) as temp_audio:
                metadata.picture_update(temp_audio, test_file)

    def test_audio_picture_extract_name_overriden(self):
        with test_utils.temp_audio_file(open_data=False) as temp_audio:
            # give it a bad ending, should be overriden with .jpg
            with test_utils.temp_image_file() as temp_pic:
                metadata.picture_update(temp_audio, temp_pic)
                with utils.temp_file(suffix='.foo') as new_temp_pic:
                    output = metadata.picture_extract(temp_audio, new_temp_pic)
                    actual_path = output['output_path']
                    self.assertNotEqual(actual_path, new_temp_pic)
                    self.assertTrue(actual_path.endswith('.jpg'))
                    # make sure file gets deleted
                    os.remove('%s.jpg' % new_temp_pic)
            # give it a bad ending, should be overriden with .png
            with test_utils.temp_image_file(suffix='.png') as temp_pic:
                metadata.picture_update(temp_audio, temp_pic)
                with utils.temp_file(suffix='.foo') as new_temp_pic:
                    output = metadata.picture_extract(temp_audio, new_temp_pic)
                    actual_path = output['output_path']
                    self.assertNotEqual(actual_path, new_temp_pic)
                    self.assertTrue(actual_path.endswith('.png'))
                    # make sure file gets deleted
                    os.remove('%s.png' % new_temp_pic)
'''
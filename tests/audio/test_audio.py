import os

from mutagen.id3._util import ID3NoHeaderError
import mock

from hathor.audio import metadata
from hathor import utils
from hathor.exc import AudioFileException

from tests import utils as test_utils

def mutagen_mock(_, **__):
    return None

def id3_mock(_, **__):
    raise ID3NoHeaderError('')

class TestAudio(test_utils.TestHelper):
    def test_generate_metadata(self):
        with mock.patch('mutagen.File', side_effect=mutagen_mock):
            with self.assertRaises(AudioFileException) as error:
                metadata._generate_metadata('foo') #pylint:disable=protected-access
            self.check_error_message('Unsupported type for tags on file foo', error)

    def test_generate_id(self):
        with mock.patch('mutagen.id3.ID3', side_effect=id3_mock):
            with self.assertRaises(AudioFileException) as error:
                metadata._generate_id3('foo.mp3') #pylint:disable=protected-access
            self.check_error_message('Invalid file foo.mp3 type -- ', error)

    def test_audio_tags(self):
        with test_utils.temp_audio_file(open_data=False) as temp:
            args = {
                'title' : utils.random_string(),
                'album' : utils.random_string(),
                'performer'  : utils.random_string(),
                'track_number' : '1/2',
                'disc_number' : '1/1',
                'genre' : utils.random_string(),
                'date' : '2015',
                'copyright' : utils.random_string(),
                'album_artist' : utils.random_string(),
            }
            metadata.tags_update(temp, **args)
            new_tags = metadata.tags_show(temp)
            self.assertEqual(args, new_tags)
            for key in args:
                metadata.tags_delete(temp, key)
            new_tags = metadata.tags_show(temp)
            self.assertEqual(new_tags, {})

    def test_audio_tags_none_isnt_set(self):
        with test_utils.temp_audio_file(open_data=False) as temp:
            args = {
                'title' : utils.random_string(),
                'album' : None,
            }
            metadata.tags_update(temp, **args)
            new_tags = metadata.tags_show(temp)
            self.assertEqual(new_tags, {'title' : args['title']})

    def test_audio_tags_delete_args_not_there(self):
        with test_utils.temp_audio_file(open_data=False) as temp:
            args = {
                'title' : utils.random_string(),
                'album' : utils.random_string(),
                'artist' : utils.random_string(),
                'album_artist' : utils.random_string(),
            }
            metadata.tags_update(temp, **args)
            metadata.tags_delete(temp, 'foo')
            new_tags = metadata.tags_show(temp)
            self.assertEqual(args, new_tags)

    def test_audio_tags_reset_mp4(self):
        with test_utils.temp_audio_file(open_data=False, suffix='.mp4') as temp:
            args = {
                'title' : utils.random_string(),
            }
            metadata.tags_update(temp, **args)
            metadata.tags_delete(temp, 'foo', 'bar')
            new_tags = metadata.tags_show(temp)
            self.assertEqual(new_tags, args)

    def test_audio_picture_extract_data(self):
        # test picture update and extract and data is same
        with test_utils.temp_audio_file(open_data=False) as temp_audio:
            # test with jpg
            with test_utils.temp_image_file() as temp_pic:
                with open(temp_pic, 'rb') as reader:
                    temp_pic_data = reader.read()
                metadata.picture_update(temp_audio, temp_pic)
                with utils.temp_file(suffix='.jpg') as new_temp_pic:
                    metadata.picture_extract(temp_audio, new_temp_pic)
                    with open(new_temp_pic, 'rb') as reader:
                        new_temp_data = reader.read()
                    self.assertEqual(new_temp_data, temp_pic_data)

            # test with png
            with test_utils.temp_image_file(suffix='.png') as temp_pic:
                with open(temp_pic, 'rb') as reader:
                    temp_pic_data = reader.read()
                metadata.picture_update(temp_audio, temp_pic)

                with utils.temp_file(suffix='.png') as new_temp_pic:
                    metadata.picture_extract(temp_audio, new_temp_pic)
                    with open(new_temp_pic, 'rb') as reader:
                        new_temp_data = reader.read()
                    self.assertEqual(new_temp_data, temp_pic_data)

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

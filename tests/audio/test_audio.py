import os

from mutagen.id3._util import ID3NoHeaderError
import mock

from hathor.audio import editor, metadata
from hathor import utils
from hathor.exc import AudioFileException

from tests import utils as test_utils
from tests.audio.data import audio_volume_data
from tests.audio.data import audio_volume_data_no_commercial

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

    def test_generate_volume_data(self):
        length = 12
        with test_utils.temp_audio_file(open_data=False, duration=length) as temp_audio:
            volume_data = editor.generate_audio_volume_array(temp_audio)
            self.assert_length(volume_data, length - 1)

    def test_volume_data_csv(self): #pylint:disable=no-self-use
        with test_utils.temp_audio_file(open_data=False) as temp_audio:
            with utils.temp_file(suffix='.csv') as temp_csv:
                editor.volume_data_csv(temp_audio, temp_csv)

    def test_volume_data_png(self): #pylint:disable=no-self-use
        with test_utils.temp_audio_file(open_data=False) as temp_audio:
            with utils.temp_file(suffix='.png') as temp_png:
                editor.volume_data_png(temp_audio, temp_png)

    def test_identify_commercials(self):
        audio_data = audio_volume_data.DATA
        commercial_intervals = editor.guess_commercial_intervals(audio_data)
        self.assert_length(commercial_intervals, 4)
        non_commercials = editor.invert_intervals(commercial_intervals, len(audio_data))
        self.assert_length(non_commercials, 5)

    def test_identify_commercials_returns_none(self):
        audio_data = audio_volume_data_no_commercial.DATA
        commercial_intervals = editor.guess_commercial_intervals(audio_data)
        self.assert_length(commercial_intervals, 0)
        non_commercials = editor.invert_intervals(commercial_intervals, len(audio_data))
        self.assertEqual(non_commercials, [(0, len(audio_data) - 1)])

    def test_fix_index_overlap(self):
        index = [(2, 3), (4, 7), (5, 9)]
        result = editor._fix_index_overlap(index) #pylint:disable=protected-access
        self.assertEqual(result, [(2, 3), (4, 9)])

        result = editor._fix_index_overlap([]) #pylint:disable=protected-access
        self.assertEqual(result, [])

        index = [(2, 3), (4, 7), (9, 12)]
        result = editor._fix_index_overlap(index) #pylint:disable=protected-access
        self.assertEqual(result, index)

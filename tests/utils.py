from contextlib import contextmanager
import logging
import os
import unittest

import httpretty
from moviepy.editor import AudioClip, ImageClip
import numpy as np
from PIL import Image
import yt_dlp

from hathor import client, utils

DATETIME_FORMAT = '%Y-%m-%d'

def mock_mp3_download(url, mp3_body):
    httpretty.register_uri(httpretty.GET, url, body=mp3_body, stream=True, content_type='audio/mpeg')

@contextmanager
def temp_audio_file(open_data=True, duration=2, suffix='.mp3', delete=True):
    assert suffix in ['.mp3', '.mp4'], 'Invalid suffix type:%s' % suffix
    # logic taken from https://zulko.github.io/moviepy/ref/AudioClip.html?highlight=sin
    with utils.temp_file(suffix=suffix, delete=delete) as temp_file:
        audio_frames = lambda t: 2 *[np.sin(404 * 2 * np.pi * t)]
        audioclip = AudioClip(audio_frames, duration=duration)
        if suffix == '.mp3':
            audioclip.write_audiofile(temp_file, logger=None)
        else:
            image = ImageClip(np.random.rand(30, 30, 3) * 255)
            videoclip = image.set_audio(audioclip)
            videoclip.duration = duration
            videoclip.fps = 24
            videoclip.write_videofile(temp_file, logger=None)
        try:
            if not open_data:
                yield temp_file
            else:
                with open(temp_file, 'rb') as f:
                    data = f.read()
                    yield data
        finally:
            pass

@contextmanager
def temp_image_file(suffix='.jpg'):
    # stolen from http://stackoverflow.com/questions/10901049/create-set-of-random-jpgs
    with utils.temp_file(suffix=suffix) as temp:
        randoms = np.random.rand(30, 30, 3) * 255
        im_out = Image.fromarray(randoms.astype('uint8')).convert('RGB')
        im_out.save(temp)
        yield temp

@contextmanager
def temp_dir(name=None, delete=True):
    if name is None:
        name = utils.random_string(prefix='/tmp/')
    name = os.path.abspath(name)
    try:
        os.makedirs(name)
        yield name
    finally:
        if delete:
            try:
                os.rmdir(name)
            except OSError as exc:
                if exc.errno == os.errno.ENOENT:
                    pass
                else:
                    raise

@contextmanager
def temp_client(database_file=None, soundcloud_client_id=True, google_api_key=True,
                logging_level=logging.DEBUG, log_file=None, podcast_directory=None):
    soundcloud = None
    google = None
    if soundcloud_client_id:
        soundcloud = utils.random_string()
    if google:
        google = utils.random_string()
    pod_client = client.HathorClient(podcast_directory=podcast_directory,
                                     logging_file=log_file,
                                     logging_file_level=logging_level,
                                     database_file=database_file,
                                     soundcloud_client_id=soundcloud,
                                     google_api_key=google,
                                     console_logging=False)
    try:
        yield {
            'podcast_client' : pod_client,
            'soundcloud_client_id' : soundcloud_client_id,
            'google_api_key' : google_api_key,
        }
    finally:
        pass

@contextmanager
def temp_podcast(pod_client, broadcast_url=False, delete=True, **kwargs):
    archive_type = kwargs.pop('archive_type', 'rss')
    podcast_name = kwargs.pop('podcast_name', utils.random_string())
    broadcast_id = kwargs.pop('broadcast_id', None)
    if broadcast_id is None:
        if broadcast_url:
            broadcast_id = 'http://example.%s.com' % utils.random_string()
        else:
            broadcast_id = utils.random_string()
    with temp_dir() as temp:
        podcast = pod_client.podcast_create(archive_type, broadcast_id,
                                            podcast_name,
                                            file_location=temp,
                                            **kwargs)
        try:
            yield podcast
        finally:
            if delete:
                pod_client.podcast_delete(podcast['id'])

class YoutubeClass(object):
    def __init__(self, options, mock_live=False, raise_error=False):
        self.output_name = None
        self.hooks = options.pop('progress_hooks', None) or []
        self.is_live = mock_live
        # only mock first one, just need to know skips at least once
        self.has_been_mocked = False
        self.raise_error = raise_error

    def download(self, _):
        if self.raise_error:
            raise yt_dlp.utils.DownloadError('error message')
        with temp_audio_file(suffix='.mp4') as mp4_body:
            with utils.temp_file(delete=False, suffix='.mp4') as temp_file:
                with open(temp_file, 'wb') as write:
                    write.write(mp4_body)
            dictionary = {
                'status' : 'finished',
                'filename' : temp_file,
            }
            for hook in self.hooks:
                hook(dictionary)

    def extract_info(self, _, **__):
        if self.raise_error:
            raise yt_dlp.utils.DownloadError('error message')
        data = {
            'is_live' : self.is_live,
            'description' : 'foo',
        }
        if not self.has_been_mocked and self.is_live:
            self.has_been_mocked = True
            self.is_live = False
        return data

@contextmanager
def youtube_mock(options):
    try:
        yield YoutubeClass(options)
    finally:
        pass

@contextmanager
def youtube_mock_live(options):
    try:
        yield YoutubeClass(options, mock_live=True)
    finally:
        pass

@contextmanager
def youtube_mock_error(options):
    try:
        yield YoutubeClass(options, raise_error=True)
    finally:
        pass

class TestHelper(unittest.TestCase):

    def assert_length(self, obj, length):
        self.assertEqual(len(obj), length)

    def assert_not_length(self, obj, length):
        self.assertNotEqual(len(obj), length)

    def assert_none(self, obj):
        self.assertEqual(obj, None)

    def assert_not_none(self, obj):
        self.assertNotEqual(obj, None)

    def assert_dictionary(self, dictionary, skip=None):
        skips = skip or []
        for key, value in dictionary.items():
            if key in skips:
                continue
            if value is None:
                self.fail("Key %s cannot be None" % key)
            if value is []:
                self.fail("Key %s cannot be empty list" % key)

    def check_error_message(self, message, error):
        self.assertEqual(message, str(error.exception))

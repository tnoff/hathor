from contextlib import contextmanager
import logging
import os
from tempfile import NamedTemporaryFile
import random
import string
import unittest

from moviepy.audio.AudioClip import AudioClip
from moviepy.video.VideoClip import ImageClip
import numpy as np
from PIL import Image
import yt_dlp

from hathor import client, utils

DATETIME_FORMAT = '%Y-%m-%d'


def random_string(prefix: str = '', suffix: str = '', length: int = 10):
    chars = string.ascii_lowercase + string.digits
    tempy = ''.join(random.choice(chars) for _ in range(length))
    return prefix + tempy + suffix

@contextmanager
def temp_audio_file(duration=2, suffix='.mp3'):
    # logic taken from https://zulko.github.io/moviepy/ref/AudioClip.html?highlight=sin
    with NamedTemporaryFile(suffix=suffix) as temp_file:
        print('tempfile', temp_file, temp_file.name)
        audio_frames = lambda t: 2 *[np.sin(404 * 2 * np.pi * t)]
        audioclip = AudioClip(audio_frames, duration=duration)
        if suffix == '.mp3':
            audioclip.write_audiofile(temp_file.name, fps=44100, logger=None)
        else:
            image = ImageClip(np.random.rand(30, 30, 3) * 255)
            videoclip = image.with_audio(audioclip)
            videoclip.duration = duration
            videoclip.fps = 24
            videoclip.write_videofile(temp_file.name, logger=None)
        yield temp_file.name

@contextmanager
def temp_image_file(suffix='.jpg'):
    # stolen from http://stackoverflow.com/questions/10901049/create-set-of-random-jpgs
    with NamedTemporaryFile(suffix=suffix) as temp_file:
        randoms = np.random.rand(30, 30, 3) * 255
        im_out = Image.fromarray(randoms.astype('uint8')).convert('RGB')
        im_out.save(temp_file.name)
        yield temp_file.name

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
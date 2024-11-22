from contextlib import contextmanager
from tempfile import NamedTemporaryFile
import random
import string

from moviepy.audio.AudioClip import AudioClip
from moviepy.video.VideoClip import ImageClip
import numpy as np
from PIL import Image

def random_string(prefix: str = '', suffix: str = '', length: int = 10):
    chars = string.ascii_lowercase + string.digits
    tempy = ''.join(random.choice(chars) for _ in range(length))
    return prefix + tempy + suffix

@contextmanager
def temp_audio_file(duration=2, suffix='.mp3'):
    # logic taken from https://zulko.github.io/moviepy/ref/AudioClip.html?highlight=sin
    try:
        with NamedTemporaryFile(suffix=suffix) as temp_file:
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
    except FileNotFoundError:
        pass


@contextmanager
def temp_image_file(suffix='.jpg'):
    # stolen from http://stackoverflow.com/questions/10901049/create-set-of-random-jpgs
    with NamedTemporaryFile(suffix=suffix) as temp_file:
        randoms = np.random.rand(30, 30, 3) * 255
        im_out = Image.fromarray(randoms.astype('uint8')).convert('RGB')
        im_out.save(temp_file.name)
        yield temp_file.name

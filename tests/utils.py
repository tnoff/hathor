from contextlib import contextmanager
from pathlib import Path
from shutil import copyfile
from tempfile import NamedTemporaryFile
import os
import random
import string

FIXTURES_DIR = Path(__file__).parent / 'fixtures'

def random_string(prefix: str = '', suffix: str = '', length: int = 10):
    chars = string.ascii_lowercase + string.digits
    tempy = ''.join(random.choice(chars) for _ in range(length))
    return prefix + tempy + suffix

@contextmanager
def temp_audio_file(suffix='.mp3'):
    src = FIXTURES_DIR / f'test_audio{suffix}'
    with NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
        copyfile(src, temp_file.name)
    try:
        yield temp_file.name
    finally:
        try:
            os.unlink(temp_file.name)
        except FileNotFoundError:
            pass

@contextmanager
def temp_image_file(suffix='.jpg'):
    src = FIXTURES_DIR / f'test_image{suffix}'
    with NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
        copyfile(src, temp_file.name)
    try:
        yield temp_file.name
    finally:
        try:
            os.unlink(temp_file.name)
        except FileNotFoundError:
            pass

from contextlib import contextmanager
import os
import random
import string

from urllib.parse  import urlparse

def process_url(url):
    processed_url = urlparse(url)
    return f'{processed_url.scheme}://{processed_url.netloc}/{processed_url.path}'

def random_string(prefix='', suffix='', length=10):
    chars = string.ascii_lowercase + string.digits
    tempy = ''.join(random.choice(chars) for _ in range(length))
    return prefix + tempy + suffix

def normalize_name(name):
    valid_chars = string.ascii_lowercase + string.digits
    valid_chars += string.ascii_uppercase + '_' + ' '

    bad_chars = []
    for char in name:
        if char not in valid_chars:
            bad_chars.append(char)
    for char in bad_chars:
        name = name.replace(char, '_')

    while True:
        new_name = name.replace('__', '_')
        if new_name == name:
            break
        name = new_name

    name = name.lstrip('_')
    name = name.rstrip('_')
    return name

def clean_string(stringy):
    if stringy is None:
        return None
    s = stringy.lstrip(' ')
    s = s.rstrip(' ').rstrip('\n').rstrip(' ')
    s = s.replace('\n', ' ').replace('\r', '')
    return s

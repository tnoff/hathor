from io import BytesIO
from pathlib import Path
import warnings

from PIL import Image
from requests import get
from requests.exceptions import RequestException

from hathor.exc import HathorException
from hathor import utils

MAX_IMAGE_BYTES = 5 * 1024 * 1024
# Podcast apps ask for 1400 to 3000 pixels square, and a bigger file is only a slower page and
# feed for the phone. Longest side after resizing
MAX_IMAGE_SIDE = 1400
# A small file can still decode to a huge bitmap (a decompression bomb). Kept below the 89 million
# at which Pillow starts warning, so this check is the one that normally answers
MAX_IMAGE_PIXELS = 50_000_000
IMAGE_TIMEOUT = 30
IMAGE_EXTENSIONS = ('.jpg', '.png', '.gif', '.webp')

def image_extension(data: bytes) -> str | None:
    '''
    File extension for image bytes, from the file's magic bytes rather than from a content type
    or a name, since either can say anything. None when the bytes are not a supported image

    data    :   Start of the file (the first 12 bytes are enough)
    '''
    if data.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return '.gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp'
    return None

def _too_big(max_bytes: int) -> HathorException:
    return HathorException(f'Image is larger than {max_bytes} bytes')

def _download(url: str, max_bytes: int, timeout: int) -> bytes:
    try:
        response = get(url, allow_redirects=True, timeout=timeout, stream=True)
        try:
            response.raise_for_status()
            if int(response.headers.get('Content-Length') or 0) > max_bytes:
                raise _too_big(max_bytes)
            data = b''
            for chunk in response.iter_content(chunk_size=64 * 1024):
                data += chunk
                if len(data) > max_bytes:
                    raise _too_big(max_bytes)
        finally:
            response.close()
    except RequestException as error:
        # The url can carry a signed token in its query string
        raise HathorException(f'Unable to download image: {utils.scrub_error(str(error))}') from error
    return data

def _decode(data: bytes, extension: str) -> tuple[bytes, str]:
    '''
    Decode the whole image, which refuses a truncated or corrupt one the magic bytes let through,
    and shrink it if it is larger than MAX_IMAGE_SIDE. An image that is already small enough is
    returned exactly as it came

    A resized image with transparency is written as png, anything else as jpeg. An animated image
    keeps only its first frame when it is resized
    '''
    try:
        with warnings.catch_warnings():
            # Pillow warns before it refuses a very large bitmap; either way it is too big
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                width, height = image.size
                if width * height > MAX_IMAGE_PIXELS:
                    raise HathorException(f'Image is {width}x{height} pixels, larger than {MAX_IMAGE_PIXELS}')
                image.load()
                if max(width, height) <= MAX_IMAGE_SIDE:
                    return data, extension
                image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
                transparent = image.mode in ('RGBA', 'LA') or 'transparency' in image.info
                output = BytesIO()
                if transparent:
                    image.convert('RGBA').save(output, 'PNG', optimize=True)
                    return output.getvalue(), '.png'
                image.convert('RGB').save(output, 'JPEG', quality=85, optimize=True)
                return output.getvalue(), '.jpg'
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise HathorException(f'Not a readable image: {error}') from error

def load_image(source: str, max_bytes: int = MAX_IMAGE_BYTES, timeout: int = IMAGE_TIMEOUT) -> tuple[bytes, str]:
    '''
    Read an image from a url or a local file and check it really is one

    Nothing is trusted but the bytes: the extension comes from the magic bytes, and a
    response that is not an image (an html error page served with a 200, say) is refused. The
    image is then decoded in full, so a corrupt one is refused too, and shrunk to MAX_IMAGE_SIDE
    if it is larger

    source      :   http(s) url or path of a file
    max_bytes   :   Largest image accepted
    timeout     :   Seconds to wait on the server

    Returns: the image bytes and the file extension for them, such as .jpg
    '''
    if source.startswith(('http://', 'https://')):
        data = _download(source, max_bytes, timeout)
    else:
        path = Path(source)
        if not path.is_file():
            raise HathorException(f'Image file not found: {source}')
        if path.stat().st_size > max_bytes:
            raise _too_big(max_bytes)
        data = path.read_bytes()
    extension = image_extension(data[:12])
    if extension is None:
        raise HathorException('Not a supported image, expected jpeg, png, gif or webp')
    return _decode(data, extension)

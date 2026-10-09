from pathlib import Path

from requests import get
from requests.exceptions import RequestException

from hathor.exc import HathorException
from hathor import utils

MAX_IMAGE_BYTES = 5 * 1024 * 1024
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

def load_image(source: str, max_bytes: int = MAX_IMAGE_BYTES, timeout: int = IMAGE_TIMEOUT) -> tuple[bytes, str]:
    '''
    Read an image from a url or a local file and check it really is one

    Nothing is trusted but the bytes: the extension comes from the magic bytes, and a
    response that is not an image (an html error page served with a 200, say) is refused

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
    return data, extension

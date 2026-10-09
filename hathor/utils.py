from logging import getLogger, Formatter, StreamHandler, RootLogger
from logging.handlers import RotatingFileHandler
import mimetypes
import os
import re
from string import ascii_lowercase, ascii_uppercase, digits
from tempfile import NamedTemporaryFile

from pathlib import Path
from urllib.parse  import urlparse

def process_url(url: str) -> str:
    '''
    Process url and remove extra options

    url: Basic url string
    '''
    processed_url = urlparse(url)
    return f'{processed_url.scheme}://{processed_url.netloc}{processed_url.path}'

def check_patreon(url: str) -> bool:
    '''
    Check if patreon url

    url: Basic url string
    '''
    processed_url = urlparse(url)
    return 'patreonusercontent' in processed_url.netloc

def normalize_name(name: str) -> str:
    '''
    Remove non alpha numeric characters from string
    name: original name
    '''
    valid_chars = ascii_lowercase + digits
    valid_chars += ascii_uppercase + '_'

    new_str = ''
    for char in name:
        if char not in valid_chars:
            new_str = f'{new_str}_'
            continue
        new_str = f'{new_str}{char}'

    while True:
        new_name = new_str.replace('__', '_')
        if new_name == new_str:
            break
        new_str = new_name

    name_str = new_str.lstrip('_')
    name_str = new_str.rstrip('_')
    return name_str

def clean_string(stringy: str) -> str:
    '''
    Clean string and remove extra bits
    stringy: Original String
    '''
    if stringy is None:
        return None
    s = stringy.lstrip(' ')
    s = s.rstrip(' ').rstrip('\n').rstrip(' ')
    s = s.replace('\n', ' ').replace('\r', '')
    return s

def setup_logger(name: str,
                 logging_file: Path = None,
                 console_logging: bool = False,
                 log_level: int = 20,
                 logging_file_backup_count: int = 4,
                 logging_file_max_bytes: int = (2 ** 20) * 10) -> RootLogger:
    '''
    Setup a generic python logger
    name: Name of logger
    log_level: level
    logging_file: If given, writes to file name
    console_logging: Defaults to true, logs to stdout
    '''
    logger = getLogger(name)
    formatter = Formatter('%(asctime)s - %(levelname)s - %(message)s',
                          datefmt='%Y-%m-%d %H:%M:%S')
    logger.setLevel(log_level)
    if logging_file is not None:
        # Create logging dir if does not exist
        log_path = Path(logging_file)
        log_path.parent.mkdir(exist_ok=True)
        fh = RotatingFileHandler(logging_file,
                                 backupCount=logging_file_backup_count,
                                 maxBytes=logging_file_max_bytes)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    if console_logging:
        sh = StreamHandler()
        sh.setFormatter(formatter)
        logger.addHandler(sh)
    return logger

def rm_tree(pth: Path) -> bool:
    '''
    Remove all files in a tree
    pth: Path to remove
    '''
    # https://stackoverflow.com/questions/50186904/pathlib-recursively-remove-directory
    for child in pth.glob('*'):
        if child.is_file():
            child.unlink()
        else:
            rm_tree(child)
    pth.rmdir()
    return True

FILENAME_MAX_LENGTH = 120

def sanitize_filename(name: str) -> str:
    '''
    Make a title safe to use as a download file name

    Drops path separators, control characters and anything else that is
    awkward in a file name, but keeps unicode letters

    name: original title
    '''
    cleaned = re.sub(r'[^\w\s.,()\'&+-]', '', name)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' .')
    return cleaned[:FILENAME_MAX_LENGTH].strip(' .') or 'episode'

def display_filename(podcast_name: str, date: str | None, title: str | None, suffix: str) -> str:
    '''
    Readable name for an episode file, the one people see when it is downloaded

    podcast_name    :   Name of the podcast
    date            :   Formatted episode date, if known
    title           :   Episode title, if known
    suffix          :   File extension including the dot
    '''
    parts = [podcast_name]
    if date:
        parts.append(date)
    if title:
        parts.append(title)
    return f'{sanitize_filename(" - ".join(parts))}{suffix.lower()}'

def guess_content_type(name: str) -> str:
    '''
    Content type for a file name, from its extension
    '''
    return mimetypes.guess_type(name)[0] or 'application/octet-stream'

def write_file_atomic(path: Path, text: str):
    '''
    Write a text file so that a reader sees either the old content or the new,
    never a half written file

    The file is made world readable (0644). A temp file is created 0600 and
    os.replace keeps that mode, which would lock out the very reader this exists
    for: something else, usually running as a different user, such as a web
    server sharing the volume

    path: File to write
    text: Content
    '''
    path = Path(path)
    with NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, prefix=f'.{path.name}.',
                            delete=False) as temp:
        temp.write(text)
    os.chmod(temp.name, 0o644)
    os.replace(temp.name, path)

URL_MASK = '<hidden>'

def mask_url_secrets(value):
    '''
    Hide the parts of a url that carry credentials: the query string and fragment (a private
    patreon feed puts its key there) and any user:password@ in front of the host

    Anything that is not an http(s) url, such as a youtube channel id, comes back unchanged
    A secret inside the path itself cannot be told from the rest of the path, so it is not hidden

    value: Anything; only strings that start with http:// or https:// are changed
    '''
    if not isinstance(value, str) or not re.match(r'https?://', value, re.IGNORECASE):
        return value
    scheme, rest = value.split('://', 1)
    authority, separator, remainder = rest.partition('/')
    if '@' in authority:
        authority = f'{URL_MASK}@{authority.rsplit("@", 1)[1]}'
    rest = authority + separator + remainder
    if '?' in rest:
        rest = f'{rest.split("?", 1)[0]}?{URL_MASK}'
    elif '#' in rest:
        rest = f'{rest.split("#", 1)[0]}#{URL_MASK}'
    return f'{scheme}://{rest}'

SECRET_KEY_NAME = re.compile(r'key|secret|token|passw', re.IGNORECASE)
# Settings whose url carries the secret in its path or password, where nothing in the url's
# shape gives it away: hide what follows the host
PATH_SECRET_KEYS = ('feed_base_url',)
CONNECTION_PASSWORD = re.compile(r'^([a-z][a-z0-9+.-]*://[^/@:]*):[^/@]*@', re.IGNORECASE)

def mask_config_secrets(data, key: str | None = None, secret: bool = False):
    '''
    A copy of config data that is safe to print: the value of any setting whose name looks
    like a credential (key, secret, token, password) is hidden, a url keeps its host but loses
    its query string, fragment and user:password@, and settings known to carry a secret in
    their path or password (feed_base_url, a database connection string) lose that part too

    Matching is by name, so a new setting called something else is not hidden: check
    dump-config output when adding one. Empty values are left as they are, so a setting that
    is not set still reads as not set

    Everything beneath a credential-named setting is hidden, whatever its own names are

    data:   Config data, nested however deeply
    key:    The name of the setting data was found under
    secret: True when an enclosing setting already has a credential name
    '''
    secret = secret or bool(key and SECRET_KEY_NAME.search(key))
    if isinstance(data, dict):
        return {name: mask_config_secrets(value, name, secret) for name, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [mask_config_secrets(item, key, secret) for item in data]
    if not isinstance(data, str) or not data:
        return data
    if secret:
        return URL_MASK
    if key in PATH_SECRET_KEYS:
        match = re.match(r'(https?://[^/?#]+)', data, re.IGNORECASE)
        return f'{match.group(1)}/{URL_MASK}' if match else URL_MASK
    data = CONNECTION_PASSWORD.sub(rf'\1:{URL_MASK}@', data)
    return mask_url_secrets(data)

def scrub_error(message: str) -> str:
    '''
    Drop the query string and fragment from every url in an error message

    Feed urls can carry credentials in their query string (a private patreon feed
    does), and an exception message includes the url it failed on

    message: error text
    '''
    return re.sub(r'(https?://[^\s?#"\'<>]+)[?#][^\s"\'<>]*', r'\1', message)

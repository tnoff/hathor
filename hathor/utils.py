from logging import getLogger, Formatter, StreamHandler, RootLogger
from logging.handlers import RotatingFileHandler
from string import ascii_lowercase, ascii_uppercase, digits

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

from contextlib import contextmanager
from json import dumps
import mimetypes
from pathlib import Path
import re
from shutil import move
from tempfile import TemporaryDirectory
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from hathor.exc import HathorException
from hathor.utils import rm_tree

DEFAULT_INDEX_OBJECT = 'index.json'
DEFAULT_URL_EXPIRY_HOURS = 24
# SigV4 presigned urls cannot be valid for longer than seven days
MAX_URL_EXPIRY_HOURS = 168
FILENAME_MAX_LENGTH = 120
DELETE_BATCH_SIZE = 1000
STORAGE_TYPES = ('local', 's3')

def sanitize_filename(name: str) -> str:
    '''
    Make a title safe to use as a download file name

    Drops path separators, control characters and anything else that is
    awkward in a file name, but keeps unicode letters, since the name is sent
    to the browser percent encoded

    name: original title
    '''
    cleaned = re.sub(r'[^\w\s.,()\'&+-]', '', name)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' .')
    return cleaned[:FILENAME_MAX_LENGTH].strip(' .') or 'episode'

def content_disposition(filename: str) -> str:
    '''
    Content-Disposition header that makes a browser save the file instead of
    playing it inline. Carries a plain ascii name for old clients and the real
    name as an RFC 5987 extended parameter

    filename: Name the file should be saved as
    '''
    fallback = filename.encode('ascii', 'ignore').decode().replace('"', '').replace('\\', '').strip()
    return f'attachment; filename="{fallback or "download"}"; filename*=UTF-8\'\'{quote(filename)}'

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

class LocalStorage():
    '''
    Episode files live on the local filesystem. A podcast's file location is a
    directory and an episode's file path is a file in it
    '''
    is_local = True

    @staticmethod
    def join(base, name: str) -> Path:
        '''
        Location for a new podcast under the default podcast directory
        '''
        return Path(base) / name

    @staticmethod
    def normalize_location(location) -> str:
        '''
        Absolute form of a podcast file location
        '''
        return str(Path(location).resolve())

    @staticmethod
    def same_location(first, second) -> bool:
        '''
        Whether two file locations are the same directory
        '''
        return Path(first).resolve() == Path(second).resolve()

    @staticmethod
    def prepare_location(location):
        '''
        Make sure the directory for a podcast exists
        '''
        Path(location).mkdir(exist_ok=True, parents=True)

    @staticmethod
    @contextmanager
    def working_directory(location):
        '''
        Directory a download is written to, which for local storage is already its final home
        '''
        yield Path(location)

    @staticmethod
    def store(local_path: Path, _location, _display_name: str | None = None) -> str:
        '''
        Put a downloaded file where it belongs. It was downloaded straight there

        Returns: file path to record for the episode
        '''
        return str(Path(local_path).resolve())

    @staticmethod
    def move(file_path, new_location) -> str:
        '''
        Move an episode file into another directory, keeping its name

        Returns: new file path
        '''
        # Not Path.rename, which is os.rename and fails with EXDEV when the two
        # directories are on different filesystems, or merely on different mount
        # points of the same filesystem -- which is what two bind mounts of one
        # drive are inside a container. move falls back to a copy and unlink.
        new_path = Path(new_location) / Path(file_path).name
        move(Path(file_path), new_path)
        return str(new_path.resolve())

    @staticmethod
    def delete(file_path) -> bool:
        '''
        Delete an episode file

        Returns: False if there was no such file
        '''
        try:
            Path(file_path).unlink()
        except FileNotFoundError:
            return False
        return True

    @staticmethod
    def delete_location(location):
        '''
        Delete a podcast directory and everything in it
        '''
        rm_tree(Path(location))

class S3Storage():  # pylint: disable=too-many-instance-attributes
    '''
    Episode files live in an S3 compatible bucket, such as AWS S3 or OCI Object
    Storage. A podcast's file location is a key prefix and an episode's file
    path is an object key. Downloads are written to a scratch directory,
    tagged, uploaded, and removed

    The bucket should stay private. Links to episodes are presigned urls
    '''
    is_local = False

    def __init__(self, client, bucket_name: str, scratch_directory: str | None = None,
                 index_object: str = DEFAULT_INDEX_OBJECT,
                 url_expiry_hours: int = DEFAULT_URL_EXPIRY_HOURS):
        '''
        client              :   boto3 s3 client
        bucket_name         :   Bucket episodes are stored in
        scratch_directory   :   Where downloads are written before upload, system temp dir if not given
        index_object        :   Key the index of episode links is written to
        url_expiry_hours    :   How long each presigned url is valid, at most 168
        '''
        if not 1 <= url_expiry_hours <= MAX_URL_EXPIRY_HOURS:
            raise HathorException(f'url_expiry_hours must be from 1 to {MAX_URL_EXPIRY_HOURS}, {url_expiry_hours} given')
        self.client = client
        self.bucket_name = bucket_name
        self.scratch_directory = scratch_directory
        self.index_object = index_object
        self.url_expiry_hours = url_expiry_hours

    @staticmethod
    def join(base, name: str) -> str:
        '''
        Location for a new podcast under the default podcast prefix
        '''
        return f'{str(base).strip("/")}/{name}'

    @staticmethod
    def normalize_location(location) -> str:
        '''
        Key prefix with no leading or trailing slashes
        '''
        normalized = re.sub(r'/+', '/', str(location)).strip('/')
        if not normalized:
            raise HathorException('A bucket location needs a non empty key prefix')
        return normalized

    @staticmethod
    def same_location(first, second) -> bool:
        '''
        Whether two file locations are the same prefix
        '''
        return S3Storage.normalize_location(first) == S3Storage.normalize_location(second)

    @staticmethod
    def prepare_location(_location):
        '''
        Prefixes need no setup
        '''

    @contextmanager
    def working_directory(self, _location):
        '''
        Scratch directory a download is written to, removed afterwards
        '''
        with TemporaryDirectory(dir=self.scratch_directory) as scratch:
            yield Path(scratch)

    def store(self, local_path: Path, location, display_name: str | None = None) -> str:
        '''
        Upload a downloaded file under a podcast's prefix

        local_path      :   Downloaded file
        location        :   Podcast file location, the key prefix
        display_name    :   Name a browser saves the file as, defaults to the file's own name

        Returns: object key to record for the episode
        '''
        local_path = Path(local_path)
        key = f'{location}/{local_path.name}'
        extra_args = {
            'ContentType': guess_content_type(local_path.name),
            'ContentDisposition': content_disposition(display_name or local_path.name),
        }
        try:
            self.client.upload_file(str(local_path), self.bucket_name, key, ExtraArgs=extra_args)
        except (BotoCoreError, ClientError, OSError) as error:
            raise HathorException(f'Unable to upload {key}: {error}') from error
        return key

    def move(self, file_path, new_location) -> str:
        '''
        Move an episode object under another prefix, keeping its name

        Returns: new object key
        '''
        new_key = f'{new_location}/{str(file_path).rsplit("/", 1)[-1]}'
        if new_key == file_path:
            # Copying an object onto itself fails on S3, and where it did not, the delete below would lose it
            return file_path
        try:
            self.client.copy({'Bucket': self.bucket_name, 'Key': file_path}, self.bucket_name, new_key)
            self.client.delete_object(Bucket=self.bucket_name, Key=file_path)
        except (BotoCoreError, ClientError) as error:
            raise HathorException(f'Unable to move {file_path} to {new_key}: {error}') from error
        return new_key

    def delete(self, file_path) -> bool:
        '''
        Delete an episode object. Deleting a key that is already gone is not an error
        '''
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=file_path)
        except (BotoCoreError, ClientError) as error:
            raise HathorException(f'Unable to delete {file_path}: {error}') from error
        return True

    def delete_location(self, location):
        '''
        Delete every object under a podcast prefix
        '''
        try:
            pages = self.client.get_paginator('list_objects_v2').paginate(Bucket=self.bucket_name,
                                                                          Prefix=f'{location}/')
            for page in pages:
                keys = [{'Key': obj['Key']} for obj in page.get('Contents', [])]
                for start in range(0, len(keys), DELETE_BATCH_SIZE):
                    self.client.delete_objects(Bucket=self.bucket_name,
                                               Delete={'Objects': keys[start:start + DELETE_BATCH_SIZE]})
        except (BotoCoreError, ClientError) as error:
            raise HathorException(f'Unable to delete prefix {location}: {error}') from error

    def presign(self, file_path) -> str:
        '''
        Time limited url to download an episode object
        '''
        try:
            return self.client.generate_presigned_url('get_object',
                                                      Params={'Bucket': self.bucket_name, 'Key': file_path},
                                                      ExpiresIn=self.url_expiry_hours * 3600)
        except (BotoCoreError, ClientError) as error:
            raise HathorException(f'Unable to presign {file_path}: {error}') from error

    def write_index(self, index: dict):
        '''
        Write the index of episode links to the bucket
        '''
        try:
            self.client.put_object(Bucket=self.bucket_name, Key=self.index_object,
                                   Body=dumps(index, indent=2).encode(), ContentType='application/json')
        except (BotoCoreError, ClientError) as error:
            raise HathorException(f'Unable to write index {self.index_object}: {error}') from error

def storage_from_options(options: dict | None):
    '''
    Build the storage backend from the storage_options section of the hathor config

    options: storage_options from the hathor config, see README
    '''
    options = options or {}
    storage_type = options.get('type', 'local')
    if storage_type == 'local':
        return LocalStorage()
    if storage_type != 's3':
        raise HathorException(f'Invalid storage type "{storage_type}", must be one of {", ".join(STORAGE_TYPES)}')
    if not options.get('bucket_name'):
        raise HathorException('s3 storage requires a bucket_name')
    endpoint_url = options.get('endpoint_url')
    client = boto3.client(
        's3',
        endpoint_url=endpoint_url,
        region_name=options.get('region_name'),
        # Credentials come from boto3's usual chain unless given here, so they
        # can stay in the environment (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        aws_access_key_id=options.get('access_key_id'),
        aws_secret_access_key=options.get('secret_access_key'),
        config=Config(
            # Presigned urls default to the legacy v2 signature in some regions,
            # and S3 compatible services generally only accept v4
            signature_version='s3v4',
            # Custom endpoints such as OCI's want path style addressing
            s3={'addressing_style': 'path' if endpoint_url else 'auto'},
            # boto3 now adds CRC checksums to every request, which S3
            # compatible services other than AWS can reject
            request_checksum_calculation='when_required',
            response_checksum_validation='when_required',
        ),
    )
    return S3Storage(client, options['bucket_name'],
                     scratch_directory=options.get('scratch_directory'),
                     index_object=options.get('index_object', DEFAULT_INDEX_OBJECT),
                     url_expiry_hours=options.get('url_expiry_hours', DEFAULT_URL_EXPIRY_HOURS))

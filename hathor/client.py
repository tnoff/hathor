# pylint: disable=too-many-lines
# HathorClient is one class by design; the sync failure handling pushed it just past 1000 lines
from datetime import datetime, timezone
import json
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from inspect import getmembers, isfunction
import os
from logging import RootLogger
import re
from hashlib import sha256
from shutil import move
from typing import Literal


from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from hathor import artwork
from hathor.audio.metadata import tags_update
from hathor.database.migrate import migrate
from hathor.database.tables import Podcast
from hathor.database.tables import PodcastEpisode, PodcastTitleFilter
from hathor import feeds
from hathor.exc import AudioFileException, EpisodeNotReady, HathorException, SyncFailure
from hathor.podcast.archive import ARCHIVE_TYPES, VALID_ARCHIVE_KEYS
from hathor import utils

# Where podcast artwork is kept, under the podcast directory
IMAGE_DIRECTORY = '.artwork'

DEFAULT_DATETIME_FORMAT = '%Y-%m-%d'

FILE_PATH = os.path.abspath(__file__)

def _load_external_plugins(plugins_dir: Path, logger) -> list:
    '''
    Load plugin functions from a directory that is not part of the package

    The files are loaded by path, so the directory can live anywhere, such as a
    volume mounted into a container. Hidden files and directories are skipped:
    a mounted Kubernetes ConfigMap holds every file three times (the file itself,
    a ..data symlink and a timestamped ..2026_... directory), and loading all of
    them would run each plugin's hook three times

    plugins_dir  :   Directory to load .py files from, recursively
    logger       :   Logger to report what was loaded
    '''
    if not plugins_dir.is_dir():
        logger.warning(f'plugins_directory {plugins_dir} is not a directory, no plugins loaded')
        return []
    functions = []
    for path in sorted(plugins_dir.glob('**/*.py')):
        relative = path.relative_to(plugins_dir)
        if path.name == '__init__.py' or not path.is_file():
            continue
        if any(part.startswith('.') for part in relative.parts):
            continue
        module_name = '.'.join(['hathor_external_plugins', *relative.with_suffix('').parts])
        spec = spec_from_file_location(module_name, path)
        module = module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as error: #pylint:disable=broad-exception-caught
            # A plugin that cannot load is a broken deployment, not something to skip over
            raise HathorException(f'Unable to load plugin {path}: {error}') from error
        found = getmembers(module, isfunction)
        logger.info(f'Loaded plugin {relative}: {", ".join(name for name, _ in found) or "no functions"}')
        functions.extend(found)
    if not functions:
        logger.warning(f'plugins_directory {plugins_dir} has no plugin functions')
    return functions

def load_plugins(plugins_directory: Path | None = None, logger=None):
    '''
    Loads plugins for dir, gets list of functions to run later

    plugins_directory   :   Load plugins from this directory instead of the package's own
                            hathor/plugins/. An explicit directory replaces the default
                            rather than adding to it, so a plugin is never loaded twice
    logger              :   Logger used when loading from plugins_directory
    '''
    if plugins_directory:
        return _load_external_plugins(Path(plugins_directory), logger or utils.setup_logger('Hathor'))
    parent_dir = Path(FILE_PATH).parent
    plugins_dir = parent_dir / 'plugins'

    functions = []
    for path in plugins_dir.glob('**/*.py'):
        if path.name == '__init__.py':
            continue
        if path.is_dir():
            continue
        relative_path = path.relative_to(parent_dir)
        # Remove .py naming
        relative_path = relative_path.parent / relative_path.stem
        import_name = f'hathor.{str(relative_path).replace(os.sep, ".")}'
        # Import and get functions
        module = import_module(import_name)
        for name, func in getmembers(module, isfunction):
            functions.append((name, func))
    return functions

def run_plugins(func):
    '''
    Decorator to add to functions
    Will add any plugin function that matches name
    '''
    def decorator(*args, **kwargs):
        func_name = func.__name__
        result = func(*args, **kwargs)
        # Assume first arg called is "self"
        selfie = args[0]
        # Look through plugins
        for plugin in selfie.plugins:
            # Plugins will be (name, func obj)
            if plugin[0] == func_name:
                # Run plugin function with client class
                # and result of original function
                plugin_func = plugin[1]
                result = plugin_func(selfie, result, *args, **kwargs)
        return result
    return decorator

ArchiveType = Literal[VALID_ARCHIVE_KEYS]

class HathorClient():  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    '''
    Hathor Client
    Sync podcasts from different sources
    '''
    def __init__(self, podcast_directory: Path | None = None,
                 datetime_output_format: str = DEFAULT_DATETIME_FORMAT,
                 logger: RootLogger | None = None,
                 database_connection_string: str | None = None,
                 google_api_key: str | None = None,
                 twitch_client_id: str | None = None,
                 twitch_client_secret: str | None = None,
                 ytdlp_options: dict | None = None,
                 youtube_skip_shorts: bool = False,
                 index_file: Path | None = None,
                 plugins_directory: Path | None = None,
                 feeds_directory: Path | None = None,
                 feed_base_url: str | None = None):
        '''
        Initialize the hathor client
        podcast_directory               :   Directory where new podcasts will be placed by default
        datetime_output_format          :   Python datetime output format
        database_connection_string      :   Sqlalchemy connection string, if None db will be stored in memory
        google_api_key                  :   Key for accessing google API for youtube
        twitch_client_id                :   Client id for accessing the twitch api
        twitch_client_secret            :   Client secret for accessing the twitch api
        logger                          :   Logger for client to use
        ytdlp_options                   :   Extra options passed to yt-dlp, merged over hathor's own
        youtube_skip_shorts             :   Leave youtube shorts out of episode syncs
        index_file                      :   Where `episode_index` writes the index of episode files
        plugins_directory               :   Load plugins from this directory instead of the package's hathor/plugins/
        feeds_directory                 :   Where `episode_index` also writes an rss feed per podcast and an opml file. Owned by hathor
        feed_base_url                   :   Where the library is served, such as https://example.com/hathor/<token>. Required with feeds_directory
        '''
        self.podcast_directory = None
        if podcast_directory:
            self.podcast_directory = Path(podcast_directory)
        self.datetime_output_format = datetime_output_format
        self.logger = logger or utils.setup_logger('Hathor')

        # Default to in memory db
        # Mostly for tests
        self.database_connection_string = database_connection_string or 'sqlite:///'
        self.engine = create_engine(f'{self.database_connection_string}')
        self.logger.debug(f'Initializing hathor client with database connection {self.database_connection_string}')

        migrate(self.engine, self.logger)
        self.db_session = sessionmaker(bind=self.engine)()

        if not google_api_key:
            self.logger.debug("No google api key given, will not be to able to access google api")
        self.google_api_key = google_api_key
        if not (twitch_client_id and twitch_client_secret):
            self.logger.debug("No twitch credentials given, will not be to able to access twitch api")
        self.twitch_client_id = twitch_client_id
        self.twitch_client_secret = twitch_client_secret
        self.ytdlp_options = ytdlp_options or {}
        self.youtube_skip_shorts = youtube_skip_shorts
        self.index_file = Path(index_file) if index_file else None
        self._archive_managers = {}

        self.plugins = load_plugins(plugins_directory, self.logger)

        # Last, so a bad value fails with every attribute __del__ needs already in place
        self.feeds_directory = Path(feeds_directory) if feeds_directory else None
        self.feed_base_url = feed_base_url.rstrip('/') if feed_base_url else None
        if self.feeds_directory and not self.feed_base_url:
            self._fail('feeds_directory needs feed_base_url: an rss feed has to link to its episodes with absolute urls')

    def close(self):
        '''
        Close database session and engine connections

        Safe on a client whose __init__ failed before it got that far: __del__ calls this, and
        an AttributeError there is printed on top of the real error and hides it
        '''
        db_session = getattr(self, 'db_session', None)
        if db_session is not None:
            db_session.close()
        engine = getattr(self, 'engine', None)
        if engine is not None:
            engine.dispose()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __del__(self):
        self.close()

    def _archive_manager(self, archive_type):
        # Kept for the life of the client. Managers are built from client config
        # that does not change, and they hold things worth reusing across the
        # episodes of a download run -- a google api client, a twitch token
        try:
            return self._archive_managers[archive_type]
        except KeyError:
            pass
        manager = ARCHIVE_TYPES[archive_type](self.logger,
                                              **{'google_api_key' : self.google_api_key,
                                                 'twitch_client_id' : self.twitch_client_id,
                                                 'twitch_client_secret' : self.twitch_client_secret,
                                                 'ytdlp_options' : self.ytdlp_options,
                                                 'youtube_skip_shorts' : self.youtube_skip_shorts})
        self._archive_managers[archive_type] = manager
        return manager

    def _database_select(self, table, given_input):
        if not given_input:
            return []
        if not isinstance(given_input, list):
            given_input = [given_input]
        return self.db_session.query(table).filter(table.id.in_(given_input))

    def _fail(self, message):
        self.logger.error(message)
        raise HathorException(message)

    def _record_failure(self, failures: list | None, stage: str, podcast_id: int, podcast_name: str,
                        error: Exception, episode_id: int | None = None):
        '''
        Log one failure and remember it so the rest of a sync can carry on. With no list to
        remember it in, the error is raised again

        The session is rolled back first: a failure partway through a commit leaves it
        unusable until it is, and every later podcast would fail with it
        '''
        self.db_session.rollback()
        message = utils.scrub_error(f'{type(error).__name__}: {error}')
        where = f'podcast {podcast_id} ({podcast_name})' + (f' episode {episode_id}' if episode_id is not None else '')
        self.logger.error(f'{stage} failed for {where}: {message}')
        self.logger.debug('Traceback for the failure above', exc_info=error)
        if failures is None:
            # Nobody is collecting failures, so keep the old behaviour: fail where it happened
            raise error
        failures.append({'stage': stage, 'podcast_id': podcast_id, 'podcast_name': podcast_name,
                         'episode_id': episode_id, 'error': message})

    @staticmethod
    def _raise_failures(failures: list, results: list | None = None):
        '''
        Raise a SyncFailure for everything recorded, if anything was
        '''
        if failures:
            raise SyncFailure(failures, results)

    @run_plugins
    def podcast_create(self, archive_type: ArchiveType,
                       broadcast_id: str,
                       podcast_name: str,
                       max_allowed: int | None = None,
                       file_location: Path | None = None,
                       artist_name: str | None = None,
                       automatic_download: bool = True) -> dict:
        '''
        Create new podcast
        archive_type         :   Where podcast is downloaded from (rss/soundcloud/youtube)
        broadcast_id         :   Identifier of podcast by archive_type, such as youtube channel ID
        podcast_name         :   Name to identify podcast in database
        max_allowed          :   When syncing the podcast, keep the last N episodes(if none keep all)
        file_location        :   Where podcast files will be stored
        artist_name          :   Name of artist to use when updating media file metadata
        automatic_download   :   Automatically download new episodes with podcast sync

        Returns: Integer dict object representing created podcast
        '''
        if max_allowed is not None and max_allowed < 1:
            self._fail(f'Max allowed must be positive integer, {max_allowed} given')

        if file_location is None:
            if self.podcast_directory is None:
                self._fail("No default podcast directory specified, will need specific file location to create podcast")
            file_location = Path(self.podcast_directory) / utils.normalize_name(podcast_name)
        else:
            file_location = Path(file_location)


        pod_args = {
            'name' : utils.clean_string(podcast_name),
            'archive_type' : archive_type,
            'broadcast_id' : utils.clean_string(broadcast_id),
            'max_allowed' : max_allowed,
            'file_location' : str(file_location.resolve()),
            'artist_name' : utils.clean_string(artist_name),
            'automatic_episode_download' : automatic_download,
        }
        new_pod = Podcast(**pod_args)
        self.db_session.add(new_pod)
        self.db_session.commit()
        self.logger.info(f'Podcast created, id: {new_pod.id}, name: {new_pod.name}')

        self.logger.debug(f'Ensuring podcast {new_pod.id} path exists {str(file_location)}')
        file_location.mkdir(exist_ok=True, parents=True)
        return new_pod.as_dict(self.datetime_output_format)

    @run_plugins
    def podcast_list(self) -> list[dict]:
        '''
        List all podcasts
        Returns: List of dictionaries for all podcasts
        '''
        query = self.db_session.query(Podcast).all()
        podcast_data = []
        for podcast in query:
            podcast_data.append(podcast.as_dict(self.datetime_output_format))
        return podcast_data

    @run_plugins
    def podcast_show(self, podcast_input) -> list[dict]:
        '''
        Get information on one or many podcasts
        podcast_input    :      Either single integer id, or list of integer ids

        Returns: List of dictionaries for podcasts requested
        '''
        query = self._database_select(Podcast, podcast_input)
        podcast_data = []
        for podcast in query:
            podcast_data.append(podcast.as_dict(self.datetime_output_format))
        return podcast_data

    @run_plugins
    def podcast_update(self, podcast_id: int,
                       podcast_name: str | None = None,
                       broadcast_id: str | None = None,
                       archive_type: ArchiveType | None = None,
                       max_allowed: int | None = None,
                       artist_name: str | None = None,
                       automatic_download: bool | None = None,
                       image: str | None = None,
                       remove_image: bool = False) -> dict:
        '''
        Update a single podcast
        podcast_id           :   ID of podcast to edit
        archive_type         :   Where podcast is downloaded from (rss/soundcloud/youtube)
        broadcast_id         :   Identifier of podcast by archive_type, such as youtube channel ID
        podcast_name         :   Name to identify podcast in database
        max_allowed          :   When syncing the podcast, keep the last N episodes. Set to 0 for unlimited
        artist_name          :   Name of artist to use when updating media file metadata
        automatic_download   :   Automatically download episodes with podcast sync
        image                :   Artwork for the podcast's feed, an http(s) url or a file. It is downloaded once and
                                 stored under the podcast directory, so a source url that expires stops mattering.
                                 It must be a jpeg, png, gif or webp under 5MB, or nothing changes
        remove_image         :   Remove the podcast's artwork

        Returns: dict object representing updated podcast
        '''
        pod = self.db_session.get(Podcast, podcast_id)
        if not pod:
            self._fail(f'Podcast not found for ID: {podcast_id}')
        # Before anything changes, so a bad image leaves the podcast and its old image alone
        image_data = self._image_load(podcast_id, image, remove_image)
        old_image = pod.image

        if podcast_name is not None:
            self.logger.debug(f'Updating podcast name to {podcast_name} for podcast {podcast_id}"')
            pod.name = utils.clean_string(podcast_name)
        if artist_name is not None:
            self.logger.debug(f'Updating artist name to {artist_name} for podcast {podcast_id}')
            pod.artist_name = utils.clean_string(artist_name)
        if archive_type is not None:
            self.logger.debug(f'Updating archive to {archive_type} for podcast {podcast_id}')
            pod.archive_type = archive_type
        if broadcast_id is not None:
            self.logger.debug(f'Updating broadcast id to {broadcast_id} for podcast {podcast_id}')
            pod.broadcast_id = utils.clean_string(broadcast_id)
        if max_allowed is not None:
            if max_allowed < 0:
                self._fail('Max allowed must be positive integer or 0')
            if max_allowed == 0:
                pod.max_allowed = None
            else:
                pod.max_allowed = max_allowed
            self.logger.debug(f'Updating max allowed to {max_allowed} for podcast {podcast_id}')
        if automatic_download is not None:
            self.logger.debug(f'Updating automatic download to {automatic_download} for podcast {podcast_id}')
            pod.automatic_episode_download = automatic_download
        if image_data is not None or remove_image:
            pod.image = self._image_store(pod.id, *image_data) if image_data else None

        self.db_session.commit()
        self.logger.info(f'Podcast {pod.id} update commited')
        if old_image and old_image != pod.image:
            self._image_remove(old_image)
        return pod.as_dict(self.datetime_output_format)

    def _image_load(self, podcast_id: int, image: str | None, remove_image: bool) -> tuple[bytes, str] | None:
        '''
        Check and read the image given to podcast_update

        Returns: image bytes and extension, or None when no image was given
        '''
        if image is None:
            return None
        if remove_image:
            self._fail('Cannot set and remove the image in the same update')
        if self.podcast_directory is None:
            self._fail('No podcast_directory set in config, nowhere to store the image')
        try:
            return artwork.load_image(image)
        except HathorException as error:
            message = f'Podcast {podcast_id} image {utils.mask_url_secrets(image)}: {error}'
            self.logger.error(message)
            raise HathorException(message) from error

    def _image_store(self, podcast_id: int, data: bytes, extension: str) -> str:
        '''
        Write a podcast's artwork under the podcast directory, replacing its previous one

        Returns: the path stored in the database, relative to the podcast directory
        '''
        directory = self.podcast_directory / IMAGE_DIRECTORY
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'{podcast_id}{extension}'
        utils.write_bytes_atomic(path, data)
        self.logger.info(f'Stored {len(data)} byte image for podcast {podcast_id}')
        return path.relative_to(self.podcast_directory).as_posix()

    def _image_path(self, relative_path: str | None) -> Path | None:
        '''
        File for a stored image path, or None if there is no such file inside the podcast directory
        '''
        if not relative_path or self.podcast_directory is None:
            return None
        path = (self.podcast_directory / relative_path).resolve()
        try:
            path.relative_to(self.podcast_directory.resolve())
        except ValueError:
            return None
        return path if path.is_file() else None

    def _image_remove(self, relative_path: str):
        path = self._image_path(relative_path)
        if path:
            path.unlink()
            self.logger.info(f'Removed stored image {relative_path}')


    @run_plugins
    def podcast_update_file_location(self, podcast_id: int,
                                     file_location: Path,
                                     move_files: bool = True) -> dict:
        '''
        Update file location of podcast files
        podcast_id       :   ID of podcast to edit
        file_location    :   New location for podcast files
        move_files       :   Whether or not episode files will be moved to new directory

        Returns: null
        '''
        pod = self.db_session.get(Podcast, podcast_id)
        if not pod:
            self._fail(f'Podcast not found for ID: {podcast_id}')
        old_podcast_dir = Path(pod.file_location)
        new_podcast_dir = Path(file_location)

        # The file location is committed only after the files have been moved. If a move
        # raises, the podcast still points at the directory the remaining files are in,
        # so the command can be run again once the cause is fixed.
        if move_files:
            self.logger.info(f'Moving files from old dir: {str(old_podcast_dir)} to new dir: {str(new_podcast_dir.resolve())}')
            new_podcast_dir.mkdir(exist_ok=True, parents=True)

            episodes = self.db_session.query(PodcastEpisode).filter(PodcastEpisode.podcast_id == podcast_id)
            episodes = episodes.filter(PodcastEpisode.file_path != None)
            for episode in episodes:
                episode_path = Path(episode.file_path)
                new_path = new_podcast_dir / episode_path.name
                # Not Path.rename, which is os.rename and fails with EXDEV when the two
                # directories are on different filesystems, or merely on different mount
                # points of the same filesystem -- which is what two bind mounts of one
                # drive are inside a container. move falls back to a copy and unlink.
                move(episode_path, new_path)
                episode.file_path = str(new_path.resolve())
                self.logger.info(f'Updating episode {episode.id} to path {str(new_path.resolve())} in db')
                self.db_session.commit()
            # rm_tree is recursive, so removing the old dir when it resolves to the new one
            # would delete the files that were just moved into it
            if old_podcast_dir.resolve() != new_podcast_dir.resolve():
                utils.rm_tree(old_podcast_dir)

        pod.file_location = str(new_podcast_dir.resolve())
        self.db_session.commit()
        self.logger.info(f'Updated podcast id: {podcast_id} file location to {str(new_podcast_dir.resolve())}')
        return pod.as_dict(self.datetime_output_format)

    @run_plugins
    def podcast_delete(self, podcast_input: list[int], delete_files: bool = True) -> list[int]:
        '''
        Delete podcasts and their episodes
        podcast_input           :   List of integer ids
        delete_files            :   Delete episode media files along with database entries

        Returns: List of integers IDs of podcasts deleted
        '''
        query = self._database_select(Podcast, podcast_input)
        return self.__podcast_delete_input(query, delete_files)

    @run_plugins
    def __podcast_delete_input(self, podcast_input: list[int], delete_files: bool) -> list[int]:
        podcasts_deleted = []
        for podcast in podcast_input:
            # first delete all episodes
            episodes = self.db_session.query(PodcastEpisode).filter(PodcastEpisode.podcast_id == podcast.id).all()
            self.__episode_delete_input(episodes, delete_files=delete_files)
            # delete all filters
            filters = self.db_session.query(PodcastTitleFilter).filter(PodcastTitleFilter.podcast_id == podcast.id).all()
            self.__podcast_title_filter_delete_input(filters)
            # delete record
            self.db_session.delete(podcast)
            self.db_session.commit()
            self.logger.info(f'Deleted podcast record: {podcast.id}')
            # delete files if needed
            if delete_files:
                utils.rm_tree(Path(podcast.file_location))
            # the artwork is not an episode file, so goes either way
            self._image_remove(podcast.image)
            podcasts_deleted.append(podcast.id)
        return podcasts_deleted

    @run_plugins
    def filter_create(self, podcast_id: int, regex_string: str) -> dict:
        '''
        Add a new title filter to podcast. When running an episode sync, if a title in the archive does
        not match the regex string, it will be ignored.

        podcast_id      :       ID of podcast to add filter to
        regex_string    :       Regex string to use when matching against an archive item title

        Returns: dict object representing new podcast filter
        '''
        podcast = self.db_session.get(Podcast, podcast_id)
        if not podcast:
            self._fail(f'Unable to find podcast with id: {podcast_id}')

        new_args = {
            'podcast_id' : podcast.id,
            'regex_string' : regex_string,
        }
        new_filter = PodcastTitleFilter(**new_args)
        self.db_session.add(new_filter)
        self.db_session.commit()
        self.logger.info(f'Created new podcast filter: {new_filter.id}, podcast_id: {podcast.id} and regex: {regex_string}')
        return new_filter.as_dict(self.datetime_output_format)

    @run_plugins
    def filter_list(self, include_podcasts: list[int] | None = None, exclude_podcasts: list[int] | None = None) -> list[dict]:
        '''
        List podcast title filters
        include_podcasts     :       Include only certain podcasts in results
        exclude_podcasts     :       Exclude certain podcasts in results

        Returns: list of dictionaries representing the podcast title filters
        '''
        query = self.db_session.query(PodcastTitleFilter)
        if include_podcasts:
            opts = (PodcastTitleFilter.podcast_id == pod for pod in include_podcasts)
            query = query.filter(or_(opts))
        if exclude_podcasts:
            opts = (PodcastTitleFilter.podcast_id != pod for pod in exclude_podcasts)
            query = query.filter(and_(opts))
        filters = []
        for title_filter in query:
            filters.append(title_filter.as_dict(self.datetime_output_format))
        return filters

    @run_plugins
    def filter_delete(self, filter_input: list[int]) -> list[int]:
        '''
        Delete one or many title filters
        filter_input    :   Either a single int id, or a list of int ids

        Returns: list of ids of deleted podcast title filters
        '''
        query = self._database_select(PodcastTitleFilter, filter_input)
        return self.__podcast_title_filter_delete_input(query)

    @run_plugins
    def __podcast_title_filter_delete_input(self, filter_input: list[int]) -> list[int]:
        filters_deleted = []
        for title_filter in filter_input:
            self.db_session.delete(title_filter)
            self.db_session.commit()
            filters_deleted.append(title_filter.id)
            self.logger.info(f'Deleted podcast title filter: {title_filter.id}')
        return filters_deleted

    @run_plugins
    def episode_sync(self, include_podcasts: list[int] | None = None, exclude_podcasts: list[int] | None = None,
                     max_episode_sync: int | None = None) -> list[dict]:
        '''
        Sync podcast episode data with the interwebs. Will not download episode files
        include_podcasts     :       Include only certain podcasts in sync
        exclude_podcasts     :       Exclude certain podcasts in sync
        max_episode_sync     :       Sync up to N number of episodes, to override each podcasts max allowed
                                     For unlimited number of episodes, use 0

        Returns: list of dictionaries representing new episodes added

        A podcast that fails to sync is logged and skipped, the rest still sync, and a SyncFailure
        listing what failed (carrying the new episodes as `results`) is raised at the end
        '''
        failures = []
        new_episodes = self.__episode_sync_cluders(include_podcasts, exclude_podcasts,
                                                   max_episode_sync=max_episode_sync, failures=failures)
        self._raise_failures(failures, new_episodes)
        return new_episodes

    @run_plugins
    def __episode_sync_cluders(self, include_podcasts: list[int] | None, exclude_podcasts: list[int] | None,
                               max_episode_sync: int | None = None, automatic_sync: bool = True,
                               failures: list | None = None) -> list[dict]:
        query = self.db_session.query(Podcast)
        if include_podcasts:
            opts = (Podcast.id == pod for pod in include_podcasts)
            query = query.filter(or_(opts))
        if exclude_podcasts:
            opts = (Podcast.id != pod for pod in exclude_podcasts)
            query = query.filter(and_(opts))

        new_episodes = []
        for podcast in list(query):
            if not automatic_sync and not podcast.automatic_episode_download:
                self.logger.debug(f'Skipping episode sync on podcast: {podcast.id}')
                continue
            # Read these now: after a rollback the row has to be reloaded
            podcast_id, podcast_name = podcast.id, podcast.name
            try:
                new_episodes.extend(self._episode_sync_podcast(podcast, max_episode_sync))
            except Exception as error: #pylint:disable=broad-exception-caught
                self._record_failure(failures, 'episode sync', podcast_id, podcast_name, error)
        return new_episodes

    def _episode_sync_podcast(self, podcast: Podcast, max_episode_sync: int | None) -> list[dict]:
        '''
        Sync the episodes of one podcast, returning the new episodes as dictionaries
        '''
        new_episodes = []
        self.logger.debug(f'Running episode sync on podcast: {podcast.id}')
        manager = self._archive_manager(podcast.archive_type)

        # check for filters for podcast
        compiled_filters = [re.compile(f.regex_string) for f in \
            self.db_session.query(PodcastTitleFilter).\
            filter(PodcastTitleFilter.podcast_id == podcast.id)]

        # Handed to the archive manager so it can stop paging once it reaches
        # episodes already stored. The per-episode checks below still run,
        # managers are free to ignore this
        known_urls = {row[0] for row in self.db_session.query(PodcastEpisode.download_url).\
            filter(PodcastEpisode.podcast_id == podcast.id)}

        # A podcast under its max allowed is missing episodes OLDER than the ones it
        # still has, and a newest-first listing that stops on known episodes can never
        # reach them -- deleting episodes, or a new filter dropping some, strands the
        # gap forever. Ask for a backfill instead, sized to the gap so it stops as
        # soon as the podcast is whole again
        episodes_stored = len(known_urls)
        backfill = podcast.max_allowed is not None and episodes_stored < podcast.max_allowed
        if backfill:
            self.logger.debug(f'Podcast {podcast.id} holds {episodes_stored} of '
                              f'{podcast.max_allowed} episodes, backfilling the difference')

        # if sync all episodes, give no max results so all episodes returned
        if max_episode_sync is None:
            # An explicit max_episode_sync is the caller's call and overrides the gap
            max_results = podcast.max_allowed - episodes_stored if backfill else podcast.max_allowed
        elif max_episode_sync == 0:
            max_results = None
        else:
            max_results = max_episode_sync

        current_episodes = manager.broadcast_update(podcast.broadcast_id,
                                                    max_results=max_results,
                                                    filters=compiled_filters,
                                                    known_urls=known_urls,
                                                    backfill=backfill)
        for episode in current_episodes:
            episode_processed_url = episode['download_link']
            # Patreon keeps the same basic url but changes up the query params
            # Have this check for the base url, default to full url for others
            is_patreon = utils.check_patreon(episode['download_link'])
            if is_patreon:
                episode_processed_url = utils.process_url(episode['download_link'])
                existing_episode = self.db_session.query(PodcastEpisode).filter(PodcastEpisode.processed_url == episode_processed_url).first()
                if existing_episode:
                    self.logger.debug(f'Episode {existing_episode.id} has same url "{episode_processed_url}", skipping saving episode')
                    continue
            existing_episode = self.db_session.query(PodcastEpisode).filter(PodcastEpisode.download_url == episode['download_link']).first()
            if existing_episode:
                self.logger.debug(f'Episode {existing_episode.id} has same url "{episode["download_link"]}", skipping saving episode')
                continue
            episode_args = {
                'title' : episode['title'],
                'date' : episode['date'],
                'description' : episode['description'],
                'download_url' : episode['download_link'],
                'processed_url': episode_processed_url,
                'podcast_id' : podcast.id,
                'prevent_deletion' : False,
            }
            new_episode = PodcastEpisode(**episode_args)
            self.db_session.add(new_episode)
            self.db_session.commit()
            self.logger.debug(f'Created new podcast episode: {new_episode.id} from url: {new_episode.download_url}')
            new_episodes.append(new_episode.as_dict(self.datetime_output_format))
        return new_episodes

    @run_plugins
    def episode_list(self, only_files: bool = True,
                     include_podcasts: list[int] | None = None, exclude_podcasts: list[int] | None = None) -> list[dict]:
        '''
        List Podcast Episodes
        only_files           :   Indicates you only want to list episodes with a file_path
        include_podcasts     :   Only include these podcasts. Single ID or lists of IDs
        exclude_podcasts     :   Do not include these podcasts. Single ID or list of IDs

        Returns: List of dictionaries for all episodes requested
        '''
        query = self.db_session.query(PodcastEpisode).order_by(desc(PodcastEpisode.date))
        if only_files:
            query = query.filter(PodcastEpisode.file_path != None)
        if include_podcasts:
            opts = (PodcastEpisode.podcast_id == pod for pod in include_podcasts)
            query = query.filter(or_(opts))
        if exclude_podcasts:
            opts = (PodcastEpisode.podcast_id != pod for pod in exclude_podcasts)
            query = query.filter(and_(opts))

        episode_data = []
        for episode in query.all():
            episode_data.append(episode.as_dict(self.datetime_output_format))
        return episode_data

    @run_plugins
    def episode_show(self, episode_input: list[int]) -> list[dict]:
        '''
        Get information about one or many podcast episodes
        episode_input    :  List of integer ids

        Returns: List of dictionaries for all episodes requested
        '''
        query = self._database_select(PodcastEpisode, episode_input)
        episode_list = []
        for episode in query:
            episode_list.append(episode.as_dict(self.datetime_output_format))
        return episode_list

    @run_plugins
    def episode_update(self, episode_id: int, prevent_delete: bool | None = None) -> dict:
        '''
        Update episode information
        episode_id           :   ID of episode to update
        prevent_deletion     :   Prevent deletion of episode from podcast sync

        Returns: dict representing updated episodes
        '''
        episode = self.db_session.get(PodcastEpisode, episode_id)
        if not episode:
            self._fail(f'Podcast Episode not found for ID: {episode_id}')

        if prevent_delete is not None:
            self.logger.debug(f'Updating prevent delete to {prevent_delete} for episode {episode_id}')
            episode.prevent_deletion = prevent_delete
        self.db_session.commit()
        return episode.as_dict(self.datetime_output_format)

    @run_plugins
    def episode_update_file_path(self, episode_id: int, file_path: Path) -> dict:
        '''
        Update episode file path
        episode_id          : ID of episode
        file_path           : File path where episode will be moved

        Returns: dict representing updated episode
        '''
        episode = self.db_session.get(PodcastEpisode, episode_id)
        if not episode:
            self._fail(f'Podcast Episode not found for ID: {episode_id}')
        podcast = self.db_session.get(Podcast, episode.podcast_id)
        file_path = Path(file_path)
        pod_path = Path(podcast.file_location)
        existing_path = Path(episode.file_path)
        if file_path.parent != pod_path.parent:
            self._fail(f'Podcast Episode cannot be moved out of podcast file location: {str(podcast.file_location)}')
        if existing_path.suffix != file_path.suffix:
            self._fail(f'New path {str(file_path)} suffix must match original suffix {str(existing_path)}')
        existing_path.rename(file_path)
        episode.file_path = str(file_path.resolve())
        self.logger.info(f'Update episode: {episode.id} file path to: {str(file_path)}')
        self.db_session.commit()
        return episode.as_dict(self.datetime_output_format)

    @run_plugins
    def episode_delete(self, episode_input: list[int], delete_files: bool = True) -> list[int]:
        '''
        Delete one or many podcast episodes
        episode_input    :   List of integer Ids
        delete_files     :   Delete media files along with database entries

        Returns: List of integer IDs of episodes deleted
        '''
        query = self._database_select(PodcastEpisode, episode_input)
        return self.__episode_delete_input(query, delete_files=delete_files)

    @run_plugins
    def __episode_delete_input(self, query_input: list[int], delete_files: bool = True) -> list[int]:
        # delete episode files to make it one call and a bit more simple
        if delete_files:
            self.__episode_delete_file_input(query_input)
        # now delete episode records
        episodes_deleted = []
        for episode in query_input:
            self.logger.info(f'Deleting podcast episode: {episode.id} from database')
            self.db_session.delete(episode)
            self.db_session.commit()
            episodes_deleted.append(episode.id)
        return episodes_deleted

    @run_plugins
    def episode_download(self, episode_input: list[int]) -> list[dict]:
        '''
        Download episode(s) to local machine
        episode_input    :  List of integer ids

        Returns: List of dictionaries of episodes downloaded

        An episode that fails is logged and skipped, the rest still download, and a SyncFailure
        listing what failed (carrying the episodes that did download as `results`) is raised at the end
        '''
        query = self.db_session.query(PodcastEpisode, Podcast).\
            filter(PodcastEpisode.podcast_id == Podcast.id).\
            filter(PodcastEpisode.id.in_(episode_input))
        failures = []
        downloaded = self.__episode_download_input(query, failures)
        self._raise_failures(failures, downloaded)
        return downloaded

    @run_plugins
    def __episode_download_input(self, episode_input, failures: list | None = None) -> list[dict]:
        episodes_downloaded = []
        # Materialized, since a failure rolls the session back and that must not
        # happen under a query that is still being read
        for query_data in list(episode_input):
            episode = query_data[0]
            podcast = query_data[1]
            # Read these now: after a rollback the rows have to be reloaded
            episode_id, podcast_id, podcast_name = episode.id, podcast.id, podcast.name
            try:
                downloaded = self._episode_download_one(episode, podcast)
            except Exception as error: #pylint:disable=broad-exception-caught
                self._record_failure(failures, 'download', podcast_id, podcast_name, error, episode_id=episode_id)
                continue
            if downloaded is not None:
                episodes_downloaded.append(downloaded)
        return episodes_downloaded

    def _episode_download_one(self, episode: PodcastEpisode, podcast: Podcast) -> dict | None:
        '''
        Download one episode and tag it. Returns the episode as a dictionary, or None
        if it was skipped because it is not ready or could not be downloaded
        '''
        def build_episode_path(episode, podcast):
            return Path(podcast.file_location) / f'{datetime.strftime(episode.date, self.datetime_output_format)}.{utils.normalize_name(episode.title)}'

        manager = self._archive_manager(podcast.archive_type)

        self.logger.debug(f'Downloading episode: {episode.id} data from url: {episode.download_url}')

        episode_path_prefix = build_episode_path(episode, podcast)

        try:
            output_path, download_size = manager.episode_download(episode.download_url,
                                                                  episode_path_prefix)
        except EpisodeNotReady as error:
            self.logger.debug(f'Skipping episode: {episode.id}, not ready for download: {str(error)}')
            return None
        if output_path is None or (download_size is None or download_size == 0):
            self.logger.error(f'Unable to download episode: {episode.id}')
            return None
        self.logger.info(f'Downloaded episode {episode.id} data to file {str(output_path)}')

        episode.file_path = str(output_path.resolve())
        episode.file_size = download_size
        self.db_session.commit()

        # Update metadata tags
        # use artist name if possible
        artist_name = podcast.artist_name or podcast.name
        audio_tags = {
            'artist' : artist_name,
            'albumartist' : artist_name,
            'album' : podcast.name,
            'title' : episode.title,
            'date' : episode.date.strftime(self.datetime_output_format),
        }
        try:
            tags_update(output_path, audio_tags)
            self.logger.debug(f'Updated database audio tags for episode {episode.id}')
        except AudioFileException as error:
            self.logger.warning(f'Unable to update tags on file {str(output_path)} : {str(error)}')
        return episode.as_dict(self.datetime_output_format)

    @run_plugins
    def episode_delete_file(self, episode_input: list[int]) -> list[int]:
        '''
        Delete media files for one or many podcast episodes
        episode_input    :  List of ids
        '''
        query = self._database_select(PodcastEpisode, episode_input)
        return self.__episode_delete_file_input(query)

    @run_plugins
    def __episode_delete_file_input(self, query_input) -> list[int]:
        episodes_deleted = []
        for episode in query_input:
            if episode.file_path is not None:
                file_path = Path(episode.file_path)
                try:
                    file_path.unlink()
                except FileNotFoundError:
                    continue
                episode.file_path = None
                episode.file_size = None
                # Make sure prevent delete is turned off
                episode.prevent_deletion = False
                self.db_session.commit()
                self.logger.info(f'Removed file and updated record for episode {episode.id}')
                episodes_deleted.append(episode.id)
        return episodes_deleted

    @run_plugins
    def episode_cleanup(self) -> bool:
        '''
        Delete all podcast episode entries without a media file associated with them in order to clear room.
        Also runs the "VACUUM" command to recreate the database in order to shrink its file size
        '''
        self.db_session.query(PodcastEpisode).filter_by(file_path=None).delete()
        self.db_session.commit()
        if 'sqlite' in self.database_connection_string:
            self.db_session.execute(text('VACUUM'))
        self.logger.info("Database cleaned of uneeded episodes")
        return True

    @run_plugins
    def podcast_sync(self, include_podcasts: list[int] | None = None, exclude_podcasts: list[int] | None = None,
                     sync_web_episodes: bool = True, download_episodes: bool = True):
        '''
        Updates the media files for podcasts. First sync with interwebs to check for newer episodes, then check to see if any need to be downloaded.
        include_podcasts     :   Only include these podcasts. Single ID or lists of IDs
        exclude_podcasts     :   Do not include these podcasts. Single ID or list of IDs
        sync_web_episodes    :   Sync latest known podcast episodes with web
        download_episodes    :   Download new podcast episodes

        A podcast or episode that fails is logged and skipped so the others still sync and download.
        Once everything else is done a SyncFailure listing what failed is raised, so a caller
        (and the CLI's exit code) still sees that something went wrong

        Returns: True
        '''
        failures = []
        if sync_web_episodes:
            self.__episode_sync_cluders(include_podcasts, exclude_podcasts,
                                        automatic_sync=False, failures=failures)
        # Download even when some podcast failed to sync: the others still have episodes to get
        if download_episodes:
            self._podcast_download_episodes(include_podcasts, exclude_podcasts, failures=failures)
        self._raise_failures(failures)
        return True

    @run_plugins
    def _podcast_download_episodes(self, include_podcasts: list[int] | None, exclude_podcasts: list[int] | None,
                                   failures: list | None = None):
        delete_episodes = []
        download_episodes = []

        # Built podcast query to iterate through
        podcast_query = self.db_session.query(Podcast).\
            filter(Podcast.automatic_episode_download == True)
        if include_podcasts:
            opts = (Podcast.id == pod for pod in include_podcasts)
            podcast_query = podcast_query.filter(or_(opts))
        if exclude_podcasts:
            opts = (Podcast.id != pod for pod in exclude_podcasts)
            podcast_query = podcast_query.filter(and_(opts))

        # Find all episodes to attempt to download
        for podcast in podcast_query:
            episode_query = self.db_session.query(PodcastEpisode).\
                    order_by(desc(PodcastEpisode.date)).\
                    filter(PodcastEpisode.podcast_id == podcast.id)

            # Make sure you call limit, then do check for file path
            # If you add the check for file path is None first

            # Get max allowed first, limit to the amount you would need to download
            # then only download ones that arent downloaded

            if podcast.max_allowed:
                episode_query = episode_query.limit(podcast.max_allowed)
            for episode in episode_query:
                if episode.file_path is None:
                    download_episodes.append((episode, podcast))

        # Download episodes from query
        if download_episodes:
            self.logger.debug(f'Episodes {[i[0].id for i in download_episodes]} set for download from file sync')
            self.__episode_download_input(download_episodes, failures)

        # Find episodes to delete if there is max allowed on the podcast
        # Not all episodes may have been downloaded, so this should use
        # another episode query, since that will check if "file_path" is defined
        # that way you dont delete episodes pre-maturely
        for podcast in podcast_query.filter(Podcast.max_allowed != None):
            episode_query = self.db_session.query(PodcastEpisode).order_by(desc(PodcastEpisode.date)).\
                    filter(PodcastEpisode.podcast_id == podcast.id).\
                    filter(PodcastEpisode.file_path != None).\
                    offset(podcast.max_allowed)
                    # Make sure offset is called first, since you want to first limit
                    # then check if prevent deletion is false
                    # This way files that should be kept, but also have
                    # prevent delete will not count against files
                    # that should be deleted
            for episode in episode_query:
                if episode.prevent_deletion is False:
                    delete_episodes.append(episode)
        if delete_episodes:
            self.logger.debug(f'Episodes {[i.id for i in delete_episodes]} set for deletion for max allowed from file sync')
            self.__episode_delete_file_input(delete_episodes)

    @run_plugins
    def episode_index(self, dry_run: bool = False) -> dict:
        '''
        Write a json index of every episode file under the podcast directory, grouped by
        podcast with the newest episodes first, for something else to serve or render. Each
        episode has its path relative to the podcast directory, size, content type, and a
        readable file name. Written atomically, so a reader never sees a half written index.
        Episodes with no file on disk, or a file outside the podcast directory, are left out

        With feeds_directory set, also writes an rss feed for each podcast that has episodes and
        a podcasts.opml listing them, and removes feed files of podcasts that no longer have any.
        The index then names each podcast's feed, and the opml, relative to feed_base_url

        dry_run              :   Return the index instead of writing it

        Returns: the index if dry_run, otherwise a dict summarizing what was written
        '''
        if self.podcast_directory is None:
            self._fail('No podcast_directory set in config, cannot index episodes')
        if self.index_file is None and not dry_run:
            self._fail('No index_file set in config, cannot write the episode index')
        root = self.podcast_directory.resolve()
        query = self.db_session.query(PodcastEpisode, Podcast).\
            join(Podcast, PodcastEpisode.podcast_id == Podcast.id).\
            filter(PodcastEpisode.file_path != None).\
            order_by(Podcast.name, desc(PodcastEpisode.date))
        podcasts = {}
        feed_podcasts = {}
        feed_episodes = {}
        episode_count = 0
        for episode, podcast in query:
            path = Path(episode.file_path)
            if not path.is_file():
                self.logger.warning(f'Episode {episode.id} file missing on disk, not indexing: {episode.file_path}')
                continue
            try:
                relative_path = path.resolve().relative_to(root)
            except ValueError:
                self.logger.warning(f'Episode {episode.id} file is outside the podcast directory, not indexing: {episode.file_path}')
                continue
            date = episode.date.strftime('%Y-%m-%d') if episode.date else None
            size = path.stat().st_size
            content_type = utils.guess_content_type(path.name)
            podcasts.setdefault(podcast.id, {'id': podcast.id, 'name': podcast.name, 'episodes': []})['episodes'].append({
                'id': episode.id,
                'title': episode.title,
                'date': date,
                'size': size,
                'content_type': content_type,
                'filename': utils.display_filename(podcast.name, date, episode.title, path.suffix),
                'path': relative_path.as_posix(),
            })
            feed_podcasts[podcast.id] = {'id': podcast.id, 'name': podcast.name, 'artist_name': podcast.artist_name,
                                         'image_source': self._image_path(podcast.image)}
            feed_episodes.setdefault(podcast.id, []).append({
                'id': episode.id, 'title': episode.title, 'date': episode.date, 'description': episode.description,
                'path': relative_path.as_posix(), 'size': size, 'content_type': content_type,
            })
            episode_count += 1
        now = datetime.now(timezone.utc).replace(microsecond=0)
        index = {
            'generated_at': now.isoformat(),
            'podcasts': list(podcasts.values()),
        }
        filenames, image_files = {}, {}
        if self.feeds_directory:
            filenames = self._feed_filenames(feed_podcasts)
            image_files = self._feed_images(feed_podcasts, filenames)
            for podcast_id, entry in podcasts.items():
                entry['feed'] = f'feeds/{filenames[podcast_id]}'
                if podcast_id in image_files:
                    entry['image'] = f'feeds/{image_files[podcast_id][1]}'
            index['opml'] = f'feeds/{feeds.OPML_FILENAME}'
        if dry_run:
            return index
        utils.write_file_atomic(self.index_file, json.dumps(index, indent=2))
        self.logger.info(f'Wrote index of {episode_count} episodes to {self.index_file}')
        summary = {
            'index_file': str(self.index_file),
            'podcasts': len(podcasts),
            'episodes': episode_count,
        }
        if self.feeds_directory:
            summary['feeds'] = self._write_feeds(feed_podcasts, feed_episodes, filenames, image_files, now)
        return summary

    @staticmethod
    def _feed_filenames(feed_podcasts: dict) -> dict[int, str]:
        '''
        Feed file name for each podcast id. Names come from the podcast name, and a second podcast
        whose name reduces to the same file name gets its id added instead of replacing the first
        '''
        filenames, used = {}, set()
        for podcast_id, podcast in feed_podcasts.items():
            filename = feeds.feed_filename(podcast['name'], podcast_id)
            if filename in used:
                filename = f'{utils.normalize_name(podcast["name"])}-{podcast_id}.xml'
            filenames[podcast_id] = filename
            used.add(filename)
        return filenames

    @staticmethod
    def _feed_images(feed_podcasts: dict, filenames: dict) -> dict[int, tuple[Path, str]]:
        '''
        Stored image and the name it is served under, for each podcast that has one on disk

        The name carries a hash of the content, so replacing an image changes its url and a
        podcast app that caches by url fetches the new one
        '''
        images = {}
        for podcast_id, podcast in feed_podcasts.items():
            source = podcast['image_source']
            if source is None:
                continue
            digest = sha256(source.read_bytes()).hexdigest()[:10]
            stem = filenames[podcast_id].removesuffix('.xml')
            images[podcast_id] = (source, f'{stem}-{digest}{source.suffix}')
        return images

    def _write_feeds(self, feed_podcasts: dict, feed_episodes: dict, filenames: dict, image_files: dict, now: datetime) -> int:
        '''
        Write an rss feed per podcast and the opml, each atomically, copy the podcasts' artwork
        next to them, and remove the files that are no longer wanted (a podcast that was deleted,
        or has no episodes left, or an image that was replaced)

        Returns: number of feeds written
        '''
        self.feeds_directory.mkdir(parents=True, exist_ok=True)
        wanted, listing = set(), []
        for podcast_id, episodes in feed_episodes.items():
            filename = filenames[podcast_id]
            podcast = dict(feed_podcasts[podcast_id])
            if podcast_id in image_files:
                source, image_name = image_files[podcast_id]
                if not (self.feeds_directory / image_name).is_file():
                    utils.write_bytes_atomic(self.feeds_directory / image_name, source.read_bytes())
                wanted.add(image_name)
                podcast['image_url'] = feeds.feed_url(self.feed_base_url, image_name)
            feed = feeds.build_feed(podcast, episodes, self.feed_base_url, now, filename)
            utils.write_file_atomic(self.feeds_directory / filename, feed.decode('utf-8'))
            wanted.add(filename)
            listing.append({'name': feed_podcasts[podcast_id]['name'], 'filename': filename})
        opml = feeds.build_opml(listing, self.feed_base_url, now)
        utils.write_file_atomic(self.feeds_directory / feeds.OPML_FILENAME, opml.decode('utf-8'))
        wanted.add(feeds.OPML_FILENAME)
        for existing in self.feeds_directory.iterdir():
            if existing.is_file() and existing.suffix in ('.xml', '.opml', *artwork.IMAGE_EXTENSIONS) and existing.name not in wanted:
                self.logger.info(f'Removing feed file no longer wanted: {existing.name}')
                existing.unlink()
        self.logger.info(f'Wrote {len(listing)} feeds to {self.feeds_directory}')
        return len(listing)

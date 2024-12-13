from datetime import datetime
from importlib import import_module
from inspect import getmembers, isfunction
import os
from logging import RootLogger
import re
from typing import Literal, List


from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import sessionmaker, Query
from sqlalchemy.sql import text

from hathor.audio.metadata import tags_update
from hathor.database.tables import BASE, Podcast
from hathor.database.tables import PodcastEpisode, PodcastTitleFilter
from hathor.exc import AudioFileException, HathorException
from hathor.podcast.archive import ARCHIVE_TYPES, VALID_ARCHIVE_KEYS
from hathor import  utils

DEFAULT_DATETIME_FORMAT = '%Y-%m-%d'

FILE_PATH = os.path.abspath(__file__)

def load_plugins():
    '''
    Loads plugins for dir, gets list of functions to run later
    '''
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

class HathorClient():
    '''
    Hathor Client
    Sync podcasts from different sources
    '''
    def __init__(self, podcast_directory: Path = None,
                 datetime_output_format: str = DEFAULT_DATETIME_FORMAT,
                 logger: RootLogger = None,
                 database_connection_string: str = None,
                 google_api_key: str = None):
        '''
        Initialize the hathor client
        podcast_directory               :   Directory where new podcasts will be placed by default
        datetime_output_format          :   Python datetime output format
        database_connection_string      :   Sqlalchemy connection string, if None db will be stored in memory
        google_api_key                  :   Key for accessing google API for youtube
        logger                          :   Logger for client to use
        '''
        self.podcast_directory = None
        if podcast_directory:
            self.podcast_directory = Path(podcast_directory)
        self.datetime_output_format = datetime_output_format
        self.logger = logger or utils.setup_logger('Hathor')

        # Default to in memory db
        # Mostly for tests
        self.database_connection_string = database_connection_string or 'sqlite:///'
        engine = create_engine(f'{self.database_connection_string}')
        self.logger.debug(f'Initializing hathor client with database connection {self.database_connection_string}')

        BASE.metadata.create_all(engine)
        BASE.metadata.bind = engine
        self.db_session = sessionmaker(bind=engine)()

        if not google_api_key:
            self.logger.debug("No google api key given, will not be to able to access google api")
        self.google_api_key = google_api_key

        self.plugins = load_plugins()

    def _archive_manager(self, archive_type):
        return ARCHIVE_TYPES[archive_type](self.logger,
                                           **{'google_api_key' : self.google_api_key})

    def _database_select(self, table, given_input):
        if not given_input:
            return []
        if not isinstance(given_input, list):
            given_input = [given_input]
        return self.db_session.query(table).filter(table.id.in_(given_input))

    def _fail(self, message):
        self.logger.error(message)
        raise HathorException(message)

    @run_plugins
    def podcast_create(self, archive_type: ArchiveType,
                       broadcast_id: str,
                       podcast_name: str,
                       max_allowed: int = None,
                       file_location: Path = None,
                       artist_name: str = None,
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
    def podcast_list(self) -> List[dict]:
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
    def podcast_show(self, podcast_input) -> List[dict]:
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
                       podcast_name: str = None,
                       broadcast_id: str = None,
                       archive_type: ArchiveType = None,
                       max_allowed: int = None,
                       artist_name: str = None,
                       automatic_download: bool = None) -> dict:
        '''
        Update a single podcast
        podcast_id           :   ID of podcast to edit
        archive_type         :   Where podcast is downloaded from (rss/soundcloud/youtube)
        broadcast_id         :   Identifier of podcast by archive_type, such as youtube channel ID
        podcast_name         :   Name to identify podcast in database
        max_allowed          :   When syncing the podcast, keep the last N episodes. Set to 0 for unlimited
        artist_name          :   Name of artist to use when updating media file metadata
        automatic_download   :   Automatically download episodes with podcast sync

        Returns: dict object representing updated podcast
        '''
        pod = self.db_session.query(Podcast).get(podcast_id)
        if not pod:
            self._fail(f'Podcast not found for ID: {podcast_id}')

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

        self.db_session.commit()
        self.logger.info(f'Podcast {pod.id} update commited')
        return pod.as_dict(self.datetime_output_format)


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
        pod = self.db_session.query(Podcast).get(podcast_id)
        if not pod:
            self._fail(f'Podcast not found for ID: {podcast_id}')
        old_podcast_dir = Path(pod.file_location)
        new_podcast_dir = Path(file_location)
        pod.file_location = str(new_podcast_dir.resolve())
        self.db_session.commit()
        self.logger.info(f'Updated podcast id: {podcast_id} file location to {str(new_podcast_dir.resolve())}')

        if move_files:
            self.logger.info(f'Moving files from old dir: {str(old_podcast_dir)} to new dir: {pod.file_location}')
            new_podcast_dir.mkdir(exist_ok=True, parents=True)

            episodes = self.db_session.query(PodcastEpisode).filter(PodcastEpisode.podcast_id == podcast_id)
            episodes = episodes.filter(PodcastEpisode.file_path != None)
            for episode in episodes:
                episode_path = Path(episode.file_path)
                new_path = new_podcast_dir / episode_path.name
                episode_path.rename(new_path)
                episode.file_path = str(new_path.resolve())
                self.logger.info(f'Updating episode {episode.id} to path {str(new_path.resolve())} in db')
                self.db_session.commit()
            utils.rm_tree(old_podcast_dir)
        return pod.as_dict(self.datetime_output_format)

    @run_plugins
    def podcast_delete(self, podcast_input: List[int], delete_files: bool = True) -> List[int]:
        '''
        Delete podcasts and their episodes
        podcast_input           :   List of integer ids
        delete_files            :   Delete episode media files along with database entries

        Returns: List of integers IDs of podcasts deleted
        '''
        query = self._database_select(Podcast, podcast_input)
        return self.__podcast_delete_input(query, delete_files)

    @run_plugins
    def __podcast_delete_input(self, podcast_input: List[int], delete_files: bool) -> List[int]:
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
        podcast = self.db_session.query(Podcast).get(podcast_id)
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
    def filter_list(self, include_podcasts: List[int] = None, exclude_podcasts: List[int] = None) -> List[dict]:
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
    def filter_delete(self, filter_input: List[int]) -> List[int]:
        '''
        Delete one or many title filters
        filter_input    :   Either a single int id, or a list of int ids

        Returns: list of ids of deleted podcast title filters
        '''
        query = self._database_select(PodcastTitleFilter, filter_input)
        return self.__podcast_title_filter_delete_input(query)

    @run_plugins
    def __podcast_title_filter_delete_input(self, filter_input: List[int]) -> List[int]:
        filters_deleted = []
        for title_filter in filter_input:
            self.db_session.delete(title_filter)
            self.db_session.commit()
            filters_deleted.append(title_filter.id)
            self.logger.info(f'Deleted podcast title filter: {title_filter.id}')
        return filters_deleted

    @run_plugins
    def episode_sync(self, include_podcasts: List[int] = None, exclude_podcasts: List[int] = None,
                     max_episode_sync: int = None) -> List[dict]:
        '''
        Sync podcast episode data with the interwebs. Will not download episode files
        include_podcasts     :       Include only certain podcasts in sync
        exclude_podcasts     :       Exclude certain podcasts in sync
        max_episode_sync     :       Sync up to N number of episodes, to override each podcasts max allowed
                                     For unlimited number of episodes, use 0

        Returns: list of dictionaries representing new episodes added
        '''
        return self.__episode_sync_cluders(include_podcasts, exclude_podcasts, max_episode_sync=max_episode_sync)

    @run_plugins
    def __episode_sync_cluders(self, include_podcasts: List[int], exclude_podcasts: List[int],
                               max_episode_sync: int = None, automatic_sync: bool = True) -> List[dict]:
        query = self.db_session.query(Podcast)
        if include_podcasts:
            opts = (Podcast.id == pod for pod in include_podcasts)
            query = query.filter(or_(opts))
        if exclude_podcasts:
            opts = (Podcast.id != pod for pod in exclude_podcasts)
            query = query.filter(and_(opts))

        new_episodes = []
        for podcast in query:
            if not automatic_sync and not podcast.automatic_episode_download:
                self.logger.debug(f'Skipping episode sync on podcast: {podcast.id}')
                continue

            self.logger.debug(f'Running episode sync on podcast: {podcast.id}')
            manager = self._archive_manager(podcast.archive_type)

            # if sync all episodes, give no max results so all episodes returned
            if max_episode_sync is None:
                max_results = podcast.max_allowed
            elif max_episode_sync == 0:
                max_results = None
            else:
                max_results = max_episode_sync

            # check for filters for podcast
            compiled_filters = [re.compile(f.regex_string) for f in \
                self.db_session.query(PodcastTitleFilter).\
                filter(PodcastTitleFilter.podcast_id == podcast.id)]

            current_episodes = manager.broadcast_update(podcast.broadcast_id,
                                                        max_results=max_results,
                                                        filters=compiled_filters)
            for episode in current_episodes:
                # Check if download link with same download link exists in podcast
                episode_processed_url = utils.process_url(episode['download_link'])
                # Patreon keeps the same basic url but changes up the query params
                # Have this check for the base url, default to full url for others
                is_patreon = utils.check_patreon(episode['download_link'])
                if is_patreon:
                    existing_episode = self.db_session.query(PodcastEpisode).filter(PodcastEpisode.processed_url == episode_processed_url).first()
                    if existing_episode:
                        self.logger.debug(f'Episode {existing_episode.id} has same url, skipping saving episode')
                        continue
                existing_episode = self.db_session.query(PodcastEpisode).filter(PodcastEpisode.download_url == episode['download_link']).first()
                if existing_episode:
                    self.logger.debug(f'Episode {existing_episode.id} has same url, skipping saving episode')
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
                     include_podcasts: List[int] = None, exclude_podcasts: List[int] = None) -> List[dict]:
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
    def episode_show(self, episode_input: List[int]) -> List[dict]:
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
    def episode_update(self, episode_id: int, prevent_delete: bool = None) -> dict:
        '''
        Update episode information
        episode_id           :   ID of episode to update
        prevent_deletion     :   Prevent deletion of episode from podcast sync

        Returns: dict representing updated episodes
        '''
        episode = self.db_session.query(PodcastEpisode).get(episode_id)
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
        episode = self.db_session.query(PodcastEpisode).get(episode_id)
        if not episode:
            self._fail(f'Podcast Episode not found for ID: {episode_id}')
        podcast = self.db_session.query(Podcast).get(episode.podcast_id)
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
    def episode_delete(self, episode_input: List[int], delete_files: bool = True) -> List[int]:
        '''
        Delete one or many podcast episodes
        episode_input    :   List of integer Ids
        delete_files     :   Delete media files along with database entries

        Returns: List of integer IDs of episodes deleted
        '''
        query = self._database_select(PodcastEpisode, episode_input)
        return self.__episode_delete_input(query, delete_files=delete_files)

    @run_plugins
    def __episode_delete_input(self, query_input: List[int], delete_files: bool = True) -> List[int]:
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
    def episode_download(self, episode_input: List[int]) -> List[dict]:
        '''
        Download episode(s) to local machine
        episode_input    :  List of integer ids

        Returns: List of dictionaries of episodes downloaded
        '''
        query = self.db_session.query(PodcastEpisode, Podcast).\
            filter(PodcastEpisode.podcast_id == Podcast.id).\
            filter(PodcastEpisode.id.in_(episode_input))
        return self.__episode_download_input(query)

    @run_plugins
    def __episode_download_input(self, episode_input: Query) -> List[dict]:
        def build_episode_path(episode, podcast):
            return Path(podcast.file_location) / f'{datetime.strftime(episode.date, self.datetime_output_format)}.{utils.normalize_name(episode.title)}'

        episodes_downloaded = []

        for query_data in episode_input:
            episode = query_data[0]
            podcast = query_data[1]

            manager = self._archive_manager(podcast.archive_type)

            self.logger.debug(f'Downloading episode: {episode.id} data from url: {episode.download_url}')

            episode_path_prefix = build_episode_path(episode, podcast)

            output_path, download_size = manager.episode_download(episode.download_url,
                                                                  episode_path_prefix)
            if output_path is None or (download_size is None or download_size == 0):
                self.logger.error(f'Unable to download episode: {episode.id}')
                continue
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
            episodes_downloaded.append(episode.as_dict(self.datetime_output_format))
        return episodes_downloaded

    @run_plugins
    def episode_delete_file(self, episode_input: List[int]) -> List[int]:
        '''
        Delete media files for one or many podcast episodes
        episode_input    :  List of ids
        '''
        query = self._database_select(PodcastEpisode, episode_input)
        return self.__episode_delete_file_input(query)

    @run_plugins
    def __episode_delete_file_input(self, query_input: Query) -> List[int]:
        episodes_deleted = []
        for episode in query_input:
            if episode.file_path is not None:
                file_path = Path(episode.file_path)
                file_path.unlink()
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
    def podcast_sync(self, include_podcasts: List[int] = None, exclude_podcasts: List[int] = None,
                     sync_web_episodes: bool = True, download_episodes: bool = True):
        '''
        Updates the media files for podcasts. First sync with interwebs to check for newer episodes, then check to see if any need to be downloaded.
        include_podcasts     :   Only include these podcasts. Single ID or lists of IDs
        exclude_podcasts     :   Do not include these podcasts. Single ID or list of IDs
        sync_web_episodes    :   Sync latest known podcast episodes with web
        download_episodes    :   Download new podcast episodes

        Returns: null
        '''
        if sync_web_episodes:
            self.__episode_sync_cluders(include_podcasts, exclude_podcasts,
                                        automatic_sync=False)
        if download_episodes:
            self._podcast_download_episodes(include_podcasts, exclude_podcasts)
        return True

    @run_plugins
    def _podcast_download_episodes(self, include_podcasts: List[int], exclude_podcasts: List[int]):
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
                if episode.file_path == None:
                    download_episodes.append((episode, podcast))

        # Download episodes from query
        if download_episodes:
            self.logger.debug(f'Episodes {[i[0].id for i in download_episodes]} set for download from file sync')
            self.__episode_download_input(download_episodes)

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

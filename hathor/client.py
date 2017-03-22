import os
import logging
from logging.handlers import RotatingFileHandler
import re

from sqlalchemy import create_engine
from sqlalchemy import and_, desc, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from hathor.audio import metadata
from hathor.database.tables import BASE, Podcast
from hathor.database.tables import PodcastEpisode, PodcastTitleFilter
from hathor.exc import AudioFileException, HathorException
from hathor.podcast.archive import ARCHIVE_TYPES, ARCHIVE_KEYS
from hathor import settings, utils

def setup_logger(name, log_file_level, logging_file=None,
                 console_logging=True, console_logging_level=logging.INFO):
    logger = logging.getLogger(name)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                                  datefmt='%Y-%m-%d %H:%M:%S')
    logger.setLevel(log_file_level)
    if logging_file is not None:
        fh = RotatingFileHandler(logging_file,
                                 backupCount=4,
                                 maxBytes=((2 ** 20) * 10))
        fh.setLevel(log_file_level)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    if console_logging:
        sh = logging.StreamHandler()
        sh.setLevel(console_logging_level)
        sh.setFormatter(formatter)
        logger.addHandler(sh)
    return logger

def check_inputs(user_input):
    if user_input is None:
        return None, 'No input given'
    # if not list, check is int
    if not isinstance(user_input, list):
        if isinstance(user_input, bool):
            return False, 'Input must be int type, %s given' % user_input
        if not isinstance(user_input, int):
            return False, 'Input must be int type, %s given' % user_input
        user_input = [user_input]
    else:
        # if it is a list, check each item in list
        for inputty in user_input:
            if isinstance(inputty, bool):
                return False, 'Input must be int type, %s given' % inputty
            if not isinstance(inputty, int):
                return False, 'Input must be int type, %s given' % inputty
    return True, user_input

def check_argument_type(value, types_allowed):
    if not isinstance(types_allowed, list):
        types_allowed = [types_allowed]
    valid = False
    for typer in types_allowed:
        if typer is None:
            if value is None:
                valid = True
                break
        elif isinstance(value, typer):
            valid = True
            break
    if not valid:
        return False, '%s type given' % str(value.__class__.__name__)
    else:
        return True, 'Valid input'

class HathorClient(object):
    def __init__(self, podcast_directory=None, datetime_output_format=settings.DEFAULT_DATETIME_FORMAT,
                 logging_file=None, logging_file_level=logging.DEBUG,
                 database_file=None, soundcloud_client_id=None, google_api_key=None,
                 console_logging=True, console_logging_level=logging.INFO):
        '''
        Initialize the hathor client
        podcast_directory       :   Directory where new podcasts will be placed by default
        datetime_output_format  :   Python datetime output format
        logging_file            :   Add logging handler for output file, will be rotational
        logging_file_level      :   Level for file logging to use
        database_file           :   Sqlite database to use, if None db will be stored in memory
        soundcloud_client_id    :   Client id for accessing soundcloud API
        google_api_key          :   Key for accessing google API for youtube
        console_logging         :   Whether or not to set logging to console
        console_logging_level   :   Level for console logging to use
        '''
        self.podcast_directory = None
        if podcast_directory is not None:
            self.podcast_directory = os.path.abspath(podcast_directory)
        self.datetime_output_format = datetime_output_format

        self.logger = setup_logger('hathor', logging_file_level, logging_file=logging_file,
                                   console_logging=console_logging,
                                   console_logging_level=console_logging_level)

        if database_file is None:
            engine = create_engine('sqlite:///', encoding='utf-8')
            self.logger.debug("Initializing hathor client in memory (no database file given")
        else:
            engine = create_engine('sqlite:///%s' % database_file, encoding='utf-8')
            self.logger.debug("Initializing hathor client with database file %s", database_file)

        BASE.metadata.create_all(engine)
        BASE.metadata.bind = engine
        self.db_session = sessionmaker(bind=engine)()

        if not soundcloud_client_id:
            self.logger.warn("No soundcloud client id given, will not be able to access soundcloud api")
        self.soundcloud_client_id = soundcloud_client_id

        if not google_api_key:
            self.logger.warn("No google api key given, will not be to able to access google api")
        self.google_api_key = google_api_key

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.db_session.close()

    def _archive_manager(self, archive_type):
        return ARCHIVE_TYPES[archive_type](self.logger,
                                           self.soundcloud_client_id,
                                           self.google_api_key)

    def _database_select(self, table, given_input):
        given_input = self._check_input(given_input)
        return self.db_session.query(table).filter(table.id.in_(given_input))

    def _fail(self, message):
        self.logger.error(message)
        raise HathorException(message)

    def _check_argument_oneof(self, value, allowed_values, message):
        if value not in allowed_values:
            self._fail('%s - %s value given' % (message, value))

    def _check_includers(self, include_args, exclude_args):
        code, result = check_inputs(include_args)
        if code is False:
            self._fail(result)
        elif code is True:
            include_args = result
        code, result = check_inputs(exclude_args)
        if code is False:
            self._fail(result)
        elif code is True:
            exclude_args = result
        return include_args, exclude_args

    def _check_input(self, user_input):
        code, result = check_inputs(user_input)
        if code is False:
            self._fail(result)
        elif code is True:
            user_input = result
        return user_input

    def _check_argument_type(self, user_input, types_allowed, message):
        code, error_message = check_argument_type(user_input, types_allowed)
        if code is True:
            return
        else:
            self._fail('%s - %s' % (message, error_message))

    def _ensure_path(self, directory_path):
        if not os.path.isdir(directory_path):
            os.makedirs(directory_path)
            self.logger.info("Created new directory:%s", directory_path)

    def _remove_directory(self, directory_path):
        try:
            os.rmdir(directory_path)
            self.logger.info("Removed directory:%s", directory_path)
        except OSError as exc:
            if exc.errno == os.errno.ENOENT:
                self.logger.warn("Unable to delete directory:%s, does not exist", directory_path)
            else:
                raise

    def _remove_file(self, file_path):
        try:
            os.remove(file_path)
            self.logger.info("Removed file:%s", file_path)
        except OSError as exc:
            if exc.errno == os.errno.ENOENT:
                self.logger.warn("Unable to delete file:%s, does not exist", file_path)
            else:
                raise

    def podcast_create(self, archive_type, broadcast_id, podcast_name, max_allowed=None,
                       file_location=None, artist_name=None, automatic_download=True):
        '''
        Create new podcast
        archive_type         :   Where podcast is downloaded from (rss/soundcloud/youtube)
        broadcast_id         :   Identifier of podcast by archive_type, such as youtube channel ID
        podcast_name         :   Name to identify podcast in database
        max_allowed          :   When syncing the podcast, keep the last N episodes(if none keep all)
        file_location        :   Where podcast files will be stored
        artist_name          :   Name of artist to use when updating media file metadata
        automatic_download   :   Automatically download new episodes with file-sync

        Returns: Integer ID of created podcast
        '''
        self._check_argument_type(podcast_name, basestring, 'Podcast name must be string type')
        self._check_argument_type(broadcast_id, basestring, 'Brodcast ID must be string type')
        self._check_argument_type(archive_type, basestring, 'Archive Type must be string type')
        self._check_argument_type(automatic_download, bool, 'Automatic download must be boolean type')
        self._check_argument_type(max_allowed, [None, int], 'Max allowed must be None or int type')
        self._check_argument_type(file_location, [None, basestring], 'File location must be None or string type')
        self._check_argument_type(artist_name, [None, basestring], 'File location must be None or string type')

        self._check_argument_oneof(archive_type, ARCHIVE_KEYS, 'Archive Type must be in accepted list of keys')

        if max_allowed is not None and max_allowed < 1:
            self._fail('Max allowed must be positive integer, %s given' % max_allowed)

        if file_location is None:
            if self.podcast_directory is None:
                self._fail("No default podcast directory specified, will need specific file location to create podcast")
            file_location = os.path.join(self.podcast_directory, utils.normalize_name(podcast_name))

        pod_args = {
            'name' : utils.clean_string(podcast_name),
            'archive_type' : archive_type,
            'broadcast_id' : utils.clean_string(broadcast_id),
            'max_allowed' : max_allowed,
            'file_location' : os.path.abspath(file_location),
            'artist_name' : utils.clean_string(artist_name),
            'automatic_episode_download' : automatic_download,
        }
        new_pod = Podcast(**pod_args)
        try:
            self.db_session.add(new_pod)
            self.db_session.commit()
            self.logger.info("Podcast created in database, id:%d, args %s",
                             new_pod.id, ' -- '.join('%s-%s' % (k, v) for k, v in pod_args.items()))
        except IntegrityError:
            self.db_session.rollback()
            self._fail('Cannot create podcast, name was %s' % pod_args['name'])

        self.logger.debug("Ensuring podcast %d path exists %s", new_pod.id, file_location)
        self._ensure_path(file_location)
        return new_pod.id

    def podcast_list(self):
        '''
        List all podcasts
        Returns: List of dictionaries for all podcasts
        '''
        query = self.db_session.query(Podcast).all()
        podcast_data = []
        for podcast in query:
            podcast_data.append(podcast.as_dict(self.datetime_output_format))
        return podcast_data

    def podcast_show(self, podcast_input):
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

    def podcast_update(self, podcast_id, podcast_name=None, broadcast_id=None, archive_type=None,
                       max_allowed=None, artist_name=None, automatic_download=None):
        '''
        Update a single podcast
        podcast_id           :   ID of podcast to edit
        archive_type         :   Where podcast is downloaded from (rss/soundcloud/youtube)
        broadcast_id         :   Identifier of podcast by archive_type, such as youtube channel ID
        podcast_name         :   Name to identify podcast in database
        max_allowed          :   When syncing the podcast, keep the last N episodes. Set to 0 for unlimited
        artist_name          :   Name of artist to use when updating media file metadata
        automatic_download   :   Automatically download episodes with file-sync

        Returns: null
        '''
        self._check_argument_type(podcast_id, int, 'Podcast ID must be int type')
        pod = self.db_session.query(Podcast).get(podcast_id)
        if not pod:
            self._fail("Podcast not found for ID:%s" % podcast_id)

        if podcast_name is not None:
            self._check_argument_type(podcast_name, basestring, 'Podcast name must be string type or None')
            self.logger.debug("Updating podcast name to %s for podcast %s", podcast_name, podcast_id)
            pod.name = utils.clean_string(podcast_name)
        if artist_name is not None:
            self._check_argument_type(artist_name, basestring, 'Podcast name must be string type or None')
            self.logger.debug("Updating artist name to %s for podcast %s", artist_name, podcast_id)
            pod.artist_name = utils.clean_string(artist_name)
        if archive_type is not None:
            self._check_argument_type(archive_type, basestring, 'Archive Type must be string type or None')
            self._check_argument_oneof(archive_type, ARCHIVE_KEYS, 'Archive Type must be in accepted list')
            self.logger.debug("Updating archive to %s for podcast %s", archive_type, podcast_id)
            pod.archive_type = archive_type
        if broadcast_id is not None:
            self._check_argument_type(broadcast_id, basestring, 'Broadcast ID must be string type or None')
            self.logger.debug("Updating broadcast id to %s for podcast %s", broadcast_id, podcast_id)
            pod.broadcast_id = utils.clean_string(broadcast_id)
        if max_allowed is not None:
            self._check_argument_type(max_allowed, int, 'Max allowed must be int type or None')
            if max_allowed < 0:
                self._fail('Max allowed must be positive integer or 0')
            if max_allowed == 0:
                pod.max_allowed = None
            else:
                pod.max_allowed = max_allowed
            self.logger.debug("Updating max allowed to %s for podcast %s", max_allowed, podcast_id)
        if automatic_download is not None:
            self._check_argument_type(automatic_download, bool, 'Automatic download must be bool type')
            self.logger.debug("Updating automatic download to %s for podcast %s", automatic_download, podcast_id)
            pod.automatic_episode_download = automatic_download

        try:
            self.db_session.commit()
            self.logger.info("Podcast %s update commited", pod.id)
        except IntegrityError:
            self.db_session.rollback()
            self._fail('Cannot update podcast id:%s' % podcast_id)

    def podcast_update_file_location(self, podcast_id, file_location, move_files=True):
        '''
        Update file location of podcast files
        podcast_id       :   ID of podcast to edit
        file_location    :   New location for podcast files
        move_files       :   Whether or not episode files will be moved to new directory

        Returns: null
        '''
        self._check_argument_type(podcast_id, int, 'Podcast ID must be int type')
        self._check_argument_type(file_location, basestring, 'File location must be None or string type')
        pod = self.db_session.query(Podcast).get(podcast_id)
        if not pod:
            self._fail("Podcast not found for ID:%s" % podcast_id)
        old_podcast_dir = pod.file_location
        pod.file_location = os.path.abspath(file_location)
        self.db_session.commit()
        self.logger.info("Updated podcast id:%s file location to %s", podcast_id, file_location)

        if move_files:
            self.logger.info("Moving files from old dir:%s to new dir:%s", old_podcast_dir, pod.file_location)
            self._ensure_path(pod.file_location)

            episodes = self.db_session.query(PodcastEpisode).filter(PodcastEpisode.podcast_id == podcast_id)
            episodes = episodes.filter(PodcastEpisode.file_path != None)
            for episode in episodes:
                episode_name_path = os.path.basename(episode.file_path)
                new_path = os.path.join(pod.file_location, episode_name_path)
                os.rename(episode.file_path, new_path)
                episode.file_path = new_path
                self.logger.info("Updating episode %s to path %s in db", episode.id, episode.file_path)
                self.db_session.commit()
            self._remove_directory(old_podcast_dir)

    def podcast_delete(self, podcast_input, delete_files=True):
        '''
        Delete podcasts and their episodes
        podcast_input           :   Either a single integer id, or list of integer ids
        delete_files            :   Delete episode media files along with database entries

        Returns: List of integers IDs of podcasts deleted
        '''
        query = self._database_select(Podcast, podcast_input)
        return self.__podcast_delete_input(query, delete_files)

    def __podcast_delete_input(self, podcast_input, delete_files):
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
            self.logger.info("Deleted podcast record:%s", podcast.id)
            # delete files if needed
            if delete_files:
                self._remove_directory(podcast.file_location)
            podcasts_deleted.append(podcast.id)
        return podcasts_deleted

    def filter_create(self, podcast_id, regex_string):
        '''
        Add a new title filter to podcast. When running an episode sync, if a title in the archive does
        not match the regex string, it will be ignored.

        podcast_id      :       ID of podcast to add filter to
        regex_string    :       Regex string to use when matching against an archive item title

        Returns: Integer id of created podcast title filter
        '''
        self._check_argument_type(podcast_id, int, 'Podcast ID must be int type')
        self._check_argument_type(regex_string, basestring, 'Regex string must be string type')

        podcast = self.db_session.query(Podcast).get(podcast_id)
        if not podcast:
            self._fail("Unable to find podcast with id:%s" % podcast_id)

        new_args = {
            'podcast_id' : podcast.id,
            'regex_string' : regex_string,
        }
        new_filter = PodcastTitleFilter(**new_args)
        self.db_session.add(new_filter)
        self.db_session.commit()
        self.logger.info("Created new podcast filter:%s, podcast_id:%s and regex:%s",
                         new_filter.id, podcast.id, regex_string)
        return new_filter.id

    def filter_list(self, include_podcasts=None, exclude_podcasts=None):
        '''
        List podcast title filters
        include_podcasts     :       Include only certain podcasts in results
        exclude_podcasts     :       Exclude certain podcasts in results

        Returns: list of dictionaries representing the podcast title filters
        '''
        include_podcasts, exclude_podcasts = self._check_includers(include_podcasts, exclude_podcasts)
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

    def filter_delete(self, filter_input):
        '''
        Delete one or many title filters
        filter_input    :   Either a single int id, or a list of int ids

        Returns: list of ids of deleted podcast title filters
        '''
        query = self._database_select(PodcastTitleFilter, filter_input)
        return self.__podcast_title_filter_delete_input(query)

    def __podcast_title_filter_delete_input(self, filter_input):
        filters_deleted = []
        for title_filter in filter_input:
            self.db_session.delete(title_filter)
            self.db_session.commit()
            filters_deleted.append(title_filter.id)
            self.logger.info("Deleted podcast title filter:%s", title_filter.id)
        return filters_deleted

    def episode_sync(self, include_podcasts=None, exclude_podcasts=None, max_episode_sync=None):
        '''
        Sync podcast episode data with the interwebs. Will not download episode files
        include_podcasts     :       Include only certain podcasts in sync
        exclude_podcasts     :       Exclude certain podcasts in sync
        max_episode_sync     :       Sync up to N number of episodes, to override each podcasts max allowed
                                     For unlimited number of episodes, use 0

        Returns: null
        '''
        include_podcasts, exclude_podcasts = self._check_includers(include_podcasts, exclude_podcasts)
        self._check_argument_type(max_episode_sync, [None, int], 'Max episode sync must be None or int type')
        self.__episode_sync_cluders(include_podcasts, exclude_podcasts, max_episode_sync=max_episode_sync)
        return True

    def __episode_sync_cluders(self, include_podcasts, exclude_podcasts,
                               max_episode_sync=None, automatic_sync=True):
        query = self.db_session.query(Podcast)
        if include_podcasts:
            opts = (Podcast.id == pod for pod in include_podcasts)
            query = query.filter(or_(opts))
        if exclude_podcasts:
            opts = (Podcast.id != pod for pod in exclude_podcasts)
            query = query.filter(and_(opts))

        for podcast in query:
            if not automatic_sync and not podcast.automatic_episode_download:
                self.logger.warn("Skipping episode sync on podcast:%s", podcast.id)
                continue

            self.logger.debug("Running episode sync on podcast %s", podcast.id)
            manager = self._archive_manager(podcast.archive_type)

            # if sync all episodes, give no max results so all episodes returned
            if max_episode_sync is None:
                max_results = podcast.max_allowed
            elif max_episode_sync is 0:
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
                episode_args = {
                    'title' : episode['title'],
                    'date' : episode['date'],
                    'description' : episode['description'],
                    'download_url' : episode['download_link'],
                    'podcast_id' : podcast.id,
                    'prevent_deletion' : False,
                }
                new_episode = PodcastEpisode(**episode_args)
                try:
                    self.db_session.add(new_episode)
                    self.db_session.commit()
                    self.logger.debug("Created new podcast episode %s with args %s", new_episode.id,
                                      ' -- '.join('%s-%s' % (k, v) for k, v in episode_args.items()))
                except IntegrityError:
                    # if you attempt to add another episode with the same
                    # url, it will fail here, thats expected, we dont want
                    # duplicate episodes
                    self.db_session.rollback()
                    self.logger.debug("Podcast episode is duplicate, title was %s", episode_args['title'])

    def episode_list(self, only_files=True, sort_date=False, include_podcasts=None, exclude_podcasts=None):
        '''
        List Podcast Episodes
        only_files           :   Indicates you only want to list episodes with a file_path
        sort_date            :   Sort by date, most recent first
        include_podcasts     :   Only include these podcasts. Single ID or lists of IDs
        exclude_podcasts     :   Do not include these podcasts. Single ID or list of IDs

        Returns: List of dictionaries for all episodes requested
        '''
        self._check_argument_type(only_files, bool, 'Only Files must be boolean type')
        self._check_argument_type(sort_date, bool, 'Sort date must be boolean type')
        include_podcasts, exclude_podcasts = self._check_includers(include_podcasts, exclude_podcasts)

        query = self.db_session.query(PodcastEpisode)
        if only_files:
            query = query.filter(PodcastEpisode.file_path != None)
        if sort_date:
            query = query.order_by(desc(PodcastEpisode.date))
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

    def episode_show(self, episode_input):
        '''
        Get information about one or many podcast episodes
        episode_input    :   Either a single integer id or list of integer ids

        Returns: List of dictionaries for all episodes requested
        '''
        query = self._database_select(PodcastEpisode, episode_input)
        episode_list = []
        for episode in query:
            episode_list.append(episode.as_dict(self.datetime_output_format))
        return episode_list

    def episode_update(self, episode_id, prevent_delete=None):
        '''
        Update episode information
        episode_id           :   ID of episode to update
        prevent_deletion     :   Prevent deletion of episode from file-sync

        Returns: null
        '''
        episode = self.db_session.query(PodcastEpisode).get(episode_id)
        if not episode:
            self._fail("Podcast Episode not found for ID:%s" % episode_id)

        self._check_argument_type(prevent_delete, [None, bool], 'Prevent delete must be None or boolean type')
        if prevent_delete is not None:
            self.logger.debug("Updating prevent delete to %s for episode %s", prevent_delete, episode_id)
            episode.prevent_deletion = prevent_delete
        self.db_session.commit()
        self.logger.info("Episode updated:%s", episode.id)

    def episode_update_file_path(self, episode_id, file_path):
        '''
        Update episode file path
        episode_id          : ID of episode
        file_path           : File path where episode will be moved

        Returns: null
        '''
        episode = self.db_session.query(PodcastEpisode).get(episode_id)
        if not episode:
            self._fail("Podcast Episode not found for ID:%s" % episode_id)
        self._check_argument_type(file_path, [basestring], 'File path must be string type')
        file_path = os.path.abspath(file_path)
        path_directory, basename = os.path.split(file_path)
        # File cannot move out of podcast file location
        podcast = self.db_session.query(Podcast).get(episode.podcast_id)
        if path_directory != podcast.file_location:
            self._fail("Podcast Episode cannot be moved out of"
                       " podcast file location:%s" % podcast.file_location)
        # Make sure file extension has not changed
        _, ext = os.path.splitext(basename)
        _, original_ext = os.path.splitext(episode.file_path)
        if ext != original_ext:
            self._fail("New file path for episode:%s must use"
                       " extension:%s" % (episode.id, original_ext))
        os.rename(episode.file_path, file_path)
        episode.file_path = utils.clean_string(file_path)
        self.logger.info("Update episode:%s file path to:%s", episode.id, file_path)
        self.db_session.commit()

    def episode_delete(self, episode_input, delete_files=True):
        '''
        Delete one or many podcast episodes
        episode_input    :   Either a single integer id or list of integer ids
        delete_files     :   Delete media files along with database entries

        Returns: List of integer IDs of episodes deleted
        '''
        query = self._database_select(PodcastEpisode, episode_input)
        return self.__episode_delete_input(query, delete_files=delete_files)

    def __episode_delete_input(self, query_input, delete_files=True):
        # delete episode files to make it one call and a bit more simple
        if delete_files:
            self.__episode_delete_file_input(query_input)
        # now delete episode records
        episodes_deleted = []
        for episode in query_input:
            self.logger.info("Deleting podcast episode:%s from database", episode.id)
            self.db_session.delete(episode)
            self.db_session.commit()
            episodes_deleted.append(episode.id)
        return episodes_deleted

    def episode_download(self, episode_input):
        '''
        Download episode(s) to local machine
        episode_input    :   Either a single integer id or list of integer ids

        Returns: List of integer IDs of episodes downloaded
        '''
        query = self._database_select(PodcastEpisode, episode_input)
        return self.__episode_download_input(query)

    def __episode_download_input(self, episode_input):
        def build_episode_path(episode, podcast):
            pod_path = podcast['file_location']
            title = utils.normalize_name(episode.title)
            date = utils.normalize_name(episode.date.strftime(self.datetime_output_format))
            file_name = '%s.%s' % (date, title)
            return os.path.join(pod_path, file_name)

        podcast_cache = dict()

        episodes_downloaded = []

        for episode in episode_input:
            try:
                podcast = podcast_cache[episode.podcast_id]
            except KeyError:
                podcast = self.db_session.query(Podcast).get(episode.podcast_id).as_dict(self.datetime_output_format)
                podcast_cache[episode.podcast_id] = podcast

            manager = self._archive_manager(podcast['archive_type'])

            self.logger.debug("Downloading data from url:%s", episode.download_url)

            episode_path_prefix = build_episode_path(episode, podcast)

            output_path, download_size = manager.episode_download(episode.download_url,
                                                                  episode_path_prefix)
            if output_path is None and download_size is None:
                self.logger.error("Unable to download episode:%s, skipping", episode.id)
                continue
            self.logger.info("Downloaded episode %s data to file %s", episode.id, output_path)

            episode.file_path = utils.clean_string(output_path)
            episode.file_size = download_size
            self.db_session.commit()

            # use artist name if possible
            artist_name = podcast['artist_name'] or podcast['name']

            try:
                metadata.tags_update(output_path, artist=artist_name, album_artist=artist_name,
                                     album=podcast['name'], title=episode.title,
                                     date=episode.date.strftime(self.datetime_output_format))
                self.logger.debug("Updated database audio tags for episode %s", episode.id)
            except AudioFileException as error:
                self.logger.warn("Unable to update tags on file %s : %s", output_path, str(error))
            episodes_downloaded.append(episode.id)
        return episodes_downloaded

    def episode_delete_file(self, episode_input):
        '''
        Delete media files for one or many podcast episodes
        episode_input    :  Either a single ID, a list of IDs
        '''
        query = self._database_select(PodcastEpisode, episode_input)
        return self.__episode_delete_file_input(query)

    def __episode_delete_file_input(self, query_input):
        episodes_deleted = []
        for episode in query_input:
            if episode.file_path is not None:
                self._remove_file(episode.file_path)
                episode.file_path = None
                episode.file_size = None
                self.db_session.commit()
                self.logger.info("Removed file and updated record for episode %s", episode.id)
                episodes_deleted.append(episode.id)
        return episodes_deleted

    def episode_cleanup(self):
        '''
        Delete all podcast episode entries without a media file associated with them in order to clear room.
        Also runs the "VACUUM" command to recreate the database in order to shrink its file size
        '''
        self.db_session.query(PodcastEpisode).filter_by(file_path=None).delete()
        self.db_session.commit()
        self.db_session.execute("VACUUM")
        self.logger.info("Database cleaned of uneeded episodes")

    def podcast_file_sync(self, include_podcasts=None, exclude_podcasts=None,
                          sync_web_episodes=True, download_episodes=True):
        '''
        Updates the media files for podcasts. First sync with interwebs to check for newer episodes, then check to see if any need to be downloaded.
        include_podcasts     :   Only include these podcasts. Single ID or lists of IDs
        exclude_podcasts     :   Do not include these podcasts. Single ID or list of IDs
        sync_web_episodes    :   Sync latest known podcast episodes with web
        download_episodes    :   Download new podcast episodes

        Returns: tuple of (downloaded episodes, deleted episodes), will use null for either if nothing to return
        '''
        include_podcasts, exclude_podcasts = self._check_includers(include_podcasts, exclude_podcasts)

        if sync_web_episodes:
            self.__episode_sync_cluders(include_podcasts, exclude_podcasts,
                                        automatic_sync=False)
        if download_episodes:
            return self._podcast_download_episodes(include_podcasts, exclude_podcasts)
        return None, None

    def _podcast_download_episodes(self, include_podcasts, exclude_podcasts):
        delete_episodes = []
        download_episodes = []

        # Built podcast query to iterate through
        podcast_query = self.db_session.query(Podcast).\
            filter(Podcast.automatic_episode_download == True) #pylint:disable=singleton-comparison
        if include_podcasts:
            opts = (Podcast.id == pod for pod in include_podcasts)
            podcast_query = podcast_query.filter(or_(opts))
        if exclude_podcasts:
            opts = (Podcast.id != pod for pod in exclude_podcasts)
            podcast_query = podcast_query.filter(and_(opts))

        # Find all episodes to attempt to download
        for podcast in podcast_query:
            episode_query = self.db_session.query(PodcastEpisode).order_by(desc(PodcastEpisode.date)).\
                    filter(PodcastEpisode.podcast_id == podcast.id)

            # Make sure you call limit, then do check for file path
            # If you add the check for file path is None first

            # Get max allowed first, limit to the amount you would need to download
            # then only download ones that arent downloaded

            if podcast.max_allowed:
                episode_query = episode_query.limit(podcast.max_allowed).from_self()
            for episode in episode_query.\
                filter(PodcastEpisode.file_path == None): #pylint:disable=singleton-comparison
                download_episodes.append(episode)

        # Download episodes from query
        episodes_downloaded = None
        if download_episodes:
            self.logger.debug("Episodes %s set for download from file sync",
                              [i.id for i in download_episodes])
            episodes_downloaded = self.__episode_download_input(download_episodes)

        # Find episodes to delete if there is max allowed on the podcast
        # Not all episodes may have been downloaded, so this should use
        # another episode query, since that will check if "file_path" is defined
        # that way you dont delete episodes pre-maturely
        for podcast in podcast_query.filter(Podcast.max_allowed != None):
            episode_query = self.db_session.query(PodcastEpisode).order_by(desc(PodcastEpisode.date)).\
                    filter(PodcastEpisode.podcast_id == podcast.id).\
                    filter(PodcastEpisode.file_path != None)
                    # Make sure offset is called first, since you want to first limit
                    # then check if prevent deletion is false
                    # This way files that should be kept, but also have
                    # prevent delete will not count against files
                    # that should be deleted
            episode_query = episode_query.offset(podcast.max_allowed).from_self().\
                    filter(PodcastEpisode.prevent_deletion == False) #pylint:disable=singleton-comparison

            for episode in episode_query:
                delete_episodes.append(episode)

        episodes_deleted = None
        if delete_episodes:
            self.logger.debug("Episodes %s set for deletion for max allowed from file sync",
                              [i.id for i in delete_episodes])
            episodes_deleted = self.__episode_delete_file_input(delete_episodes)

        return episodes_downloaded, episodes_deleted

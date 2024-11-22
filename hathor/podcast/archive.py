from datetime import datetime
from logging import RootLogger
from mimetypes import guess_extension, guess_type
from re import match
from pathlib import Path
from time import mktime
from typing import List

from feedparser import parse
from googleapiclient.discovery import build
from validators import url

from requests import get
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from hathor.exc import FunctionUndefined, HathorException
from hathor import utils

def curl_download(episode_url: str, output_path: Path) -> int:
    '''
    Download url to file
    episode_url : Episode url
    output_path : Path to output file
    '''
    req = get(episode_url, allow_redirects=True, timeout=120, stream=True)
    try:
        content_type = req.headers['content-type']
    except KeyError:
        content_type = ''
    extension = guess_extension(content_type)
    if not extension:
        try:
            extension = guess_extension(guess_type(episode_url)[0])
        except AttributeError:
            extension = None
    if extension is None:
        raise HathorException(f'Unable to determine extension type for url: {episode_url}')
    output_path = Path(f'{output_path}{extension}')
    track_download_size = False

    try:
        download_size = int(req.headers.get('content-length'))
    except TypeError:
        track_download_size = True
        download_size = 0
    chunk_size = 16 * 1024
    with open(str(output_path), 'wb') as file_output:
        for chunk in req.iter_content(chunk_size=chunk_size):
            file_output.write(chunk)
            if track_download_size:
                download_size += len(chunk)
    return output_path, download_size

def verify_title_filters(filters: List[str], title: str) -> bool:
    '''
    Verify title matches filters given

    filters: Regex filters
    title: Title to check
    '''
    valid = True
    for filty in filters:
        matches = match(filty, title)
        if not matches:
            valid = False
            break
    return valid

class ArchiveInterface():
    '''
    Basic Archive Interface
    Must be inherited
    '''
    def __init__(self, logger: RootLogger, **_):
        self.logger = logger

    def broadcast_update(self, broadcast_id, max_results=None, filters=None, **kwargs):
        '''
        Basic broadcast update
        '''
        raise FunctionUndefined("No broadcast update for class")

    def episode_download(self, download_url, output_prefix, **kwargs):
        '''
        Basic podcast episode
        '''
        raise FunctionUndefined("No episode download for class")

class RSSManager(ArchiveInterface):
    '''
    RSS Archive Manager
    '''
    def __init__(self, logger: RootLogger, **_):
        ArchiveInterface.__init__(self, logger)

    def broadcast_update(self, broadcast_id: str, max_results: int = None, filters: List[str] = None, **_):
        '''
        Get latest episodes from broadcast
        broadcast_id : URL to generate episodes from
        max_results  : Only return N results
        filters      : Regex filters to match against titles
        '''
        self.logger.debug(f'Getting episode info from RSS feed: {broadcast_id}')
        data = parse(broadcast_id)
        try:
            data['feed']['link']
        except KeyError as error:
            raise HathorException(f'Invalid data from rss feed {broadcast_id}') from error

        filters = filters or []

        episodes = []
        for item in data['entries']:
            if max_results and len(episodes) >= max_results:
                self.logger.debug(f'Exiting rss update early, at max results: {max_results}')
                return episodes

            # Description not important so dont worry if its not there
            try:
                desc = utils.clean_string(item['description'])
            except (KeyError, AttributeError):
                desc = None

            episode_url = None
            # URL can be in a few different spots, lets check for proper urls
            try:
                if url(item['id']):
                    episode_url = item['id']
            except KeyError:
                pass
            # Else lets check the links
            if not episode_url:
                try:
                    for link in item['links']:
                        if link['type'] == 'text/html':
                            continue
                        episode_url = link['href']
                        break
                except KeyError:
                    pass

            if not episode_url:
                raise HathorException('Cannot find valid url for episode')

            episode_data = {
                'download_link' : episode_url,
                'title' : utils.clean_string(item['title']),
                'date' : datetime.fromtimestamp(mktime(item['published_parsed'])),
                'description' : desc,
            }
            if not verify_title_filters(filters, episode_data['title']):
                self.logger.debug(f'Title: {episode_data["title"]}, does not pass filters, skipping')
                continue
            episodes.append(episode_data)
        return episodes

    def episode_download(self, download_url: str, output_prefix: str, **_) -> (Path, int):
        '''
        Download episode from url
        download_url    : URL to download from
        output_prefix   : Name of file, should not include suffix
        '''
        return curl_download(download_url, output_prefix)

class YoutubeManager(ArchiveInterface):
    '''
    Youtube Archive Manager
    '''
    def __init__(self, logger, **kwargs):
        ArchiveInterface.__init__(self, logger)
        self.google_api_key = kwargs.get('google_api_key', None)
        if not self.google_api_key:
            raise HathorException('Google API Key not passed')

    def broadcast_update(self, broadcast_id, max_results=None, filters=None, **_):
        '''
        Get latest episodes from broadcast
        broadcast_id    : Youtube channel id
        max_results     : Return max N results
        filters         : List of regex filters
        '''
        self.logger.debug(f'Getting episodes for youtube broadcast: {broadcast_id}')
        archive_data = []
        filters = filters or []
        youtube_api = build('youtube', 'v3', developerKey=self.google_api_key)


        data_inputs = {
            'part': 'id,snippet',
            'channelId': broadcast_id,
            'type': 'video',
            'fields': 'nextPageToken,items(id(videoId),snippet(publishedAt,title,description))'
        }
        req = youtube_api.search().list(**data_inputs) #pylint:disable=no-member
        while req is not None:
            response = req.execute()
            for item in response['items']:
                title = utils.clean_string(item['snippet']['title'])
                if not verify_title_filters(filters, title):
                    self.logger.debug(f'Title: {title} , does not pass filters, skipping')
                    continue

                download_url = f'https://www.youtube.com/watch?v={item["id"]["videoId"]}'
                date = datetime.fromisoformat(item['snippet']['publishedAt'])
                episode_data = {
                    'title' : title,
                    'description' : utils.clean_string(item['snippet']['description']),
                    'download_link' : download_url,
                    'date' : date,
                }
                archive_data.append(episode_data)
                if max_results and len(archive_data) >= max_results:
                    self.logger.debug(f'At max results: {max_results}, exiting early')
                    return archive_data
            req = youtube_api.search().list_next(req, response) #pylint:disable=no-member
        return archive_data

    def episode_download(self, download_url: str, output_prefix: str, **_) -> (Path, int):
        '''
        Download episode from url
        download_url    : URL to download from
        output_prefix   : Name of file, should not include suffix
        '''
        options = {
            'outtmpl' : f'{output_prefix}.%(ext)s',
            'noplaylist' : True,
            'format': 'best',
            'logger' : self.logger,
        }
        try:
            with YoutubeDL(options) as yt:
                data = yt.extract_info(download_url, download=True)
                file_path = Path(data['requested_downloads'][0]['filepath'])
                return file_path, file_path.stat().st_size
        except DownloadError as e:
            self.logger.error(f'Error downloading youtube url: {download_url}, {str(e)}')
            return None, None

ARCHIVE_TYPES = {
    'rss' : RSSManager,
    'youtube' : YoutubeManager,
}

VALID_ARCHIVE_KEYS = list(ARCHIVE_TYPES.keys())

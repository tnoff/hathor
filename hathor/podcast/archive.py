from datetime import datetime
import json
from logging import RootLogger
import os
from re import match
from time import mktime
from typing import Literal, List

from dateutil import parser
from feedparser import parse
from googleapiclient.discovery import build
import mimetypes
from pathlib import Path
from requests import get
import yt_dlp.YoutubeDL

from hathor.exc import FunctionUndefined, HathorException
from hathor import utils

def curl_download(episode_url: str, output_path: Path) -> int:
    '''
    Download url to file
    episode_url : Episode url
    output_path : Path to output file
    '''
    req = get(episode_url, stream=True)

    content_type = req.headers['content-type']
    extension = mimetypes.guess_extension(content_type)
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

class ArchiveInterface(object):
    def __init__(self, logger: RootLogger, **kwargs):
        self.logger = logger

    def broadcast_update(self, broadcast_id, max_results=None, filters=None, **kwargs): #pylint:disable=unused-argument,no-self-use
        raise FunctionUndefined("No broadcast update for class")

    def episode_download(self, download_url, **kwargs): #pylint:disable=unused-argument,no-self-use
        raise FunctionUndefined("No episode download for class")

class RSSManager(ArchiveInterface):
    def __init__(self, logger: RootLogger, **kwargs):
        '''
        RSS Podcast manager
        logger: logger instance
        '''
        ArchiveInterface.__init__(self, logger)

    def broadcast_update(self, broadcast_id: str, max_results: int = None, filters: List[str] = None):
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
        except KeyError:
            raise HathorException(f'Invalid data from rss feed {broadcast_id}')

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

            # Check for URL
            try:
                url = item['link']
            except (KeyError, AttributeError):
                # Ignore entry if url not found
                self.logger.error(f'Ignoring item: {item}, url not found')
                continue

            episode_data = {
                'download_link' : utils.clean_string(url),
                'title' : utils.clean_string(item['title']),
                'date' : datetime.fromtimestamp(item['published_parsed']),
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
        pagetoken = None
        archive_data = []
        filters = filters or []
        youtube_api = build('youtube', 'v3', developerKey=self.google_api_key)


        data_inputs = {
            'part': 'id,snippet',
            'channelId': broadcast_id,
            'type': 'video',
            'fields': 'nextPageToken,items(id(videoId),snippet(publishedAt,title,description))'
        }
        req = youtube_api.search.list(**data_inputs)
        while req is not None:
            response = req.execute()
            for item in data['items']:
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
            req = youtube_api.search.list_next(req, response)

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
            with yt_dlp.YoutubeDL(options) as yt:
                data = yt.extract_info(download_url, download=True)
                data = data['entries'][0]
                file_path = Path(data['requested_downloads'][0]['filepath'])
                return file_name, file_path.stat().st_size
        except yt_dlp.utils.DownloadError as e:
            self.logger.error(f'Error downloading youtube url: {download_url}, {str(e)}')
            return None, None

ARCHIVE_TYPES = {
    'rss' : RSSManager,
    'youtube' : YoutubeManager,
}

VALID_ARCHIVE_KEYS = list(ARCHIVE_TYPES.keys())

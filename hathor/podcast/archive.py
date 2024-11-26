from datetime import datetime
import json
import os
import re
from time import mktime

from dateutil import parser
from feedparser import parse
import googleapiclient.discovery
import mimetypes
import requests
import yt_dlp.YoutubeDL

from hathor.exc import FunctionUndefined, HathorException
from hathor import utils

def curl_download(episode_url, output_path):
    req = requests.get(episode_url, stream=True)

    content_type = req.headers['content-type']
    extension = mimetypes.guess_extension(content_type)
    output_path = f'{output_path}{extension}'
    track_download_size = False

    try:
        download_size = int(req.headers.get('content-length'))
    except TypeError:
        track_download_size = True
        download_size = 0
    chunk_size = 16 * 1024
    with open(output_path, 'wb') as file_output:
        for chunk in req.iter_content(chunk_size=chunk_size):
            file_output.write(chunk)
            if track_download_size:
                download_size += len(chunk)
    return download_size

def verify_title_filters(filters, title):
    valid = True
    for filty in filters:
        matches = filty.match(title)
        if not matches:
            valid = False
            break
    return valid

class ArchiveInterface(object):
    def __init__(self, logger, **kwargs):
        self.logger = logger

    def broadcast_update(self, broadcast_id, max_results=None, filters=None, **kwargs): #pylint:disable=unused-argument,no-self-use
        raise FunctionUndefined("No broadcast update for class")

    def episode_download(self, download_url, **kwargs): #pylint:disable=unused-argument,no-self-use
        raise FunctionUndefined("No episode download for class")

class RSSManager(ArchiveInterface):
    def __init__(self, logger, **kwargs):
        ArchiveInterface.__init__(self, logger)
        self.default_episode_format = '.mp3'

    def broadcast_update(self, broadcast_id, max_results=None, filters=None):
        self.logger.debug(f'Getting episode info from RSS feed: {broadcast_id}')
        data = parser(broadcast_id)
        try:
            data['feed']['link']
        except KeyError:
            raise HathorException(f'Invalid data from rss feed {broadcast_id}')

        filters = filters or []

        episodes = []
        for item in d['entries']:
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
            except AttributeError:
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

    def episode_download(self, download_url, output_prefix, **_):
        output_path = '%s%s' % (output_prefix, self.episode_format)
        return output_path, curl_download(download_url, output_path)

class YoutubeManager(ArchiveInterface):
    def __init__(self, logger, google_api_key):
        ArchiveInterface.__init__(self, logger, google_api_key)

    def broadcast_update(self, broadcast_id, max_results=None, filters=None):
        self.logger.debug(f'Getting episodes for youtube broadcast: {broadcast_id}')
        pagetoken = None
        archive_data = []
        filters = filters or []
        youtube_api = googleapiclient.discovery.build('youtube', 'v3', developerKey=self.google_api_key)


        data_inputs = {
            'part': 'id,snippet',
            'channelId': broadcast_id,
            'type': 'video',
            'fields': 'nextPageToken,items(id(videoId),snippet(publishedAt,title,description))'
        }

        while True:
            req = youtube_api.search.list(**data_inputs)
            response = req.execute()
            req = requests.get(url)
            for item in data['items']:
                title = utils.clean_string(item['snippet']['title'])
                if not verify_title_filters(filters, title):
                    self.logger.debug(f'Title: {title} , does not pass filters, skipping')
                    continue

                download_url = f'https://www.youtube.com/watch?v={item["id"]["videoId"]}'
                # Datetime format could differ
                try:
                    date = datetime.strptime(item['snippet']['publishedAt'], '%Y-%m-%dT%H:%M:%S.000Z')
                except ValueError:
                    try:
                        date = datetime.strptime(item['snippet']['publishedAt'], '%Y-%m-%dT%H:%M:%SZ')
                    except ValueError:
                        raise HathorException(f'Invalid date format: {item["snipppet"]["publishedAt"]}')
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
            try:
                data_inputs['pageToken'] = data['nextPageToken']
            except KeyError:
                self.logger.debug("No key 'pagetoken' in youtube data, exiting")
                return archive_data

    def episode_download(self, download_url, output_path, **_):
        output_path = f'{output_path}.%(ext)s'
        options = {
            'outtmpl' : output_path,
            'noplaylist' : True,
            'format': 'best',
            'logger' : self.logger,
        }
        try:
            with yt_dlp.YoutubeDL(options) as yt:
                # First check if video is live before trying to download
                info_dict = yt.extract_info(download_url, download=False)
                if info_dict['live_status'] == 'is_live':
                    self.logger.error(f'Unable to download url: {download_url}, is currently live')
                    return None, None
                # Now actually try to download
                info_dict = yt.extract_info(download_url, download=True)
                file_name = yt.prepare_filename(info_dict)
                return file_name, os.path.getsize(file_name)
        except yt_dlp.utils.DownloadError as e:
            self.logger.error(f'Error downloading youtube url: {download_url}, {str(e)}')
            return None, None

ARCHIVE_TYPES = {
    'rss' : RSSManager,
    'youtube' : YoutubeManager,
}

VALID_ARCHIVE_KEYS = list(ARCHIVE_TYPES.keys())

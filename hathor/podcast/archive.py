from datetime import datetime
import json
import os
import re

from dateutil import parser
import requests
from bs4 import BeautifulSoup as i_like_soup
import yt_dlp.YoutubeDL

from hathor.exc import FunctionUndefined, HathorException
from hathor.podcast import urls
from hathor import utils

def clean_title(title):
    '''
    Remove any emojis from title
    '''
    # https://stackoverflow.com/questions/33404752/removing-emojis-from-a-string-in-python
    emoji_pattern = re.compile("["
            u"\U0001F600-\U0001F64F"  # emoticons
            u"\U0001F300-\U0001F5FF"  # symbols & pictographs
            u"\U0001F680-\U0001F6FF"  # transport & map symbols
            u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
                               "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', title) # no emoji

def curl_download(episode_url, output_path):
    req = requests.get(episode_url, stream=True)
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
    def __init__(self, logger, soundcloud_client_id, google_api_key):
        self.logger = logger
        self.soundcloud_client_id = soundcloud_client_id
        self.google_api_key = google_api_key
        self.episode_format = None

    def broadcast_update(self, broadcast_id, max_results=None, filters=None): #pylint:disable=unused-argument,no-self-use
        raise FunctionUndefined("No broadcast update for class")

    def episode_download(self, download_url, output_prefix, **_): #pylint:disable=unused-argument,no-self-use
        raise FunctionUndefined("No episode download for class")

class RSSManager(ArchiveInterface):
    def __init__(self, logger, soundcloud_client_id, google_api_key):
        ArchiveInterface.__init__(self, logger, soundcloud_client_id, google_api_key)
        self.episode_format = '.mp3'

    def broadcast_update(self, broadcast_id, max_results=None, filters=None):
        self.logger.debug("Getting episode info from RSS feed:%s", broadcast_id)
        req = requests.get(broadcast_id)
        if req.status_code != 200:
            raise HathorException("Getting invalid status code:%s for rss feed" % req.status_code)
        soup_data = i_like_soup(req.text, 'html.parser')

        filters = filters or []

        episodes = []
        for item in soup_data.find_all('item'):
            if max_results and len(episodes) >= max_results:
                self.logger.debug("Exiting rss update early, at max results:%s", max_results)
                return episodes

            # Description not important so dont worry if its not there
            try:
                desc = utils.clean_string(item.find('description').string)
            except (KeyError, AttributeError):
                desc = None

            # Check for URL
            try:
                url = item.find('enclosure').attrs['url']
            except AttributeError:
                # Ignore entry if url not found
                self.logger.error("Ignoring item:%s, url not found", item)
                continue

            episode_data = {
                'download_link' : utils.clean_string(url),
                'title' : clean_title(utils.clean_string(item.find('title').string)),
                'date' : parser.parse(item.find('pubdate').string),
                'description' : desc,
            }
            if not verify_title_filters(filters, episode_data['title']):
                self.logger.debug("Title:%s , does not pass filters, skipping",
                                  episode_data['title'])
                continue
            episodes.append(episode_data)
        return episodes

    def episode_download(self, download_url, output_prefix, **_):
        output_path = '%s%s' % (output_prefix, self.episode_format)
        return output_path, curl_download(download_url, output_path)

class SoundcloudManager(ArchiveInterface):
    def __init__(self, logger, soundcloud_client_id, google_api_key):
        ArchiveInterface.__init__(self, logger, soundcloud_client_id, google_api_key)
        self.episode_format = 'mp3'

    def broadcast_update(self, broadcast_id, max_results=None, filters=None):
        archive_data = []
        filters = filters or []

        self.logger.debug("Getting account id for soundcloud channel name:%s", broadcast_id)
        account_url = urls.soundcloud_account(broadcast_id, self.soundcloud_client_id)
        req = requests.get(account_url)
        if req.status_code != 200:
            raise HathorException("Error getting soundcloud account id, request error:%s" % req.status_code)
        data = json.loads(req.text)
        account_id = data['id']

        self.logger.debug("Getting episodes from soundcloud account id:%s", account_id)
        url = urls.soundcloud_track_list(account_id, self.soundcloud_client_id)

        while True:
            req = requests.get(url)
            if req.status_code != 200:
                raise HathorException("Error getting soundcloud track list, request error:%s" % req.status_code)
            data = json.loads(req.text)

            for item in data['collection']:
                # if not downloadable, skip
                if not item['downloadable']:
                    self.logger.debug("Item with title:%s not downloadable, skipping", item['title'])
                    continue
                episode_data = {
                    'date' : datetime.strptime(item['created_at'], '%Y/%m/%d %H:%M:%S +0000'),
                    'title' : clean_title(utils.clean_string(item['title'])),
                    'download_link' : utils.clean_string(item['download_url']),
                    'description' : utils.clean_string(item['description']),

                }
                if not verify_title_filters(filters, episode_data['title']):
                    self.logger.debug("Title:%s , does not pass filters, skipping",
                                      episode_data['title'])
                    continue
                archive_data.append(episode_data)
                if max_results and max_results <= len(archive_data):
                    self.logger.debug("At max results limit:%s, exiting early", len(archive_data))
                    return archive_data
            # check if another page is there
            try:
                url = data['next_href']
            except KeyError:
                self.logger.debug("No more soundcloud episodes found, exiting")
                break

        return archive_data

    def episode_download(self, download_url, output_prefix, **_):
        download_url = "%s?client_id=%s" % (download_url, self.soundcloud_client_id)
        output_path = '%s.%s' % (output_prefix, self.episode_format)
        return output_path, curl_download(download_url, output_path)

class YoutubeManager(ArchiveInterface):
    def __init__(self, logger, soundcloud_client_id, google_api_key):
        ArchiveInterface.__init__(self, logger, soundcloud_client_id, google_api_key)

    def broadcast_update(self, broadcast_id, max_results=None, filters=None):
        self.logger.debug("Getting episodes for youtube broadcast:%s", broadcast_id)
        pagetoken = None
        archive_data = []
        filters = filters or []

        while True:
            url = urls.youtube_channel_get(broadcast_id, self.google_api_key, page_token=pagetoken)
            req = requests.get(url)
            if req.status_code == 400 or req.status_code == 403:
                self.logger.error("Invalid status code:%s", req.status_code)
                self.logger.error("Request data:%s", req.text)
                raise HathorException("Invalid status code:%s" % req.status_code)

            data = json.loads(req.text)
            for item in data['items']:
                if item['id']['kind'] != 'youtube#video':
                    self.logger.debug("Item %s is not a video, skipping" % str(item['id']))
                    continue
                title = clean_title(utils.clean_string(item['snippet']['title']))
                if not verify_title_filters(filters, title):
                    self.logger.debug("Title:%s , does not pass filters, skipping",
                                      title)
                    continue

                download_url = 'https://www.youtube.com/watch?v=%s' % item['id']['videoId']
                # Datetime format could differ
                try:
                    date = datetime.strptime(item['snippet']['publishedAt'],
                                             '%Y-%m-%dT%H:%M:%S.000Z')
                except ValueError:
                    try:
                        date = datetime.strptime(item['snippet']['publishedAt'],
                                                 '%Y-%m-%dT%H:%M:%SZ')
                    except ValueError:
                        raise HathorException("Invalid date format:%s" % item['snippet']['publishedAt'])
                episode_data = {
                    'title' : title,
                    'description' : utils.clean_string(item['snippet']['description']),
                    'download_link' : download_url,
                    'date' : date,
                }
                archive_data.append(episode_data)
                if max_results and len(archive_data) >= max_results:
                    self.logger.debug("At max results:%s, exiting early", max_results)
                    return archive_data
            try:
                pagetoken = data['nextPageToken']
            except KeyError:
                self.logger.debug("No key 'pagetoken' in youtube data, exiting")
                break
            if not pagetoken:
                self.logger.debug("Page token is none in youtube data, exiting")
                break

        return archive_data

    def episode_download(self, download_url, output_prefix, **_):
        output_path = '%s.%%(ext)s' % output_prefix
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
                if info_dict['is_live']:
                    self.logger.error("Unable to download url:%s, is currently live", download_url)
                    return None, None
                # Now actually try to download
                info_dict = yt.extract_info(download_url, download=True)
                file_name = yt.prepare_filename(info_dict)
                return file_name, os.path.getsize(file_name)
        except yt_dlp.utils.DownloadError as e:
            self.logger.error('Error downloading youtube url:%s', download_url)
            self.logger.error("Youtube-dl error error:%s", str(e))
            return None, None

ARCHIVE_TYPES = {
    'rss' : RSSManager,
    'soundcloud' : SoundcloudManager,
    'youtube' : YoutubeManager,
}
ARCHIVE_KEYS = ARCHIVE_TYPES.keys()

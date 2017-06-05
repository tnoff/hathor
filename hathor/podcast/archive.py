from datetime import datetime
import json
import os


from dateutil import parser
import requests
from bs4 import BeautifulSoup as i_like_soup
import youtube_dl.YoutubeDL

from hathor.exc import FunctionUndefined, HathorException
from hathor.podcast import urls
from hathor import utils

def curl_download(episode_url, output_path):
    req = requests.get(episode_url, stream=True)
    download_size = int(req.headers.get('content-length'))
    chunk_size = 16 * 1024
    with open(output_path, 'wb') as file_output:
        written_data = 0
        for chunk in req.iter_content(chunk_size=chunk_size):
            file_output.write(chunk)
            written_data += chunk_size
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
            episode_data = {
                'download_link' : utils.clean_string(item.find('enclosure').attrs['url']),
                'title' : utils.clean_string(item.find('title').string),
                'date' : parser.parse(item.find('pubdate').string),
                'description' : utils.clean_string(item.find('description').string),
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
                    'title' : utils.clean_string(item['title']),
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
        self.file_name = None

    def __check_filename_hook(self, info_dict):
        if info_dict['status'] == 'finished':
            self.file_name = info_dict['filename']

    def broadcast_update(self, broadcast_id, max_results=None, filters=None):
        self.logger.debug("Getting episodes for youtube broadcast:%s", broadcast_id)
        pagetoken = None
        archive_data = []
        filters = filters or []

        while True:
            url = urls.youtube_channel_get(broadcast_id, self.google_api_key, page_token=pagetoken)
            req = requests.get(url)
            if req.status_code == 400 or req.status_code == 403:
                raise HathorException("Invalid status code:%s" % req.status_code)

            data = json.loads(req.text)
            for item in data['items']:
                if item['id']['kind'] != 'youtube#video':
                    self.logger.debug("Item %s is not a video, skipping" % str(item['id']))
                    continue
                title = utils.clean_string(item['snippet']['title'])
                if not verify_title_filters(filters, title):
                    self.logger.debug("Title:%s , does not pass filters, skipping",
                                      title)
                    continue

                download_url = 'https://www.youtube.com/watch?v=%s' % item['id']['videoId']
                date = datetime.strptime(item['snippet']['publishedAt'],
                                         '%Y-%m-%dT%H:%M:%S.000Z')
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
            'progress_hooks' : [self.__check_filename_hook],
            'logger' : self.logger,
        }
        try:
            with youtube_dl.YoutubeDL(options) as yt:
                info_dict = yt.extract_info(download_url, download=False)
                if info_dict['is_live']:
                    self.logger.error("Unable to download url:%s, is currently live", download_url)
                    return None, None
                yt.download([download_url])
        except youtube_dl.utils.DownloadError as e:
            self.logger.error('Error downloading youtube url:%s', download_url)
            self.logger.error("Youtube-dl error error:%s", str(e))
            return None, None
        return self.file_name, os.path.getsize(self.file_name)

ARCHIVE_TYPES = {
    'rss' : RSSManager,
    'soundcloud' : SoundcloudManager,
    'youtube' : YoutubeManager,
}
ARCHIVE_KEYS = ARCHIVE_TYPES.keys()

import re
from datetime import datetime
from logging import RootLogger
from mimetypes import guess_extension, guess_type
from pathlib import Path
from time import mktime

from feedparser import parse
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from validators import url

from requests import get, head, post
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from hathor.exc import EpisodeNotReady, FunctionUndefined, HathorException
from hathor import utils

_YOUTUBE_VIDEO_ID_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?(?:[^ ]*&)?v=|live/|embed/|shorts/)|youtu\.be/)'
    r'(?P<id>[A-Za-z0-9_-]{11})'
)

_TWITCH_VIDEO_ID_RE = re.compile(r'twitch\.tv/videos/(?P<id>\d+)')

TWITCH_OAUTH_URL = 'https://id.twitch.tv/oauth2/token'
TWITCH_API_URL = 'https://api.twitch.tv/helix'
TWITCH_REQUEST_TIMEOUT = 30
# Helix caps a page at 100 items
TWITCH_PAGE_SIZE = 100
# While a broadcast is still being recorded, and for a while after it ends, twitch
# serves a placeholder in place of the real thumbnail. It is the only field on the
# video object that marks a VOD as not yet finished.
TWITCH_PROCESSING_THUMBNAIL = '404_processing'

# Youtube rate limits an unpaced client hard. Downloading a backlog back to back
# earns HTTP 429 on the first request of each video, which youtube escalates into
# "Sign in to confirm you're not a bot" -- at which point nothing downloads until
# the client backs off, and no amount of retrying helps.
#
# sleep_requests spaces out the requests within a single extraction (webpage,
# player JS, the various player API calls); sleep_interval/max_sleep_interval put
# a randomised gap in front of each download, so a sync of many episodes does not
# arrive as an evenly spaced machine-looking burst.
#
# Overridable per deployment through the ytdlp_options setting.
YOUTUBE_PACING_YTDLP_OPTIONS = {
    'sleep_requests': 1,
    'sleep_interval': 2,
    'max_sleep_interval': 6,
}

# The data api bills per call, against a default of 10,000 units a day.
# search.list costs 100 units a call; playlistItems.list reads the same fields
# off the channel's uploads playlist for 1. A channel's uploads playlist id is
# its channel id with the leading "UC" swapped for "UU", so the cheap path
# needs no extra lookup.
YOUTUBE_CHANNEL_ID_PREFIX = 'UC'
YOUTUBE_UPLOADS_PLAYLIST_PREFIX = 'UU'
# Largest page the api allows. The default is 5, which spends a call on every
# fifth video.
YOUTUBE_PAGE_SIZE = 50
# Results come back newest first, so a run that recognises this many videos in
# a row has caught up with what is already stored and can stop paging. A streak
# rather than a single video because premieres and finished live streams do not
# always land in strict publish order.
YOUTUBE_KNOWN_STREAK_STOP = 3
# Hard ceiling on pages walked in one sync, so no podcast can ever page through
# a whole channel -- an aggressive title filter or a wiped database would
# otherwise walk to the oldest upload.
YOUTUBE_MAX_PAGES = 20
# Handed to execute(). The client retries 429, 5xx and the rate-limit flavours
# of 403 with randomised exponential backoff, and leaves quotaExceeded alone --
# that one does not recover inside a run.
YOUTUBE_NUM_RETRIES = 4
# 403 reasons that mean the daily quota is spent
YOUTUBE_QUOTA_REASONS = ('quotaExceeded', 'dailyLimitExceeded')

# Shorts sit in the uploads playlist next to everything else and the data api
# has no field that marks one. The shorts player does the marking instead: it
# serves a short at 200 and bounces anything else to /watch with a 303. A HEAD
# costs no api quota and no body, and unlike duration it does not mistake a
# two minute regular upload for a short.
YOUTUBE_SHORTS_URL = 'https://www.youtube.com/shorts'
YOUTUBE_SHORTS_REQUEST_TIMEOUT = 30

def twitch_timestamp(timestamp: str) -> datetime:
    '''
    Parse an RFC3339 timestamp from the twitch api
    timestamp : Timestamp string, such as 2026-08-11T17:55:36Z
    '''
    return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

def extract_twitch_video_id(twitch_url: str) -> str | None:
    '''Return the numeric video id from a Twitch VOD URL, or None if not parseable.'''
    if not twitch_url:
        return None
    m = _TWITCH_VIDEO_ID_RE.search(twitch_url)
    return m.group('id') if m else None

def extract_youtube_video_id(youtube_url: str) -> str | None:
    '''Return the 11-char videoId from a YouTube URL, or None if not parseable.'''
    if not youtube_url:
        return None
    m = _YOUTUBE_VIDEO_ID_RE.search(youtube_url)
    return m.group('id') if m else None

def youtube_quota_exhausted(error: HttpError) -> bool:
    '''
    Check whether an api error means the daily quota is spent. Retrying will not
    clear it, the quota resets on googles clock.
    error : Error raised by the google api client
    '''
    details = error.error_details or []
    if isinstance(details, dict):
        details = [details]
    for detail in details:
        if isinstance(detail, dict) and detail.get('reason') in YOUTUBE_QUOTA_REASONS:
            return True
    return False

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

def verify_title_filters(filters: list[str], title: str) -> bool:
    '''
    Verify title matches filters given

    filters: Regex filters
    title: Title to check
    '''
    valid = True
    for filty in filters:
        matches = re.match(filty, title)
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

    def broadcast_update(self, broadcast_id: str, max_results: int | None = None, filters: list[str] | None = None, **_):
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
        self.ytdlp_options = kwargs.get('ytdlp_options', None) or {}
        self.skip_shorts = kwargs.get('youtube_skip_shorts', False)
        # Built once and reused. Every call off it goes through _execute
        self.youtube_api = build('youtube', 'v3', developerKey=self.google_api_key)

    def _execute(self, request):
        '''
        Run an api request, retrying the transient rate limits and turning a
        spent quota into something readable
        request : Request object from the google api client
        '''
        try:
            return request.execute(num_retries=YOUTUBE_NUM_RETRIES)
        except HttpError as error:
            if youtube_quota_exhausted(error):
                raise HathorException('Youtube api daily quota exceeded') from error
            raise

    def _uploads_playlist_id(self, broadcast_id: str) -> str:
        '''
        Find the uploads playlist that holds a channels videos
        broadcast_id : Youtube channel id
        '''
        if broadcast_id.startswith(YOUTUBE_CHANNEL_ID_PREFIX):
            suffix = broadcast_id[len(YOUTUBE_CHANNEL_ID_PREFIX):]
            return f'{YOUTUBE_UPLOADS_PLAYLIST_PREFIX}{suffix}'
        # Older channel ids do not carry the uploads id in their name, so ask.
        # One unit, and only for channels that need it.
        response = self._execute(self.youtube_api.channels().list( #pylint:disable=no-member
            part='contentDetails',
            id=broadcast_id,
            fields='items(contentDetails/relatedPlaylists/uploads)',
        ))
        items = response.get('items') or []
        if not items:
            raise HathorException(f'No youtube channel found for: {broadcast_id}')
        return items[0]['contentDetails']['relatedPlaylists']['uploads']

    def _is_short(self, video_id: str) -> bool:
        '''
        Check whether a video id points at a short
        video_id : 11 char youtube video id

        Returns False when the check cannot be made, so a video is only ever
        skipped on a definite answer
        '''
        try:
            response = head(f'{YOUTUBE_SHORTS_URL}/{video_id}', allow_redirects=False,
                            timeout=YOUTUBE_SHORTS_REQUEST_TIMEOUT)
        except Exception as e: #pylint:disable=broad-except
            self.logger.warning(f'Shorts check failed for video {video_id}: {str(e)}')
            return False
        return response.status_code == 200

    def broadcast_update(self, broadcast_id, max_results=None, filters=None, known_urls=None, **_):
        '''
        Get latest episodes from broadcast
        broadcast_id    : Youtube channel id
        max_results     : Return max N results
        filters         : List of regex filters
        known_urls      : Download urls already stored for this podcast. Paging stops
                          once YOUTUBE_KNOWN_STREAK_STOP of them turn up in a row
        '''
        self.logger.debug(f'Getting episodes for youtube broadcast: {broadcast_id}')
        archive_data = []
        filters = filters or []
        known_ids = set()
        for known_url in known_urls or []:
            video_id = extract_youtube_video_id(known_url)
            if video_id:
                known_ids.add(video_id)

        data_inputs = {
            'part': 'snippet,contentDetails',
            'playlistId': self._uploads_playlist_id(broadcast_id),
            'maxResults': YOUTUBE_PAGE_SIZE,
            'fields': 'nextPageToken,items(snippet(title,description,resourceId/videoId),'
                      'contentDetails/videoPublishedAt)',
        }
        playlist_items = self.youtube_api.playlistItems() #pylint:disable=no-member
        req = playlist_items.list(**data_inputs)
        pages = 0
        known_streak = 0
        while req is not None:
            response = self._execute(req)
            pages += 1
            for item in response['items']:
                video_id = item['snippet']['resourceId']['videoId']
                # Checked ahead of the title filters, so a filter that matches
                # rarely cannot keep the walk going to the end of the channel
                if video_id in known_ids:
                    known_streak += 1
                    if known_streak >= YOUTUBE_KNOWN_STREAK_STOP:
                        self.logger.debug(f'Saw {known_streak} known videos in a row, caught up on {broadcast_id}')
                        return archive_data
                    continue

                title = utils.clean_string(item['snippet']['title'])
                if not verify_title_filters(filters, title):
                    self.logger.debug(f'Title: {title} , does not pass filters, skipping')
                    known_streak = 0
                    continue

                # Checked after the filters, which are free, so the request is
                # only spent on videos that would otherwise be stored. A skipped
                # short leaves the streak alone: it never enters known_urls, so
                # resetting here would mean a channel that posts shorts between
                # uploads could never reach the streak and would page on to the
                # ceiling on every sync
                if self.skip_shorts and self._is_short(video_id):
                    self.logger.debug(f'Video {video_id} is a short, skipping')
                    continue
                known_streak = 0

                download_url = f'https://www.youtube.com/watch?v={video_id}'
                # snippet.publishedAt is when the video joined the playlist, the
                # date the episode wants is when the video itself went up
                date = datetime.fromisoformat(item['contentDetails']['videoPublishedAt'])
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
            if pages >= YOUTUBE_MAX_PAGES:
                self.logger.warning(f'Hit page ceiling {YOUTUBE_MAX_PAGES} on broadcast {broadcast_id}, stopping')
                return archive_data
            req = playlist_items.list_next(req, response)
        return archive_data

    def _youtube_vod_ready(self, download_url: str) -> bool:
        '''
        Return False iff the URL points at a YouTube video that is currently
        live, scheduled, or a finished live still being processed into a VOD.
        Return True otherwise (regular VODs, fully-processed live VODs, and
        any case where we cannot decide confidently).
        '''
        video_id = extract_youtube_video_id(download_url)
        if not video_id:
            return True

        try:
            resp = self._execute(self.youtube_api.videos().list( #pylint:disable=no-member
                part='snippet,liveStreamingDetails,contentDetails',
                id=video_id,
                fields='items(snippet/liveBroadcastContent,'
                       'liveStreamingDetails/actualEndTime,'
                       'contentDetails/duration)',
            ))
        except Exception as e: #pylint:disable=broad-except
            self.logger.warning(f'YouTube liveness check failed for {download_url}: {str(e)}')
            return True

        items = resp.get('items') or []
        if not items:
            return True

        item = items[0]
        broadcast = (item.get('snippet') or {}).get('liveBroadcastContent')
        if broadcast in ('live', 'upcoming'):
            self.logger.info(f'Deferring {download_url}: broadcast is {broadcast}')
            return False

        live_details = item.get('liveStreamingDetails') or {}
        duration = (item.get('contentDetails') or {}).get('duration')
        if live_details.get('actualEndTime') and duration in (None, 'PT0S'):
            self.logger.info(f'Deferring {download_url}: live ended, VOD still processing')
            return False

        return True

    def episode_download(self, download_url: str, output_prefix: str, **_) -> (Path, int):
        '''
        Download episode from url
        download_url    : URL to download from
        output_prefix   : Name of file, should not include suffix

        Raises EpisodeNotReady if the broadcast cannot be downloaded yet
        '''
        if not self._youtube_vod_ready(download_url):
            raise EpisodeNotReady(f'Episode not ready for download: {download_url}')
        options = {
            'noplaylist' : True,
            'format': (
                'bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]'
                '/bestvideo[vcodec^=vp9]+bestaudio'
                '/bestvideo+bestaudio'
                '/best'
            ),
            **YOUTUBE_PACING_YTDLP_OPTIONS,
            **self.ytdlp_options,
            # Not overridable: the episode file path is read back out of the
            # download result, and yt-dlp's output belongs on hathor's logger.
            'outtmpl' : f'{output_prefix}.%(ext)s',
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

class TwitchManager(ArchiveInterface):
    '''
    Twitch Archive Manager

    Downloads past broadcasts (VODs) from a twitch channel. Live streams are
    skipped, and picked up on a later sync once twitch has finished the VOD.
    '''
    def __init__(self, logger, **kwargs):
        ArchiveInterface.__init__(self, logger)
        self.twitch_client_id = kwargs.get('twitch_client_id', None)
        self.twitch_client_secret = kwargs.get('twitch_client_secret', None)
        if not self.twitch_client_id or not self.twitch_client_secret:
            raise HathorException('Twitch client id and client secret not passed')
        self.ytdlp_options = kwargs.get('ytdlp_options', None) or {}
        self._access_token = None

    def _token(self) -> str:
        '''
        Fetch an app access token, and reuse it for the life of the manager.
        Only public data is read, so the client credentials grant is enough and
        no user ever has to log in.
        '''
        if self._access_token:
            return self._access_token
        response = post(TWITCH_OAUTH_URL, params={
            'client_id': self.twitch_client_id,
            'client_secret': self.twitch_client_secret,
            'grant_type': 'client_credentials',
        }, timeout=TWITCH_REQUEST_TIMEOUT)
        response.raise_for_status()
        self._access_token = response.json()['access_token']
        return self._access_token

    def _api_get(self, endpoint: str, params: dict) -> dict:
        '''
        Call a helix endpoint
        endpoint : Helix endpoint name, such as "videos"
        params   : Query params
        '''
        response = get(f'{TWITCH_API_URL}/{endpoint}', params=params, headers={
            'Client-Id': self.twitch_client_id,
            'Authorization': f'Bearer {self._token()}',
        }, timeout=TWITCH_REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def _user_id(self, channel_name: str) -> str:
        '''
        Resolve a channel login name to the numeric user id helix wants
        channel_name : Twitch channel login name
        '''
        data = self._api_get('users', {'login': channel_name})
        users = data.get('data') or []
        if not users:
            raise HathorException(f'No twitch channel found for: {channel_name}')
        return users[0]['id']

    def broadcast_update(self, broadcast_id, max_results=None, filters=None, **_):
        '''
        Get latest episodes from broadcast
        broadcast_id    : Twitch channel login name
        max_results     : Return max N results
        filters         : List of regex filters
        '''
        self.logger.debug(f'Getting episodes for twitch broadcast: {broadcast_id}')
        archive_data = []
        filters = filters or []
        user_id = self._user_id(broadcast_id)

        params = {
            'user_id': user_id,
            # Past broadcasts only, so channel highlights and uploaded videos
            # are left alone
            'type': 'archive',
            'first': TWITCH_PAGE_SIZE,
        }
        while True:
            response = self._api_get('videos', params)
            for item in response.get('data') or []:
                title = utils.clean_string(item['title'])
                if not verify_title_filters(filters, title):
                    self.logger.debug(f'Title: {title} , does not pass filters, skipping')
                    continue

                description = utils.clean_string(item.get('description') or '') or None
                episode_data = {
                    'title' : title,
                    'description' : description,
                    'download_link' : item['url'],
                    'date' : twitch_timestamp(item['published_at']),
                }
                archive_data.append(episode_data)
                if max_results and len(archive_data) >= max_results:
                    self.logger.debug(f'At max results: {max_results}, exiting early')
                    return archive_data
            cursor = (response.get('pagination') or {}).get('cursor')
            if not cursor:
                return archive_data
            params['after'] = cursor

    def _twitch_vod_ready(self, download_url: str) -> bool:
        '''
        Return False iff the URL points at a VOD that twitch is still recording
        or still processing. Return True otherwise (finished VODs, and any case
        where we cannot decide confidently).
        '''
        video_id = extract_twitch_video_id(download_url)
        if not video_id:
            return True

        try:
            response = self._api_get('videos', {'id': video_id})
            videos = response.get('data') or []
            if not videos:
                return True

            video = videos[0]
            if TWITCH_PROCESSING_THUMBNAIL in (video.get('thumbnail_url') or ''):
                self.logger.info(f'Deferring {download_url}: VOD still processing')
                return False

            # A broadcast that is still going shows up in the archive list right
            # away, and downloading it now would capture a partial stream. The
            # live stream carries the same id as the VOD's stream_id.
            stream_id = video.get('stream_id')
            user_id = video.get('user_id')
            if stream_id and user_id:
                streams = self._api_get('streams', {'user_id': user_id})
                for stream in streams.get('data') or []:
                    if stream.get('id') == stream_id:
                        self.logger.info(f'Deferring {download_url}: broadcast is still live')
                        return False
        except Exception as e: #pylint:disable=broad-except
            self.logger.warning(f'Twitch liveness check failed for {download_url}: {str(e)}')
            return True

        return True

    def episode_download(self, download_url: str, output_prefix: str, **_) -> (Path, int):
        '''
        Download episode from url
        download_url    : URL to download from
        output_prefix   : Name of file, should not include suffix

        Raises EpisodeNotReady if the broadcast cannot be downloaded yet
        '''
        if not self._twitch_vod_ready(download_url):
            raise EpisodeNotReady(f'Episode not ready for download: {download_url}')
        options = {
            'noplaylist' : True,
            # Twitch serves muxed HLS variants, the split streams are a fallback
            'format': 'bestvideo+bestaudio/best',
            **self.ytdlp_options,
            # Not overridable: the episode file path is read back out of the
            # download result, and yt-dlp's output belongs on hathor's logger.
            'outtmpl' : f'{output_prefix}.%(ext)s',
            'logger' : self.logger,
        }
        try:
            with YoutubeDL(options) as yt:
                data = yt.extract_info(download_url, download=True)
                file_path = Path(data['requested_downloads'][0]['filepath'])
                return file_path, file_path.stat().st_size
        except DownloadError as e:
            self.logger.error(f'Error downloading twitch url: {download_url}, {str(e)}')
            return None, None

ARCHIVE_TYPES = {
    'rss' : RSSManager,
    'twitch' : TwitchManager,
    'youtube' : YoutubeManager,
}

VALID_ARCHIVE_KEYS = list(ARCHIVE_TYPES.keys())

from datetime import datetime
import json

import httpretty
import mock

from hathor.audio import metadata
from hathor.exc import HathorException
from hathor.podcast import urls
from hathor import utils

from tests import utils as test_utils
from tests.podcasts.data import history_on_fire
from tests.podcasts.data import soundcloud_archive_page1, soundcloud_archive_page2
from tests.podcasts.data import soundcloud_one_track
from tests.podcasts.data import soundcloud_two_tracks, soundcloud_three_tracks
from tests.podcasts.data import youtube_archive1, youtube_archive2

class TestPodcastEpisodes(test_utils.TestHelper): #pylint:disable=too-many-public-methods
    def run(self, result=None):
        with test_utils.temp_client() as client_args:
            self.client = client_args.pop('podcast_client') #pylint:disable=attribute-defined-outside-init
            super(TestPodcastEpisodes, self).run(result)

    @httpretty.activate
    def test_episode_sync_soundcloud(self):
        with test_utils.temp_podcast(self.client, archive_type='soundcloud') as podcast:
            page1_url = urls.soundcloud_track_list(podcast['broadcast_id'], self.client.soundcloud_client_id)
            httpretty.register_uri(httpretty.GET, page1_url, body=json.dumps(soundcloud_archive_page1.DATA),
                                   content_type='application/json')
            page2_url = soundcloud_archive_page1.DATA['next_href']
            httpretty.register_uri(httpretty.GET, page2_url, body=json.dumps(soundcloud_archive_page2.DATA),
                                   content_type='application/json')
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            self.assertEqual(len(episode_list), 4)

    @httpretty.activate
    def test_episode_sync_soundcloud_max_allowed(self):
        # make sure you only get the one page from soundcloud pagination
        with test_utils.temp_podcast(self.client, archive_type='soundcloud', max_allowed=2) as podcast:
            page1_url = urls.soundcloud_track_list(podcast['broadcast_id'], self.client.soundcloud_client_id)
            httpretty.register_uri(httpretty.GET, page1_url, body=json.dumps(soundcloud_archive_page1.DATA),
                                   content_type='application/json')
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            self.assertEqual(len(episode_list), 2)

    @httpretty.activate
    def test_episode_sync_maximum_episodes(self):
        with test_utils.temp_podcast(self.client, archive_type='soundcloud', max_allowed=2) as podcast:
            page1_url = urls.soundcloud_track_list(podcast['broadcast_id'], self.client.soundcloud_client_id)
            httpretty.register_uri(httpretty.GET, page1_url, body=json.dumps(soundcloud_archive_page1.DATA),
                                   content_type='application/json')
            page2_url = soundcloud_archive_page1.DATA['next_href']
            httpretty.register_uri(httpretty.GET, page2_url, body=json.dumps(soundcloud_archive_page2.DATA),
                                   content_type='application/json')
            self.client.episode_sync(max_episode_sync=0)
            episode_list = self.client.episode_list(only_files=False)
            self.assertEqual(len(episode_list), 4)

    @httpretty.activate
    def test_episode_sync_set_number_episodes(self):
        with test_utils.temp_podcast(self.client, archive_type='soundcloud', max_allowed=2) as podcast:
            page1_url = urls.soundcloud_track_list(podcast['broadcast_id'], self.client.soundcloud_client_id)
            httpretty.register_uri(httpretty.GET, page1_url, body=json.dumps(soundcloud_archive_page1.DATA),
                                   content_type='application/json')
            page2_url = soundcloud_archive_page1.DATA['next_href']
            httpretty.register_uri(httpretty.GET, page2_url, body=json.dumps(soundcloud_archive_page2.DATA),
                                   content_type='application/json')
            self.client.episode_sync(max_episode_sync=3)
            episode_list = self.client.episode_list(only_files=False)
            self.assertEqual(len(episode_list), 3)

    @httpretty.activate
    def test_episode_sync_exits_on_maximum(self):
        with test_utils.temp_podcast(self.client, archive_type='youtube', max_allowed=1) as podcast:
            url1 = urls.youtube_channel_get(podcast['broadcast_id'], self.client.google_api_key)
            with mock.patch('youtube_dl.YoutubeDL', side_effect=test_utils.youtube_mock):
                httpretty.register_uri(httpretty.GET, url1,
                                       body=json.dumps(youtube_archive1.DATA),
                                       content_type='application/json')
                self.client.episode_sync()

                episode_list = self.client.episode_list(only_files=False)
                self.assert_length(episode_list, 1)

    @httpretty.activate
    def test_episode_passes_title_filters(self):
        with test_utils.temp_podcast(self.client, archive_type='youtube', max_allowed=1) as podcast:
            url1 = urls.youtube_channel_get(podcast['broadcast_id'], self.client.google_api_key)
            episode_title = youtube_archive1.DATA['items'][-1]['snippet']['title']
            first_item_title_regex = '^%s' % episode_title
            self.client.podcast_title_filter_create(podcast['id'], first_item_title_regex)

            with mock.patch('youtube_dl.YoutubeDL', side_effect=test_utils.youtube_mock):
                httpretty.register_uri(httpretty.GET, url1,
                                       body=json.dumps(youtube_archive1.DATA),
                                       content_type='application/json')
                self.client.episode_sync()
                episode_list = self.client.episode_list(only_files=False)
                self.assert_length(episode_list, 1)

                self.assertEqual(episode_title, episode_list[0]['title'])

    @httpretty.activate
    def test_episode_sync_and_download_youtube(self):
        with test_utils.temp_podcast(self.client, archive_type='youtube', max_allowed=8) as podcast:
            url1 = urls.youtube_channel_get(podcast['broadcast_id'], self.client.google_api_key)
            with mock.patch('youtube_dl.YoutubeDL', side_effect=test_utils.youtube_mock):
                httpretty.register_uri(httpretty.GET, url1,
                                       body=json.dumps(youtube_archive1.DATA),
                                       content_type='application/json')
                url2 = urls.youtube_channel_get(podcast['broadcast_id'], self.client.google_api_key,
                                                page_token=youtube_archive1.DATA['nextPageToken'])
                httpretty.register_uri(httpretty.GET, url2,
                                       body=json.dumps(youtube_archive2.DATA),
                                       content_type='application/json')
                self.client.episode_sync(max_episode_sync=0)

                episode_list = self.client.episode_list(only_files=False)
                self.assert_length(episode_list, 11)
                test_episode = episode_list[0]
                self.client.episode_download(test_episode['id'], )
                episode = self.client.episode_show(test_episode['id'])[0]
                self.assert_not_none(episode['file_path'])

    @httpretty.activate
    def test_youtube_download_fails(self):
        with test_utils.temp_podcast(self.client, archive_type='youtube', max_allowed=1) as podcast:
            url1 = urls.youtube_channel_get(podcast['broadcast_id'], self.client.google_api_key)
            with mock.patch('youtube_dl.YoutubeDL', side_effect=test_utils.youtube_mock_error):
                httpretty.register_uri(httpretty.GET, url1,
                                       body=json.dumps(youtube_archive1.DATA),
                                       content_type='application/json')
                url2 = urls.youtube_channel_get(podcast['broadcast_id'], self.client.google_api_key,
                                                page_token=youtube_archive1.DATA['nextPageToken'])
                httpretty.register_uri(httpretty.GET, url2,
                                       body=json.dumps(youtube_archive2.DATA),
                                       content_type='application/json')
                self.client.episode_sync(max_episode_sync=0)

                episode_list = self.client.episode_list(only_files=False)
                test_episode = episode_list[0]
                self.client.episode_download(test_episode['id'], )
                episode = self.client.episode_show(test_episode['id'])[0]
                self.assert_none(episode['file_path'])

    @httpretty.activate
    def test_download_youtube_skips_live(self):
        with test_utils.temp_podcast(self.client, archive_type='youtube', max_allowed=1) as podcast:
            url1 = urls.youtube_channel_get(podcast['broadcast_id'], self.client.google_api_key)
            with mock.patch('youtube_dl.YoutubeDL', side_effect=test_utils.youtube_mock_live):
                httpretty.register_uri(httpretty.GET, url1,
                                       body=json.dumps(youtube_archive1.DATA),
                                       content_type='application/json')
                url2 = urls.youtube_channel_get(podcast['broadcast_id'], self.client.google_api_key,
                                                page_token=youtube_archive1.DATA['nextPageToken'])
                httpretty.register_uri(httpretty.GET, url2,
                                       body=json.dumps(youtube_archive2.DATA),
                                       content_type='application/json')
                self.client.episode_sync()

                episode_list = self.client.episode_list(only_files=False)
                test_episode = episode_list[0]
                self.client.episode_download(test_episode['id'], )
                episode = self.client.episode_show(test_episode['id'])[0]
                self.assert_none(episode['file_path'])

    @httpretty.activate
    def test_episode_list_with_sort_date(self):
        with test_utils.temp_podcast(self.client, archive_type='rss', broadcast_url=True) as podcast:
            httpretty.register_uri(httpretty.GET, podcast['broadcast_id'], body=history_on_fire.DATA)

            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False, sort_date=True)
            # assume sql isnt totally borked, just make sure first is ahead of last
            date1 = datetime.strptime(episode_list[0]['date'], test_utils.DATETIME_FORMAT)
            date2 = datetime.strptime(episode_list[-1]['date'], test_utils.DATETIME_FORMAT)
            self.assertTrue(date1 > date2)

    @httpretty.activate
    def test_episode_list_include_podcast_filter(self):
        with test_utils.temp_podcast(self.client, archive_type='rss', broadcast_url=True) as podcast1:
            httpretty.register_uri(httpretty.GET, podcast1['broadcast_id'], body=history_on_fire.DATA)

            with test_utils.temp_podcast(self.client, archive_type='soundcloud', max_allowed=2) as podcast2:
                page1_url = urls.soundcloud_track_list(podcast2['broadcast_id'],
                                                       self.client.soundcloud_client_id)
                httpretty.register_uri(httpretty.GET, page1_url, body=json.dumps(soundcloud_archive_page1.DATA),
                                       content_type='application/json')
                self.client.episode_sync()
                episode_list_all = self.client.episode_list(only_files=False)
                episode_list_inc = self.client.episode_list(only_files=False, include_podcasts=[podcast1['id']])
                self.assertNotEqual(len(episode_list_all), len(episode_list_inc))

                for episode in episode_list_inc:
                    self.assertEqual(episode['podcast_id'], podcast1['id'])

    @httpretty.activate
    def test_episode_list_exclude_podcast_filter(self):
        with test_utils.temp_podcast(self.client, archive_type='rss', broadcast_url=True) as podcast1:
            httpretty.register_uri(httpretty.GET, podcast1['broadcast_id'], body=history_on_fire.DATA)

            with test_utils.temp_podcast(self.client, archive_type='soundcloud', max_allowed=2) as podcast2:
                page1_url = urls.soundcloud_track_list(podcast2['broadcast_id'],
                                                       self.client.soundcloud_client_id)
                httpretty.register_uri(httpretty.GET, page1_url, body=json.dumps(soundcloud_archive_page1.DATA),
                                       content_type='application/json')
                self.client.episode_sync()
                episode_list_all = self.client.episode_list(only_files=False)
                episode_list_exc = self.client.episode_list(only_files=False, exclude_podcasts=[podcast2['id']])
                self.assertNotEqual(len(episode_list_all), len(episode_list_exc))

                for episode in episode_list_exc:
                    self.assertEqual(episode['podcast_id'], podcast1['id'])

    @httpretty.activate
    def test_episode_show(self):
        # check works with valid data
        with test_utils.temp_podcast(self.client, archive_type='rss', broadcast_url=True) as podcast:
            httpretty.register_uri(httpretty.GET, podcast['broadcast_id'], body=history_on_fire.DATA)

            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            self.assert_not_length(episode_list, 0)

            with test_utils.temp_audio_file() as mp3_body:
                test_utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                self.client.episode_download(episode_list[0]['id'], )

            # works as single
            episode = self.client.episode_show(episode_list[0]['id'])[0]
            self.assert_dictionary(episode)
            # works as list
            episode = self.client.episode_show([episode_list[0]['id']])[0]
            self.assert_dictionary(episode)

    @httpretty.activate
    def test_episode_download_curl(self):
        # curl download used for rss and soundcloud
        with test_utils.temp_podcast(self.client, archive_type='rss', broadcast_url=True) as podcast:
            httpretty.register_uri(httpretty.GET, podcast['broadcast_id'], body=history_on_fire.DATA)
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            with test_utils.temp_audio_file() as mp3_body:
                test_utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                self.client.episode_download(episode_list[0]['id'], )
                episode = self.client.episode_show(episode_list[0]['id'])[0]
                self.assert_not_none(episode['file_path'])
                # make sure episode list shows episode with only_files=True
                episode_list = self.client.episode_list()
                self.assert_length(episode_list, 1)

    @httpretty.activate
    def test_episode_download_remove_commercial(self):
        # curl download used for rss and soundcloud
        pod_args = {
            'archive_type' : 'rss',
            'max_allowed' : 1,
            'remove_commercials' : True,
        }
        with test_utils.temp_podcast(self.client, broadcast_url=True, **pod_args) as podcast:
            httpretty.register_uri(httpretty.GET, podcast['broadcast_id'], body=history_on_fire.DATA)
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            with test_utils.temp_audio_file() as mp3_body:
                test_utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                self.client.episode_download(episode_list[0]['id'], )
                episode = self.client.episode_show(episode_list[0]['id'])[0]
                self.assert_not_none(episode['file_path'])
                # make sure episode list shows episode with only_files=True
                episode_list = self.client.episode_list()
                self.assert_length(episode_list, 1)
                self.assert_not_none(episode_list[0]['file_size'])
                self.assertTrue(episode_list[0]['file_size'] > 0)

    @httpretty.activate
    def test_episode_download_remove_commercial_with_picture(self):
        # curl download used for rss and soundcloud
        pod_args = {
            'archive_type' : 'rss',
            'max_allowed' : 1,
            'remove_commercials' : True,
        }
        with test_utils.temp_podcast(self.client, broadcast_url=True, **pod_args) as podcast:
            httpretty.register_uri(httpretty.GET, podcast['broadcast_id'], body=history_on_fire.DATA)
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            with test_utils.temp_audio_file(open_data=False) as mp3_file:
                with test_utils.temp_image_file() as image_file:
                    metadata.picture_update(mp3_file, image_file)
                    with open(mp3_file, 'r') as f:
                        mp3_body = f.read()
                        test_utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                        self.client.episode_download(episode_list[0]['id'], )
                        episode = self.client.episode_show(episode_list[0]['id'])[0]
                        self.assert_not_none(episode['file_path'])
                        # make sure episode list shows episode with only_files=True
                        episode_list = self.client.episode_list()
                        self.assert_length(episode_list, 1)
                        self.assert_not_none(episode_list[0]['file_size'])
                        self.assertTrue(episode_list[0]['file_size'] > 0)

                        # make sure image file is right
                        with utils.temp_file(suffix='.jpg') as temper:
                            metadata.picture_extract(episode_list[0]['file_path'], temper)
                            with open(temper, 'r') as f:
                                with open(image_file, 'r') as ff:
                                    self.assertEqual(f.read(), ff.read())

    @httpretty.activate
    def test_episode_delete(self):
        with test_utils.temp_podcast(self.client, archive_type='rss', broadcast_url=True) as podcast:
            httpretty.register_uri(httpretty.GET, podcast['broadcast_id'], body=history_on_fire.DATA)
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            with test_utils.temp_audio_file() as mp3_body:
                test_utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                self.client.episode_download(episode_list[0]['id'], )
                episode = self.client.episode_show(episode_list[0]['id'])[0]
                self.assert_not_none(episode['file_path'])
                self.client.episode_delete(episode_list[0]['id'])

            # make sure actually deleted
            self.assert_length(self.client.episode_list(), 0)

    @httpretty.activate
    def test_episode_delete_file(self):
        # check works with valid input
        with test_utils.temp_podcast(self.client, archive_type='rss', broadcast_url=True) as podcast:
            httpretty.register_uri(httpretty.GET, podcast['broadcast_id'], body=history_on_fire.DATA)
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            with test_utils.temp_audio_file() as mp3_body:
                test_utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                self.client.episode_download(episode_list[0]['id'], )
                # make sure file exists
                episode = self.client.episode_show(episode_list[0]['id'])[0]
                self.assert_not_none(episode['file_path'])
                # delete episode file, but not episode
                self.client.episode_delete_file(episode_list[0]['id'])
                episode = self.client.episode_show(episode_list[0]['id'])[0]
                self.assert_none(episode['file_path'])
                self.assert_none(episode['file_size'])

    def test_episode_update_fail(self):
        with self.assertRaises(HathorException) as error:
            self.client.episode_update(1)
        self.check_error_message('Podcast Episode not found for ID:1', error)

    @httpretty.activate
    def test_episode_prevent_deletion(self):
        # download only one podcast episode
        with test_utils.temp_podcast(self.client, archive_type='soundcloud', max_allowed=1) as podcast:
            url = urls.soundcloud_track_list(podcast['broadcast_id'],
                                             self.client.soundcloud_client_id)
            httpretty.register_uri(httpretty.GET, url, body=json.dumps(soundcloud_one_track.DATA))
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            with test_utils.temp_audio_file() as mp3_body:
                test_utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                self.client.podcast_file_sync()
                # mark episode to prevent deletion
                self.client.episode_update(episode_list[0]['id'], prevent_delete=True)

                # add an additional, newer podcast, make sure prevented deletion episode stays
                url = urls.soundcloud_track_list(podcast['broadcast_id'],
                                                 self.client.soundcloud_client_id)
                httpretty.register_uri(httpretty.GET, url, body=json.dumps(soundcloud_three_tracks.DATA))
                self.client.episode_sync(max_episode_sync=0)
                episode_list = self.client.episode_list(only_files=False)

                test_utils.mock_mp3_download(episode_list[1]['download_url'], mp3_body)
                test_utils.mock_mp3_download(episode_list[2]['download_url'], mp3_body)
                self.client.podcast_file_sync()

                episode_list = self.client.episode_list()
                ep_ids = [i['id'] for i in episode_list]

                self.assertTrue(2 in ep_ids)
                self.assertTrue(1 in ep_ids)
                self.assertTrue(3 not in ep_ids)

    @httpretty.activate
    def test_podcast_database_cleanup(self):
        # download only one podcast episode
        with test_utils.temp_podcast(self.client, archive_type='soundcloud', max_allowed=1) as podcast:
            url = urls.soundcloud_track_list(podcast['broadcast_id'],
                                             self.client.soundcloud_client_id)
            httpretty.register_uri(httpretty.GET, url, body=json.dumps(soundcloud_two_tracks.DATA))

            self.client.episode_sync(max_episode_sync=0)
            episode_list = self.client.episode_list(only_files=False)
            with test_utils.temp_audio_file() as mp3_body:
                test_utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                self.client.podcast_file_sync()
                episode_list = self.client.episode_list()
                self.assert_not_none(episode_list[0]['file_path'])
                all_episodes = self.client.episode_list(only_files=False)
                self.assertTrue(len(all_episodes) > 1)

                self.client.database_cleanup()
                all_episodes = self.client.episode_list(only_files=False)
                self.assert_length(all_episodes, 1)

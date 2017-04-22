from datetime import datetime
import os
import json

import httpretty

from hathor.exc import HathorException
from hathor.podcast import urls

from tests import utils
from tests.podcasts.data import history_on_fire
from tests.podcasts.data import soundcloud_one_track, soundcloud_one_track_only_page
from tests.podcasts.data import soundcloud_two_tracks

class TestPodcast(utils.TestHelper):
    def run(self, result=None):
        with utils.temp_client() as client_args:
            self.client = client_args.pop('podcast_client') #pylint:disable=attribute-defined-outside-init
            super(TestPodcast, self).run(result)

    def test_podcast_basic_crud(self):
        # test create, list, show, and delete
        with utils.temp_podcast(self.client) as podcast:
            self.assert_dictionary(podcast, skip=['max_allowed', 'artist_name'])
            podcast_list = self.client.podcast_list()
            self.assert_length(podcast_list, 1)

        with self.assertRaises(HathorException) as error:
            self.client.podcast_show(['foo'])
        self.check_error_message('Input must be int type, foo given', error)

        with self.assertRaises(HathorException) as error:
            self.client.podcast_update(podcast['id'] + 1)
        self.check_error_message('Podcast not found for ID:%s' % (podcast['id'] + 1), error)

    def test_podcast_create_with_file_location(self):
        with utils.temp_dir(delete=False) as temp_dir:
            podcast = self.client.podcast_create('rss', '123', 'foo', file_location=temp_dir)
            self.assertEqual(podcast['file_location'], temp_dir)
            self.client.podcast_delete(podcast['id'])

    def test_podcast_multiple_crud(self):
        # check multiple outputs on show and delete
        with utils.temp_podcast(self.client, delete=False) as podcast1:
            with utils.temp_podcast(self.client, delete=False) as podcast2:
                podcasts = self.client.podcast_show([podcast1['id'], podcast2['id']])
                self.assert_length(podcasts, 2)
        self.client.podcast_delete([podcasts[0]['id'], podcasts[1]['id']])
        pod_list = self.client.podcast_list()
        self.assert_length(pod_list, 0)

    def test_podcast_update_archive_type(self):
        with self.assertRaises(HathorException) as error:
            with utils.temp_podcast(self.client, archive_type='foo') as podcast:
                pass
        self.check_error_message('Archive Type must be in accepted list of keys - foo value given', error)
        with utils.temp_podcast(self.client) as podcast:
            self.client.podcast_update(podcast['id'], archive_type='soundcloud')
            with self.assertRaises(HathorException) as error:
                self.client.podcast_update(podcast['id'], archive_type='bar')
            self.check_error_message('Archive Type must be in accepted list - bar value given', error)

    def test_podcast_duplicates(self):
        # make sure duplicate name, or archive type and broadcast id not allowed
        with utils.temp_podcast(self.client) as podcast1:
            with utils.temp_dir() as temp_dir:
                with self.assertRaises(HathorException) as error:
                    self.client.podcast_create(podcast1['archive_type'],
                                               podcast1['broadcast_id'] + '1',
                                               podcast1['name'],
                                               file_location=temp_dir)
                self.check_error_message('Cannot create podcast, name was %s' % podcast1['name'], error)
                with self.assertRaises(HathorException) as error:
                    self.client.podcast_create(podcast1['archive_type'],
                                               podcast1['broadcast_id'],
                                               podcast1['name'] + 's',
                                               file_location=temp_dir)
                self.check_error_message('Cannot create podcast, name was %ss' % podcast1['name'], error)
            # also check updating fails an existing one to one that exists fails
            with utils.temp_podcast(self.client) as podcast2:
                with self.assertRaises(HathorException) as error:
                    self.client.podcast_update(podcast1['id'], podcast_name=podcast2['name'])
                self.check_error_message('Cannot update podcast id:%s' % podcast1['id'], error)
                # also check updating fails an existing one to one that exists fails
                with utils.temp_podcast(self.client) as podcast2:
                    with self.assertRaises(HathorException) as error:
                        self.client.podcast_update(podcast1['id'], podcast_name=podcast2['name'])
                    self.check_error_message('Cannot update podcast id:%s' % podcast1['id'], error)
                    with self.assertRaises(HathorException) as error:
                        self.client.podcast_update(podcast1['id'], broadcast_id=podcast2['broadcast_id'])
                    self.check_error_message('Cannot update podcast id:%s' % podcast1['id'], error)

    def test_podcast_artist_name(self):
        with utils.temp_podcast(self.client, artist_name='foo') as podcast:
            self.assertEqual('foo', podcast['artist_name'])
            self.client.podcast_update(podcast['id'], artist_name='bar')
            podcast = self.client.podcast_show(podcast['id'])
            self.assertEqual('bar', podcast[0]['artist_name'])

    def test_podcast_update_automatic_episode_download(self):
        with utils.temp_podcast(self.client) as podcast:
            self.client.podcast_update(podcast['id'], automatic_download=False)
            pod = self.client.podcast_show(podcast['id'])[0]
            self.assertFalse(pod['automatic_episode_download'])

    def test_podcast_max_allowed_valid_values(self):
        # must be positive int
        with self.assertRaises(HathorException) as error:
            with utils.temp_podcast(self.client, max_allowed=0):
                pass
        self.check_error_message('Max allowed must be positive integer, 0 given', error)

        with utils.temp_podcast(self.client, max_allowed=2) as podcast:
            # make sure negative numbers are invalid
            with self.assertRaises(HathorException) as error:
                self.client.podcast_update(podcast['id'], max_allowed=-1)
            self.check_error_message('Max allowed must be positive integer or 0', error)
            # check update works as expected
            self.client.podcast_update(podcast['id'], max_allowed=0)
            podcast = self.client.podcast_show(podcast['id'])[0]
            self.assertEqual(podcast['max_allowed'], None)

            self.client.podcast_update(podcast['id'], max_allowed=3)
            podcast = self.client.podcast_show(podcast['id'])[0]
            self.assertEqual(podcast['max_allowed'], 3)

    @httpretty.activate
    def test_podcast_location_update(self):
        # check fails with invalid data
        with self.assertRaises(HathorException) as error:
            self.client.podcast_update_file_location(1, 'foo')
        self.check_error_message('Podcast not found for ID:1', error)

        # check works with valid data
        with utils.temp_podcast(self.client, archive_type='rss', broadcast_url=True, max_allowed=2) as podcast:
            httpretty.register_uri(httpretty.GET, podcast['broadcast_id'],
                                   body=history_on_fire.DATA)
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            with utils.temp_audio_file() as mp3_body:
                utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                self.client.episode_download(episode_list[0]['id'])
                old_episode = self.client.episode_show(episode_list[0]['id'])[0]
                with utils.temp_dir(delete=False) as temp:
                    self.client.podcast_update_file_location(podcast['id'], temp)
                    # make sure episode path changed
                    new_episode = self.client.episode_show(episode_list[0]['id'])[0]
                    self.assertTrue(new_episode['file_path'].startswith(temp))
                    self.assertNotEqual(old_episode['file_path'], new_episode['file_path'])
                    # make sure podcast path changed
                    new_podcast = self.client.podcast_show(podcast['id'])[0]
                    self.assertNotEqual(podcast['file_location'], new_podcast['file_location'])

    @httpretty.activate
    def test_podcast_sync_no_max_allowed(self):
        # make sure no max allowed downloads all possible podcasts
        with utils.temp_podcast(self.client, archive_type='soundcloud', max_allowed=None) as podcast:
            url = urls.soundcloud_track_list(podcast['broadcast_id'],
                                             self.client.soundcloud_client_id)
            httpretty.register_uri(httpretty.GET, url, body=json.dumps(soundcloud_one_track_only_page.DATA))
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            with utils.temp_audio_file() as mp3_body:
                utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                self.client.podcast_sync()
                episode_list = self.client.episode_list()
                self.assert_length(episode_list, 1)
                self.assert_not_none(episode_list[0]['file_path'])

    @httpretty.activate
    def test_podcast_sync_no_automatic_episode_download(self):
        # make sure no max allowed downloads all possible podcasts
        with utils.temp_podcast(self.client, archive_type='soundcloud', max_allowed=None, automatic_download=False) as podcast:
            url = urls.soundcloud_track_list(podcast['broadcast_id'],
                                             self.client.soundcloud_client_id)
            httpretty.register_uri(httpretty.GET, url, body=json.dumps(soundcloud_one_track_only_page.DATA))
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            with utils.temp_audio_file() as mp3_body:
                utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                self.client.podcast_sync()
                episode_list = self.client.episode_list()
                self.assert_length(episode_list, 0)

    @httpretty.activate
    def test_podcast_sync(self):
        # download only one podcast episode
        with utils.temp_podcast(self.client, archive_type='soundcloud', max_allowed=1) as podcast:
            url = urls.soundcloud_track_list(podcast['broadcast_id'],
                                             self.client.soundcloud_client_id)
            httpretty.register_uri(httpretty.GET, url, body=json.dumps(soundcloud_one_track.DATA))
            self.client.episode_sync()

            episode_list = self.client.episode_list(only_files=False)
            with utils.temp_audio_file() as mp3_body:
                utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                self.client.podcast_sync()
                episode_list = self.client.episode_list()
                self.assert_not_none(episode_list[0]['file_path'])
                first_episode_date = episode_list[0]['date']
                # add an additional, newer podcast, make sure things are deleted
                url = urls.soundcloud_track_list(podcast['broadcast_id'],
                                                 self.client.soundcloud_client_id)
                httpretty.register_uri(httpretty.GET, url, body=json.dumps(soundcloud_two_tracks.DATA))
                self.client.episode_sync()
                episode_list = self.client.episode_list(only_files=False)
                with utils.temp_audio_file() as mp3_body:
                    utils.mock_mp3_download(episode_list[1]['download_url'], mp3_body)
                    self.client.podcast_sync()

                    # make sure 2 episodes in db, but only 1 with a file path
                    episode_list = self.client.episode_list()
                    self.assert_not_none(episode_list[0]['file_path'])
                    all_episodes = self.client.episode_list(only_files=False)
                    self.assertNotEqual(len(episode_list), len(all_episodes))
                    second_episode_date = episode_list[0]['date']

                    self.assertTrue(datetime.strptime(second_episode_date, self.client.datetime_output_format) >
                                    datetime.strptime(first_episode_date, self.client.datetime_output_format))

    @httpretty.activate
    def test_podcast_sync_include(self):
        # create two podcasts, then run a podcast sync that only includes one
        # make sure any episodes created point back to that pod
        with utils.temp_podcast(self.client, archive_type='soundcloud', max_allowed=1) as podcast:
            url = urls.soundcloud_track_list(podcast['broadcast_id'],
                                             self.client.soundcloud_client_id)
            httpretty.register_uri(httpretty.GET, url, body=json.dumps(soundcloud_one_track.DATA))
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            with utils.temp_audio_file() as mp3_body:
                utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                with utils.temp_podcast(self.client):
                    self.client.podcast_sync(include_podcasts=[podcast['id']], )
                    episode_list = self.client.episode_list()
                    self.assertTrue(len(episode_list) > 0)
                    for episode in episode_list:
                        self.assertEqual(podcast['id'], episode['podcast_id'])

    @httpretty.activate
    def test_podcast_sync_exclude(self):
        # create two podcasts, exclude one, make sure only that pod was updated
        with utils.temp_podcast(self.client, archive_type='soundcloud', max_allowed=1) as podcast1:
            url = urls.soundcloud_track_list(podcast1['broadcast_id'],
                                             self.client.soundcloud_client_id)
            httpretty.register_uri(httpretty.GET, url, body=json.dumps(soundcloud_one_track.DATA))
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            with utils.temp_audio_file() as mp3_body:
                utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                with utils.temp_podcast(self.client) as podcast2:
                    self.client.podcast_sync(exclude_podcasts=[podcast2['id']], )
                    episode_list = self.client.episode_list()
                    self.assertTrue(len(episode_list) > 0)
                    for episode in episode_list:
                        self.assertEqual(podcast1['id'], episode['podcast_id'])

    @httpretty.activate
    def test_podcast_dont_delete_episode_files(self):
        with utils.temp_podcast(self.client, archive_type='soundcloud', max_allowed=1) as podcast:
            url = urls.soundcloud_track_list(podcast['broadcast_id'],
                                             self.client.soundcloud_client_id)
            httpretty.register_uri(httpretty.GET, url, body=json.dumps(soundcloud_one_track.DATA))
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            with utils.temp_audio_file() as mp3_body:
                utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                self.client.podcast_sync()
                episode_list = self.client.episode_list()
                # delete and make sure file is still there
                self.client.podcast_delete(podcast['id'], delete_files=False)
                self.assertTrue(len(os.listdir(podcast['file_location'])) > 0)
                os.remove(episode_list[0]['file_path'])
                os.rmdir(podcast['file_location'])

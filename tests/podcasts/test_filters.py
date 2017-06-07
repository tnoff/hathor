import json

import httpretty

from hathor.exc import HathorException
from hathor.podcast import urls
from hathor import utils as common_utils

from tests import utils
from tests.podcasts.data import rss_feed
from tests.podcasts.data import soundcloud_two_tracks

class TestPodcastFilters(utils.TestHelper): #pylint:disable=too-many-public-methods
    def run(self, result=None):
        with utils.temp_client() as client_args:
            self.client = client_args.pop('podcast_client') #pylint:disable=attribute-defined-outside-init
            super(TestPodcastFilters, self).run(result)

    def test_filter_crud(self):
        with utils.temp_podcast(self.client, max_allowed=1) as podcast:
            regex = common_utils.random_string()
            result = self.client.filter_create(podcast['id'], regex)
            filters = self.client.filter_list()
            self.assertEqual(filters, [{'id' : result['id'], 'podcast_id' : podcast['id'], 'regex_string' : regex}])
            self.client.filter_delete(result['id'])
            self.assert_length(self.client.filter_list(), 0)

    def test_filter_deleted_with_podcast(self):
        with utils.temp_podcast(self.client, max_allowed=1) as podcast:
            regex = common_utils.random_string()
            result = self.client.filter_create(podcast['id'], regex)
        filter_list = self.client.filter_list()
        self.assertFalse(result in [i['id'] for i in filter_list])

    def test_filter_bad_podcast_id(self):
        regex = common_utils.random_string()
        with self.assertRaises(HathorException) as error:
            self.client.filter_create(1, regex)
        self.check_error_message('Unable to find podcast with id:1', error)

    def test_filter_list_cluders(self):
        with utils.temp_podcast(self.client, archive_type='rss', max_allowed=1) as podcast1:
            with utils.temp_podcast(self.client, max_allowed=1) as podcast2:
                regex = common_utils.random_string()
                result1 = self.client.filter_create(podcast1['id'], regex)
                result2 = self.client.filter_create(podcast2['id'], regex)

                include_pod1 = self.client.filter_list(include_podcasts=[podcast1['id']])
                self.assert_length(include_pod1, 1)
                self.assertEqual([result1], [i for i in include_pod1])

                exclude_pod1 = self.client.filter_list(exclude_podcasts=[podcast1['id']])
                self.assert_length(exclude_pod1, 1)
                self.assertEqual([result2], [i for i in exclude_pod1])

    @httpretty.activate
    def test_filters_with_broadcast_update(self):
        two_track_data = soundcloud_two_tracks.DATA
        first_title = two_track_data['collection'][0]['title']
        regex1 = '^%s' % first_title

        with utils.temp_podcast(self.client, archive_type='soundcloud', max_allowed=3) as podcast:
            self.client.filter_create(podcast['id'], regex1)

            url = urls.soundcloud_track_list(podcast['broadcast_id'],
                                             self.client.soundcloud_client_id)
            httpretty.register_uri(httpretty.GET, url, body=json.dumps(two_track_data))
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            self.assert_length(episode_list, 1)

    @httpretty.activate
    def test_filters_with_broadcast_update_rss(self):
        regex1 = '^EPISODE 5'
        broadcast_url = 'http://%s.com' % common_utils.random_string()
        with utils.temp_podcast(self.client, archive_type='rss', broadcast_id=broadcast_url,
                                max_allowed=3) as podcast:
            self.client.filter_create(podcast['id'], regex1)
            httpretty.register_uri(httpretty.GET, broadcast_url, body=rss_feed.DATA)
            self.client.episode_sync()
            episode_list = self.client.episode_list(only_files=False)
            self.assert_length(episode_list, 1)

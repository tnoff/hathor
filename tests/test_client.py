import os
import logging
from tempfile import TemporaryDirectory

from mock import patch
import pytest

from hathor.client import HathorClient
from hathor.exc import HathorException
from hathor.database.tables import PodcastEpisode
from hathor import utils
from tests import utils as test_utils
from tests.podcasts.data import rss_feed

def mock_plugin(self, result, *args, **kwargs):
    episode = self.db_session.query(PodcastEpisode).get(result[0]['id'])
    episode.description = "foo-description"
    self.db_session.commit()
    return result


def test_plugins():
    client = HathorClient()
    client.plugins = ([('episode_download', mock_plugin)])
    with TemporaryDirectory() as tmp_dir:
        client.podcast_create('rss', 'https://example.foo', 'temp', file_location=tmp_dir)
        client.episode_sync()


'''
class TestClient(test_utils.TestHelper):
    @httpretty.activate
    def test_plugins_loaded(self):
        def mock_plugin(self, result):
            episode = self.db_session.query(PodcastEpisode).get(result[0]['id'])
            episode.description = "foo-description"
            self.db_session.commit()
            return result

        with test_utils.temp_client() as client_args:
            client = client_args.pop('podcast_client')
            client.plugins = [('episode_download', mock_plugin)]
            with test_utils.temp_podcast(client, archive_type='rss', broadcast_url=True) as podcast:
                httpretty.register_uri(httpretty.GET, podcast['broadcast_id'], body=rss_feed.DATA)

                client.episode_sync()
                episode_list = client.episode_list(only_files=False)
                self.assert_not_length(episode_list, 0)

                with test_utils.temp_audio_file() as mp3_body:
                    test_utils.mock_mp3_download(episode_list[0]['download_url'], mp3_body)
                    client.episode_download(episode_list[0]['id'], )
                episode = client.episode_show(episode_list[0]['id'])[0]
                self.assertEqual(episode['description'], 'foo-description')

    def test_database_file(self):
        with utils.temp_file() as temp_file:
            with test_utils.temp_client(database_file=temp_file) as client_args:
                client = client_args.pop('podcast_client')
                self.assert_not_none(client.podcast_list())

    def test_no_api_tokens_warning(self):
        commands = []
        def mock_logging(*_, **__):
            return MockLogging(commands)

        with mock.patch('hathor.client.setup_logger', side_effect=mock_logging):
            with test_utils.temp_client(google_api_key=False):
                pass
        self.assertTrue('No google api key given, will not be to able to access google api' in commands)

    def test_logger_file(self):
        with utils.temp_file() as log_file:
            with test_utils.temp_client(log_file=log_file):
                with open(log_file, 'r') as file_read:
                    data = file_read.read()
                    self.assertTrue(len(data) > 0)

    def test_delete_dir(self):
        with test_utils.temp_client(logging_level=logging.WARNING) as client_args:
            client = client_args.pop('podcast_client')
            with test_utils.temp_dir() as temp_dir:
                client._remove_directory(temp_dir) #pylint:disable=protected-access
                self.assertFalse(os.path.isdir(temp_dir))

    def test_delete_dir_not_exists(self):
        with test_utils.temp_client(logging_level=logging.WARNING) as client_args:
            client = client_args.pop('podcast_client')
            random_name = utils.random_string(prefix='/tmp/')
            self.assertFalse(os.path.isdir(random_name))
            client._remove_directory(random_name) #pylint:disable=protected-access
            self.assertFalse(os.path.isdir(random_name))

    def test_delete_file(self):
        with test_utils.temp_client(logging_level=logging.WARNING) as client_args:
            client = client_args.pop('podcast_client')
            with utils.temp_file() as temp_file:
                client._remove_file(temp_file) #pylint:disable=protected-access
                self.assertFalse(os.path.isfile(temp_file))

    def test_delete_file_not_exists(self):
        with test_utils.temp_client(logging_level=logging.WARNING) as client_args:
            client = client_args.pop('podcast_client')
            random_name = utils.random_string(prefix='/tmp/')
            self.assertFalse(os.path.isfile(random_name))
            client._remove_file(random_name) #pylint:disable=protected-access
            self.assertFalse(os.path.isfile(random_name))

    def test_podcast_dir_given(self):
        with test_utils.temp_dir(delete=False) as dir_temp:
            with test_utils.temp_client(podcast_directory=dir_temp) as client_args:
                client = client_args.pop('podcast_client')
                podcast = client.podcast_create('rss', '1234', utils.random_string())
                self.assertTrue(podcast['file_location'].startswith(dir_temp))
                os.rmdir(podcast['file_location'])
                client.podcast_delete(podcast['id'])
'''
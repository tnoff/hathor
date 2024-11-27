from datetime import datetime
import os
import logging
from tempfile import TemporaryDirectory
from time import time

from mock import patch
from pathlib import Path
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


def test_plugins(mocker):
    client = HathorClient()
    client.plugins = ([('episode_download', mock_plugin)])
    with TemporaryDirectory() as tmp_dir:
        parse_mock = mocker.patch('hathor.podcast.archive.parse')
        parse_mock.return_value = {
            'feed': {
                'link': 'https://example.foo'
            },
            'entries': [
                {
                    'link': 'https://example.foo/download1',
                    'title': 'Episode 0',
                    'published_parsed': time(),
                },
            ]
        }
        client.podcast_create('rss', 'https://example.foo', 'temp', file_location=tmp_dir)
        client.episode_sync()
        episode_list = client.episode_list(only_files=False)
        with test_utils.temp_audio_file() as temp_audio_file:
            curl_mock = mocker.patch('hathor.podcast.archive.curl_download')
            curl_mock.return_value = (Path(temp_audio_file), 1)
            client.episode_download([episode_list[0]['id']])
        episode_list = client.episode_list()
        assert episode_list[0]['description'] == 'foo-description'
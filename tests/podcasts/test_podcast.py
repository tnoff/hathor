from datetime import datetime
import os
import json
from tempfile import TemporaryDirectory

import pytest

from hathor.client import HathorClient
from hathor.exc import HathorException

from tests import utils
from tests.podcasts.data import rss_feed

def test_podcast_create():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)
        client.podcast_create('rss', 'foo1234', 'temp pod name')
        podcast_list = client.podcast_list()
        assert len(podcast_list) == 1
        assert podcast_list[0]['name'] == 'temp pod name'

def test_podcast_create_invalid_max_allowed():
    client = HathorClient()
    with pytest.raises(HathorException) as error:
        client.podcast_create('rss', 'foo1234', 'temp pod name', max_allowed=0)
    assert 'Max allowed must be positive integer' in str(error.value)

def test_podcast_create_with_no_file_location():
    client = HathorClient()
    with pytest.raises(HathorException) as error:
        client.podcast_create('rss', 'foo1234', 'temp pod name')
    assert 'No default podcast directory specified' in str(error.value)

def test_podcast_create_with_specific_file_location():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient()
        client.podcast_create('rss', 'foo1234', 'temp pod name', file_location=tmp_dir)
        podcast_list = client.podcast_list()
        assert len(podcast_list) == 1
        assert podcast_list[0]['name'] == 'temp pod name'    

def test_podcast_show():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)
        client.podcast_create('rss', 'foo1234', 'temp pod name')
        podcast_list = client.podcast_list()
        pod_info = client.podcast_show(podcast_list[0]['id'])
        assert 'temp_pod_name' in pod_info[0]['file_location']

def test_podcast_show_no_input():
    client = HathorClient()
    podcast_list = client.podcast_show([])
    assert len(podcast_list) == 0

def test_podcast_update_non_existing():
    client = HathorClient()
    with pytest.raises(HathorException) as error:
        client.podcast_update(1)
    assert 'Podcast not found' in str(error.value)

def test_podcast_update():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)
        client.podcast_create('rss', 'foo1234', 'temp pod name')
        podcast_list = client.podcast_list()
        client.podcast_update(podcast_list[0]['id'],
                              podcast_name='test',
                              broadcast_id='bar1234',
                              archive_type='youtube',
                              max_allowed=5,
                              artist_name='foobar1234',
                              automatic_download=False)

def test_podcast_update_invalid_max_download():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)
        client.podcast_create('rss', 'foo1234', 'temp pod name')
        podcast_list = client.podcast_list()
        with pytest.raises(HathorException) as error:
            client.podcast_update(podcast_list[0]['id'],
                                max_allowed=-1)
        assert 'Max allowed must be positive integer or 0' in str(error.value)

def test_podcast_update_max_allowed_zero():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)
        client.podcast_create('rss', 'foo1234', 'temp pod name')
        podcast_list = client.podcast_list()
        client.podcast_update(podcast_list[0]['id'],
                              max_allowed=0)
        podcast_list = client.podcast_list()
        assert podcast_list[0]['max_allowed'] == None
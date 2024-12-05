from tempfile import TemporaryDirectory

import pytest

from hathor.client import HathorClient
from hathor.exc import HathorException

def test_filter_create():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)
        podcast = client.podcast_create('rss', '1234', 'foo')
        client.filter_create(podcast['id'], '1234')

        filter_list = client.filter_list()
        assert filter_list[0]['regex_string'] == '1234'

def test_filter_create_no_podcast():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)
        with pytest.raises(HathorException) as error:
            client.filter_create(1, '1234')
        assert 'Unable to find podcast with id' in str(error.value)

def test_filter_list_includes():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)
        podcast1 = client.podcast_create('rss', '1234', 'foo')
        podcast2 = client.podcast_create('rss', '12314414', 'bar')
        client.filter_create(podcast1['id'], '1234')
        client.filter_create(podcast2['id'], 'foo')

        filter_list = client.filter_list(include_podcasts=[podcast1['id']])
        assert len(filter_list) == 1
        assert filter_list[0]['regex_string'] == '1234'

        filter_list = client.filter_list(exclude_podcasts=[podcast1['id']])
        assert len(filter_list) == 1
        assert filter_list[0]['regex_string'] == 'foo'

def test_filter_delete():
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)
        podcast = client.podcast_create('rss', '1234', 'foo')
        client.filter_create(podcast['id'], '1234')

        filter_list = client.filter_list()
        client.filter_delete([filter_list[0]['id']])

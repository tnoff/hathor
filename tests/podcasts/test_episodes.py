from datetime import datetime

from tempfile import TemporaryDirectory

from hathor.client import HathorClient
from hathor.podcast.archive import RSSManager

mock_episode_data = [
    {
        'download_link': 'https://foo.com/example1',
        'title': 'Episode 0',
        'date': datetime.now(),
        'description': 'Episode 0 description',
    },
    {
        'download_link': 'https://foo.com/example2',
        'title': 'Episode 1',
        'date': datetime.now(),
        'description': 'Episode 1 description',
    },
]

def test_episode_sync(mocker):
    with TemporaryDirectory() as tmp_dir:
        client = HathorClient(podcast_directory=tmp_dir)

        new_pod = client.podcast_create('rss', '1234', 'foo')
        mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
        client.episode_sync(include_podcasts=[new_pod['id']])

        episode_list = client.episode_list(only_files=False)
        assert len(episode_list) == 2

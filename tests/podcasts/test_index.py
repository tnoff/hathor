from datetime import datetime
from json import loads
from pathlib import Path

import pytest

from hathor.client import HathorClient
from hathor.database.tables import Podcast, PodcastEpisode
from hathor.exc import HathorException

def add_podcast(client, name):
    podcast = Podcast(name=name, archive_type='rss', broadcast_id=name)
    client.db_session.add(podcast)
    client.db_session.commit()
    return podcast

def add_episode(client, podcast, title, path, date=datetime(2024, 12, 7), content=b'abc'):
    if path is not None and content is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(content)
    episode = PodcastEpisode(download_url=f'https://foo.com/{podcast.name}/{title}', title=title, date=date,
                             podcast_id=podcast.id, file_path=str(path) if path else None)
    client.db_session.add(episode)
    client.db_session.commit()
    return episode

@pytest.fixture(name='library')
def library_fixture(tmp_path):
    root = tmp_path / 'library'
    root.mkdir()
    return root

def test_index_groups_and_orders(library, tmp_path):
    client = HathorClient(podcast_directory=library, index_file=tmp_path / 'index.json')
    zed = add_podcast(client, 'Zed')
    alpha = add_podcast(client, 'Alpha')
    add_episode(client, zed, 'Only', library / 'zed' / 'only.mp3')
    old = add_episode(client, alpha, 'Old', library / 'alpha' / 'old.mp3', date=datetime(2024, 12, 1), content=b'12345')
    new = add_episode(client, alpha, 'New/Title', library / 'alpha' / 'new.MP4', date=datetime(2024, 12, 8))
    # No file at all, and no podcast with files
    add_episode(client, alpha, 'Not downloaded', None)
    add_podcast(client, 'Empty')

    index = client.episode_index(dry_run=True)
    assert [p['name'] for p in index['podcasts']] == ['Alpha', 'Zed']
    assert index['generated_at'].endswith('+00:00')
    alpha_episodes = index['podcasts'][0]['episodes']
    # Newest first
    assert [e['id'] for e in alpha_episodes] == [new.id, old.id]
    assert alpha_episodes[0] == {
        'id': new.id, 'title': 'New/Title', 'date': '2024-12-08', 'size': 3, 'content_type': 'video/mp4',
        'filename': 'Alpha - 2024-12-08 - NewTitle.mp4', 'path': 'alpha/new.MP4',
    }
    assert alpha_episodes[1]['size'] == 5
    assert alpha_episodes[1]['content_type'] == 'audio/mpeg'
    assert not (tmp_path / 'index.json').exists()

def test_index_write(library, tmp_path):
    index_file = tmp_path / 'out' / 'index.json'
    index_file.parent.mkdir()
    client = HathorClient(podcast_directory=library, index_file=index_file)
    podcast = add_podcast(client, 'Pod')
    add_episode(client, podcast, 'One', library / 'pod' / 'one.mp3')
    add_episode(client, podcast, 'Two', library / 'pod' / 'two.mp3')

    summary = client.episode_index()
    assert summary == {'index_file': str(index_file), 'podcasts': 1, 'episodes': 2}
    written = loads(index_file.read_text(encoding='utf-8'))
    assert len(written['podcasts'][0]['episodes']) == 2
    # No temp files left next to it
    assert [p.name for p in index_file.parent.iterdir()] == ['index.json']

    # Running again replaces it
    client.episode_delete([1])
    assert client.episode_index()['episodes'] == 1
    assert len(loads(index_file.read_text(encoding='utf-8'))['podcasts'][0]['episodes']) == 1

def test_index_skips_missing_and_outside_files(library, tmp_path, caplog):
    client = HathorClient(podcast_directory=library, index_file=tmp_path / 'index.json')
    podcast = add_podcast(client, 'Pod')
    add_episode(client, podcast, 'Good', library / 'pod' / 'good.mp3')
    add_episode(client, podcast, 'Gone', library / 'pod' / 'gone.mp3', content=None)
    add_episode(client, podcast, 'Elsewhere', tmp_path / 'elsewhere' / 'x.mp3')

    index = client.episode_index(dry_run=True)
    assert [e['title'] for e in index['podcasts'][0]['episodes']] == ['Good']
    assert 'file missing on disk' in caplog.text
    assert 'outside the podcast directory' in caplog.text

def test_index_follows_symlinked_library(library, tmp_path):
    link = tmp_path / 'link'
    link.symlink_to(library)
    client = HathorClient(podcast_directory=link)
    podcast = add_podcast(client, 'Pod')
    add_episode(client, podcast, 'One', link / 'pod' / 'one.mp3')
    assert client.episode_index(dry_run=True)['podcasts'][0]['episodes'][0]['path'] == 'pod/one.mp3'

def test_index_episode_without_date(library):
    client = HathorClient(podcast_directory=library)
    podcast = add_podcast(client, 'Pod')
    add_episode(client, podcast, 'One', library / 'pod' / 'one.mp3', date=None)
    episode = client.episode_index(dry_run=True)['podcasts'][0]['episodes'][0]
    assert episode['date'] is None
    assert episode['filename'] == 'Pod - One.mp3'

def test_index_requires_podcast_directory():
    with pytest.raises(HathorException, match='No podcast_directory'):
        HathorClient().episode_index(dry_run=True)

def test_index_requires_index_file_unless_dry_run(library):
    client = HathorClient(podcast_directory=library)
    with pytest.raises(HathorException, match='No index_file'):
        client.episode_index()
    assert client.episode_index(dry_run=True)['podcasts'] == []

import json
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner
from yaml import dump

from hathor.cli import cli
from hathor.client import HathorClient
from hathor.exc import HathorException, SyncFailure
from hathor.podcast.archive import RSSManager
from hathor import utils

from tests.utils import temp_audio_file

def feed(n, day=1):
    return {'download_link': f'https://foo.com/ep{n}', 'title': f'Episode {n}',
            'date': datetime(2024, 12, day), 'description': f'Episode {n} description'}

class World:
    '''Three rss podcasts whose feeds can each be made to fail'''
    def __init__(self, tmp_path):
        self.client = HathorClient(podcast_directory=tmp_path)
        self.pods = [self.client.podcast_create('rss', f'https://feed{i}.example/rss', f'Pod {i}') for i in (1, 2, 3)]
        self.failing = {}   # broadcast_id -> exception to raise
        self.episodes = {i: [feed(i * 10 + 1)] for i in (1, 2, 3)}

    def broadcast_update(self, broadcast_id, **_):
        if broadcast_id in self.failing:
            raise self.failing[broadcast_id]
        number = int(broadcast_id.split('feed')[1][0])
        return self.episodes[number]

@pytest.fixture(name='world')
def world_fixture(tmp_path, mocker):
    w = World(tmp_path)
    mocker.patch.object(RSSManager, 'broadcast_update', side_effect=w.broadcast_update)
    return w

def titles(client, podcast_id):
    return [e['title'] for e in client.episode_list(only_files=False, include_podcasts=[podcast_id])]

def test_one_bad_feed_does_not_stop_the_others_but_is_reported(world):
    world.failing['https://feed2.example/rss'] = HathorException(
        'Invalid data from rss feed https://feed2.example/rss?auth=TOPSECRET&x=1')
    with pytest.raises(SyncFailure) as caught:
        world.client.podcast_sync(download_episodes=False)
    # the healthy podcasts still synced
    assert titles(world.client, 1) == ['Episode 11']
    assert titles(world.client, 2) == []
    assert titles(world.client, 3) == ['Episode 31']
    [failure] = caught.value.failures
    assert (failure['stage'], failure['podcast_id'], failure['podcast_name'], failure['episode_id']) == \
        ('episode sync', 2, 'Pod 2', None)
    assert 'HathorException: Invalid data from rss feed https://feed2.example/rss' in failure['error']

def test_urls_are_scrubbed_in_the_error_and_the_log(world, caplog):
    world.failing['https://feed2.example/rss'] = HathorException(
        'Invalid data from rss feed https://feed2.example/rss?auth=TOPSECRET#frag')
    with pytest.raises(SyncFailure) as caught:
        world.client.podcast_sync(download_episodes=False)
    assert 'TOPSECRET' not in str(caught.value)
    assert 'TOPSECRET' not in caplog.text
    assert 'episode sync failed for podcast 2 (Pod 2)' in caplog.text

def test_episode_sync_raises_at_the_end_with_the_new_episodes(world):
    world.failing['https://feed1.example/rss'] = RuntimeError('boom')
    with pytest.raises(SyncFailure) as caught:
        world.client.episode_sync()
    assert sorted(e['title'] for e in caught.value.results) == ['Episode 21', 'Episode 31']
    assert [f['podcast_id'] for f in caught.value.failures] == [1]

def test_plugin_hooks_still_run_for_the_podcasts_that_synced(world):
    seen = []
    def hook(self, results, *args, **kwargs): #pylint:disable=unused-argument
        seen.append(sorted(e['title'] for e in results))
        return results
    world.client.plugins = [('__episode_sync_cluders', hook)]
    world.failing['https://feed2.example/rss'] = RuntimeError('boom')
    with pytest.raises(SyncFailure):
        world.client.podcast_sync(download_episodes=False)
    assert seen == [['Episode 11', 'Episode 31']]

def test_a_failure_that_leaves_the_session_unusable_does_not_break_later_podcasts(world):
    # A date that cannot be stored fails at commit and leaves the session needing a rollback;
    # without one, every podcast after it would fail too.
    world.episodes[1] = [{**feed(11), 'date': 'not a datetime'}]
    with pytest.raises(SyncFailure) as caught:
        world.client.podcast_sync(download_episodes=False)
    assert [f['podcast_id'] for f in caught.value.failures] == [1]
    assert titles(world.client, 2) == ['Episode 21']
    assert titles(world.client, 3) == ['Episode 31']

def test_every_failure_is_reported_not_just_the_first(world):
    for i in (1, 3):
        world.failing[f'https://feed{i}.example/rss'] = RuntimeError(f'boom {i}')
    with pytest.raises(SyncFailure) as caught:
        world.client.podcast_sync(download_episodes=False)
    assert [f['podcast_id'] for f in caught.value.failures] == [1, 3]
    assert 'boom 1' in str(caught.value) and 'boom 3' in str(caught.value)
    assert titles(world.client, 2) == ['Episode 21']

def test_success_is_unchanged(world):
    assert world.client.podcast_sync(download_episodes=False) is True
    assert len(world.client.episode_sync()) == 0      # nothing new the second time

def test_downloads_continue_after_a_failed_download(world, mocker):
    world.client.podcast_sync(download_episodes=False)
    calls = []
    def download(_url, prefix):
        calls.append(prefix.name)
        if len(calls) == 1:
            raise OSError('disk on fire')
        with temp_audio_file() as audio:
            target = Path(f'{prefix}.mp3')
            target.write_bytes(Path(audio).read_bytes())
            return target, target.stat().st_size
    mocker.patch.object(RSSManager, 'episode_download', side_effect=download)
    with pytest.raises(SyncFailure) as caught:
        world.client.podcast_sync(sync_web_episodes=False)
    assert len(calls) == 3                              # all three were attempted
    [failure] = caught.value.failures
    assert failure['stage'] == 'download' and failure['episode_id'] is not None
    assert 'OSError: disk on fire' in failure['error']
    assert len(world.client.episode_list(only_files=True)) == 2   # the other two are recorded

def test_downloads_still_happen_when_a_podcast_failed_to_sync(world, mocker):
    world.client.podcast_sync(download_episodes=False)       # episodes exist, none downloaded
    world.failing['https://feed1.example/rss'] = RuntimeError('boom')
    def download(_url, prefix):
        with temp_audio_file() as audio:
            target = Path(f'{prefix}.mp3')
            target.write_bytes(Path(audio).read_bytes())
            return target, target.stat().st_size
    mocker.patch.object(RSSManager, 'episode_download', side_effect=download)
    with pytest.raises(SyncFailure) as caught:
        world.client.podcast_sync()
    assert [f['stage'] for f in caught.value.failures] == ['episode sync']
    assert len(world.client.episode_list(only_files=True)) == 3

def test_explicit_episode_download_reports_failures_with_the_successes(world, mocker):
    world.client.podcast_sync(download_episodes=False)
    ids = [e['id'] for e in world.client.episode_list(only_files=False)]
    def download(url, prefix):
        if url.endswith('ep11'):
            raise RuntimeError('nope')
        with temp_audio_file() as audio:
            target = Path(f'{prefix}.mp3')
            target.write_bytes(Path(audio).read_bytes())
            return target, target.stat().st_size
    mocker.patch.object(RSSManager, 'episode_download', side_effect=download)
    with pytest.raises(SyncFailure) as caught:
        world.client.episode_download(ids)
    assert len(caught.value.results) == 2
    assert len(caught.value.failures) == 1

def test_without_a_failure_list_the_error_is_raised_where_it_happened(world):
    with pytest.raises(RuntimeError, match='raw'):
        try:
            raise RuntimeError('raw')
        except RuntimeError as error:
            world.client._record_failure(None, 'x', 1, 'Pod', error) #pylint:disable=protected-access

def test_cli_exits_nonzero_and_still_syncs_the_rest(tmp_path, mocker):
    def broadcast(broadcast_id, **_):
        if 'feed2' in broadcast_id:
            raise HathorException('Invalid data from rss feed')
        return [feed(int(broadcast_id.split('feed')[1][0]) * 10 + 1)]   # a distinct url per feed
    mocker.patch.object(RSSManager, 'broadcast_update', side_effect=broadcast)
    db = tmp_path / 'db.sql'
    config = tmp_path / 'config.yml'
    config.write_text(dump({'hathor': {'database_connection_string': f'sqlite:///{db}', 'podcast_directory': str(tmp_path / 'p')}}),
                      encoding='utf-8')
    runner = CliRunner()
    for i in (1, 2, 3):
        runner.invoke(cli, ['-c', str(config), 'podcast', 'create', 'rss', f'https://feed{i}.example/rss', f'Pod {i}'])
    result = runner.invoke(cli, ['-c', str(config), 'podcast', 'sync', '--no-download-episodes'])
    assert result.exit_code == 1
    assert isinstance(result.exception, SyncFailure)
    assert 'podcast 2 (Pod 2)' in str(result.exception)
    listing = runner.invoke(cli, ['-c', str(config), '--json', 'episode', 'list'])
    assert sorted({e['podcast_id'] for e in json.loads(listing.output)}) == [1, 3]

def test_sync_failure_message_is_capped():
    failures = [{'stage': 'episode sync', 'podcast_id': i, 'podcast_name': f'P{i}', 'episode_id': None,
                 'error': 'X'} for i in range(14)]
    error = SyncFailure(failures, results=['a'])
    assert str(error).startswith('14 failure(s) during sync:')
    assert 'podcast 9 (P9)' in str(error) and 'podcast 10 (P10)' not in str(error)
    assert '... and 4 more' in str(error)
    assert error.failures == failures and error.results == ['a']
    assert SyncFailure(failures[:1]).results == []
    assert 'episode 7' in str(SyncFailure([{**failures[0], 'episode_id': 7}]))

@pytest.mark.parametrize('before,after', [
    ('failed https://a.example/f?auth=SECRET&x=1', 'failed https://a.example/f'),
    ('see https://a.example/f#frag and https://b.example/g?k=v end', 'see https://a.example/f and https://b.example/g end'),
    ('Invalid https://feeds.example/zach|10|/media/x?auth=S', 'Invalid https://feeds.example/zach|10|/media/x'),
    ('no url here', 'no url here'),
    ('https://plain.example/path', 'https://plain.example/path'),
])
def test_scrub_error(before, after):
    assert utils.scrub_error(before) == after

import gc
from json import loads
import sys

from click.testing import CliRunner
import pytest
from yaml import dump

from hathor.cli import cli, hide_feed_secrets
from hathor.client import HathorClient
from hathor.exc import HathorException
from hathor.utils import mask_url_secrets

SECRET = 'SECRETKEY123'
FEED = f'https://www.patreon.com/rss/some-show?auth={SECRET}&show=1'

# ------------------------------------------------------------------ the helper

@pytest.mark.parametrize('value, expected', [
    (FEED, 'https://www.patreon.com/rss/some-show?<hidden>'),
    ('https://feeds.example.com/show.xml', 'https://feeds.example.com/show.xml'),     # nothing to hide
    ('http://feeds.example.com/show.xml?a=1', 'http://feeds.example.com/show.xml?<hidden>'),
    ('https://feeds.example.com/show.xml#key=abc', 'https://feeds.example.com/show.xml#<hidden>'),
    ('https://feeds.example.com/show.xml?a=1#frag', 'https://feeds.example.com/show.xml?<hidden>'),
    ('https://user:pa55@feeds.example.com/show.xml', 'https://<hidden>@feeds.example.com/show.xml'),
    ('https://user:pa55@feeds.example.com/x?k=1', 'https://<hidden>@feeds.example.com/x?<hidden>'),
    ('https://feeds.example.com?k=1', 'https://feeds.example.com?<hidden>'),             # no path at all
    ('HTTPS://feeds.example.com/x?k=1', 'HTTPS://feeds.example.com/x?<hidden>'),
    ('https://feeds.example.com/a@b/show?k=1', 'https://feeds.example.com/a@b/show?<hidden>'),   # @ in the path is not userinfo
    ('UCx3FZj77zMjFP4K_ig6dvnA', 'UCx3FZj77zMjFP4K_ig6dvnA'),                            # a youtube channel id
    ('Not Available', 'Not Available'),
    ('', ''),
    (None, None),
    (42, 42),
])
def test_mask_url_secrets(value, expected):
    assert mask_url_secrets(value) == expected

def test_the_secret_never_survives():
    for value in (FEED, f'https://u:{SECRET}@h.example/p', f'https://h.example/p#{SECRET}'):
        assert SECRET not in mask_url_secrets(value)

def test_hide_feed_secrets_walks_nested_data_and_leaves_the_input_alone():
    data = [{'id': 1, 'name': 'A', 'broadcast_id': FEED}, {'nested': [{'broadcast_id': FEED}]}, 'text', 3]
    masked = hide_feed_secrets(data)
    assert masked[0]['broadcast_id'] == 'https://www.patreon.com/rss/some-show?<hidden>'
    assert masked[0]['name'] == 'A'
    assert masked[1]['nested'][0]['broadcast_id'].endswith('?<hidden>')
    assert masked[2:] == ['text', 3]
    assert data[0]['broadcast_id'] == FEED                      # the original is untouched

def test_only_broadcast_id_is_masked():
    assert hide_feed_secrets({'name': FEED, 'artist_name': FEED}) == {'name': FEED, 'artist_name': FEED}

# ------------------------------------------------------------------ the commands

@pytest.fixture(name='config')
def config_fixture(tmp_path):
    path = tmp_path / 'config.yml'
    path.write_text(dump({'hathor': {'podcast_directory': str(tmp_path / 'lib'),
                                    'database_connection_string': f'sqlite:///{tmp_path}/hathor.db'},
                          'logging': {}}), encoding='utf-8')
    return str(path)

def run(config, *args, json=True):
    result = CliRunner().invoke(cli, ['-c', config, *(['--json'] if json else []), *args])
    assert result.exit_code == 0, result.output
    return result.output

def test_list_hides_the_key_by_default(config):
    run(config, 'podcast', 'create', 'rss', FEED, 'Some Show')
    out = run(config, 'podcast', 'list')
    assert SECRET not in out
    assert loads(out)[0]['broadcast_id'] == 'https://www.patreon.com/rss/some-show?<hidden>'

def test_list_shows_everything_with_show_secrets(config):
    run(config, 'podcast', 'create', 'rss', FEED, 'Some Show')
    assert loads(run(config, 'podcast', 'list', '--show-secrets'))[0]['broadcast_id'] == FEED

def test_show_hides_and_reveals(config):
    run(config, 'podcast', 'create', 'rss', FEED, 'Some Show')
    assert SECRET not in run(config, 'podcast', 'show', '1')
    assert loads(run(config, 'podcast', 'show', '1', '--show-secrets'))[0]['broadcast_id'] == FEED

def test_the_table_output_is_masked_too(config):
    run(config, 'podcast', 'create', 'rss', FEED, 'Some Show')
    out = run(config, 'podcast', 'list', json=False)
    assert SECRET not in out and '<hidden>' in out

def test_create_and_update_do_not_echo_the_key(config):
    assert SECRET not in run(config, 'podcast', 'create', 'rss', FEED, 'Some Show')
    other = f'https://other.example/feed?auth={SECRET}'
    assert SECRET not in run(config, 'podcast', 'update', '1', '--broadcast-id', other)

def test_delete_does_not_echo_the_key(config):
    run(config, 'podcast', 'create', 'rss', FEED, 'Some Show')
    assert SECRET not in run(config, 'podcast', 'delete', '1')

def test_the_database_keeps_the_real_value(config):
    run(config, 'podcast', 'create', 'rss', FEED, 'Some Show')
    run(config, 'podcast', 'list')
    assert loads(run(config, 'podcast', 'show', '1', '--show-secrets'))[0]['broadcast_id'] == FEED

def test_a_youtube_channel_id_is_shown_as_is(config):
    run(config, 'podcast', 'create', 'youtube', 'UCx3FZj77zMjFP4K_ig6dvnA', 'Chan')
    assert loads(run(config, 'podcast', 'list'))[0]['broadcast_id'] == 'UCx3FZj77zMjFP4K_ig6dvnA'

# ------------------------------------------------------------------ __del__ after a failed init

def test_close_works_on_a_client_that_never_finished_init():
    client = HathorClient.__new__(HathorClient)
    client.close()                                               # used to raise AttributeError

def test_a_failed_init_leaves_no_second_traceback(tmp_path):
    seen = []
    original = sys.unraisablehook
    sys.unraisablehook = seen.append
    try:
        with pytest.raises(HathorException, match='needs feed_base_url'):
            HathorClient(feeds_directory=tmp_path / 'feeds')
        gc.collect()
    finally:
        sys.unraisablehook = original
    assert not seen, [str(u.exc_value) for u in seen]

def test_a_failure_before_the_database_exists_is_clean():
    seen = []
    original = sys.unraisablehook
    sys.unraisablehook = seen.append
    try:
        with pytest.raises(Exception):                           # pylint: disable=broad-exception-caught
            HathorClient(database_connection_string='not-a-valid-url')
        gc.collect()
    finally:
        sys.unraisablehook = original
    assert not seen, [str(u.exc_value) for u in seen]

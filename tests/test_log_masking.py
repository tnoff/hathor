from datetime import datetime
import logging
from uuid import uuid4

import pytest

from hathor import utils
from hathor.client import HathorClient
from hathor.podcast.archive import RSSManager

PATREON = 'https://www.patreon.com/rss/someshow?auth=SECRETKEY&show=123'

# ------------------------------------------------------------------ the text masker

def test_a_query_string_is_hidden_wherever_the_url_sits_in_the_line():
    line = f'Getting episode info from RSS feed: {PATREON}'
    assert utils.mask_log_text(line) == 'Getting episode info from RSS feed: https://www.patreon.com/rss/someshow?<hidden>'

def test_a_quoted_url_keeps_its_quote():
    # how hathor logs an episode url it already knows
    line = 'Episode 4 has same url "https://cdn.example/a.mp3?token-hash=SECRETSIG&e=1", skipping saving episode'
    assert utils.mask_log_text(line) == 'Episode 4 has same url "https://cdn.example/a.mp3?<hidden>", skipping saving episode'

def test_every_url_in_a_line_is_masked():
    masked = utils.mask_log_text('a https://x.example/?k=ONE b https://y.example/p?k=TWO#frag c')
    assert 'ONE' not in masked and 'TWO' not in masked and 'frag' not in masked
    assert masked.startswith('a https://x.example/?<hidden> b https://y.example/p?<hidden>')

def test_userinfo_is_hidden():
    assert utils.mask_log_text('proxy https://user:hunter2@proxy.example:8080/x') == 'proxy https://<hidden>@proxy.example:8080/x'

def test_a_database_password_is_hidden_and_the_rest_kept():
    masked = utils.mask_log_text('Initializing hathor client with database connection postgresql://hathor:s3cret@db.example:5432/hathor')
    assert masked.endswith('postgresql://hathor:<hidden>@db.example:5432/hathor') and 's3cret' not in masked

def test_a_connection_string_with_no_password_and_sqlite_are_unchanged():
    for line in ('database sqlite:////data/hathor.db', 'database postgresql://db.example/hathor'):
        assert utils.mask_log_text(line) == line

def test_text_without_urls_and_urls_without_secrets_are_unchanged():
    for line in ('Syncing episodes of podcast 3 (Some Show)', 'fetch https://example.com/feed.xml ok', ''):
        assert utils.mask_log_text(line) == line

# ------------------------------------------------------------------ the logger

@pytest.fixture(name='logger_name')
def logger_name_fixture():
    name = f'hathor-test-{uuid4().hex}'
    yield name
    logger = logging.getLogger(name)
    for handler in list(logger.handlers):
        handler.close()                                                  # an open log file is a ResourceWarning, which this suite turns into an error
        logger.removeHandler(handler)

def test_a_file_handler_masks_the_message_and_a_traceback(tmp_path, logger_name):
    log_file = tmp_path / 'hathor.log'
    logger = utils.setup_logger(logger_name, logging_file=log_file, log_level=logging.DEBUG)
    logger.debug(f'Getting episode info from RSS feed: {PATREON}')
    try:
        raise RuntimeError(f'failed fetching {PATREON}')
    except RuntimeError:
        logger.error('boom', exc_info=True)
    for handler in logger.handlers:
        handler.flush()
    text = log_file.read_text(encoding='utf-8')
    assert 'SECRETKEY' not in text
    assert 'https://www.patreon.com/rss/someshow?<hidden>' in text
    assert 'RuntimeError: failed fetching https://www.patreon.com/rss/someshow?<hidden>' in text    # traceback masked too

def test_the_console_handler_masks_too(capsys, logger_name):
    logger = utils.setup_logger(logger_name, console_logging=True, log_level=logging.INFO)
    logger.info('fetching %s now', PATREON)                              # %-style args are formatted, then masked
    assert 'SECRETKEY' not in capsys.readouterr().err

def test_the_log_format_is_unchanged(tmp_path, logger_name):
    log_file = tmp_path / 'hathor.log'
    logger = utils.setup_logger(logger_name, logging_file=log_file)
    logger.info('hello')
    assert log_file.read_text(encoding='utf-8').strip().endswith(' - INFO - hello')

def test_a_real_client_run_at_debug_leaks_no_feed_key(tmp_path, mocker, logger_name):
    # the lines the cluster's DEBUG run printed: the feed url and each known episode url
    log_file = tmp_path / 'hathor.log'
    logger = utils.setup_logger(logger_name, logging_file=log_file, log_level=logging.DEBUG)
    client = HathorClient(podcast_directory=tmp_path, logger=logger)
    client.podcast_create('rss', PATREON, 'Some Show')
    episode = {'download_link': 'https://cdn.example/a.mp3?token-hash=SECRETSIG&e=1', 'title': 'E1',
               'date': datetime(2026, 10, 1), 'description': 'about'}
    mocker.patch.object(RSSManager, 'broadcast_update', return_value=[episode])
    client.episode_sync()
    client.episode_sync()                                                # the second sees the episode as known
    text = log_file.read_text(encoding='utf-8')
    assert 'SECRETKEY' not in text and 'SECRETSIG' not in text
    assert 'has same url' in text                                        # the line that carried the url is still there
    client.close()

# ------------------------------------------------------------------ progress lines

def test_a_sync_says_which_podcast_it_is_in_and_what_it_found(tmp_path, mocker, caplog):
    client = HathorClient(podcast_directory=tmp_path)
    client.podcast_create('rss', 'https://feed.example/rss', 'Some Show')
    mocker.patch.object(RSSManager, 'broadcast_update', return_value=[
        {'download_link': 'https://foo.com/e1', 'title': 'E1', 'date': datetime(2026, 10, 1), 'description': 'x'}])
    with caplog.at_level(logging.INFO, logger='Hathor'):
        client.episode_sync()
    assert 'Syncing episodes of podcast 1 (Some Show)' in caplog.text
    assert 'Podcast 1 (Some Show): 1 new episodes' in caplog.text
    client.close()

def test_a_download_says_which_episode_it_started(tmp_path, mocker, caplog):
    client = HathorClient(podcast_directory=tmp_path)
    client.podcast_create('rss', 'https://feed.example/rss', 'Some Show')
    mocker.patch.object(RSSManager, 'broadcast_update', return_value=[
        {'download_link': 'https://foo.com/e1?auth=SECRETKEY', 'title': 'The Title\nwith a break', 'date': datetime(2026, 10, 1), 'description': 'x'}])
    client.episode_sync()
    mocker.patch.object(RSSManager, 'episode_download', return_value=(None, None))
    with caplog.at_level(logging.INFO, logger='Hathor'):
        client.episode_download([1])
    assert 'Downloading episode 1 of podcast 1 (Some Show): The Title with a break' in caplog.text    # one line, no url
    assert 'SECRETKEY' not in caplog.text.split('Downloading episode 1')[1].split('\n')[0]
    client.close()

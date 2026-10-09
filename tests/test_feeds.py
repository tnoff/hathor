from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import stat
from urllib.parse import unquote
import xml.etree.ElementTree as ET

import feedparser
import pytest

from hathor import feeds
from hathor.client import HathorClient
from hathor.database.tables import Podcast, PodcastEpisode
from hathor.exc import HathorException

BASE = 'https://example.com/hathor/TOKEN'
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
PODCAST = {'id': 3, 'name': 'My Show', 'artist_name': None}

def episode(n=1, **overrides):
    data = {'id': n, 'title': f'Episode {n}', 'date': datetime(2026, 10, n), 'description': f'About {n}',
            'path': f'My_Show/2026-10-0{n}.Episode_{n}.mp3', 'size': 1000 + n, 'content_type': 'audio/mpeg'}
    data.update(overrides)
    return data

def parse(feed_bytes):
    parsed = feedparser.parse(feed_bytes)
    assert not parsed.bozo, parsed.get('bozo_exception')
    return parsed

# ------------------------------------------------------------------ the builder

def test_feed_parses_as_a_podcast_feed():
    parsed = parse(feeds.build_feed(PODCAST, [episode(2), episode(1)], BASE, NOW))
    assert parsed.feed.title == 'My Show'
    assert parsed.feed.link == f'{BASE}/'
    assert parsed.feed.author == 'My Show'
    assert [e.title for e in parsed.entries] == ['Episode 2', 'Episode 1']      # order is kept
    first = parsed.entries[0]
    assert first.id == 'hathor-3-2'
    assert first.summary == 'About 2'
    [enclosure] = first.enclosures
    assert enclosure.href == f'{BASE}/files/My_Show/2026-10-02.Episode_2.mp3'
    assert (enclosure.type, enclosure.length) == ('audio/mpeg', '1002')
    assert tuple(first.published_parsed[:3]) == (2026, 10, 2)

def test_self_link_and_build_date():
    parsed = parse(feeds.build_feed(PODCAST, [episode()], BASE, NOW))
    selves = [link.href for link in parsed.feed.links if link.rel == 'self']
    assert selves == [f'{BASE}/feeds/My_Show.xml']
    assert parsedate_to_datetime(parsed.feed.updated) == NOW

def test_artist_name_becomes_the_author():
    parsed = parse(feeds.build_feed({**PODCAST, 'artist_name': 'Some Artist'}, [episode()], BASE, NOW))
    assert parsed.feed.author == 'Some Artist'

def test_guid_does_not_depend_on_the_url():
    # The url carries the token and the file name, both of which can change; an app that keyed on
    # it would treat every renamed or re-hosted episode as new.
    one = parse(feeds.build_feed(PODCAST, [episode()], BASE, NOW)).entries[0].id
    two = parse(feeds.build_feed(PODCAST, [episode(path='elsewhere/x.mp3')], 'https://other.example/t', NOW)).entries[0].id
    assert one == two == 'hathor-3-1'

def test_special_characters_stay_valid_xml_and_round_trip():
    nasty = episode(title='Q&A: <b>"Hot"</b> takes', description='<p>hi\x0b there &amp; more\x00</p> ☃ 日本語')
    raw = feeds.build_feed({**PODCAST, 'name': 'Rock & Roll <Live>'}, [nasty], BASE, NOW)
    parse(raw)                                                    # a real parser accepts it
    root = ET.fromstring(raw)                                     # and the text is exactly what went in
    assert root.find('channel/title').text == 'Rock & Roll <Live>'
    item = root.find('channel/item')
    assert item.find('title').text == 'Q&A: <b>"Hot"</b> takes'
    assert item.find('description').text == '<p>hi there &amp; more</p> ☃ 日本語'    # control characters gone, the rest intact

def test_file_names_with_spaces_and_unicode_are_percent_encoded():
    path = 'My_Show/2026-10-01 Café & Résumé #1.mp4'
    parsed = parse(feeds.build_feed(PODCAST, [episode(path=path, content_type='video/mp4')], BASE, NOW))
    href = parsed.entries[0].enclosures[0].href
    assert ' ' not in href and '#' not in href.split('/files/')[1]
    assert unquote(href.split('/files/')[1]) == path
    assert parsed.entries[0].enclosures[0].type == 'video/mp4'

def test_missing_fields_are_tolerated():
    bare = episode(title=None, date=None, description=None, size=None)
    parsed = parse(feeds.build_feed(PODCAST, [bare], BASE, NOW))
    entry = parsed.entries[0]
    assert entry.title == 'Episode 1'
    assert 'published' not in entry
    assert entry.enclosures[0].length == '0'

def test_naive_and_aware_dates_both_come_out_in_utc():
    for moment in (datetime(2026, 10, 1, 8, 30), datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc)):
        parsed = parse(feeds.build_feed(PODCAST, [episode(date=moment)], BASE, NOW))
        assert parsed.entries[0].published.endswith('+0000')
        assert tuple(parsed.entries[0].published_parsed[:5]) == (2026, 10, 1, 8, 30)

def test_empty_feed_is_still_valid():
    assert parse(feeds.build_feed(PODCAST, [], BASE, NOW)).entries == []

def test_urls():
    assert feeds.feed_filename('Jenkins and Jonez - Youtube') == 'Jenkins_and_Jonez_Youtube.xml'
    assert feeds.feed_filename('日本語 !!', 7) == 'podcast-7.xml'
    assert feeds.feed_filename('???') == 'podcast.xml'
    assert feeds.feed_url(BASE, 'My Show.xml') == f'{BASE}/feeds/My%20Show.xml'
    assert feeds.enclosure_url(BASE, 'a b/c#d.mp3') == f'{BASE}/files/a%20b/c%23d.mp3'

def test_xml_text():
    assert feeds.xml_text(None) == ''
    assert feeds.xml_text('tab\tnewline\ncr\r ok') == 'tab\tnewline\ncr\r ok'
    assert feeds.xml_text('a\ufffeb\uffffc') == 'abc'                  # noncharacters are not valid XML either
    assert feeds.xml_text('a\x00b\x0bc\x1fd') == 'abcd'
    assert feeds.xml_text('emoji 😀') == 'emoji 😀'
    assert feeds.xml_text(42) == '42'

def test_opml():
    listing = [{'name': 'Rock & Roll', 'filename': 'Rock_Roll.xml'}, {'name': 'Other', 'filename': 'Other.xml'}]
    root = ET.fromstring(feeds.build_opml(listing, BASE, NOW))
    assert root.tag == 'opml' and root.get('version') == '2.0'
    assert root.find('head/title').text == 'hathor'
    outlines = root.findall('body/outline')
    assert [o.get('text') for o in outlines] == ['Rock & Roll', 'Other']
    assert [o.get('xmlUrl') for o in outlines] == [f'{BASE}/feeds/Rock_Roll.xml', f'{BASE}/feeds/Other.xml']
    assert all(o.get('type') == 'rss' and o.get('htmlUrl') == f'{BASE}/' for o in outlines)
    assert feeds.build_opml(listing, BASE, NOW).startswith(b"<?xml version='1.0' encoding='utf-8'?>")

# ------------------------------------------------------------------ in the client

@pytest.fixture(name='world')
def world_fixture(tmp_path):
    library, feed_dir = tmp_path / 'library', tmp_path / 'feeds'
    library.mkdir()
    client = HathorClient(podcast_directory=library, index_file=tmp_path / 'index.json',
                          feeds_directory=feed_dir, feed_base_url=f'{BASE}/')
    return client, library, feed_dir, tmp_path

def add(client, library, name, titles, artist=None):
    podcast = Podcast(name=name, archive_type='rss', broadcast_id=name, artist_name=artist)
    client.db_session.add(podcast)
    client.db_session.commit()
    for n, title in enumerate(titles, start=1):
        path = library / name.replace(' ', '_') / f'ep{n}.mp3'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x' * (100 * n))
        client.db_session.add(PodcastEpisode(download_url=f'https://x/{name}/{n}', title=title, date=datetime(2026, 10, n),
                                             description=f'About {title}', podcast_id=podcast.id, file_path=str(path)))
    client.db_session.commit()
    return podcast

def test_index_writes_a_feed_per_podcast_and_the_opml(world):
    client, library, feed_dir, tmp = world
    add(client, library, 'Alpha Show', ['A1', 'A2'], artist='Some Artist')
    add(client, library, 'Beta', ['B1'])
    summary = client.episode_index()
    assert summary == {'index_file': str(tmp / 'index.json'), 'podcasts': 2, 'episodes': 3, 'feeds': 2}
    assert sorted(p.name for p in feed_dir.iterdir()) == ['Alpha_Show.xml', 'Beta.xml', 'podcasts.opml']

    alpha = parse((feed_dir / 'Alpha_Show.xml').read_bytes())
    assert [e.title for e in alpha.entries] == ['A2', 'A1']                      # newest first
    assert alpha.feed.author == 'Some Artist'
    assert alpha.entries[0].enclosures[0].href == f'{BASE}/files/Alpha_Show/ep2.mp3'    # trailing slash on the base is dropped
    assert alpha.entries[0].enclosures[0].length == '200'
    opml = ET.fromstring((feed_dir / 'podcasts.opml').read_bytes())
    assert [o.get('text') for o in opml.findall('body/outline')] == ['Alpha Show', 'Beta']

def test_index_json_points_at_the_feeds(world):
    client, library, _, tmp = world
    add(client, library, 'Alpha Show', ['A1'])
    client.episode_index()
    index = json.loads((tmp / 'index.json').read_text(encoding='utf-8'))
    assert index['opml'] == 'feeds/podcasts.opml'
    assert [p['feed'] for p in index['podcasts']] == ['feeds/Alpha_Show.xml']

def test_without_feeds_directory_nothing_changes(tmp_path):
    library = tmp_path / 'library'
    library.mkdir()
    client = HathorClient(podcast_directory=library, index_file=tmp_path / 'index.json')
    add(client, library, 'Alpha Show', ['A1'])
    assert 'feeds' not in client.episode_index()
    index = json.loads((tmp_path / 'index.json').read_text(encoding='utf-8'))
    assert 'opml' not in index and 'feed' not in index['podcasts'][0]
    assert sorted(p.name for p in tmp_path.iterdir()) == ['index.json', 'library']

def test_dry_run_returns_the_index_and_writes_no_feeds(world):
    client, library, feed_dir, tmp = world
    add(client, library, 'Alpha Show', ['A1'])
    index = client.episode_index(dry_run=True)
    assert index['podcasts'][0]['feed'] == 'feeds/Alpha_Show.xml'
    assert not feed_dir.exists() and not (tmp / 'index.json').exists()

def test_stale_feed_files_are_removed_and_other_files_left_alone(world):
    client, library, feed_dir, _ = world
    feed_dir.mkdir()
    for name in ('Gone.xml', 'old.opml', 'notes.txt'):
        (feed_dir / name).write_text('x', encoding='utf-8')
    (feed_dir / 'sub').mkdir()
    add(client, library, 'Alpha Show', ['A1'])
    client.episode_index()
    assert sorted(p.name for p in feed_dir.iterdir()) == ['Alpha_Show.xml', 'notes.txt', 'podcasts.opml', 'sub']

def test_a_podcast_with_no_episodes_on_disk_loses_its_feed(world):
    client, library, feed_dir, _ = world
    alpha = add(client, library, 'Alpha Show', ['A1'])
    add(client, library, 'Beta', ['B1'])
    client.episode_index()
    assert (feed_dir / 'Alpha_Show.xml').exists()
    for ep in client.db_session.query(PodcastEpisode).filter(PodcastEpisode.podcast_id == alpha.id):
        ep.file_path = None
    client.db_session.commit()
    assert client.episode_index()['feeds'] == 1
    assert sorted(p.name for p in feed_dir.iterdir()) == ['Beta.xml', 'podcasts.opml']

def test_files_missing_from_disk_are_not_in_the_feed(world):
    client, library, feed_dir, _ = world
    add(client, library, 'Alpha Show', ['A1', 'A2'])
    (library / 'Alpha_Show' / 'ep1.mp3').unlink()
    client.episode_index()
    assert [e.title for e in parse((feed_dir / 'Alpha_Show.xml').read_bytes()).entries] == ['A2']

def test_names_that_reduce_to_the_same_file_name_do_not_overwrite_each_other(world):
    client, library, feed_dir, _ = world
    add(client, library, 'Show!', ['A1'])
    second = add(client, library, 'Show?', ['B1'])
    client.episode_index()
    assert {p.name for p in feed_dir.iterdir()} == {'Show.xml', f'Show-{second.id}.xml', 'podcasts.opml'}
    # each feed's self link names the file it is actually written to, and the opml agrees
    assert [l.href for l in parse((feed_dir / 'Show.xml').read_bytes()).feed.links if l.rel == 'self'] == [f'{BASE}/feeds/Show.xml']
    assert [l.href for l in parse((feed_dir / f'Show-{second.id}.xml').read_bytes()).feed.links if l.rel == 'self'] == \
        [f'{BASE}/feeds/Show-{second.id}.xml']
    urls = [o.get('xmlUrl') for o in ET.fromstring((feed_dir / 'podcasts.opml').read_bytes()).findall('body/outline')]
    assert sorted(urls) == sorted([f'{BASE}/feeds/Show.xml', f'{BASE}/feeds/Show-{second.id}.xml'])

def test_a_name_with_nothing_usable_in_it_still_gets_a_real_file_name(world):
    client, library, feed_dir, _ = world
    podcast = add(client, library, '日本語!!', ['A1'])
    client.episode_index()
    assert sorted(p.name for p in feed_dir.iterdir()) == [f'podcast-{podcast.id}.xml', 'podcasts.opml']

def test_feeds_are_world_readable_and_no_temp_files_remain(world):
    client, library, feed_dir, _ = world
    add(client, library, 'Alpha Show', ['A1'])
    client.episode_index()
    client.episode_index()
    for path in feed_dir.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
    assert not [p for p in feed_dir.iterdir() if p.name.startswith('.')]

def test_feeds_directory_requires_a_base_url(tmp_path):
    with pytest.raises(HathorException, match='needs feed_base_url'):
        HathorClient(feeds_directory=tmp_path / 'feeds')

def test_base_url_alone_is_harmless():
    assert HathorClient(feed_base_url=BASE).feeds_directory is None

def test_config_reaches_the_client(mocker):
    from click.testing import CliRunner                          # pylint: disable=import-outside-toplevel
    from yaml import dump                                        # pylint: disable=import-outside-toplevel
    from tempfile import NamedTemporaryFile                      # pylint: disable=import-outside-toplevel
    from hathor.cli import cli                                   # pylint: disable=import-outside-toplevel
    client_cls = mocker.patch('hathor.cli.HathorClient')
    with NamedTemporaryFile(suffix='.yml') as config:
        with open(config.name, 'w+', encoding='utf-8') as writer:
            dump({'hathor': {'feeds_directory': '/data/feeds', 'feed_base_url': BASE}}, writer)
        CliRunner().invoke(cli, ['-c', config.name, 'dump-config'])
    kwargs = client_cls.call_args.kwargs
    assert (kwargs['feeds_directory'], kwargs['feed_base_url']) == ('/data/feeds', BASE)

from datetime import datetime, timezone
from io import BytesIO
import json
import stat
import xml.etree.ElementTree as ET

import feedparser
from PIL import Image
from click.testing import CliRunner
import pytest
import requests
from yaml import dump

from hathor import artwork, feeds
from hathor.cli import cli
from hathor.client import HathorClient
from hathor.database.tables import Podcast, PodcastEpisode
from hathor.exc import HathorException

BASE = 'https://example.com/hathor/TOKEN'

def make_image(fmt='PNG', size=(8, 8), color=(200, 30, 30), mode='RGB'):
    buffer = BytesIO()
    Image.new(mode, size, color).save(buffer, fmt)
    return buffer.getvalue()

def decode(data):
    image = Image.open(BytesIO(data))
    image.load()
    return image

JPEG = make_image('JPEG')
PNG = make_image('PNG')
PNG_OTHER = make_image('PNG', color=(10, 200, 10))
GIF = make_image('GIF')
WEBP = make_image('WEBP')
HTML = b'<!doctype html><html><body>Sorry, not found</body></html>'
URL = 'https://cdn.example.com/art/cover.jpg?token-hash=SECRETSIGNATURE&expires=1'

# ------------------------------------------------------------------ the loader

@pytest.mark.parametrize('data,extension', [(JPEG, '.jpg'), (PNG, '.png'), (GIF, '.gif'), (WEBP, '.webp')])
def test_extension_comes_from_the_magic_bytes(data, extension):
    assert artwork.image_extension(data[:12]) == extension

@pytest.mark.parametrize('data', [HTML, b'', b'<svg xmlns="http://www.w3.org/2000/svg"/>', b'RIFF\x00\x00\x00\x00WAVEfmt '])
def test_other_bytes_are_not_images(data):
    assert artwork.image_extension(data[:12]) is None

def test_load_from_a_file(tmp_path):
    path = tmp_path / 'cover.bin'                                  # the name says nothing
    path.write_bytes(PNG)
    assert artwork.load_image(str(path)) == (PNG, '.png')

def test_load_refuses_a_file_that_is_not_an_image(tmp_path):
    path = tmp_path / 'cover.jpg'                                  # nor does a lying name
    path.write_bytes(HTML)
    with pytest.raises(HathorException, match='Not a supported image'):
        artwork.load_image(str(path))

def test_load_refuses_a_missing_file(tmp_path):
    with pytest.raises(HathorException, match='not found'):
        artwork.load_image(str(tmp_path / 'nope.jpg'))

def test_load_refuses_a_large_file(tmp_path):
    path = tmp_path / 'big.jpg'
    path.write_bytes(JPEG + b'x' * 100)
    with pytest.raises(HathorException, match='larger than'):
        artwork.load_image(str(path), max_bytes=50)

def test_load_keeps_a_small_image_exactly_as_it_came(tmp_path):
    path = tmp_path / 'cover.jpg'
    path.write_bytes(JPEG)
    assert artwork.load_image(str(path))[0] == JPEG

def test_load_shrinks_a_large_image(tmp_path):
    big = make_image('JPEG', size=(3000, 2000))
    path = tmp_path / 'big.jpg'
    path.write_bytes(big)
    data, extension = artwork.load_image(str(path))
    assert extension == '.jpg' and len(data) < len(big)
    assert decode(data).size == (1400, 933)                          # aspect ratio kept

def test_load_shrinks_a_large_opaque_png_to_jpeg(tmp_path):
    path = tmp_path / 'big.png'
    path.write_bytes(make_image('PNG', size=(2000, 2000)))
    data, extension = artwork.load_image(str(path))
    assert extension == '.jpg' and decode(data).format == 'JPEG' and decode(data).size == (1400, 1400)

def test_load_keeps_transparency_when_it_shrinks(tmp_path):
    path = tmp_path / 'big.png'
    path.write_bytes(make_image('PNG', size=(2000, 2000), color=(200, 30, 30, 0), mode='RGBA'))
    data, extension = artwork.load_image(str(path))
    image = decode(data)
    assert extension == '.png' and image.size == (1400, 1400) and image.mode == 'RGBA'
    assert image.getpixel((0, 0))[3] == 0

def test_load_refuses_a_truncated_image(tmp_path):
    path = tmp_path / 'cut.jpg'
    path.write_bytes(make_image('JPEG', size=(600, 600))[:200])      # right magic bytes, then it stops
    with pytest.raises(HathorException, match='Not a readable image'):
        artwork.load_image(str(path))

def test_load_refuses_magic_bytes_with_garbage_after(tmp_path):
    path = tmp_path / 'junk.png'
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'not really a png' * 20)
    with pytest.raises(HathorException, match='Not a readable image'):
        artwork.load_image(str(path))

def test_load_refuses_a_bitmap_far_larger_than_its_file(tmp_path):
    path = tmp_path / 'bomb.png'
    Image.new('1', (8000, 8000)).save(path)                          # a few KB of file, 64 million pixels
    assert path.stat().st_size < 1024 * 1024
    with pytest.raises(HathorException, match='larger than 50000000'):
        artwork.load_image(str(path))

def test_load_refuses_what_pillow_calls_a_decompression_bomb(tmp_path, monkeypatch):
    path = tmp_path / 'bomb.png'
    path.write_bytes(make_image('PNG', size=(100, 100)))
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', 1000)             # Pillow's own limit, which warns past it
    with pytest.raises(HathorException, match='Not a readable image'):
        artwork.load_image(str(path))

def test_load_from_a_url(requests_mock):
    requests_mock.get(URL, content=WEBP, headers={'Content-Type': 'text/plain'})    # content type is ignored
    assert artwork.load_image(URL) == (WEBP, '.webp')

def test_load_refuses_html_served_with_a_200(requests_mock):
    requests_mock.get(URL, content=HTML, headers={'Content-Type': 'image/jpeg'})
    with pytest.raises(HathorException, match='Not a supported image'):
        artwork.load_image(URL)

def test_load_refuses_an_error_status_without_leaking_the_signature(requests_mock):
    requests_mock.get(URL, status_code=403)
    with pytest.raises(HathorException) as error:
        artwork.load_image(URL)
    assert 'Unable to download' in str(error.value)
    assert 'SECRETSIGNATURE' not in str(error.value)

def test_load_refuses_a_connection_error_without_leaking_the_signature(requests_mock):
    requests_mock.get(URL, exc=requests.exceptions.ConnectTimeout(f'timed out talking to {URL}'))
    with pytest.raises(HathorException) as error:
        artwork.load_image(URL)
    assert 'SECRETSIGNATURE' not in str(error.value)

def test_load_refuses_a_declared_oversize_before_reading(requests_mock):
    requests_mock.get(URL, content=JPEG, headers={'Content-Length': '999999999'})
    with pytest.raises(HathorException, match='larger than'):
        artwork.load_image(URL, max_bytes=1000)

def test_load_refuses_an_oversize_with_no_content_length(requests_mock):
    requests_mock.get(URL, content=JPEG + b'x' * 5000)
    with pytest.raises(HathorException, match='larger than'):
        artwork.load_image(URL, max_bytes=1000)

def test_feed_builder_writes_both_image_tags_or_neither():
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    podcast = {'id': 1, 'name': 'A & B', 'artist_name': None}
    plain = ET.fromstring(feeds.build_feed(podcast, [], BASE, now)).find('channel')
    assert plain.find('image') is None and plain.find(f'{{{feeds.ITUNES_NS}}}image') is None
    with_image = ET.fromstring(feeds.build_feed({**podcast, 'image_url': 'https://e/x.png'}, [], BASE, now)).find('channel')
    assert with_image.find(f'{{{feeds.ITUNES_NS}}}image').get('href') == 'https://e/x.png'
    assert [with_image.find(f'image/{tag}').text for tag in ('url', 'title', 'link')] == ['https://e/x.png', 'A & B', f'{BASE}/']

# ------------------------------------------------------------------ in the client

@pytest.fixture(name='world')
def world_fixture(tmp_path):
    library, feed_dir = tmp_path / 'library', tmp_path / 'feeds'
    library.mkdir()
    client = HathorClient(podcast_directory=library, index_file=tmp_path / 'index.json',
                          feeds_directory=feed_dir, feed_base_url=BASE)
    yield client, library, feed_dir, tmp_path
    client.close()

def add(client, library, name='Alpha Show'):
    podcast = Podcast(name=name, archive_type='rss', broadcast_id=name)
    client.db_session.add(podcast)
    client.db_session.commit()
    path = library / name.replace(' ', '_') / 'ep1.mp3'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x' * 100)
    client.db_session.add(PodcastEpisode(download_url=f'https://x/{name}', title='E1', date=datetime(2026, 10, 1),
                                         description='About', podcast_id=podcast.id, file_path=str(path)))
    client.db_session.commit()
    return podcast.id

def source(tmp_path, data, name='cover'):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)

def test_update_stores_the_image_under_the_podcast_directory(world):
    client, library, _, tmp = world
    podcast_id = add(client, library)
    result = client.podcast_update(podcast_id, image=source(tmp, PNG))
    assert result['image'] == f'.artwork/{podcast_id}.png'
    assert (library / result['image']).read_bytes() == PNG
    assert client.podcast_show([podcast_id])[0]['image'] == result['image']

def test_update_stores_a_large_image_shrunk_under_the_type_it_ended_up_as(world):
    client, library, _, tmp = world
    podcast_id = add(client, library)
    result = client.podcast_update(podcast_id, image=source(tmp, make_image('PNG', size=(3000, 3000))))
    assert result['image'] == f'.artwork/{podcast_id}.jpg'            # an opaque png is stored as jpeg once resized
    assert decode((library / result['image']).read_bytes()).size == (1400, 1400)
    assert [p.name for p in (library / '.artwork').iterdir()] == [f'{podcast_id}.jpg']

def test_resetting_a_stored_image_from_its_own_file_shrinks_it_in_place(world):
    # how an image stored before the resize existed is brought down: point --image at it
    client, library, _, _ = world
    podcast_id = add(client, library)
    (library / '.artwork').mkdir()
    stored = library / '.artwork' / f'{podcast_id}.jpg'
    stored.write_bytes(make_image('JPEG', size=(3000, 3000)))
    client.db_session.get(Podcast, podcast_id).image = f'.artwork/{podcast_id}.jpg'
    client.db_session.commit()
    result = client.podcast_update(podcast_id, image=str(stored))
    assert result['image'] == f'.artwork/{podcast_id}.jpg'
    assert decode(stored.read_bytes()).size == (1400, 1400)

def test_update_downloads_a_url_once_and_keeps_no_trace_of_it(world, requests_mock):
    client, library, _, _ = world
    podcast_id = add(client, library)
    requests_mock.get(URL, content=JPEG)
    result = client.podcast_update(podcast_id, image=URL)
    requests_mock.get(URL, status_code=410)                         # the signed url expires
    assert (library / result['image']).read_bytes() == JPEG
    assert 'SECRETSIGNATURE' not in json.dumps(result)

def test_a_refresh_that_fails_keeps_the_old_image(world, requests_mock):
    client, library, _, tmp = world
    podcast_id = add(client, library)
    stored = client.podcast_update(podcast_id, image=source(tmp, PNG))['image']
    requests_mock.get(URL, content=HTML)
    with pytest.raises(HathorException, match='Not a supported image'):
        client.podcast_update(podcast_id, artist_name='changed too', image=URL)
    pod = client.podcast_show([podcast_id])[0]
    assert pod['image'] == stored and pod['artist_name'] is None    # nothing else was applied either
    assert (library / stored).read_bytes() == PNG
    requests_mock.get(URL, status_code=500)
    with pytest.raises(HathorException, match='Unable to download'):
        client.podcast_update(podcast_id, image=URL)
    assert (library / stored).read_bytes() == PNG

def test_a_failure_message_does_not_carry_the_signature(world, requests_mock):
    client, library, _, _ = world
    podcast_id = add(client, library)
    requests_mock.get(URL, content=HTML)
    with pytest.raises(HathorException) as error:
        client.podcast_update(podcast_id, image=URL)
    assert 'SECRETSIGNATURE' not in str(error.value)

def test_replacing_with_another_type_removes_the_old_file(world):
    client, library, _, tmp = world
    podcast_id = add(client, library)
    client.podcast_update(podcast_id, image=source(tmp, PNG))
    result = client.podcast_update(podcast_id, image=source(tmp, JPEG, 'second'))
    assert result['image'] == f'.artwork/{podcast_id}.jpg'
    assert [p.name for p in (library / '.artwork').iterdir()] == [f'{podcast_id}.jpg']

def test_replacing_with_the_same_type_keeps_one_file(world):
    client, library, _, tmp = world
    podcast_id = add(client, library)
    client.podcast_update(podcast_id, image=source(tmp, PNG))
    result = client.podcast_update(podcast_id, image=source(tmp, PNG_OTHER, 'second'))
    assert (library / result['image']).read_bytes() == PNG_OTHER
    assert len(list((library / '.artwork').iterdir())) == 1

def test_remove_image(world):
    client, library, _, tmp = world
    podcast_id = add(client, library)
    stored = client.podcast_update(podcast_id, image=source(tmp, PNG))['image']
    assert client.podcast_update(podcast_id, remove_image=True)['image'] is None
    assert not (library / stored).exists()

def test_remove_image_with_no_image_is_fine(world):
    client, library, _, _ = world
    podcast_id = add(client, library)
    assert client.podcast_update(podcast_id, remove_image=True)['image'] is None

def test_setting_and_removing_together_is_refused(world):
    client, library, _, tmp = world
    podcast_id = add(client, library)
    with pytest.raises(HathorException, match='same update'):
        client.podcast_update(podcast_id, image=source(tmp, PNG), remove_image=True)

def test_an_image_needs_a_podcast_directory():
    client = HathorClient()
    client.db_session.add(Podcast(name='p', archive_type='rss', broadcast_id='x'))
    client.db_session.commit()
    with pytest.raises(HathorException, match='podcast_directory'):
        client.podcast_update(1, image='/tmp/whatever.png')
    client.close()

def test_deleting_a_podcast_removes_its_image_with_or_without_the_files(world):
    client, library, _, tmp = world
    kept, gone = add(client, library, 'Keep Files'), add(client, library, 'Drop Files')
    kept_image = client.podcast_update(kept, image=source(tmp, PNG))['image']
    gone_image = client.podcast_update(gone, image=source(tmp, PNG))['image']
    # file_location is unset on these podcasts, so give deletion something to remove
    for pod_id in (kept, gone):
        (library / f'loc{pod_id}').mkdir()
        client.db_session.get(Podcast, pod_id).file_location = str(library / f'loc{pod_id}')
    client.db_session.commit()
    client.podcast_delete([kept], delete_files=False)
    client.podcast_delete([gone])
    assert not (library / kept_image).exists() and not (library / gone_image).exists()

# ------------------------------------------------------------------ in the feed

def test_index_serves_the_image_and_the_feed_points_at_it(world):
    client, library, feed_dir, tmp = world
    podcast_id = add(client, library)
    client.podcast_update(podcast_id, image=source(tmp, PNG))
    client.episode_index()
    [image] = [p for p in feed_dir.iterdir() if p.suffix == '.png']
    assert image.name.startswith('Alpha_Show-') and image.read_bytes() == PNG
    assert stat.S_IMODE(image.stat().st_mode) == 0o644
    url = f'{BASE}/feeds/{image.name}'
    parsed = feedparser.parse((feed_dir / 'Alpha_Show.xml').read_bytes())
    assert not parsed.bozo and parsed.feed.image.href == url                       # what a podcast app reads
    channel = ET.parse(feed_dir / 'Alpha_Show.xml').getroot().find('channel')
    assert channel.find(f'{{{feeds.ITUNES_NS}}}image').get('href') == url
    assert channel.find('image/url').text == url
    index = json.loads((tmp / 'index.json').read_text(encoding='utf-8'))
    assert index['podcasts'][0]['image'] == f'feeds/{image.name}'
    assert not [p for p in feed_dir.iterdir() if p.name.startswith('.')]          # no temp files left

def test_a_podcast_with_no_image_gets_none(world):
    client, library, feed_dir, tmp = world
    add(client, library)
    client.episode_index()
    assert sorted(p.name for p in feed_dir.iterdir()) == ['Alpha_Show.xml', 'podcasts.opml']
    assert 'image' not in (feed_dir / 'Alpha_Show.xml').read_text(encoding='utf-8')
    assert 'image' not in json.loads((tmp / 'index.json').read_text(encoding='utf-8'))['podcasts'][0]

def test_a_new_image_gets_a_new_url_and_the_old_copy_goes(world):
    client, library, feed_dir, tmp = world
    podcast_id = add(client, library)
    client.podcast_update(podcast_id, image=source(tmp, PNG))
    client.episode_index()
    [first] = [p.name for p in feed_dir.iterdir() if p.suffix == '.png']
    client.podcast_update(podcast_id, image=source(tmp, PNG_OTHER, 'second'))
    client.episode_index()
    [second] = [p.name for p in feed_dir.iterdir() if p.suffix == '.png']
    assert first != second                                          # an app caching by url fetches the new one
    assert second in (feed_dir / 'Alpha_Show.xml').read_text(encoding='utf-8')

def test_unchanged_image_is_not_rewritten(world):
    client, library, feed_dir, tmp = world
    podcast_id = add(client, library)
    client.podcast_update(podcast_id, image=source(tmp, PNG))
    client.episode_index()
    [image] = [p for p in feed_dir.iterdir() if p.suffix == '.png']
    before = image.stat().st_mtime_ns
    client.episode_index()
    assert image.stat().st_mtime_ns == before

def test_removing_the_image_removes_the_copy_and_the_tags(world):
    client, library, feed_dir, tmp = world
    podcast_id = add(client, library)
    client.podcast_update(podcast_id, image=source(tmp, PNG))
    client.episode_index()
    client.podcast_update(podcast_id, remove_image=True)
    client.episode_index()
    assert sorted(p.name for p in feed_dir.iterdir()) == ['Alpha_Show.xml', 'podcasts.opml']
    assert 'image' not in (feed_dir / 'Alpha_Show.xml').read_text(encoding='utf-8')

def test_an_image_missing_from_disk_is_left_out(world):
    client, library, feed_dir, tmp = world
    podcast_id = add(client, library)
    stored = client.podcast_update(podcast_id, image=source(tmp, PNG))['image']
    (library / stored).unlink()
    client.episode_index()
    assert sorted(p.name for p in feed_dir.iterdir()) == ['Alpha_Show.xml', 'podcasts.opml']

def test_an_image_path_outside_the_podcast_directory_is_ignored(world):
    client, library, feed_dir, tmp = world
    podcast_id = add(client, library)
    outside = tmp / 'secret.png'
    outside.write_bytes(PNG)
    client.db_session.get(Podcast, podcast_id).image = '../secret.png'
    client.db_session.commit()
    client.episode_index()
    assert sorted(p.name for p in feed_dir.iterdir()) == ['Alpha_Show.xml', 'podcasts.opml']

def test_dry_run_names_the_image_and_writes_nothing(world):
    client, library, feed_dir, tmp = world
    podcast_id = add(client, library)
    client.podcast_update(podcast_id, image=source(tmp, PNG))
    index = client.episode_index(dry_run=True)
    assert index['podcasts'][0]['image'].startswith('feeds/Alpha_Show-')
    assert not feed_dir.exists()

def test_without_feeds_directory_the_image_is_just_stored(tmp_path):
    library = tmp_path / 'library'
    library.mkdir()
    client = HathorClient(podcast_directory=library, index_file=tmp_path / 'index.json')
    podcast_id = add(client, library)
    client.podcast_update(podcast_id, image=source(tmp_path, PNG))
    client.episode_index()
    assert 'image' not in json.loads((tmp_path / 'index.json').read_text(encoding='utf-8'))['podcasts'][0]
    client.close()

# ------------------------------------------------------------------ the command line

def test_cli_sets_and_removes_an_image(tmp_path):
    library = tmp_path / 'library'
    library.mkdir()
    config = tmp_path / 'config.yml'
    config.write_text(dump({'hathor': {'database_connection_string': f'sqlite:///{tmp_path}/h.db',
                                       'podcast_directory': str(library)}}), encoding='utf-8')
    picture = tmp_path / 'cover.png'
    picture.write_bytes(PNG)
    runner = CliRunner()
    runner.invoke(cli, ['-c', str(config), 'podcast', 'create', 'rss', 'https://foo.com/example', 'temp-pod',
                        '--file-location', str(library)])
    result = runner.invoke(cli, ['-c', str(config), '--json', 'podcast', 'update', '1', '--image', str(picture)])
    assert json.loads(result.output)['image'] == '.artwork/1.png'
    assert (library / '.artwork' / '1.png').read_bytes() == PNG
    result = runner.invoke(cli, ['-c', str(config), '--json', 'podcast', 'update', '1', '--remove-image'])
    assert json.loads(result.output)['image'] is None
    assert not (library / '.artwork' / '1.png').exists()

from datetime import datetime, timezone
from email.utils import format_datetime
import re
from urllib.parse import quote
# Only ever BUILDS xml, never parses any: bandit's warning is about parsing untrusted input
import xml.etree.ElementTree as ET # nosec B405

from hathor.utils import normalize_name

ITUNES_NS = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
ATOM_NS = 'http://www.w3.org/2005/Atom'
ET.register_namespace('itunes', ITUNES_NS)
ET.register_namespace('atom', ATOM_NS)

OPML_FILENAME = 'podcasts.opml'
# Anything XML 1.0 cannot carry. Feed descriptions are scraped from the web and do contain
# stray control characters, and one of them makes the whole feed unparseable.
INVALID_XML_CHARS = re.compile('[^\x09\x0a\x0d\x20-퟿-�\U00010000-\U0010ffff]')

def xml_text(value) -> str:
    '''
    Text that is safe to put in an XML document

    value: any value, None becomes an empty string
    '''
    return INVALID_XML_CHARS.sub('', '' if value is None else str(value))

def feed_filename(podcast_name: str, podcast_id: int | None = None) -> str:
    '''
    File name of a podcast's feed, from its name so the url stays readable

    A name with nothing in it that survives normalising (all punctuation, or not ascii) would
    otherwise give a hidden ".xml" file, so it falls back to the podcast id

    podcast_name    :   name of the podcast
    podcast_id      :   id of the podcast, for the fallback
    '''
    slug = normalize_name(podcast_name)
    if not slug.strip('_'):
        slug = f'podcast-{podcast_id}' if podcast_id is not None else 'podcast'
    return f'{slug}.xml'

def feed_url(base_url: str, filename: str) -> str:
    '''
    Absolute url of a file in the feeds directory

    base_url    :   Where the library is served, such as https://example.com/hathor/<token>
    filename    :   Feed or opml file name
    '''
    return f'{base_url}/feeds/{quote(filename)}'

def enclosure_url(base_url: str, path: str) -> str:
    '''
    Absolute url of an episode file, with the path percent encoded

    base_url    :   Where the library is served
    path        :   Path of the file relative to the podcast directory
    '''
    return f'{base_url}/files/{quote(path, safe="/")}'

def _rfc822(moment: datetime) -> str:
    return format_datetime(moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc))

def build_feed(podcast: dict, episodes: list[dict], base_url: str, now: datetime,
               filename: str | None = None) -> bytes:
    '''
    RSS 2.0 feed for one podcast, with the itunes tags podcast apps look for

    Each item's guid comes from the podcast and episode ids, never from its url, so an app
    keeps recognising an episode however the urls change.

    podcast     :   dict with id, name and artist_name, and image_url when it has artwork
    episodes    :   newest first; dicts with id, title, date (datetime or None), description,
                    path (relative to the podcast directory), size and content_type
    base_url    :   Where the library is served
    now         :   Build time, for lastBuildDate
    filename    :   The file name this feed is written under, for its self link. Defaults to the one
                    feed_filename gives, which differs when two podcasts reduce to the same name
    '''
    rss = ET.Element('rss', {'version': '2.0'})
    channel = ET.SubElement(rss, 'channel')
    author = podcast.get('artist_name') or podcast['name']
    ET.SubElement(channel, 'title').text = xml_text(podcast['name'])
    ET.SubElement(channel, 'link').text = f'{base_url}/'
    ET.SubElement(channel, 'description').text = xml_text(f'{podcast["name"]}, episodes saved by hathor')
    ET.SubElement(channel, 'language').text = 'en'
    ET.SubElement(channel, 'lastBuildDate').text = _rfc822(now)
    ET.SubElement(channel, 'generator').text = 'hathor'
    ET.SubElement(channel, f'{{{ITUNES_NS}}}author').text = xml_text(author)
    ET.SubElement(channel, f'{{{ATOM_NS}}}link', {
        'rel': 'self', 'type': 'application/rss+xml',
        'href': feed_url(base_url, filename or feed_filename(podcast['name'], podcast['id'])),
    })
    if podcast.get('image_url'):
        # itunes:image is what podcast apps read; the rss 2.0 image is for readers that predate it
        ET.SubElement(channel, f'{{{ITUNES_NS}}}image', {'href': podcast['image_url']})
        image = ET.SubElement(channel, 'image')
        ET.SubElement(image, 'url').text = podcast['image_url']
        ET.SubElement(image, 'title').text = xml_text(podcast['name'])
        ET.SubElement(image, 'link').text = f'{base_url}/'
    for episode in episodes:
        item = ET.SubElement(channel, 'item')
        ET.SubElement(item, 'title').text = xml_text(episode['title'] or f'Episode {episode["id"]}')
        ET.SubElement(item, 'guid', {'isPermaLink': 'false'}).text = f'hathor-{podcast["id"]}-{episode["id"]}'
        if episode.get('date'):
            ET.SubElement(item, 'pubDate').text = _rfc822(episode['date'])
        ET.SubElement(item, 'description').text = xml_text(episode.get('description'))
        ET.SubElement(item, 'enclosure', {
            'url': enclosure_url(base_url, episode['path']),
            'length': str(episode['size'] or 0),
            'type': episode['content_type'],
        })
    ET.indent(rss)
    return ET.tostring(rss, encoding='utf-8', xml_declaration=True)

def build_opml(feeds: list[dict], base_url: str, now: datetime) -> bytes:
    '''
    OPML listing every feed, so a podcast app can subscribe to all of them in one import

    feeds       :   dicts with name and filename
    base_url    :   Where the library is served
    now         :   Build time
    '''
    opml = ET.Element('opml', {'version': '2.0'})
    head = ET.SubElement(opml, 'head')
    ET.SubElement(head, 'title').text = 'hathor'
    ET.SubElement(head, 'dateCreated').text = _rfc822(now)
    body = ET.SubElement(opml, 'body')
    for feed in feeds:
        name = xml_text(feed['name'])
        ET.SubElement(body, 'outline', {
            'type': 'rss', 'text': name, 'title': name,
            'xmlUrl': feed_url(base_url, feed['filename']), 'htmlUrl': f'{base_url}/',
        })
    ET.indent(opml)
    return ET.tostring(opml, encoding='utf-8', xml_declaration=True)

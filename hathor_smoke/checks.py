'''
The checks: ask a deployed hathor server's public address for what a phone would ask for,
and fail if any of it is wrong. Read only. It never runs a sync and never touches the
database or the volume, so it is safe to run at any time, against production

Nothing here imports hathor: this package only knows the server's public interface (the page,
index.json, the feeds and the files), so it can never run hathor's code, migrations included

The address is <base url>/<token>/, where the token is the whole of the server's
authentication. It is read from the environment, and never printed: every message is
scrubbed of it before it leaves this module
'''
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from hathor_smoke.exc import SmokeFailure

# What the server must answer 404 to, standing in for a guessed address
WRONG_SEGMENT = 'smoke-wrong-segment'
DEFAULT_MAX_INDEX_AGE = 7200
DEFAULT_TIMEOUT = 15
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 2
# The server is a single replica that restarts on every deploy, so a request can meet a 502
# from the ingress for a few seconds. Retry those, never a 404 or a 200 with the wrong body
RETRY_STATUSES = (502, 503, 504)

def utcnow() -> datetime:
    '''
    Current time, in one place so tests can move it
    '''
    return datetime.now(timezone.utc)

def expect(condition: bool, message: str):
    '''
    Raise SmokeFailure with message unless condition holds
    '''
    if not condition:
        raise SmokeFailure(message)

class Smoke:
    '''
    The address under test and the options every check shares

    base_url        : Address the server is under, before the token, such as https://example.com/hathor
    token           : The url token
    max_index_age   : Oldest allowed index.json, in seconds. The sync rewrites it every hour
    timeout         : Seconds to wait on one request
    retries         : Times a request is retried on a connection error or a 502, 503 or 504
    backoff_factor  : Seconds the wait between retries grows by, doubling each time after the first
    allow_empty     : Do not fail an index with no episodes in it
    '''
    def __init__(self, base_url: str, token: str, max_index_age: int = DEFAULT_MAX_INDEX_AGE,
                 timeout: int = DEFAULT_TIMEOUT, retries: int = DEFAULT_RETRIES, allow_empty: bool = False,
                 backoff_factor: float = DEFAULT_BACKOFF):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.max_index_age = max_index_age
        self.timeout = timeout
        self.allow_empty = allow_empty
        self.session = requests.Session()
        adapter = HTTPAdapter(max_retries=Retry(total=retries, backoff_factor=backoff_factor, status_forcelist=RETRY_STATUSES,
                                                allowed_methods=('GET',)))
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

    def close(self):
        '''
        Release the connections. Always call it, a warning for an unclosed socket is an error in tests
        '''
        self.session.close()

    def url(self, path: str, token: str | None = None) -> str:
        '''
        Full url of a path below the token. A path from the index is relative to it

        path    : Path below the token, already percent encoded where it needs to be
        token   : Use this in place of the real token
        '''
        return f'{self.base_url}/{quote(token or self.token, safe="")}/{path}'

    def get(self, path: str, token: str | None = None, **kwargs) -> requests.Response:
        '''
        GET a path below the token, with this run's timeout. Other arguments go to requests
        '''
        return self.session.get(self.url(path, token), timeout=self.timeout, **kwargs)

    def scrub(self, text: str) -> str:
        '''
        Hide the token wherever it appears, in either form it can be written. An error from
        requests names the whole url it was fetching
        '''
        for form in (self.token, quote(self.token, safe='')):
            text = text.replace(form, '<token>')
        return text

@dataclass
class Result:
    '''
    Outcome of one check
    '''
    name: str
    passed: bool
    detail: str

def index_of(state: dict) -> dict:
    '''
    The parsed index from the index check, which later checks build on
    '''
    expect('index' in state, 'needs the index check, which did not pass')
    return state['index']

def check_page(smoke: Smoke, _state: dict) -> str:
    '''
    The page a browser lands on is served as html
    '''
    response = smoke.get('')
    expect(response.status_code == 200, f'status {response.status_code}, expected 200')
    expect(response.headers.get('Content-Type', '').startswith('text/html'),
           f'content type {response.headers.get("Content-Type")}, expected text/html')
    return f'{len(response.content)} bytes'

def check_invalid_token(smoke: Smoke, _state: dict) -> str:
    '''
    A wrong address is a 404, so nothing is served without the token
    '''
    response = smoke.get('index.json', token=WRONG_SEGMENT)
    expect(response.status_code == 404, f'status {response.status_code} for a wrong token, expected 404')
    return '404 for a wrong token'

def check_index(smoke: Smoke, state: dict) -> str:
    '''
    index.json parses, has the shape the feeds are built from, is recent, and has episodes in it.
    A sync that stopped shows up here first: the index is rewritten on every run, new episodes or not
    '''
    response = smoke.get('index.json')
    expect(response.status_code == 200, f'status {response.status_code}, expected 200')
    try:
        index = response.json()
    except ValueError as error:
        raise SmokeFailure('index.json is not json') from error
    expect(isinstance(index, dict) and isinstance(index.get('podcasts'), list), 'index.json has no list of podcasts')
    generated = index.get('generated_at')
    expect(isinstance(generated, str), 'index.json has no generated_at')
    try:
        generated_at = datetime.fromisoformat(generated)
    except ValueError as error:
        raise SmokeFailure('generated_at is not a timestamp') from error
    expect(generated_at.tzinfo is not None, 'generated_at has no timezone')
    age = (utcnow() - generated_at).total_seconds()
    expect(age <= smoke.max_index_age, f'index is {age / 60:.0f} minutes old, the limit is {smoke.max_index_age / 60:.0f}')
    episodes = sum(len(podcast.get('episodes', [])) for podcast in index['podcasts'])
    expect(episodes > 0 or smoke.allow_empty, 'index has no episodes in it')
    state['index'] = index
    return f'{len(index["podcasts"])} podcasts, {episodes} episodes, generated {age / 60:.0f} minutes ago'

def check_opml(smoke: Smoke, state: dict) -> str:
    '''
    The opml is served with its own content type and lists a feed for every podcast in the index
    '''
    index = index_of(state)
    expect(isinstance(index.get('opml'), str), 'index.json names no opml')
    response = smoke.get(quote(index['opml'], safe='/'))
    expect(response.status_code == 200, f'status {response.status_code}, expected 200')
    expect(response.headers.get('Content-Type', '').startswith('text/x-opml'),
           f'content type {response.headers.get("Content-Type")}, expected text/x-opml')
    # Counted, not parsed: the feeds are the real check, and this only has to agree with the index
    outlines = response.text.count('xmlUrl=')
    expect(outlines == len(index['podcasts']), f'opml lists {outlines} feeds, index has {len(index["podcasts"])} podcasts')
    return f'{outlines} feeds listed'

def check_feeds(smoke: Smoke, state: dict) -> str:
    '''
    Every feed the index names is served, parses as a feed, and holds exactly the episodes the index lists
    '''
    index = index_of(state)
    for podcast in index['podcasts']:
        name = podcast.get('name')
        expect(isinstance(podcast.get('feed'), str), f'index.json names no feed for {name}')
        response = smoke.get(quote(podcast['feed'], safe='/'))
        expect(response.status_code == 200, f'feed of {name}: status {response.status_code}, expected 200')
        parsed = feedparser.parse(response.content)
        expect(not parsed.bozo, f'feed of {name} does not parse: {parsed.get("bozo_exception")}')
        expected = len(podcast.get('episodes', []))
        expect(len(parsed.entries) == expected, f'feed of {name} has {len(parsed.entries)} episodes, index has {expected}')
    return f'{len(index["podcasts"])} feeds parse and match the index'

def check_file_range(smoke: Smoke, state: dict) -> str:
    '''
    Ask for one byte of the smallest episode: proves files are served and that resuming a
    download works, which is why phones can finish a download that dropped
    '''
    index = index_of(state)
    episodes = [episode for podcast in index['podcasts'] for episode in podcast.get('episodes', [])]
    if not episodes:
        # Only reachable when allowed: the index check already fails an index with none
        return 'no episodes, skipped'
    episode = min(episodes, key=lambda item: item.get('size', 0))
    expect(isinstance(episode.get('path'), str), f'episode {episode.get("id")} has no path')
    with smoke.get(f'files/{quote(episode["path"], safe="/")}', headers={'Range': 'bytes=0-0'}, stream=True) as response:
        expect(response.status_code == 206, f'status {response.status_code} for a range request, expected 206')
        expect(response.headers.get('Content-Range', '').startswith('bytes 0-0/'),
               f'content range {response.headers.get("Content-Range")}, expected bytes 0-0/<size>')
        body = next(response.iter_content(2), b'')
    expect(len(body) == 1, f'{len(body)} bytes came back for a one byte range')
    return f'episode {episode["id"]} answers a range request'

CHECKS = (
    ('page', check_page),
    ('invalid-token', check_invalid_token),
    ('index', check_index),
    ('opml', check_opml),
    ('feeds', check_feeds),
    ('file-range', check_file_range),
)

def run_checks(smoke: Smoke) -> list[Result]:
    '''
    Run every check, in order. One failing never stops the others, so a run says everything
    that is wrong at once. A check that needs the index fails if the index check did
    '''
    state = {}
    results = []
    for name, check in CHECKS:
        try:
            results.append(Result(name, True, smoke.scrub(check(smoke, state))))
        except (SmokeFailure, requests.RequestException) as error:
            results.append(Result(name, False, smoke.scrub(str(error))))
    return results

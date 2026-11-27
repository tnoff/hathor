from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from threading import Thread
from urllib.parse import unquote, urlsplit

from click.testing import CliRunner
import pytest
import requests
from requests_mock import ANY

from hathor.client import HathorClient
from hathor_smoke import checks
from hathor_smoke.checks import Smoke, run_checks
from hathor_smoke.cli import cli

from tests.test_feeds import add

SERVER = 'https://example.com/hathor'
TOKEN = 'TOKEN-abc123'
ROOT = f'{SERVER}/{TOKEN}'

CONTENT_TYPES = {'.xml': 'application/rss+xml', '.opml': 'text/x-opml', '.mp3': 'audio/mpeg'}

class Site:
    '''
    A hathor library on disk, indexed by the real client, served the way the nginx config serves it:
    the page and index.json, the feeds directory, and the files with range requests. Only the
    token path answers; everything else is a 404
    '''
    def __init__(self, tmp_path, requests_mock):
        self.library = tmp_path / 'library'
        self.library.mkdir()
        self.feeds = tmp_path / 'feeds'
        self.index_file = tmp_path / 'index.json'
        self.client = HathorClient(podcast_directory=self.library, index_file=self.index_file,
                                   feeds_directory=self.feeds, feed_base_url=ROOT)
        add(self.client, self.library, 'Alpha Show', ['A1', 'A2'])
        add(self.client, self.library, 'Beta', ['B1'])
        self.reindex()
        requests_mock.get(ANY, content=self.respond)

    def reindex(self):
        self.client.episode_index()

    def index(self) -> dict:
        return json.loads(self.index_file.read_text(encoding='utf-8'))

    def write_index(self, data):
        self.index_file.write_text(data if isinstance(data, str) else json.dumps(data), encoding='utf-8')

    def respond(self, request, context):
        prefix = f'/hathor/{TOKEN}/'
        # request.path is lowercased by requests_mock; the url keeps the case it was asked in
        path = unquote(urlsplit(request.url).path)
        context.status_code = 404
        if not path.startswith(prefix):
            return b'not found'
        relative = path[len(prefix):]
        context.status_code = 200
        if relative == '':
            context.headers['Content-Type'] = 'text/html'
            return b'<html></html>'
        if relative == 'index.json':
            context.headers['Content-Type'] = 'application/json'
            return self.index_file.read_bytes()
        for directory, root in (('feeds/', self.feeds), ('files/', self.library)):
            target = root / relative[len(directory):]
            if relative.startswith(directory) and target.is_file():
                context.headers['Content-Type'] = CONTENT_TYPES.get(target.suffix, 'application/octet-stream')
                return self.slice(target.read_bytes(), request, context)
        context.status_code = 404
        return b'not found'

    @staticmethod
    def slice(data: bytes, request, context) -> bytes:
        match = re.fullmatch(r'bytes=(\d+)-(\d+)', request.headers.get('Range', ''))
        if not match:
            return data
        start, end = int(match.group(1)), int(match.group(2))
        context.status_code = 206
        context.headers['Content-Range'] = f'bytes {start}-{end}/{len(data)}'
        return data[start:end + 1]

@pytest.fixture(name='site')
def site_fixture(tmp_path, requests_mock):
    site = Site(tmp_path, requests_mock)
    yield site
    site.client.db_session.close()
    site.client.db_session.get_bind().dispose()

def run(**options):
    runner = Smoke(SERVER, TOKEN, **options)
    try:
        return {result.name: result for result in run_checks(runner)}
    finally:
        runner.close()

def failures(results):
    return {name: result.detail for name, result in results.items() if not result.passed}

# ------------------------------------------------------------------ against the real index

@pytest.mark.usefixtures('site')
def test_everything_passes_against_what_the_client_writes():
    results = run()
    assert failures(results) == {}
    assert list(results) == ['page', 'invalid-token', 'index', 'opml', 'feeds', 'file-range']
    assert results['index'].detail.startswith('2 podcasts, 3 episodes, generated ')
    assert results['opml'].detail == '2 feeds listed'
    assert results['feeds'].detail == '2 feeds parse and match the index'

def test_a_podcast_name_that_needs_encoding_still_resolves(site):
    add(site.client, site.library, 'Café & Résumé #1', ['C1'])
    site.reindex()
    assert failures(run()) == {}

@pytest.mark.usefixtures('site')
def test_the_smallest_episode_is_the_one_fetched(requests_mock):
    run()
    ranged = [request for request in requests_mock.request_history if request.headers.get('Range')]
    assert [unquote(urlsplit(request.url).path) for request in ranged] == [f'/hathor/{TOKEN}/files/Alpha_Show/ep1.mp3']

@pytest.mark.usefixtures('site')
def test_cli_prints_a_line_per_check_and_exits_zero():
    result = CliRunner().invoke(cli, ['--base-url', SERVER], env={'HATHOR_TOKEN': TOKEN})
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert [line.split(':')[0] for line in lines[:-1]] == [
        'PASS page', 'PASS invalid-token', 'PASS index', 'PASS opml', 'PASS feeds', 'PASS file-range']
    assert lines[-1] == '6/6 checks passed'
    assert TOKEN not in result.output

@pytest.mark.usefixtures('site')
def test_cli_exits_one_and_names_what_failed(requests_mock):
    requests_mock.get(f'{ROOT}/', status_code=500)
    result = CliRunner().invoke(cli, ['--base-url', SERVER, '--retries', '0'], env={'HATHOR_TOKEN': TOKEN})
    assert result.exit_code == 1
    assert 'FAIL page: status 500, expected 200' in result.output
    assert result.output.splitlines()[-1] == '5/6 checks passed'

@pytest.mark.usefixtures('site')
def test_cli_reads_the_base_url_from_the_environment():
    result = CliRunner().invoke(cli, [], env={'HATHOR_TOKEN': TOKEN, 'HATHOR_SMOKE_BASE_URL': f'{SERVER}/'})
    assert result.exit_code == 0, result.output

@pytest.mark.parametrize('env,missing', [({}, '--base-url'), ({'HATHOR_SMOKE_BASE_URL': SERVER}, '--token')])
def test_cli_needs_both_the_address_and_the_token(env, missing):
    result = CliRunner().invoke(cli, [], env=env)
    assert result.exit_code == 2
    assert f"Missing option '{missing}'" in result.output

def test_the_token_is_never_in_the_help_or_a_usage_error():
    runner = CliRunner()
    for args in (['--help'], ['--base-url', SERVER, '--timeout', '0']):
        result = runner.invoke(cli, args, env={'HATHOR_TOKEN': TOKEN})
        assert TOKEN not in result.output
    assert 'HATHOR_TOKEN' in runner.invoke(cli, ['--help']).output

# ------------------------------------------------------------------ page and token

@pytest.mark.usefixtures('site')
def test_page_must_be_html(requests_mock):
    requests_mock.get(f'{ROOT}/', text='ok', headers={'Content-Type': 'text/plain'})
    assert failures(run()) == {'page': 'content type text/plain, expected text/html'}

@pytest.mark.usefixtures('site')
def test_page_must_answer(requests_mock):
    requests_mock.get(f'{ROOT}/', status_code=404)
    assert failures(run()) == {'page': 'status 404, expected 200'}

@pytest.mark.usefixtures('site')
def test_a_wrong_token_must_be_a_404(requests_mock):
    requests_mock.get(f'{SERVER}/{checks.WRONG_SEGMENT}/index.json', text='{}')
    assert failures(run()) == {'invalid-token': 'status 200 for a wrong token, expected 404'}

# ------------------------------------------------------------------ the index

@pytest.mark.usefixtures('site')
def test_a_stale_index_fails_and_what_needs_it_says_so(mocker):
    mocker.patch('hathor_smoke.checks.utcnow', return_value=datetime.now(timezone.utc) + timedelta(hours=3))
    found = failures(run())
    assert found['index'] == 'index is 180 minutes old, the limit is 120'
    assert {name for name in found if name != 'index'} == {'opml', 'feeds', 'file-range'}
    assert all(found[name] == 'needs the index check, which did not pass' for name in ('opml', 'feeds', 'file-range'))

@pytest.mark.usefixtures('site')
def test_the_age_limit_can_be_raised(mocker):
    mocker.patch('hathor_smoke.checks.utcnow', return_value=datetime.now(timezone.utc) + timedelta(hours=3))
    assert failures(run(max_index_age=4 * 3600)) == {}

@pytest.mark.usefixtures('site')
def test_index_must_answer(requests_mock):
    requests_mock.get(f'{ROOT}/index.json', status_code=502)
    assert failures(run())['index'] == 'status 502, expected 200'

@pytest.mark.parametrize('body,message', [
    ('<html>', 'index.json is not json'),
    ('[]', 'index.json has no list of podcasts'),
    ('{"podcasts": {}}', 'index.json has no list of podcasts'),
    ('{"podcasts": []}', 'index.json has no generated_at'),
    ('{"podcasts": [], "generated_at": "yesterday"}', 'generated_at is not a timestamp'),
    ('{"podcasts": [], "generated_at": "2026-10-09T12:00:00"}', 'generated_at has no timezone'),
])
def test_a_malformed_index_fails_the_index_check(site, body, message):
    site.write_index(body)
    assert failures(run())['index'] == message

def empty_the_library(site):
    for episode_file in site.library.rglob('*.mp3'):
        episode_file.unlink()
    site.reindex()

def test_an_empty_index_fails_unless_allowed(site):
    empty_the_library(site)
    assert failures(run())['index'] == 'index has no episodes in it'

def test_an_empty_index_is_fine_when_allowed(site):
    empty_the_library(site)
    results = run(allow_empty=True)
    assert failures(results) == {}
    assert results['index'].detail.startswith('0 podcasts, 0 episodes, ')
    assert results['file-range'].detail == 'no episodes, skipped'

# ------------------------------------------------------------------ opml and feeds

def test_opml_must_be_named(site):
    index = site.index()
    del index['opml']
    site.write_index(index)
    assert failures(run()) == {'opml': 'index.json names no opml'}

@pytest.mark.usefixtures('site')
def test_opml_must_answer_as_opml(requests_mock):
    requests_mock.get(f'{ROOT}/feeds/podcasts.opml', text='<opml/>', headers={'Content-Type': 'application/octet-stream'})
    assert failures(run()) == {'opml': 'content type application/octet-stream, expected text/x-opml'}

def test_opml_must_list_every_podcast(site):
    (site.feeds / 'podcasts.opml').write_text('<opml><body><outline xmlUrl="x"/></body></opml>', encoding='utf-8')
    assert failures(run()) == {'opml': 'opml lists 1 feeds, index has 2 podcasts'}

def test_opml_must_exist(site):
    (site.feeds / 'podcasts.opml').unlink()
    assert failures(run()) == {'opml': 'status 404, expected 200'}

def test_every_podcast_needs_a_feed(site):
    index = site.index()
    del index['podcasts'][1]['feed']
    site.write_index(index)
    assert failures(run())['feeds'] == 'index.json names no feed for Beta'

def test_a_missing_feed_is_named(site):
    (site.feeds / 'Beta.xml').unlink()
    assert failures(run()) == {'feeds': 'feed of Beta: status 404, expected 200'}

def test_a_broken_feed_is_named(site):
    (site.feeds / 'Alpha_Show.xml').write_text('<rss><channel>', encoding='utf-8')
    assert failures(run())['feeds'].startswith('feed of Alpha Show does not parse: ')

def test_a_feed_must_hold_the_indexed_episodes(site):
    index = site.index()
    index['podcasts'][0]['episodes'].pop()
    site.write_index(index)
    assert failures(run()) == {'feeds': 'feed of Alpha Show has 2 episodes, index has 1'}

# ------------------------------------------------------------------ files

@pytest.mark.usefixtures('site')
def test_the_server_must_honour_a_range_request(requests_mock):
    requests_mock.get(re.compile(r'.*/files/.*'), content=b'whole file')
    assert failures(run()) == {'file-range': 'status 200 for a range request, expected 206'}

@pytest.mark.usefixtures('site')
def test_the_content_range_must_be_for_the_first_byte(requests_mock):
    requests_mock.get(re.compile(r'.*/files/.*'), status_code=206, content=b'x', headers={'Content-Range': 'bytes 5-5/9'})
    assert failures(run()) == {'file-range': 'content range bytes 5-5/9, expected bytes 0-0/<size>'}

@pytest.mark.usefixtures('site')
def test_one_byte_must_come_back(requests_mock):
    requests_mock.get(re.compile(r'.*/files/.*'), status_code=206, content=b'xyz', headers={'Content-Range': 'bytes 0-0/9'})
    assert failures(run()) == {'file-range': '2 bytes came back for a one byte range'}

def test_a_missing_file_is_a_failure(site):
    index = site.index()
    for podcast in index['podcasts']:
        for episode in podcast['episodes']:
            episode['path'] = 'gone.mp3'
    site.write_index(index)
    assert failures(run()) == {'file-range': 'status 404 for a range request, expected 206'}

def test_an_episode_without_a_path_is_a_failure(site):
    index = site.index()
    for podcast in index['podcasts']:
        for episode in podcast['episodes']:
            del episode['path']
    site.write_index(index)
    assert failures(run())['file-range'].endswith('has no path')

# ------------------------------------------------------------------ the token stays out of the output

@pytest.mark.usefixtures('site')
def test_an_error_that_names_the_url_does_not_leak_the_token(requests_mock):
    requests_mock.get(f'{ROOT}/', exc=requests.ConnectionError(f'cannot reach {ROOT}/ and {SERVER}/{TOKEN}/index.json'))
    detail = failures(run())['page']
    assert detail == f'cannot reach {SERVER}/<token>/ and {SERVER}/<token>/index.json'

def test_scrub_hides_a_token_in_both_spellings():
    runner = Smoke(SERVER, 'a b/c')
    try:
        assert runner.scrub('x a b/c y a%20b%2Fc z') == 'x <token> y <token> z'
        assert runner.url('index.json') == f'{SERVER}/a%20b%2Fc/index.json'
    finally:
        runner.close()

def test_the_base_url_may_end_in_a_slash():
    runner = Smoke(f'{SERVER}/', TOKEN)
    try:
        assert runner.url('') == f'{ROOT}/'
    finally:
        runner.close()

# ------------------------------------------------------------------ retries, against a real socket

class Flaky(BaseHTTPRequestHandler):
    '''
    Answers 503 until told otherwise, then a page
    '''
    refusals = 0
    served = []

    def serve(self):
        Flaky.served.append(self.path)
        if Flaky.refusals > 0:
            Flaky.refusals -= 1
            self.send_response(503)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        body = b'<html></html>'
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # BaseHTTPRequestHandler dispatches on this exact name
    do_GET = serve

@pytest.fixture(name='flaky')
def flaky_fixture():
    Flaky.refusals, Flaky.served = 0, []
    server = ThreadingHTTPServer(('127.0.0.1', 0), Flaky)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()
    server.server_close()
    thread.join()

def test_a_502_or_503_while_the_server_restarts_is_retried(flaky):
    Flaky.refusals = 2
    runner = Smoke(flaky, TOKEN, retries=3, backoff_factor=0)
    try:
        assert checks.check_page(runner, {}) == '13 bytes'
    finally:
        runner.close()
    assert Flaky.served == [f'/{TOKEN}/'] * 3

def test_retries_run_out(flaky):
    Flaky.refusals = 10
    runner = Smoke(flaky, TOKEN, retries=1, backoff_factor=0)
    try:
        results = run_checks(runner)
    finally:
        runner.close()
    page = results[0]
    assert (page.name, page.passed) == ('page', False)
    assert TOKEN not in page.detail
    assert len(Flaky.served) == 2 + 2 + 2    # page, wrong token, index: each tried twice, then given up on

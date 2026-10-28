from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import logging
import os
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from uuid import uuid4

from click.testing import CliRunner
from opentelemetry import _logs, trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.environment_variables import OTEL_LOGS_EXPORTER, OTEL_TRACES_EXPORTER
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.environment_variables import (
    OTEL_EXPORTER_OTLP_ENDPOINT,
    OTEL_EXPORTER_OTLP_LOGS_ENDPOINT,
    OTEL_EXPORTER_OTLP_LOGS_TIMEOUT,
    OTEL_EXPORTER_OTLP_TIMEOUT,
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
    OTEL_EXPORTER_OTLP_TRACES_TIMEOUT,
    OTEL_RESOURCE_ATTRIBUTES,
    OTEL_SDK_DISABLED,
    OTEL_SERVICE_NAME,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
import pytest
import requests
from yaml import dump

from hathor import telemetry
from hathor.cli import cli
from hathor.client import HathorClient
from hathor.database.tables import PodcastEpisode
from hathor.exc import SyncFailure
from hathor.podcast.archive import RSSManager
from tests.utils import temp_audio_file

KEY_URL = 'https://www.patreon.com/rss/someshow?auth=SECRETKEY&show=123'
OTEL_VARIABLES = (OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_LOGS_ENDPOINT, OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
                  OTEL_SDK_DISABLED, OTEL_LOGS_EXPORTER, OTEL_TRACES_EXPORTER, OTEL_SERVICE_NAME,
                  OTEL_RESOURCE_ATTRIBUTES, OTEL_EXPORTER_OTLP_TIMEOUT, OTEL_EXPORTER_OTLP_LOGS_TIMEOUT,
                  OTEL_EXPORTER_OTLP_TRACES_TIMEOUT)

def episode(n):
    return {'download_link': f'https://cdn.example/ep{n}.mp3?token-hash=SECRETSIG&e=1', 'title': f'Episode {n}',
            'date': datetime(2026, 10, n), 'description': f'about {n}'}

def reset_otel():
    '''
    Put OpenTelemetry back as if nothing had set it up. The API lets a provider be set once per
    process, which is right for hathor and wrong for a test suite
    '''
    for provider in (trace.get_tracer_provider(), get_logger_provider()):
        if isinstance(provider, (TracerProvider, LoggerProvider)):
            provider.shutdown()
    if RequestsInstrumentor().is_instrumented_by_opentelemetry:
        RequestsInstrumentor().uninstrument()
    trace._TRACER_PROVIDER = None #pylint:disable=protected-access
    trace._TRACER_PROVIDER_SET_ONCE._done = False #pylint:disable=protected-access
    _logs._internal._LOGGER_PROVIDER = None #pylint:disable=protected-access
    _logs._internal._LOGGER_PROVIDER_SET_ONCE._done = False #pylint:disable=protected-access
    telemetry.TRACER._real_tracer = None #pylint:disable=protected-access

def flush():
    '''What the SDK does as the process exits'''
    trace.get_tracer_provider().force_flush()
    get_logger_provider().force_flush()

def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

@pytest.fixture(autouse=True, name='clean_environment')
def clean_environment_fixture(monkeypatch):
    for name in OTEL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    yield
    reset_otel()

@pytest.fixture(name='exporters')
def exporters_fixture(monkeypatch):
    '''Telemetry set up as it is when hathor loads with an endpoint set, the exports kept in memory instead of sent'''
    spans, logs = InMemorySpanExporter(), InMemoryLogRecordExporter()
    monkeypatch.setattr(telemetry, '_span_exporter', lambda: spans)
    monkeypatch.setattr(telemetry, '_log_exporter', lambda: logs)
    monkeypatch.setenv(OTEL_EXPORTER_OTLP_ENDPOINT, 'http://collector.invalid:4318')
    telemetry.setup_otlp()
    return spans, logs

@pytest.fixture(name='logger')
def logger_fixture():
    logger = logging.getLogger(f'hathor-telemetry-{uuid4().hex}')
    logger.setLevel(logging.DEBUG)
    yield logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

@pytest.fixture(name='world')
def world_fixture(tmp_path, mocker, logger, exporters):
    del exporters
    mocker.patch.object(RSSManager, 'broadcast_update', return_value=[episode(1), episode(2)])
    client = HathorClient(podcast_directory=tmp_path, logger=logger)
    client.podcast_create('rss', KEY_URL, 'Some Show')
    yield client
    client.close()

def everything_exported(spans, logs):
    '''All exported text in one string, to search for a secret'''
    parts = []
    for finished in spans.get_finished_spans():
        parts.append(finished.name)
        parts.append(str(dict(finished.attributes)))
        parts.append(str(finished.status.description))
        parts.append(str([(event.name, dict(event.attributes)) for event in finished.events]))
    for data in logs.get_finished_logs():
        parts.append(str(data.log_record.body))
        parts.append(str(dict(data.log_record.attributes)))
    return '\n'.join(parts)

# ------------------------------------------------------------------ off by default

def test_without_an_endpoint_nothing_is_set_up_and_a_run_is_unchanged(tmp_path, mocker, logger):
    telemetry.setup_otlp()
    mocker.patch.object(RSSManager, 'broadcast_update', return_value=[episode(1)])
    client = HathorClient(podcast_directory=tmp_path, logger=logger)
    client.podcast_create('rss', 'https://feed.example/rss', 'Show')
    assert len(client.episode_sync()) == 1
    assert not isinstance(trace.get_tracer_provider(), TracerProvider)
    assert not isinstance(get_logger_provider(), LoggerProvider)
    assert not RequestsInstrumentor().is_instrumented_by_opentelemetry
    assert not logger.handlers
    client.close()

@pytest.mark.parametrize('environment, logs, traces', [
    ({OTEL_EXPORTER_OTLP_ENDPOINT: 'http://c:4318'}, True, True),
    ({OTEL_EXPORTER_OTLP_LOGS_ENDPOINT: 'http://c:4318/v1/logs'}, True, False),
    ({OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: 'http://c:4318/v1/traces'}, False, True),
    ({OTEL_EXPORTER_OTLP_ENDPOINT: 'http://c:4318', OTEL_SDK_DISABLED: 'True'}, False, False),
    ({OTEL_EXPORTER_OTLP_ENDPOINT: 'http://c:4318', OTEL_TRACES_EXPORTER: 'none'}, True, False),
    ({OTEL_EXPORTER_OTLP_ENDPOINT: 'http://c:4318', OTEL_LOGS_EXPORTER: 'none'}, False, True),
    ({OTEL_EXPORTER_OTLP_ENDPOINT: '  '}, False, False),
])
def test_the_environment_picks_the_signals(monkeypatch, environment, logs, traces):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    assert telemetry.signal_enabled('logs') is logs
    assert telemetry.signal_enabled('traces') is traces
    telemetry.setup_otlp()
    assert isinstance(get_logger_provider(), LoggerProvider) is logs
    assert isinstance(trace.get_tracer_provider(), TracerProvider) is traces

def test_setting_up_twice_keeps_the_first_providers(exporters):
    del exporters
    tracer_provider, logger_provider = trace.get_tracer_provider(), get_logger_provider()
    telemetry.setup_otlp()
    assert trace.get_tracer_provider() is tracer_provider and get_logger_provider() is logger_provider

def test_the_service_is_named_hathor_unless_the_environment_says_otherwise(monkeypatch, exporters):
    del exporters
    assert trace.get_tracer_provider().resource.attributes['service.name'] == 'hathor'
    reset_otel()
    monkeypatch.setenv(OTEL_SERVICE_NAME, 'hathor-sync')
    telemetry.setup_otlp()
    assert trace.get_tracer_provider().resource.attributes['service.name'] == 'hathor-sync'
    reset_otel()
    monkeypatch.delenv(OTEL_SERVICE_NAME)
    monkeypatch.setenv(OTEL_RESOURCE_ATTRIBUTES, 'service.name=from-attributes,k8s.namespace=hathor')
    telemetry.setup_otlp()
    assert trace.get_tracer_provider().resource.attributes['service.name'] == 'from-attributes'

def test_the_timeout_is_ours_unless_the_environment_sets_one(monkeypatch):
    assert telemetry._timeout_kwargs('logs') == {'timeout': telemetry.EXPORT_TIMEOUT} #pylint:disable=protected-access
    monkeypatch.setenv(OTEL_EXPORTER_OTLP_TIMEOUT, '30000')
    assert not telemetry._timeout_kwargs('logs') #pylint:disable=protected-access
    monkeypatch.delenv(OTEL_EXPORTER_OTLP_TIMEOUT)
    monkeypatch.setenv(OTEL_EXPORTER_OTLP_TRACES_TIMEOUT, '30000')
    assert not telemetry._timeout_kwargs('traces') #pylint:disable=protected-access

# ------------------------------------------------------------------ spans and logs

def test_a_sync_exports_a_span_tree_and_its_log_lines(world, exporters):
    spans, logs = exporters
    world.podcast_sync(download_episodes=False)
    flush()
    finished = {s.name: s for s in spans.get_finished_spans()}
    assert set(finished) == {'hathor.podcast_sync', 'hathor.podcast.sync', 'hathor.broadcast_update'}
    run, one, listing = finished['hathor.podcast_sync'], finished['hathor.podcast.sync'], finished['hathor.broadcast_update']
    assert run.parent is None
    assert one.parent.span_id == run.context.span_id
    assert listing.parent.span_id == one.context.span_id
    assert dict(one.attributes) == {'podcast_id': 1, 'podcast_name': 'Some Show', 'archive_type': 'rss',
                                    'stage': 'episode sync', 'new_episodes': 2}
    assert dict(listing.attributes)['episodes_found'] == 2
    assert dict(run.attributes)['failures'] == 0
    [syncing] = [data.log_record for data in logs.get_finished_logs() if data.log_record.body == 'Syncing episodes of podcast 1 (Some Show)']
    assert syncing.trace_id == run.context.trace_id                       # log lines inside a span carry its trace

def test_downloads_get_a_span_per_episode_with_stages(world, exporters, mocker):
    spans, _ = exporters
    world.episode_sync()
    with temp_audio_file() as audio:
        mocker.patch.object(RSSManager, 'episode_download', return_value=(world.podcast_directory / 'a.mp3', 10))
        mocker.patch('hathor.client.tags_update')
        mocker.patch('pathlib.Path.resolve', return_value=audio)
        world.episode_download([1])
    flush()
    finished = {s.name: s for s in spans.get_finished_spans()}
    one = finished['hathor.episode.download']
    assert dict(one.attributes) == {'episode_id': 1, 'podcast_id': 1, 'podcast_name': 'Some Show', 'archive_type': 'rss',
                                    'stage': 'download', 'downloaded': True}
    assert finished['hathor.archive_download'].parent.span_id == one.context.span_id
    assert finished['hathor.tag_update'].parent.span_id == one.context.span_id
    assert finished['hathor.episode_download'].parent is None
    assert dict(finished['hathor.episode_download'].attributes) == {'episodes_requested': 1, 'episodes_downloaded': 1, 'failures': 0}

def test_cleanup_gets_a_span(world, exporters):
    spans, _ = exporters
    world.podcast_update(1, max_allowed=1)
    world.episode_sync()
    for stored in world.db_session.query(PodcastEpisode):
        stored.file_path = str(world.podcast_directory / f'{stored.id}.mp3')
    world.db_session.commit()
    world.podcast_sync(sync_web_episodes=False)
    flush()
    assert 'hathor.cleanup' in [s.name for s in spans.get_finished_spans()]

def test_a_failed_podcast_marks_its_spans_and_the_run_still_reports(world, exporters, mocker):
    spans, logs = exporters
    mocker.patch.object(RSSManager, 'broadcast_update', side_effect=RuntimeError(f'cannot fetch {KEY_URL}'))
    with pytest.raises(SyncFailure):
        world.podcast_sync(download_episodes=False)
    flush()
    finished = {s.name: s for s in spans.get_finished_spans()}
    for name in ('hathor.broadcast_update', 'hathor.podcast.sync', 'hathor.podcast_sync'):
        assert finished[name].status.status_code == StatusCode.ERROR
    assert finished['hathor.podcast.sync'].status.description == 'RuntimeError: cannot fetch https://www.patreon.com/rss/someshow?<hidden>'
    assert dict(finished['hathor.podcast_sync'].attributes)['failures'] == 1
    assert 'SECRETKEY' not in everything_exported(spans, logs)             # the recorded exception included

def test_sigterm_ends_the_open_spans_so_they_are_exported(exporters):
    spans, _ = exporters
    previous = signal.getsignal(signal.SIGTERM)
    telemetry.exit_on_sigterm()
    try:
        with pytest.raises(SystemExit) as caught:
            with telemetry.TRACER.start_as_current_span('hathor.stuck'):
                os.kill(os.getpid(), signal.SIGTERM)
                time.sleep(5)
    finally:
        signal.signal(signal.SIGTERM, previous)
    flush()
    assert caught.value.code == 143
    [stuck] = spans.get_finished_spans()
    assert stuck.name == 'hathor.stuck' and stuck.end_time > stuck.start_time        # ended, so exported, with how long it ran

# ------------------------------------------------------------------ masking

def test_a_feed_url_with_a_key_is_in_no_log_record_and_no_span(world, exporters, mocker):
    spans, logs = exporters
    world.logger.setLevel(logging.DEBUG)
    world.episode_sync()
    world.episode_sync()                                                  # the second sees the episodes as known: a DEBUG line with their urls
    mocker.patch.object(RSSManager, 'broadcast_update', side_effect=RuntimeError(f'cannot fetch {KEY_URL}'))
    with pytest.raises(SyncFailure):
        world.episode_sync()
    flush()
    text = everything_exported(spans, logs)
    assert 'SECRETKEY' not in text and 'SECRETSIG' not in text and 'auth=' not in text
    assert 'has same url' in text                                         # the line that carried the url was exported, masked
    assert 'Traceback for the failure above' in text

def test_the_log_filter_exports_the_message_and_traceback_only(logger, exporters):
    _, logs = exporters
    telemetry.attach(logger)
    try:
        raise ValueError(f'bad {KEY_URL}')
    except ValueError:
        logger.error('failed on %s', KEY_URL, exc_info=True, extra={'cookie': 'COOKIEVALUE'})
    flush()
    [data] = logs.get_finished_logs()
    record = data.log_record
    assert record.body.startswith('failed on https://www.patreon.com/rss/someshow?<hidden>\nTraceback')
    assert 'ValueError: bad https://www.patreon.com/rss/someshow?<hidden>' in record.body
    assert record.severity_text == 'ERROR'
    assert 'COOKIEVALUE' not in everything_exported(InMemorySpanExporter(), logs)    # extra fields stay behind

def raised_exc_info():
    try:
        raise ValueError('boom')
    except ValueError:
        return sys.exc_info()

def test_the_filter_copies_the_record_so_other_handlers_see_it_whole():
    record = logging.LogRecord('x', logging.ERROR, __file__, 1, 'fetching %s', (KEY_URL,), raised_exc_info())
    record.cookie = 'COOKIEVALUE'
    masked = telemetry.MaskingFilter().filter(record)
    assert masked is not record
    assert record.args == (KEY_URL,) and record.exc_info and record.cookie == 'COOKIEVALUE'
    assert 'SECRETKEY' not in masked.getMessage() and not masked.exc_info and not hasattr(masked, 'cookie')

def test_the_span_exporter_hides_urls_in_attributes_status_and_events():
    spans = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(telemetry.MaskingSpanExporter(spans)))
    tracer = provider.get_tracer('test')
    with pytest.raises(RuntimeError):
        with tracer.start_as_current_span('masked', attributes={'url': KEY_URL, 'urls': [KEY_URL, 'plain'], 'count': 3, 'ok': True}):
            raise RuntimeError(f'failed on {KEY_URL}')
    with tracer.start_as_current_span('fine'):
        pass
    masked, fine = spans.get_finished_spans()
    assert dict(masked.attributes) == {'url': 'https://www.patreon.com/rss/someshow?<hidden>',
                                       'urls': ('https://www.patreon.com/rss/someshow?<hidden>', 'plain'), 'count': 3, 'ok': True}
    assert masked.status.description == 'RuntimeError: failed on https://www.patreon.com/rss/someshow?<hidden>'
    assert masked.status.status_code == StatusCode.ERROR
    assert masked.events and all('SECRETKEY' not in str(dict(event.attributes)) for event in masked.events)
    assert fine.status.status_code == StatusCode.UNSET and fine.status.description is None
    assert telemetry.MaskingSpanExporter(spans).force_flush() is True
    telemetry.MaskingSpanExporter(spans).shutdown()

class Server(BaseHTTPRequestHandler):
    '''Answers a GET and keeps what an OTLP exporter POSTs'''
    received = []
    def do_GET(self): #pylint:disable=invalid-name
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'ok')
    def do_POST(self): #pylint:disable=invalid-name
        Server.received.append((self.path, self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(200)
        self.send_header('Content-Length', '0')
        self.end_headers()
    def log_message(self, *_): #pylint:disable=arguments-differ
        pass

@pytest.fixture(name='server')
def server_fixture():
    Server.received = []
    server = HTTPServer(('127.0.0.1', 0), Server)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join()

def test_http_calls_get_a_span_without_the_key(server, exporters):
    spans, logs = exporters
    url = f'http://127.0.0.1:{server.server_port}/rss?auth=SECRETKEY'
    assert requests.get(url, timeout=5).text == 'ok'
    with pytest.raises(requests.exceptions.ConnectionError):
        requests.get(f'http://127.0.0.1:{closed_port()}/rss?auth=SECRETKEY', timeout=5)
    flush()
    ok, failed = spans.get_finished_spans()
    assert dict(ok.attributes)['http.url'] == f'http://127.0.0.1:{server.server_port}/rss?<hidden>'
    assert dict(ok.attributes)['http.status_code'] == 200
    assert failed.status.status_code == StatusCode.ERROR
    assert 'Max retries exceeded with url: /rss?<hidden>' in str(dict(failed.events[0].attributes))    # the message that names the path and query
    assert 'SECRETKEY' not in everything_exported(spans, logs)

# ------------------------------------------------------------------ never in the way

def test_setup_failing_is_a_warning_and_the_sync_still_works(tmp_path, mocker, monkeypatch, logger, caplog):
    monkeypatch.setenv(OTEL_EXPORTER_OTLP_ENDPOINT, 'http://collector.invalid:4318')
    mocker.patch.object(telemetry, '_span_exporter', side_effect=RuntimeError('no go https://c.invalid/?k=SECRETKEY'))
    mocker.patch.object(RSSManager, 'broadcast_update', return_value=[episode(1)])
    with caplog.at_level(logging.WARNING):
        telemetry.setup_otlp()
    client = HathorClient(podcast_directory=tmp_path, logger=logger)
    client.podcast_create('rss', 'https://feed.example/rss', 'Show')
    assert len(client.episode_sync()) == 1
    assert 'could not start' in caplog.text and 'SECRETKEY' not in caplog.text
    assert not isinstance(trace.get_tracer_provider(), TracerProvider)
    client.close()

def test_an_unreachable_collector_costs_nothing_but_the_end_of_the_run(tmp_path, mocker, monkeypatch, logger):
    monkeypatch.setenv(OTEL_EXPORTER_OTLP_ENDPOINT, f'http://127.0.0.1:{closed_port()}')    # nothing listens: refused at once
    monkeypatch.setattr(telemetry, 'EXPORT_TIMEOUT', 1)
    mocker.patch.object(RSSManager, 'broadcast_update', return_value=[episode(1), episode(2)])
    telemetry.setup_otlp()
    client = HathorClient(podcast_directory=tmp_path, logger=logger)
    client.podcast_create('rss', 'https://feed.example/rss', 'Show')
    started = time.monotonic()
    new = client.episode_sync()
    client.episode_sync()
    assert time.monotonic() - started < 2                                # the sync itself never waits on an export
    flush()                                                              # what the SDK does as the process exits
    assert len(new) == 2
    assert time.monotonic() - started < 2 + 2 * telemetry.EXPORT_TIMEOUT * 2
    client.close()

def test_a_short_run_delivers_its_telemetry_as_the_process_exits(tmp_path, server):
    script = textwrap.dedent('''
        import logging, sys
        from pathlib import Path
        import requests
        from hathor.client import HathorClient
        from hathor.podcast.archive import RSSManager
        RSSManager.broadcast_update = lambda *args, **kwargs: []
        logger = logging.getLogger('hathor')
        logger.setLevel(logging.INFO)
        client = HathorClient(podcast_directory=Path(sys.argv[1]), logger=logger)
        client.podcast_create('rss', sys.argv[2], 'Some Show')
        logger.warning('fetching %s', sys.argv[2])
        requests.get(sys.argv[2], timeout=5)
        client.episode_sync()
        client.close()
    ''')
    feed = f'http://127.0.0.1:{server.server_port}/rss?auth=SECRETKEY'
    environment = {key: value for key, value in os.environ.items() if not key.startswith('OTEL_')}
    environment.update({OTEL_EXPORTER_OTLP_ENDPOINT: f'http://127.0.0.1:{server.server_port}', OTEL_SERVICE_NAME: 'hathor-sync'})
    subprocess.run([sys.executable, '-I', '-c', script, str(tmp_path), feed], check=True, env=environment, timeout=60)
    assert {path for path, _ in Server.received} == {'/v1/traces', '/v1/logs'}
    payload = b''.join(body for _, body in Server.received)
    assert b'hathor.episode_sync' in payload and b'hathor-sync' in payload and b'Syncing episodes of podcast 1' in payload
    assert b'SECRETKEY' not in payload and b'SECRETSIG' not in payload

# ------------------------------------------------------------------ attaching and the cli

def test_attaching_does_nothing_without_a_log_export(logger, monkeypatch):
    telemetry.attach(logger)
    assert not logger.handlers                                           # nothing is set up
    monkeypatch.setattr(telemetry, '_span_exporter', InMemorySpanExporter)
    monkeypatch.setenv(OTEL_EXPORTER_OTLP_TRACES_ENDPOINT, 'http://collector.invalid:4318/v1/traces')
    telemetry.setup_otlp()
    telemetry.attach(logger)
    assert not logger.handlers                                           # traces only: no log export to attach to

def test_attaching_twice_adds_one_handler(logger, exporters):
    del exporters
    telemetry.attach(logger)
    telemetry.attach(logger)
    assert len([h for h in logger.handlers if isinstance(h, LoggingHandler)]) == 1

def test_a_cli_run_exports_and_will_unwind_on_sigterm(tmp_path, mocker, exporters):
    spans, logs = exporters
    mocker.patch.object(RSSManager, 'broadcast_update', return_value=[])
    config = tmp_path / 'config.yml'
    config.write_text(dump({'hathor': {'database_connection_string': f'sqlite:///{tmp_path / "h.db"}', 'podcast_directory': str(tmp_path / 'p')},
                            'logging': {'log_level': 10}}), encoding='utf-8')
    previous = signal.getsignal(signal.SIGTERM)
    try:
        runner = CliRunner()
        runner.invoke(cli, ['-c', str(config), 'podcast', 'create', 'rss', 'https://feed.example/rss', 'Show'])
        result = runner.invoke(cli, ['-c', str(config), 'podcast', 'sync', '--no-download-episodes'])
        assert result.exit_code == 0
        flush()
        assert 'hathor.podcast_sync' in [s.name for s in spans.get_finished_spans()]
        assert logs.get_finished_logs()
        assert signal.getsignal(signal.SIGTERM) is not previous           # a killed run now unwinds and exits
    finally:
        signal.signal(signal.SIGTERM, previous)
        for handler in list(logging.getLogger('hathor').handlers):
            handler.close()
            logging.getLogger('hathor').removeHandler(handler)

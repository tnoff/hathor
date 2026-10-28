from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from uuid import uuid4

from click.testing import CliRunner
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
import pytest
from yaml import dump

from hathor import telemetry
from hathor.cli import cli
from hathor.client import HathorClient
from hathor.database.tables import PodcastEpisode
from hathor.exc import SyncFailure
from hathor.podcast.archive import RSSManager
from tests.utils import temp_audio_file

KEY_URL = 'https://www.patreon.com/rss/someshow?auth=SECRETKEY&show=123'
OTEL_VARIABLES = ('OTEL_EXPORTER_OTLP_ENDPOINT', 'OTEL_EXPORTER_OTLP_LOGS_ENDPOINT', 'OTEL_EXPORTER_OTLP_TRACES_ENDPOINT',
                  'OTEL_SDK_DISABLED', 'OTEL_LOGS_EXPORTER', 'OTEL_TRACES_EXPORTER', 'OTEL_SERVICE_NAME',
                  'OTEL_RESOURCE_ATTRIBUTES', 'OTEL_EXPORTER_OTLP_TIMEOUT', 'OTEL_EXPORTER_OTLP_LOGS_TIMEOUT',
                  'OTEL_EXPORTER_OTLP_TRACES_TIMEOUT')

def episode(n):
    return {'download_link': f'https://cdn.example/ep{n}.mp3?token-hash=SECRETSIG&e=1', 'title': f'Episode {n}',
            'date': datetime(2026, 10, n), 'description': f'about {n}'}

@pytest.fixture(autouse=True, name='clean_environment')
def clean_environment_fixture(monkeypatch):
    for name in OTEL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    yield
    while telemetry.enabled():
        telemetry.shutdown(timeout=1)
    logging.getLogger('opentelemetry').handlers.clear()

@pytest.fixture(name='exporters')
def exporters_fixture(monkeypatch):
    '''Telemetry switched on, with the exports kept in memory instead of sent'''
    spans, logs = InMemorySpanExporter(), InMemoryLogRecordExporter()
    monkeypatch.setattr(telemetry, '_span_exporter', lambda: spans)
    monkeypatch.setattr(telemetry, '_log_exporter', lambda: logs)
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://collector.invalid:4318')
    return spans, logs

@pytest.fixture(name='logger')
def logger_fixture():
    logger = logging.getLogger(f'hathor-telemetry-{uuid4().hex}')
    logger.setLevel(logging.DEBUG)
    yield logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

@pytest.fixture(name='world')
def world_fixture(tmp_path, mocker, logger):
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

def test_without_an_endpoint_nothing_changes_and_nothing_is_imported(tmp_path):
    script = (
        'import sys\n'
        'from pathlib import Path\n'
        'from hathor.client import HathorClient\n'
        f'client = HathorClient(podcast_directory=Path({str(tmp_path)!r}))\n'
        'client.podcast_create("rss", "https://feed.example/rss", "Show")\n'
        'client.podcast_sync(sync_web_episodes=False, download_episodes=False)\n'
        'client.close()\n'
        'print(sorted(m for m in sys.modules if m.startswith("opentelemetry")))\n'
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith('OTEL_')}
    result = subprocess.run([sys.executable, '-I', '-c', script], capture_output=True, text=True, check=True, env=env)
    assert result.stdout.strip() == '[]'

def test_configure_does_nothing_without_an_endpoint(logger):
    assert telemetry.configure(logger) is False
    assert not telemetry.enabled()
    assert not logger.handlers

def test_spans_do_nothing_without_telemetry():
    with telemetry.span('anything', podcast_id=1) as handle:
        handle.set(more=2)
        handle.fail(RuntimeError('x'))
    assert handle is telemetry.NOOP_SPAN
    telemetry.shutdown()                                                 # and shutting down nothing is fine

@pytest.mark.parametrize('environment, logs, traces', [
    ({'OTEL_EXPORTER_OTLP_ENDPOINT': 'http://c:4318'}, True, True),
    ({'OTEL_EXPORTER_OTLP_LOGS_ENDPOINT': 'http://c:4318/v1/logs'}, True, False),
    ({'OTEL_EXPORTER_OTLP_TRACES_ENDPOINT': 'http://c:4318/v1/traces'}, False, True),
    ({'OTEL_EXPORTER_OTLP_ENDPOINT': 'http://c:4318', 'OTEL_SDK_DISABLED': 'True'}, False, False),
    ({'OTEL_EXPORTER_OTLP_ENDPOINT': 'http://c:4318', 'OTEL_TRACES_EXPORTER': 'none'}, True, False),
    ({'OTEL_EXPORTER_OTLP_ENDPOINT': 'http://c:4318', 'OTEL_LOGS_EXPORTER': 'none'}, False, True),
    ({'OTEL_EXPORTER_OTLP_ENDPOINT': '  '}, False, False),
])
def test_the_environment_picks_the_signals(monkeypatch, environment, logs, traces):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    assert telemetry.signal_enabled('logs') is logs
    assert telemetry.signal_enabled('traces') is traces

# ------------------------------------------------------------------ spans and logs

def test_a_sync_exports_a_span_tree_and_its_log_lines(world, exporters):
    spans, logs = exporters
    assert telemetry.configure(world.logger)
    world.podcast_sync(download_episodes=False)
    telemetry.shutdown()                                                 # what close() does at the end of a run
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
    bodies = [data.log_record.body for data in logs.get_finished_logs()]
    assert 'Syncing episodes of podcast 1 (Some Show)' in bodies
    assert logs.get_finished_logs()[0].log_record.trace_id                # log lines inside a span carry its trace

def test_the_client_switches_telemetry_on_from_the_environment_and_close_flushes(tmp_path, mocker, exporters, logger):
    spans, logs = exporters
    mocker.patch.object(RSSManager, 'broadcast_update', return_value=[])
    client = HathorClient(podcast_directory=tmp_path, logger=logger)
    assert telemetry.enabled()
    client.podcast_create('rss', 'https://feed.example/rss', 'Show')
    client.episode_sync()
    assert not spans.get_finished_spans()                                 # the batch has not been sent yet: a run this short ends first
    client.close()
    assert not telemetry.enabled()
    assert [s.name for s in spans.get_finished_spans()] == ['hathor.broadcast_update', 'hathor.podcast.sync', 'hathor.episode_sync']
    assert logs.get_finished_logs()

def test_downloads_get_a_span_per_episode_with_stages(world, exporters, mocker):
    spans, _ = exporters
    telemetry.configure(world.logger)
    world.episode_sync()
    with temp_audio_file() as audio:
        mocker.patch.object(RSSManager, 'episode_download', return_value=(world.podcast_directory / 'a.mp3', 10))
        mocker.patch('hathor.client.tags_update')
        mocker.patch('pathlib.Path.resolve', return_value=audio)
        world.episode_download([1])
    telemetry.shutdown()
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
    telemetry.configure(world.logger)
    world.podcast_update(1, max_allowed=1)
    world.episode_sync()
    for stored in world.db_session.query(PodcastEpisode):
        stored.file_path = str(world.podcast_directory / f'{stored.id}.mp3')
    world.db_session.commit()
    world.podcast_sync(sync_web_episodes=False)
    telemetry.shutdown()
    assert 'hathor.cleanup' in [s.name for s in spans.get_finished_spans()]

def test_a_failed_podcast_marks_its_span_and_the_run_still_reports(world, exporters, mocker):
    spans, _ = exporters
    telemetry.configure(world.logger)
    mocker.patch.object(RSSManager, 'broadcast_update', side_effect=RuntimeError(f'cannot fetch {KEY_URL}'))
    with pytest.raises(SyncFailure):
        world.podcast_sync(download_episodes=False)
    telemetry.shutdown()
    finished = {s.name: s for s in spans.get_finished_spans()}
    for name in ('hathor.broadcast_update', 'hathor.podcast.sync', 'hathor.podcast_sync'):
        assert finished[name].status.status_code == StatusCode.ERROR
        assert dict(finished[name].attributes)['exception.type'] in ('RuntimeError', 'SyncFailure')
    assert finished['hathor.podcast.sync'].status.description == 'RuntimeError: cannot fetch https://www.patreon.com/rss/someshow'
    assert dict(finished['hathor.podcast_sync'].attributes)['failures'] == 1

# ------------------------------------------------------------------ masking

def test_a_feed_url_with_a_key_is_in_no_log_record_and_no_span(world, exporters, mocker):
    spans, logs = exporters
    world.logger.setLevel(logging.DEBUG)
    telemetry.configure(world.logger)
    world.episode_sync()
    world.episode_sync()                                                  # the second sees the episodes as known: a DEBUG line with their urls
    mocker.patch.object(RSSManager, 'broadcast_update', side_effect=RuntimeError(f'cannot fetch {KEY_URL}'))
    with pytest.raises(SyncFailure):
        world.episode_sync()
    with telemetry.span('hathor.manual', feed=KEY_URL, detail=f'fetched {KEY_URL} ok') as handle:
        handle.set(again=KEY_URL, count=3, ok=True, nothing=None)
    telemetry.shutdown()
    text = everything_exported(spans, logs)
    assert 'SECRETKEY' not in text and 'SECRETSIG' not in text and 'auth=' not in text
    assert 'has same url' in text                                         # the line that carried the url was exported, masked
    assert 'Traceback for the failure above' in text
    manual = [s for s in spans.get_finished_spans() if s.name == 'hathor.manual'][0]
    assert dict(manual.attributes) == {'feed': 'https://www.patreon.com/rss/someshow', 'detail': 'fetched https://www.patreon.com/rss/someshow ok',
                                       'again': 'https://www.patreon.com/rss/someshow', 'count': 3, 'ok': True}

def test_the_log_handler_exports_the_message_and_traceback_only(logger, exporters):
    _, logs = exporters
    telemetry.configure(logger)
    try:
        raise ValueError(f'bad {KEY_URL}')
    except ValueError:
        logger.error('failed on %s', KEY_URL, exc_info=True, extra={'cookie': 'COOKIEVALUE'})
    telemetry.shutdown()
    [data] = logs.get_finished_logs()
    record = data.log_record
    assert record.body == 'failed on https://www.patreon.com/rss/someshow?<hidden>'
    assert record.severity_text == 'ERROR' and record.severity_number.value == 17 and record.severity_number.name == 'ERROR'
    assert record.attributes['exception.type'] == 'ValueError'
    assert 'ValueError: bad https://www.patreon.com/rss/someshow?<hidden>' in record.attributes['exception.stacktrace']
    assert 'COOKIEVALUE' not in everything_exported(InMemorySpanExporter(), logs)    # extra fields stay behind

def test_levels_map_to_otel_names(logger, exporters):
    _, logs = exporters
    telemetry.configure(logger)
    logger.warning('w')
    logger.critical('c')
    telemetry.shutdown()
    assert [d.log_record.severity_text for d in logs.get_finished_logs()] == ['WARN', 'FATAL']

def test_a_record_that_cannot_be_formatted_is_dropped_quietly(logger, exporters):
    _, logs = exporters
    telemetry.configure(logger)
    handler = [h for h in logger.handlers if isinstance(h, telemetry.OtlpLogHandler)][0]
    handler.emit(logging.LogRecord('x', logging.INFO, __file__, 1, 'needs %s and %s', ('one',), None))
    telemetry.shutdown()
    assert not logs.get_finished_logs()

# ------------------------------------------------------------------ never in the way

def test_setup_failing_is_a_warning_and_the_sync_still_works(tmp_path, mocker, monkeypatch, logger, caplog):
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://collector.invalid:4318/?k=SECRETKEY')
    mocker.patch.object(telemetry, '_build_providers', side_effect=RuntimeError('no go https://c.invalid/?k=SECRETKEY'))
    mocker.patch.object(RSSManager, 'broadcast_update', return_value=[episode(1)])
    with caplog.at_level(logging.WARNING):
        client = HathorClient(podcast_directory=tmp_path, logger=logger)
    assert not telemetry.enabled()
    client.podcast_create('rss', 'https://feed.example/rss', 'Show')
    assert len(client.episode_sync()) == 1
    assert 'could not start' in caplog.text and 'SECRETKEY' not in caplog.text
    client.close()

def test_an_unreachable_collector_costs_nothing_but_one_warning(tmp_path, mocker, monkeypatch, logger, caplog):
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://127.0.0.1:1')        # nothing listens: refused at once
    monkeypatch.setattr(telemetry, 'EXPORT_TIMEOUT', 1)
    mocker.patch.object(RSSManager, 'broadcast_update', return_value=[episode(1), episode(2)])
    with caplog.at_level(logging.WARNING):
        client = HathorClient(podcast_directory=tmp_path, logger=logger)
        client.podcast_create('rss', 'https://feed.example/rss', 'Show')
        started = time.monotonic()
        new = client.episode_sync()
        client.episode_sync()
        assert time.monotonic() - started < 2                            # the sync itself never waits on an export
        client.close()
    assert len(new) == 2
    assert time.monotonic() - started < telemetry.SHUTDOWN_TIMEOUT + 2
    assert len([r for r in caplog.records if 'Telemetry export is failing' in r.getMessage()]) <= 1

def test_a_collector_that_never_answers_cannot_hold_the_process(monkeypatch, logger, caplog):
    class Stuck:
        def __init__(self):
            self.release = threading.Event()
        def force_flush(self, _timeout_millis):
            self.release.wait(5)
        def shutdown(self):
            pass
    stuck = Stuck()
    state = telemetry._Telemetry(None, stuck, None) #pylint:disable=protected-access
    state.error_handler = telemetry.ExportErrorHandler(logger)
    state.loggers, state.log_handler = [logger], telemetry.OtlpLogHandler(None, None, None)
    logger.addHandler(state.log_handler)
    monkeypatch.setattr(telemetry, '_STATE', state)
    started = time.monotonic()
    with caplog.at_level(logging.DEBUG):
        telemetry.shutdown(timeout=0.2)
    assert time.monotonic() - started < 2
    assert 'giving up' in caplog.text
    stuck.release.set()

def test_a_provider_that_raises_while_stopping_is_ignored(monkeypatch, logger):
    class Broken:
        def force_flush(self, _timeout_millis):
            raise RuntimeError('boom')
    state = telemetry._Telemetry(None, Broken(), None) #pylint:disable=protected-access
    state.error_handler = telemetry.ExportErrorHandler(logger)
    monkeypatch.setattr(telemetry, '_STATE', state)
    telemetry.shutdown(timeout=1)
    assert not telemetry.enabled()

@pytest.mark.usefixtures('exporters')
def test_only_the_first_export_error_is_passed_on(logger, caplog):
    telemetry.configure(logger)
    sdk_logger = logging.getLogger('opentelemetry.exporter.otlp.proto.http.trace_exporter')
    with caplog.at_level(logging.WARNING):
        sdk_logger.error('Failed to export batch: https://c.invalid/v1/traces?k=SECRETKEY')
        sdk_logger.error('Failed to export batch again')
    messages = [r.getMessage() for r in caplog.records if 'Telemetry export is failing' in r.getMessage()]
    assert messages == ['Telemetry export is failing, continuing without it: Failed to export batch: https://c.invalid/v1/traces']

def test_an_error_handler_whose_logger_breaks_stays_quiet():
    class Broken:
        def warning(self, _message):
            raise RuntimeError('boom')
    telemetry.ExportErrorHandler(Broken()).emit(logging.LogRecord('x', logging.ERROR, __file__, 1, 'm', (), None))

@pytest.mark.usefixtures('exporters')
def test_a_tracer_that_breaks_gives_a_noop_span(monkeypatch, logger):
    class Broken:
        def start_as_current_span(self, *_, **__):
            raise RuntimeError('boom')
    telemetry.configure(logger)
    monkeypatch.setattr(telemetry._STATE, 'tracer', Broken()) #pylint:disable=protected-access
    with telemetry.span('x') as handle:
        pass
    assert handle is telemetry.NOOP_SPAN

def test_ending_a_span_that_breaks_is_ignored():
    class Broken:
        def __exit__(self, *_):
            raise RuntimeError('boom')
    telemetry._end(Broken(), None) #pylint:disable=protected-access

def test_a_span_that_breaks_while_annotated_is_ignored():
    class Broken:
        def set_attribute(self, *_):
            raise RuntimeError('boom')
    handle = telemetry._Span(Broken()) #pylint:disable=protected-access
    handle.set(a=1)
    handle.fail(RuntimeError('x'))

def test_logs_only_gives_no_spans(logger, monkeypatch):
    logs = InMemoryLogRecordExporter()
    monkeypatch.setattr(telemetry, '_log_exporter', lambda: logs)
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_LOGS_ENDPOINT', 'http://collector.invalid:4318/v1/logs')
    assert telemetry.configure(logger)
    with telemetry.span('x') as handle:
        logger.warning('inside')
    assert handle is telemetry.NOOP_SPAN
    telemetry.shutdown()
    assert [d.log_record.body for d in logs.get_finished_logs()] == ['inside']

def test_traces_only_adds_no_log_handler(logger, monkeypatch):
    spans = InMemorySpanExporter()
    monkeypatch.setattr(telemetry, '_span_exporter', lambda: spans)
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT', 'http://collector.invalid:4318/v1/traces')
    assert telemetry.configure(logger)
    assert not logger.handlers
    with telemetry.span('x'):
        pass
    telemetry.shutdown()
    assert [s.name for s in spans.get_finished_spans()] == ['x']

def test_a_second_client_logger_gets_the_handler_too(logger, exporters):
    _, logs = exporters
    other = logging.getLogger(f'hathor-telemetry-{uuid4().hex}')
    telemetry.configure(logger)
    assert telemetry.configure(other)
    assert telemetry.configure(other)                                    # and asking again adds nothing
    assert len(other.handlers) == 1
    other.warning('from the other')
    for _ in range(3):                                                   # one shutdown for each configure that returned True
        telemetry.shutdown()
    assert [d.log_record.body for d in logs.get_finished_logs()] == ['from the other']
    assert not other.handlers

@pytest.mark.usefixtures('exporters')
def test_a_caller_that_asks_with_telemetry_off_is_not_a_user_of_it(logger, monkeypatch):
    telemetry.configure(logger)
    monkeypatch.delenv('OTEL_EXPORTER_OTLP_ENDPOINT')
    assert telemetry.configure(logger) is False
    telemetry.shutdown()                                                 # the one real user leaving
    assert not telemetry.enabled()

def test_telemetry_stops_only_when_the_last_client_closes(tmp_path, exporters, logger):
    spans, _ = exporters
    first = HathorClient(podcast_directory=tmp_path, logger=logger)
    second = HathorClient(podcast_directory=tmp_path, logger=logger)
    first.close()
    first.close()                                                        # closing twice (close, then __del__) gives up only one use
    assert telemetry.enabled()
    with telemetry.span('still-running'):
        pass
    second.close()
    assert not telemetry.enabled()
    assert [s.name for s in spans.get_finished_spans()] == ['still-running']

def test_a_client_made_with_telemetry_off_never_stops_it(tmp_path, monkeypatch, exporters, logger):
    spans, _ = exporters
    running = HathorClient(podcast_directory=tmp_path, logger=logger)
    monkeypatch.delenv('OTEL_EXPORTER_OTLP_ENDPOINT')
    stray = HathorClient(podcast_directory=tmp_path, logger=logger)
    stray.close()
    assert telemetry.enabled()
    running.close()
    assert not telemetry.enabled()
    assert not spans.get_finished_spans()

def test_the_timeout_is_ours_unless_the_environment_sets_one(monkeypatch):
    assert telemetry._timeout_kwargs('logs') == {'timeout': telemetry.EXPORT_TIMEOUT} #pylint:disable=protected-access
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_TIMEOUT', '30000')
    assert not telemetry._timeout_kwargs('logs') #pylint:disable=protected-access
    monkeypatch.delenv('OTEL_EXPORTER_OTLP_TIMEOUT')
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_TRACES_TIMEOUT', '30000')
    assert not telemetry._timeout_kwargs('traces') #pylint:disable=protected-access

def test_the_service_is_named_hathor_unless_the_environment_says_otherwise(monkeypatch):
    assert telemetry._resource().attributes['service.name'] == 'hathor' #pylint:disable=protected-access
    monkeypatch.setenv('OTEL_SERVICE_NAME', 'hathor-sync')
    assert telemetry._resource().attributes['service.name'] == 'hathor-sync' #pylint:disable=protected-access
    monkeypatch.delenv('OTEL_SERVICE_NAME')
    monkeypatch.setenv('OTEL_RESOURCE_ATTRIBUTES', 'service.name=from-attributes,k8s.namespace=hathor')
    assert telemetry._resource().attributes['service.name'] == 'from-attributes' #pylint:disable=protected-access

# ------------------------------------------------------------------ over the wire

class Collector(BaseHTTPRequestHandler):
    received = []
    def do_POST(self): #pylint:disable=invalid-name
        body = self.rfile.read(int(self.headers['Content-Length']))
        Collector.received.append((self.path, body))
        self.send_response(200)
        self.send_header('Content-Length', '0')
        self.end_headers()
    def log_message(self, *_): #pylint:disable=arguments-differ
        pass

def test_the_real_exporters_deliver_a_short_run_without_the_key(tmp_path, mocker, monkeypatch, logger):
    Collector.received = []
    server = HTTPServer(('127.0.0.1', 0), Collector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv('OTEL_EXPORTER_OTLP_ENDPOINT', f'http://127.0.0.1:{server.server_port}')
        monkeypatch.setenv('OTEL_SERVICE_NAME', 'hathor-sync')
        mocker.patch.object(RSSManager, 'broadcast_update', return_value=[episode(1)])
        client = HathorClient(podcast_directory=tmp_path, logger=logger)
        client.podcast_create('rss', KEY_URL, 'Some Show')
        logger.warning('fetching %s', KEY_URL)
        client.episode_sync()
        client.close()                                                   # the run ends here, long before a batch would be sent
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    paths = {path for path, _ in Collector.received}
    assert paths == {'/v1/traces', '/v1/logs'}
    payload = b''.join(body for _, body in Collector.received)
    assert b'hathor.episode_sync' in payload and b'hathor-sync' in payload and b'Syncing episodes of podcast 1' in payload
    assert b'SECRETKEY' not in payload and b'SECRETSIG' not in payload

# ------------------------------------------------------------------ the cli

def test_a_cli_run_sends_its_telemetry_before_it_exits(tmp_path, mocker, monkeypatch, exporters):
    spans, logs = exporters
    monkeypatch.delenv('OTEL_EXPORTER_OTLP_ENDPOINT')          # the setup command runs with telemetry off
    mocker.patch.object(RSSManager, 'broadcast_update', return_value=[])
    config = tmp_path / 'config.yml'
    config.write_text(dump({'hathor': {'database_connection_string': f'sqlite:///{tmp_path / "h.db"}', 'podcast_directory': str(tmp_path / 'p')},
                            'logging': {'log_level': 10}}), encoding='utf-8')
    previous = signal.getsignal(signal.SIGTERM)
    try:
        runner = CliRunner()
        runner.invoke(cli, ['-c', str(config), 'podcast', 'create', 'rss', 'https://feed.example/rss', 'Show'])
        monkeypatch.setenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://collector.invalid:4318')
        result = runner.invoke(cli, ['-c', str(config), 'podcast', 'sync', '--no-download-episodes'])
        assert result.exit_code == 0
        assert 'hathor.podcast_sync' in [s.name for s in spans.get_finished_spans()]
        assert logs.get_finished_logs()
        assert signal.getsignal(signal.SIGTERM) is not previous           # a killed run now unwinds and flushes
    finally:
        signal.signal(signal.SIGTERM, previous)
        for handler in list(logging.getLogger('hathor').handlers):
            handler.close()
            logging.getLogger('hathor').removeHandler(handler)

def test_sigterm_unwinds_the_open_spans(exporters, logger):
    spans, _ = exporters
    telemetry.configure(logger)
    previous = signal.getsignal(signal.SIGTERM)
    telemetry.exit_on_sigterm()
    try:
        with pytest.raises(SystemExit) as caught:
            with telemetry.span('hathor.stuck'):
                os.kill(os.getpid(), signal.SIGTERM)
                time.sleep(5)
    finally:
        signal.signal(signal.SIGTERM, previous)
    telemetry.shutdown()
    assert caught.value.code == 143
    [stuck] = spans.get_finished_spans()
    assert stuck.status.status_code == StatusCode.ERROR and dict(stuck.attributes)['exception.type'] == 'SystemExit'

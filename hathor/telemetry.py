from contextlib import contextmanager, suppress
import logging
import os
import signal
import threading
import time
import traceback

from opentelemetry._logs import LogRecord, SeverityNumber
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.environment_variables import (
    OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_LOGS_ENDPOINT, OTEL_EXPORTER_OTLP_LOGS_TIMEOUT,
    OTEL_EXPORTER_OTLP_TIMEOUT, OTEL_EXPORTER_OTLP_TRACES_ENDPOINT, OTEL_EXPORTER_OTLP_TRACES_TIMEOUT,
    OTEL_RESOURCE_ATTRIBUTES, OTEL_SDK_DISABLED, OTEL_SERVICE_NAME,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

from hathor.utils import mask_log_text, scrub_error

# Telemetry is opt-in and driven by the standard OTEL_* environment variables: nothing is started
# unless an endpoint is set. Every failure in here is swallowed: a sync must never fail or slow
# down because a collector is unreachable

# Seconds one export request may take, shorter than the SDK's 10. Setting OTEL_EXPORTER_OTLP_TIMEOUT
# (or the _LOGS_ / _TRACES_ variant) overrides it
EXPORT_TIMEOUT = 3
# Seconds close() waits, in total, for what is still queued to be sent
SHUTDOWN_TIMEOUT = 8

ENDPOINT_VARIABLES = {
    'logs': (OTEL_EXPORTER_OTLP_LOGS_ENDPOINT, OTEL_EXPORTER_OTLP_ENDPOINT),
    'traces': (OTEL_EXPORTER_OTLP_TRACES_ENDPOINT, OTEL_EXPORTER_OTLP_ENDPOINT),
}
# Standard, but the SDK has no constants for these two: it reads them in its auto-configuration
# entry point, which hathor does not use
EXPORTER_VARIABLES = {'logs': 'OTEL_LOGS_EXPORTER', 'traces': 'OTEL_TRACES_EXPORTER'}
TIMEOUT_VARIABLES = {'logs': OTEL_EXPORTER_OTLP_LOGS_TIMEOUT, 'traces': OTEL_EXPORTER_OTLP_TRACES_TIMEOUT}

SEVERITY_NUMBERS = {logging.DEBUG: SeverityNumber.DEBUG, logging.INFO: SeverityNumber.INFO,
                    logging.WARNING: SeverityNumber.WARN, logging.ERROR: SeverityNumber.ERROR,
                    logging.CRITICAL: SeverityNumber.FATAL}
SEVERITY_TEXTS = {'WARNING': 'WARN', 'CRITICAL': 'FATAL'}

def signal_enabled(kind: str) -> bool:
    '''
    Whether telemetry of this kind ('logs' or 'traces') is switched on: OTEL_SDK_DISABLED is not
    true, the signal's exporter is not "none", and an endpoint is set for it
    '''
    if os.environ.get(OTEL_SDK_DISABLED, '').strip().lower() == 'true':
        return False
    if os.environ.get(EXPORTER_VARIABLES[kind], '').strip().lower() == 'none':
        return False
    return any(os.environ.get(name, '').strip() for name in ENDPOINT_VARIABLES[kind])

def _clean_attributes(attributes: dict) -> dict:
    '''
    Attribute values safe to export: numbers and booleans as they are, everything else as text
    with the credentials in any url hidden. None is dropped
    '''
    clean = {}
    for key, value in attributes.items():
        if value is None:
            continue
        if isinstance(value, (bool, int, float)):
            clean[key] = value
        else:
            clean[key] = mask_log_text(scrub_error(str(value)))
    return clean

def _timeout_kwargs(kind: str) -> dict:
    if os.environ.get(TIMEOUT_VARIABLES[kind]) or os.environ.get(OTEL_EXPORTER_OTLP_TIMEOUT):
        return {}
    return {'timeout': EXPORT_TIMEOUT}

def _span_exporter():
    return OTLPSpanExporter(**_timeout_kwargs('traces'))

def _log_exporter():
    return OTLPLogExporter(**_timeout_kwargs('logs'))

class OtlpLogHandler(logging.Handler):
    '''
    Sends log records to an OTEL logger. Written here rather than using the SDK's LoggingHandler,
    which is deprecated and exports the record's raw exception and extra fields: only the message
    and the traceback leave this handler, both with the credentials in urls hidden, as the
    formatter on the stdout and file handlers does
    '''
    def __init__(self, otel_logger):
        super().__init__()
        self._otel_logger = otel_logger

    def emit(self, record):
        # Telemetry is never allowed to break the code being logged. Not handleError: that
        # prints a traceback for every record while the pipeline is broken
        with suppress(Exception):
            attributes = {
                'code.file.path': record.pathname,
                'code.function.name': record.funcName,
                'code.line.number': record.lineno,
            }
            if record.exc_info and record.exc_info[0] is not None:
                attributes['exception.type'] = record.exc_info[0].__name__
                attributes['exception.stacktrace'] = mask_log_text(''.join(traceback.format_exception(*record.exc_info)))
            self._otel_logger.emit(LogRecord(
                timestamp=int(record.created * 1e9),
                severity_text=SEVERITY_TEXTS.get(record.levelname, record.levelname),
                severity_number=SEVERITY_NUMBERS.get(record.levelno, SeverityNumber.INFO),
                body=mask_log_text(record.getMessage()),
                attributes=attributes,
            ))

class ExportErrorHandler(logging.Handler):
    '''
    The OTEL SDK reports every failed export through the "opentelemetry" logger, which would print
    a line for each batch while the collector is down. Pass the first one on to hathor's own
    logger as a warning and drop the rest
    '''
    def __init__(self, logger):
        super().__init__(level=logging.WARNING)
        self.logger = logger
        self._reported = False

    def emit(self, record):
        if self._reported:
            return
        self._reported = True
        with suppress(Exception):
            self.logger.warning(f'Telemetry export is failing, continuing without it: {mask_log_text(scrub_error(record.getMessage()))}')

class _Span:
    '''
    The span a `span()` block yields. Sets only attributes that have been cleaned
    '''
    def __init__(self, otel_span=None):
        self._otel_span = otel_span

    def set(self, **attributes):
        '''
        Add attributes to the span; urls inside text values lose their query string
        '''
        if self._otel_span is None:
            return
        with suppress(Exception):
            for key, value in _clean_attributes(attributes).items():
                self._otel_span.set_attribute(key, value)

    def fail(self, error: BaseException):
        '''
        Mark the span as failed. The message goes through the same masking as a log line, and the
        exception's own stacktrace is not exported
        '''
        if self._otel_span is None:
            return
        with suppress(Exception):
            self._otel_span.set_attribute('exception.type', type(error).__name__)
            self._otel_span.set_status(Status(StatusCode.ERROR, mask_log_text(scrub_error(f'{type(error).__name__}: {error}'))))

NOOP_SPAN = _Span()

class _Telemetry: #pylint:disable=too-few-public-methods
    def __init__(self, tracer, tracer_provider, logger_provider):
        self.tracer = tracer
        self.tracer_provider = tracer_provider
        self.logger_provider = logger_provider
        self.log_handler = None
        self.loggers = []
        self.users = 0
        self.error_handler = None

_STATE = None

def _resource():
    attributes = {}
    # Attributes given to Resource.create beat the environment, so only name the service
    # when nobody else has
    if not os.environ.get(OTEL_SERVICE_NAME) and SERVICE_NAME not in os.environ.get(OTEL_RESOURCE_ATTRIBUTES, ''):
        attributes[SERVICE_NAME] = 'hathor'
    return Resource.create(attributes)

def _build_providers():
    '''
    Returns (tracer_provider, logger_provider), either None when that signal is not enabled
    '''
    resource = _resource()
    export_millis = EXPORT_TIMEOUT * 1000
    tracer_provider = logger_provider = None
    if signal_enabled('traces'):
        # shutdown_on_exit=False: the SDK's atexit hook has no bound on how long it waits.
        # close() does the shutdown, with one
        tracer_provider = TracerProvider(resource=resource, shutdown_on_exit=False)
        tracer_provider.add_span_processor(BatchSpanProcessor(_span_exporter(), export_timeout_millis=export_millis))
    if signal_enabled('logs'):
        logger_provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(_log_exporter(), export_timeout_millis=export_millis))
    return tracer_provider, logger_provider

def configure(logger: logging.Logger) -> bool:
    '''
    Switch on the exports the environment asks for, attaching the log export to `logger`

    Does nothing unless OTEL_EXPORTER_OTLP_ENDPOINT (or
    the _LOGS_ / _TRACES_ variant) is set. Safe to call again: a second call only makes sure this
    logger has the handler. Never raises; a problem setting up is logged as a warning

    Every call that returns True must be matched by one shutdown(): the exporters stop when the
    last caller has shut down, so one client closing does not cut off another that is still running

    Returns: whether this caller now uses an export
    '''
    global _STATE #pylint:disable=global-statement
    if not (signal_enabled('logs') or signal_enabled('traces')):
        return False
    try:
        if _STATE is None:
            _STATE = _start(logger)
        elif _STATE.logger_provider is not None and logger not in _STATE.loggers:
            logger.addHandler(_STATE.log_handler)
            _STATE.loggers.append(logger)
    except Exception as error: #pylint:disable=broad-exception-caught
        _STATE = None
        logger.warning(f'Telemetry is set up but could not start, continuing without it: {mask_log_text(scrub_error(str(error)))}')
    if _STATE is None:
        return False
    _STATE.users += 1
    return True

def _start(logger: logging.Logger) -> _Telemetry:
    tracer_provider, logger_provider = _build_providers()
    state = _Telemetry(tracer_provider.get_tracer('hathor') if tracer_provider else None, tracer_provider, logger_provider)
    if logger_provider is not None:
        state.log_handler = OtlpLogHandler(logger_provider.get_logger('hathor'))
        logger.addHandler(state.log_handler)
        state.loggers.append(logger)
    sdk_logger = logging.getLogger('opentelemetry')
    state.error_handler = ExportErrorHandler(logger)
    sdk_logger.addHandler(state.error_handler)
    sdk_logger.propagate = False
    return state

def enabled() -> bool:
    '''
    Whether configure() switched anything on
    '''
    return _STATE is not None

@contextmanager
def span(name: str, **attributes):
    '''
    Run a block inside a trace span; yields an object with `set(**attributes)` and `fail(error)`.
    An exception leaving the block marks the span failed and carries on. With tracing off this
    does nothing

    name        : Span name
    attributes  : Starting attributes. Text values have the credentials in any url hidden;
                  still never pass a feed url
    '''
    if _STATE is None or _STATE.tracer is None:
        yield NOOP_SPAN
        return
    try:
        manager = _STATE.tracer.start_as_current_span(name, attributes=_clean_attributes(attributes),
                                                      record_exception=False, set_status_on_exception=False)
        otel_span = manager.__enter__() #pylint:disable=unnecessary-dunder-call
    except Exception: #pylint:disable=broad-exception-caught
        yield NOOP_SPAN
        return
    handle = _Span(otel_span)
    try:
        yield handle
    except BaseException as error:
        handle.fail(error)
        _end(manager, error)
        raise
    _end(manager, None)

def _end(manager, error):
    with suppress(Exception):
        manager.__exit__(type(error) if error else None, error, error.__traceback__ if error else None)

def shutdown(timeout: float = SHUTDOWN_TIMEOUT):
    '''
    Give up one use of telemetry, and when it was the last, send what is still queued and stop
    the exporters, waiting no longer than `timeout` seconds in total. A short-lived run ends before
    a batching exporter would send on its own. Does nothing when telemetry is off
    '''
    global _STATE #pylint:disable=global-statement
    state = _STATE
    if state is None:
        return
    state.users -= 1
    if state.users > 0:
        return
    _STATE = None
    for logger in state.loggers:
        logger.removeHandler(state.log_handler)
    def stop():
        for provider in (state.tracer_provider, state.logger_provider):
            if provider is None:
                continue
            with suppress(Exception):
                provider.force_flush(int(timeout * 1000))
                provider.shutdown()
    worker = threading.Thread(target=stop, name='hathor-telemetry-shutdown', daemon=True)
    started = time.monotonic()
    worker.start()
    worker.join(timeout)
    if worker.is_alive() and state.error_handler is not None:
        state.error_handler.logger.debug(f'Telemetry did not finish sending in {time.monotonic() - started:.1f}s, giving up')
    logging.getLogger('opentelemetry').removeHandler(state.error_handler)
    logging.getLogger('opentelemetry').propagate = True

def exit_on_sigterm():
    '''
    Turn SIGTERM into SystemExit so a run killed by a deadline unwinds through its open spans
    (marking them failed) and flushes, instead of vanishing with them still unsent. Kubernetes
    sends SIGTERM first, SIGKILL only after the grace period
    '''
    def handler(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, handler)

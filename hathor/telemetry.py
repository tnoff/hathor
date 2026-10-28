from contextlib import contextmanager, suppress
import logging
import os
import signal
import threading
import traceback

from opentelemetry._logs import LogRecord, SeverityNumber
from opentelemetry.environment_variables import OTEL_LOGS_EXPORTER, OTEL_TRACES_EXPORTER
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
FLUSH_TIMEOUT = 8

LOGGER = logging.getLogger(__name__)

ENDPOINT_VARIABLES = {
    'logs': (OTEL_EXPORTER_OTLP_LOGS_ENDPOINT, OTEL_EXPORTER_OTLP_ENDPOINT),
    'traces': (OTEL_EXPORTER_OTLP_TRACES_ENDPOINT, OTEL_EXPORTER_OTLP_ENDPOINT),
}
EXPORTER_VARIABLES = {'logs': OTEL_LOGS_EXPORTER, 'traces': OTEL_TRACES_EXPORTER}
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
    a line for each batch while the collector is down. Pass the first one on as a warning, to the
    logger given to Telemetry.attach (this module's own until then), and drop the rest
    '''
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.logger = LOGGER
        self.reported = False

    def emit(self, record):
        if self.reported:
            return
        self.reported = True
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

def _resource():
    attributes = {}
    # Attributes given to Resource.create beat the environment, so only name the service
    # when nobody else has
    if not os.environ.get(OTEL_SERVICE_NAME) and SERVICE_NAME not in os.environ.get(OTEL_RESOURCE_ATTRIBUTES, ''):
        attributes[SERVICE_NAME] = 'hathor'
    return Resource.create(attributes)

class Telemetry:
    '''
    The exports the environment asks for, started when the object is made (this module makes one,
    TELEMETRY, when hathor loads). With no endpoint set it holds nothing and every method does
    nothing. A problem starting is a logged warning, never an exception
    '''
    def __init__(self):
        self.tracer = None
        self.tracer_provider = None
        self.logger_provider = None
        self.log_handler = None
        self.error_handler = None
        if not (signal_enabled('logs') or signal_enabled('traces')):
            return
        try:
            self._start()
        except Exception as error: #pylint:disable=broad-exception-caught
            self.shutdown()
            LOGGER.warning(f'Telemetry is set up but could not start, continuing without it: {mask_log_text(scrub_error(str(error)))}')

    def _start(self):
        resource = _resource()
        export_millis = EXPORT_TIMEOUT * 1000
        # shutdown_on_exit=False: the SDK's atexit hook has no bound on how long it waits
        if signal_enabled('traces'):
            self.tracer_provider = TracerProvider(resource=resource, shutdown_on_exit=False)
            self.tracer_provider.add_span_processor(BatchSpanProcessor(_span_exporter(), export_timeout_millis=export_millis))
            self.tracer = self.tracer_provider.get_tracer('hathor')
        if signal_enabled('logs'):
            self.logger_provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
            self.logger_provider.add_log_record_processor(BatchLogRecordProcessor(_log_exporter(), export_timeout_millis=export_millis))
            self.log_handler = OtlpLogHandler(self.logger_provider.get_logger('hathor'))
        self.error_handler = ExportErrorHandler()
        sdk_logger = logging.getLogger('opentelemetry')
        sdk_logger.addHandler(self.error_handler)
        sdk_logger.propagate = False

    @property
    def enabled(self) -> bool:
        '''
        Whether any export is running
        '''
        return self.tracer_provider is not None or self.logger_provider is not None

    def attach(self, logger: logging.Logger):
        '''
        Export what this logger records, and report a failing export on it. Safe to repeat
        '''
        if self.log_handler is not None and self.log_handler not in logger.handlers:
            logger.addHandler(self.log_handler)
        if self.error_handler is not None and self.error_handler.logger is LOGGER:
            self.error_handler.logger = logger

    @contextmanager
    def span(self, name: str, **attributes):
        '''
        Run a block inside a trace span; yields an object with `set(**attributes)` and `fail(error)`.
        An exception leaving the block marks the span failed and carries on. With tracing off this
        does nothing

        name        : Span name
        attributes  : Starting attributes. Text values have the credentials in any url hidden;
                      still never pass a feed url
        '''
        if self.tracer is None:
            yield NOOP_SPAN
            return
        with self.tracer.start_as_current_span(name, attributes=_clean_attributes(attributes),
                                               record_exception=False, set_status_on_exception=False) as otel_span:
            handle = _Span(otel_span)
            try:
                yield handle
            except BaseException as error:
                handle.fail(error)
                raise

    def _providers(self) -> list:
        return [provider for provider in (self.tracer_provider, self.logger_provider) if provider is not None]

    def flush(self, timeout: float = FLUSH_TIMEOUT):
        '''
        Send what is still queued, waiting no longer than `timeout` seconds in total. A short-lived
        run ends before a batching exporter would send on its own. Nothing is stopped, so this can
        be called whenever a client closes
        '''
        providers = self._providers()
        def send():
            for provider in providers:
                with suppress(Exception):
                    provider.force_flush(int(timeout * 1000))
        # The SDK's own timeout does not hold while an exporter is blocked on a collector that
        # never answers, so the wait is bounded here. The thread is left to finish on its own
        if providers:
            worker = threading.Thread(target=send, name='hathor-telemetry-flush', daemon=True)
            worker.start()
            worker.join(timeout)

    @staticmethod
    def _stop(provider):
        with suppress(Exception):
            provider.shutdown()

    def shutdown(self, timeout: float = FLUSH_TIMEOUT):
        '''
        Flush, then stop the exporters and put the "opentelemetry" logger back as it was. The
        object does nothing afterwards
        '''
        self.flush(timeout)
        for provider in self._providers():
            worker = threading.Thread(target=self._stop, args=(provider,), name='hathor-telemetry-stop', daemon=True)
            worker.start()
            worker.join(timeout)
        if self.error_handler is not None:
            sdk_logger = logging.getLogger('opentelemetry')
            sdk_logger.removeHandler(self.error_handler)
            sdk_logger.propagate = True
        self.tracer = self.tracer_provider = self.logger_provider = self.log_handler = self.error_handler = None

TELEMETRY = Telemetry()

def enabled() -> bool:
    '''
    Whether any export is running
    '''
    return TELEMETRY.enabled

def attach(logger: logging.Logger):
    '''
    Export what this logger records
    '''
    TELEMETRY.attach(logger)

def span(name: str, **attributes):
    '''
    Run a block inside a trace span, see Telemetry.span
    '''
    return TELEMETRY.span(name, **attributes)

def flush(timeout: float = FLUSH_TIMEOUT):
    '''
    Send what is still queued, see Telemetry.flush
    '''
    TELEMETRY.flush(timeout)

def exit_on_sigterm():
    '''
    Turn SIGTERM into SystemExit so a run killed by a deadline unwinds through its open spans
    (marking them failed) and flushes, instead of vanishing with them still unsent. Kubernetes
    sends SIGTERM first, SIGKILL only after the grace period
    '''
    def handler(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, handler)

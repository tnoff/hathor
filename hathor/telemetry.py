from copy import copy
import logging
import os
import signal
import traceback

from opentelemetry import trace
from opentelemetry._logs import get_logger_provider, set_logger_provider
from opentelemetry.environment_variables import OTEL_LOGS_EXPORTER, OTEL_TRACES_EXPORTER
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.environment_variables import (
    OTEL_EXPORTER_OTLP_ENDPOINT,
    OTEL_EXPORTER_OTLP_LOGS_ENDPOINT,
    OTEL_EXPORTER_OTLP_LOGS_TIMEOUT,
    OTEL_EXPORTER_OTLP_TIMEOUT,
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
    OTEL_EXPORTER_OTLP_TRACES_TIMEOUT,
    OTEL_SDK_DISABLED,
)
from opentelemetry.sdk.resources import SERVICE_NAME, OTELResourceDetector, Resource, get_aggregated_resources
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Status

from hathor.utils import mask_log_text

# Opt-in, from the standard OTEL_* environment variables, started once when hathor loads (the
# bottom of this module): nothing is set up unless an endpoint is set. The rest of hathor makes
# spans with TRACER like any other OpenTelemetry user

LOGGER = logging.getLogger(__name__)
TRACER = trace.get_tracer('hathor')

# Seconds one export request may take, shorter than the SDK's 10, so a collector that is down or
# slow holds up the end of a run (the SDK sends what is left when the process exits) for little
# time. OTEL_EXPORTER_OTLP_TIMEOUT, or the _LOGS_ / _TRACES_ variant, overrides it
EXPORT_TIMEOUT = 3

ENDPOINT_VARIABLES = {
    'logs': (OTEL_EXPORTER_OTLP_LOGS_ENDPOINT, OTEL_EXPORTER_OTLP_ENDPOINT),
    'traces': (OTEL_EXPORTER_OTLP_TRACES_ENDPOINT, OTEL_EXPORTER_OTLP_ENDPOINT),
}
EXPORTER_VARIABLES = {'logs': OTEL_LOGS_EXPORTER, 'traces': OTEL_TRACES_EXPORTER}
TIMEOUT_VARIABLES = {'logs': OTEL_EXPORTER_OTLP_LOGS_TIMEOUT, 'traces': OTEL_EXPORTER_OTLP_TRACES_TIMEOUT}
# The attributes every LogRecord has: anything else on a record was added by whoever logged it
STANDARD_RECORD_ATTRIBUTES = set(vars(logging.makeLogRecord({}))) | {'message', 'asctime', 'taskName'}

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

def _timeout_kwargs(kind: str) -> dict:
    if os.environ.get(TIMEOUT_VARIABLES[kind]) or os.environ.get(OTEL_EXPORTER_OTLP_TIMEOUT):
        return {}
    return {'timeout': EXPORT_TIMEOUT}

def _span_exporter():
    return OTLPSpanExporter(**_timeout_kwargs('traces'))

def _log_exporter():
    return OTLPLogExporter(**_timeout_kwargs('logs'))

def _mask(value):
    if isinstance(value, str):
        return mask_log_text(value)
    if isinstance(value, (list, tuple)):
        return tuple(_mask(item) for item in value)
    return value

def _masked_attributes(attributes) -> dict:
    return {key: _mask(value) for key, value in (attributes or {}).items()}

class MaskingSpanExporter(SpanExporter):
    '''
    Hides the credentials in urls in everything a span carries on its way out: its attributes, its
    status and the exceptions it recorded. The spans that need it are the ones hathor does not
    write: requests' keep the full url in `http.url` (a private Patreon feed has its key in the
    query string) and name the path and query in a ConnectionError
    '''
    def __init__(self, exporter: SpanExporter):
        self.exporter = exporter

    def export(self, spans):
        return self.exporter.export([self._masked(span) for span in spans])

    def shutdown(self):
        self.exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.exporter.force_flush(timeout_millis)

    @staticmethod
    def _masked(span: ReadableSpan) -> ReadableSpan:
        description = mask_log_text(span.status.description) if span.status.description else None
        return ReadableSpan(
            name=span.name, context=span.context, parent=span.parent, resource=span.resource,
            attributes=_masked_attributes(span.attributes),
            events=[Event(event.name, _masked_attributes(event.attributes), event.timestamp) for event in span.events],
            links=span.links, kind=span.kind, status=Status(span.status.status_code, description),
            start_time=span.start_time, end_time=span.end_time, instrumentation_scope=span.instrumentation_scope,
        )

class MaskingFilter(logging.Filter):
    '''
    Gives the handler it is on a copy of the record with the credentials in urls hidden, in the
    message and in the traceback, and without the fields whoever logged it added. The same masking
    the stdout and file handlers get from MaskingFormatter, which this handler does not use: it
    reads the record's own exception and fields rather than a formatted line
    '''
    def filter(self, record):
        masked = copy(record)
        masked.msg = mask_log_text(record.getMessage())
        masked.args = None
        if record.exc_info:
            masked.msg += '\n' + mask_log_text(''.join(traceback.format_exception(*record.exc_info)))
            masked.exc_info = masked.exc_text = None
        for key in set(vars(masked)) - STANDARD_RECORD_ATTRIBUTES:
            delattr(masked, key)
        return masked

def setup_otlp():
    '''
    Set up the exporters and instrumentation the environment asks for, as the global providers
    other OpenTelemetry users in the process expect. Does nothing without an endpoint, or when a
    provider is already set. A problem setting up is a logged warning, not an exception: hathor
    has to run without telemetry
    '''
    try:
        resource = get_aggregated_resources([OTELResourceDetector()], Resource({SERVICE_NAME: 'hathor'}))
        if signal_enabled('traces') and not isinstance(trace.get_tracer_provider(), TracerProvider):
            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(BatchSpanProcessor(MaskingSpanExporter(_span_exporter()),
                                                                  export_timeout_millis=EXPORT_TIMEOUT * 1000))
            trace.set_tracer_provider(tracer_provider)
            RequestsInstrumentor().instrument(tracer_provider=tracer_provider)
            # skip_dep_check: the instrumentor caps SQLAlchemy at < 2.1.0 (opentelemetry-python-contrib
            # #5118, lifted upstream but not released), so on 2.1.x it logs an error and instruments
            # nothing. 0.66b1 does produce spans on 2.1.6, which test_sql_gets_a_span asserts, and it
            # fails if a bump ever stops that. Drop the flag once a release carries the wider range.
            # This is what discord-bot did for its db pod (discord-bot#1149)
            SQLAlchemyInstrumentor().instrument(tracer_provider=tracer_provider, skip_dep_check=True)
        if signal_enabled('logs') and not isinstance(get_logger_provider(), LoggerProvider):
            logger_provider = LoggerProvider(resource=resource)
            logger_provider.add_log_record_processor(BatchLogRecordProcessor(_log_exporter(),
                                                                             export_timeout_millis=EXPORT_TIMEOUT * 1000))
            set_logger_provider(logger_provider)
    except Exception as error: #pylint:disable=broad-exception-caught
        LOGGER.warning(f'Telemetry is set up but could not start, continuing without it: {mask_log_text(str(error))}')

def attach(logger: logging.Logger):
    '''
    Export the records of this logger. Safe to repeat. Does nothing when there is no log export

    The records are masked by a filter on the handler. Only hathor's loggers should be given: a
    record from anywhere else would have the fields it carries removed
    '''
    if isinstance(get_logger_provider(), LoggerProvider) and not any(isinstance(h, LoggingHandler) for h in logger.handlers):
        handler = LoggingHandler(logger_provider=get_logger_provider())
        handler.addFilter(MaskingFilter())
        logger.addHandler(handler)

def exit_on_sigterm():
    '''
    Turn SIGTERM into SystemExit so a run killed by a deadline unwinds through its open spans,
    ending them, and exits normally, which is when the SDK sends what is queued, instead of
    vanishing with them unsent. Kubernetes sends SIGTERM first, SIGKILL only after the grace
    period. SystemExit is not an Exception, so the spans are not marked as errors, but they carry
    how long they ran and which step it was
    '''
    def handler(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, handler)

setup_otlp()

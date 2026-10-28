# telemetry first: setting it up patches sqlalchemy.create_engine, and a module that imported that
# function before the patch keeps the one that is not instrumented
from hathor import telemetry
from hathor import podcast

# pylint: disable=no-member
from alembic import context

from hathor.database.tables import BASE

# hathor.database.migrations.migrate hands over its own connection, so an
# in memory database is migrated on the connection the client will use
connection = context.config.attributes['connection']
context.configure(connection=connection, target_metadata=BASE.metadata, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()

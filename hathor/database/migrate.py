from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from hathor.exc import HathorException

MIGRATIONS_DIRECTORY = Path(__file__).parent / 'migrations'

# Revision of the schema `create_all` produced before migrations existed
BASELINE_REVISION = '0001'
BASELINE_COLUMNS = {
    'podcast': {'id', 'name', 'archive_type', 'broadcast_id', 'max_allowed', 'file_location',
                'artist_name', 'automatic_episode_download'},
    'podcast_episode': {'id', 'download_url', 'processed_url', 'title', 'description', 'date',
                        'podcast_id', 'file_path', 'file_size', 'prevent_deletion'},
    'podcast_title_filter': {'id', 'podcast_id', 'regex_string'},
}

def check_baseline(connection):
    '''
    Raise unless an unversioned database has the baseline schema, since stamping
    it would claim a schema it does not have
    '''
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    for table, expected in BASELINE_COLUMNS.items():
        if table not in tables:
            raise HathorException(f'Database has hathor tables but no "{table}" table, refusing to stamp it as the baseline schema')
        missing = expected - {column['name'] for column in inspector.get_columns(table)}
        if missing:
            raise HathorException(f'Table "{table}" is missing columns {sorted(missing)}, refusing to stamp it as the baseline schema')

def migrate(engine, logger):
    '''
    Bring the database up to the newest schema

    Empty database: run every migration
    Tables but no alembic_version (made by `create_all`, before migrations): stamp the baseline, then upgrade
    Otherwise: upgrade
    '''
    config = Config()
    config.set_main_option('script_location', str(MIGRATIONS_DIRECTORY))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        tables = set(inspect(connection).get_table_names())
        if 'alembic_version' not in tables and tables & set(BASELINE_COLUMNS):
            check_baseline(connection)
            logger.info(f'Database predates migrations, stamping it as revision {BASELINE_REVISION}')
            command.stamp(config, BASELINE_REVISION)
        command.upgrade(config, 'head')

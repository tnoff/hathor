import logging

import pytest
from alembic.config import Config
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from hathor.client import HathorClient
from hathor.database.migrate import BASELINE_REVISION, MIGRATIONS_DIRECTORY, migrate
from hathor.database.tables import BASE
from hathor.exc import HathorException

LOGGER = logging.getLogger('test-migrations')

@pytest.fixture(name='make_engine')
def fixture_make_engine():
    # Python 3.13+ warns about sqlite connections that are garbage collected
    # open, and the suite turns warnings into errors
    engines = []
    def make(url='sqlite:///'):
        engine = create_engine(url)
        engines.append(engine)
        return engine
    yield make
    for engine in engines:
        engine.dispose()

def versions(engine):
    with engine.connect() as connection:
        return [row[0] for row in connection.execute(text('select version_num from alembic_version'))]

def test_fresh_database_gets_every_table(make_engine):
    engine = make_engine()
    migrate(engine, LOGGER)
    assert set(inspect(engine).get_table_names()) == {'alembic_version', 'podcast', 'podcast_episode', 'podcast_title_filter'}
    assert versions(engine) == [BASELINE_REVISION]

def test_migrations_match_models(make_engine):
    # A model change without a revision shows up here as a diff
    engine = make_engine()
    migrate(engine, LOGGER)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), BASE.metadata)
    assert not diff

def test_upgrade_twice_changes_nothing(make_engine):
    engine = make_engine()
    migrate(engine, LOGGER)
    migrate(engine, LOGGER)
    assert versions(engine) == [BASELINE_REVISION]

def test_database_from_before_migrations_is_stamped_and_keeps_data(make_engine, tmp_path):
    engine = make_engine(f'sqlite:///{tmp_path}/old.db')
    BASE.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("insert into podcast (name, archive_type, broadcast_id) values ('keep me', 'rss', 'https://example.com/feed')"))
    assert 'alembic_version' not in inspect(engine).get_table_names()
    migrate(engine, LOGGER)
    assert versions(engine) == [BASELINE_REVISION]
    with engine.connect() as connection:
        assert connection.execute(text('select name from podcast')).scalar() == 'keep me'

def test_database_missing_a_table_is_not_stamped(make_engine, tmp_path):
    engine = make_engine(f'sqlite:///{tmp_path}/old.db')
    BASE.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text('drop table podcast_title_filter'))
    with pytest.raises(HathorException, match='podcast_title_filter'):
        migrate(engine, LOGGER)
    assert 'alembic_version' not in inspect(engine).get_table_names()

def test_database_missing_a_column_is_not_stamped(make_engine, tmp_path):
    engine = make_engine(f'sqlite:///{tmp_path}/old.db')
    with engine.begin() as connection:
        connection.execute(text('create table podcast (id integer primary key, name varchar)'))
        connection.execute(text('create table podcast_episode (id integer primary key)'))
        connection.execute(text('create table podcast_title_filter (id integer primary key)'))
    with pytest.raises(HathorException, match='missing columns'):
        migrate(engine, LOGGER)
    assert 'alembic_version' not in inspect(engine).get_table_names()

def test_client_migrates_a_file_database(make_engine, tmp_path):
    connection_string = f'sqlite:///{tmp_path}/hathor.db'
    BASE.metadata.create_all(make_engine(connection_string))
    client = HathorClient(database_connection_string=connection_string)
    try:
        assert versions(client.engine) == [BASELINE_REVISION]
        assert not client.podcast_list()
    finally:
        client.close()

def test_baseline_downgrade_drops_every_table(make_engine):
    engine = make_engine()
    migrate(engine, LOGGER)
    config = Config()
    config.set_main_option('script_location', str(MIGRATIONS_DIRECTORY))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.downgrade(config, 'base')
    assert set(inspect(engine).get_table_names()) == {'alembic_version'}

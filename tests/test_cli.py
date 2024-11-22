from copy import deepcopy
from datetime import datetime
from json import loads
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from click.testing import CliRunner
from yaml import dump

from hathor.cli import cli
from hathor.podcast.archive import RSSManager

from tests.utils import temp_audio_file

basic_config_data = {
    'hathor': {
    },
    'logging': {
    }
}

logging_config_data = {
    'hathor': {
    },
    'logging': {
        'log_level': 10,
    },
}

mock_episode_data = [
    {
        'download_link': 'https://foo.com/example1',
        'title': 'Episode 0',
        'date': datetime(2024, 12, 7, 14, 00, 00),
        'description': 'Episode 0 description',
    },
]

class FakeClient():
    def init(self, *args, **kwargs):
        pass

def test_invalid_config():
    runner = CliRunner()
    with NamedTemporaryFile(suffix='.yml') as config:
        result = runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'list'])
        assert result.exit_code == 1
        assert 'Invalid config with no data' in str(result.exception)

def test_invalid_config_file():
    runner = CliRunner()
    result = runner.invoke(cli, ['-c', '/tmp/foo/bar', 'podcast', 'list'])
    assert result.exit_code == 1
    assert 'Invalid path for config file' in str(result.exception)

def test_dump_config():
    with NamedTemporaryFile(suffix='.yml') as config:
        with open(config.name, 'w+', encoding='utf-8') as writer:
            dump(basic_config_data, writer)
        runner = CliRunner()
        result = runner.invoke(cli, ['-c', f'{config.name}', 'dump-config'])
        assert result.exit_code == 0
        assert result.output == '{\n    "hathor": {},\n    "logging": {}\n}\n'

def test_logging_config():
    with NamedTemporaryFile(suffix='.log') as log_file:
        config_data = deepcopy(logging_config_data)
        config_data['logging']['logging_file'] = log_file.name
        with NamedTemporaryFile(suffix='.yml') as config:
            with open(config.name, 'w+', encoding='utf-8') as writer:
                dump(config_data, writer)
            runner = CliRunner()
            runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'list'])
            log_file_path = Path(log_file.name)
            assert 'Initializing hathor client with database connection' in log_file_path.read_text(encoding='utf-8')

def test_console_logging():
    config_data = {
        'hathor': {
        },
        'logging': {
            'logging_file': None,
            'console_logging': True,
            'log_level': 10,
        },
    }
    with NamedTemporaryFile(suffix='.yml') as config:
        with open(config.name, 'w+', encoding='utf-8') as writer:
            dump(config_data, writer)
        runner = CliRunner()
        result = runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'list'])
        assert 'Initializing hathor client with database ' in result.output

def test_database_connection():
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            config_data = {
                'hathor': {
                    'database_connection_string': f'sqlite:///{db_file.name}',
                    'podcast_directory': tmp_dir,
                }
            }
            with NamedTemporaryFile(suffix='.yml') as config:
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod'])
                db_path = Path(db_file.name)
                assert db_path.stat().st_size > 0

def test_podcast_create():
    with TemporaryDirectory() as tmp_dir:
        with NamedTemporaryFile(suffix='.yml') as config:
            with open(config.name, 'w+', encoding='utf-8') as writer:
                dump(basic_config_data, writer)
            runner = CliRunner()
            result = runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                        'rss', 'https://foo.com/example', 'temp-pod',
                                        '--max-allowed', '2', '--file-location', tmp_dir,
                                        '--artist-name', 'foo', '--no-automatic-download'])
            assert loads(result.output) == {
                'archive_type': 'rss',
                'artist_name': 'foo',
                'automatic_episode_download': False,
                'broadcast_id': 'https://foo.com/example',
                'file_location': tmp_dir,
                'id': 1,
                'max_allowed': 2,
                'name': 'temp-pod'
            }

def test_podcast_create_no_automatic_flag():
    with TemporaryDirectory() as tmp_dir:
        with NamedTemporaryFile(suffix='.yml') as config:
            with open(config.name, 'w+', encoding='utf-8') as writer:
                dump(basic_config_data, writer)
            runner = CliRunner()
            result = runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                        'rss', 'https://foo.com/example', 'temp-pod',
                                        '--max-allowed', '2', '--file-location', tmp_dir,
                                        '--artist-name', 'foo'])
            assert loads(result.output) == {
                'archive_type': 'rss',
                'artist_name': 'foo',
                'automatic_episode_download': True,
                'broadcast_id': 'https://foo.com/example',
                'file_location': tmp_dir,
                'id': 1,
                'max_allowed': 2,
                'name': 'temp-pod'
            }

def test_podcast_show():
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'show', '1'])
                assert loads(result.output) == [
                    {
                        'archive_type': 'rss',
                        'artist_name': None,
                        'automatic_episode_download': True,
                        'broadcast_id': 'https://foo.com/example',
                        'file_location': tmp_dir,
                        'id': 1,
                        'max_allowed': None,
                        'name': 'temp-pod'
                    },
                ]

def test_podcast_update():
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'update', '1', '--artist-name', 'bar'])
                assert loads(result.output) == {
                    'archive_type': 'rss',
                    'artist_name': 'bar',
                    'automatic_episode_download': True,
                    'broadcast_id': 'https://foo.com/example',
                    'file_location': tmp_dir,
                    'id': 1,
                    'max_allowed': None,
                    'name': 'temp-pod'
                }

def test_podcast_update_file_location():
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with TemporaryDirectory() as tmp_dir2:
                with NamedTemporaryFile(suffix='.yml') as config:
                    config_data = {
                        'hathor': {
                            'database_connection_string': f'sqlite:///{db_file.name}',
                            'podcast_directory': tmp_dir,
                        }
                    }
                    with open(config.name, 'w+', encoding='utf-8') as writer:
                        dump(config_data, writer)
                    runner = CliRunner()
                    runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                        'rss', 'https://foo.com/example', 'temp-pod',
                                        '--file-location', tmp_dir])
                    result = runner.invoke(cli, ['-c', f'{config.name}', 'podcast',
                                                 'update-file-location', '1', tmp_dir2])
                    assert loads(result.output) == {
                        'archive_type': 'rss',
                        'artist_name': None,
                        'automatic_episode_download': True,
                        'broadcast_id': 'https://foo.com/example',
                        'file_location': tmp_dir2,
                        'id': 1,
                        'max_allowed': None,
                        'name': 'temp-pod'
                    }

def test_podcast_delete():
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'podcast',
                                             'delete', '1'])
                assert loads(result.output) == [1]

def test_filter_create():
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'filter',
                                             'create', '1', "r'foo.*'"])
                assert loads(result.output) == {
                    'id': 1,
                    'podcast_id': 1,
                    'regex_string': "r'foo.*'"
                }

def test_filter_list():
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                runner.invoke(cli, ['-c', f'{config.name}', 'filter',
                                    'create', '1', "r'foo.*'"])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'filter', 'list'])
                assert loads(result.output) == [
                    {
                        'id': 1,
                        'podcast_id': 1,
                        'regex_string': "r'foo.*'"
                    },
                ]

def test_filter_list_invalid_include():
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                runner.invoke(cli, ['-c', f'{config.name}', 'filter',
                                    'create', '1', "r'foo.*'"])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'filter', 'list',
                                             '--include-podcasts', 'foo'])            
                assert 'Invalid include podcasts arg, must be comma separated list of ints' in str(result.exception)

def test_filter_list_invalid_exclude():
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                runner.invoke(cli, ['-c', f'{config.name}', 'filter',
                                    'create', '1', "r'foo.*'"])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'filter', 'list',
                                             '--exclude-podcasts', 'foo'])            
                assert 'Invalid exclude podcasts arg, must be comma separated list of ints' in str(result.exception)

def test_filter_list_include():
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                runner.invoke(cli, ['-c', f'{config.name}', 'filter',
                                    'create', '1', "r'foo.*'"])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'filter', 'list',
                                             '--include-podcasts', '1'])            
                assert loads(result.output) == [
                    {
                        'id': 1,
                        'podcast_id': 1,
                        'regex_string': "r'foo.*'"
                    },
                ]

def test_filter_list_exclude():
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                runner.invoke(cli, ['-c', f'{config.name}', 'filter',
                                    'create', '1', "r'foo.*'"])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'filter', 'list',
                                             '--exclude-podcasts', '1'])            
                assert loads(result.output) == []

def test_filter_delete():
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                runner.invoke(cli, ['-c', f'{config.name}', 'filter',
                                    'create', '1', "r'foo.*'"])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'filter', 'delete', '1'])
                assert loads(result.output) == [1]

def test_episode_sync(mocker):
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
                result = runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'sync'])
                assert loads(result.output) == [
                    {
                        'date': '2024-12-07',
                        'description': 'Episode 0 description',
                        'download_url': 'https://foo.com/example1',
                        'processed_url': 'https://foo.com/example1',
                        'file_path': None,
                        'file_size': None,
                        'id': 1,
                        'podcast_id': 1,
                        'prevent_deletion': False,
                        'title': 'Episode 0',
                    },
                ]

def test_episode_list(mocker):
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
                runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'sync'])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'list'])
                assert loads(result.output) == [
                    {
                        'date': '2024-12-07',
                        'description': 'Episode 0 description',
                        'download_url': 'https://foo.com/example1',
                        'processed_url': 'https://foo.com/example1',
                        'file_path': None,
                        'file_size': None,
                        'id': 1,
                        'podcast_id': 1,
                        'prevent_deletion': False,
                        'title': 'Episode 0',
                    },
                ]

def test_episode_list_only_files(mocker):
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
                runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'sync'])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'list', '--only-files'])
                assert loads(result.output) == []

def test_episode_show(mocker):
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
                runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'sync'])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'show', '1'])
                assert loads(result.output) == [
                    {
                        'date': '2024-12-07',
                        'description': 'Episode 0 description',
                        'download_url': 'https://foo.com/example1',
                        'processed_url': 'https://foo.com/example1',
                        'file_path': None,
                        'file_size': None,
                        'id': 1,
                        'podcast_id': 1,
                        'prevent_deletion': False,
                        'title': 'Episode 0',
                    },
                ]

def test_episode_download(mocker):
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                with temp_audio_file() as temp_audio:
                    config_data = {
                        'hathor': {
                            'database_connection_string': f'sqlite:///{db_file.name}',
                            'podcast_directory': tmp_dir,
                        }
                    }
                    with open(config.name, 'w+', encoding='utf-8') as writer:
                        dump(config_data, writer)
                    runner = CliRunner()
                    runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                        'rss', 'https://foo.com/example', 'temp-pod',
                                        '--file-location', tmp_dir])
                    mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
                    mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
                    runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'sync'])
                    result = runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'download', '1'])
                    assert loads(result.output) == [
                        {
                            'date': '2024-12-07',
                            'description': 'Episode 0 description',
                            'download_url': 'https://foo.com/example1',
                            'processed_url': 'https://foo.com/example1',
                            'file_path': temp_audio,
                            'file_size': 123,
                            'id': 1,
                            'podcast_id': 1,
                            'prevent_deletion': False,
                            'title': 'Episode 0',
                        }
                    ]

def test_episode_delete(mocker):
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                with temp_audio_file() as temp_audio:
                    config_data = {
                        'hathor': {
                            'database_connection_string': f'sqlite:///{db_file.name}',
                            'podcast_directory': tmp_dir,
                        }
                    }
                    with open(config.name, 'w+', encoding='utf-8') as writer:
                        dump(config_data, writer)
                    runner = CliRunner()
                    runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                        'rss', 'https://foo.com/example', 'temp-pod',
                                        '--file-location', tmp_dir])
                    mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
                    mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
                    runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'sync'])
                    runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'download', '1'])
                    result = runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'delete', '1'])
                    assert loads(result.output) == [1]
                    temp_audio_path = Path(temp_audio)
                    assert not temp_audio_path.exists()

def test_episode_delete_keep_files(mocker):
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                with temp_audio_file() as temp_audio:
                    config_data = {
                        'hathor': {
                            'database_connection_string': f'sqlite:///{db_file.name}',
                            'podcast_directory': tmp_dir,
                        }
                    }
                    with open(config.name, 'w+', encoding='utf-8') as writer:
                        dump(config_data, writer)
                    runner = CliRunner()
                    runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                        'rss', 'https://foo.com/example', 'temp-pod',
                                        '--file-location', tmp_dir])
                    mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
                    mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
                    runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'sync'])
                    runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'download', '1'])
                    result = runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'delete', '1', '--no-delete-files'])
                    assert loads(result.output) == [1]
                    temp_audio_path = Path(temp_audio)
                    assert temp_audio_path.exists()

def test_episode_update_file_location(mocker):
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                with temp_audio_file() as temp_audio:
                    with NamedTemporaryFile(suffix='.mp3') as temp_audio_new:
                        config_data = {
                            'hathor': {
                                'database_connection_string': f'sqlite:///{db_file.name}',
                                'podcast_directory': tmp_dir,
                            }
                        }
                        with open(config.name, 'w+', encoding='utf-8') as writer:
                            dump(config_data, writer)
                        runner = CliRunner()
                        runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                            'rss', 'https://foo.com/example', 'temp-pod',
                                            '--file-location', tmp_dir])
                        mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
                        mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
                        runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'sync'])
                        runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'download', '1'])
                        result = runner.invoke(cli, ['-c', f'{config.name}', 'episode',
                                                     'update-file-path', '1', temp_audio_new.name])
                        assert loads(result.output) == {
                            'date': '2024-12-07',
                            'description': 'Episode 0 description',
                            'download_url': 'https://foo.com/example1',
                            'processed_url': 'https://foo.com/example1',
                            'file_path': temp_audio_new.name,
                            'file_size': 123,
                            'id': 1,
                            'podcast_id': 1,
                            'prevent_deletion': False,
                            'title': 'Episode 0',
                        }

def test_episode_delete_file(mocker):
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                with temp_audio_file() as temp_audio:
                    config_data = {
                        'hathor': {
                            'database_connection_string': f'sqlite:///{db_file.name}',
                            'podcast_directory': tmp_dir,
                        }
                    }
                    with open(config.name, 'w+', encoding='utf-8') as writer:
                        dump(config_data, writer)
                    runner = CliRunner()
                    runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                        'rss', 'https://foo.com/example', 'temp-pod',
                                        '--file-location', tmp_dir])
                    mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
                    mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
                    runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'sync'])
                    runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'download', '1'])
                    result = runner.invoke(cli, ['-c', f'{config.name}', 'episode',
                                                    'delete-file', '1'])
                    assert loads(result.output) == [1]
                    temp_audio_path = Path(temp_audio)
                    assert not temp_audio_path.exists()

def test_episode_update(mocker):
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                with temp_audio_file() as temp_audio:
                    config_data = {
                        'hathor': {
                            'database_connection_string': f'sqlite:///{db_file.name}',
                            'podcast_directory': tmp_dir,
                        }
                    }
                    with open(config.name, 'w+', encoding='utf-8') as writer:
                        dump(config_data, writer)
                    runner = CliRunner()
                    runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                        'rss', 'https://foo.com/example', 'temp-pod',
                                        '--file-location', tmp_dir])
                    mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
                    mocker.patch.object(RSSManager, 'episode_download', return_value=(Path(temp_audio), 123))
                    runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'sync'])
                    runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'download', '1'])
                    result = runner.invoke(cli, ['-c', f'{config.name}', 'episode',
                                                    'update', '1', 'True'])
                    assert loads(result.output) == {
                        'date': '2024-12-07',
                        'description': 'Episode 0 description',
                        'download_url': 'https://foo.com/example1',
                        'processed_url': 'https://foo.com/example1',
                        'file_path': temp_audio,
                        'file_size': 123,
                        'id': 1,
                        'podcast_id': 1,
                        'prevent_deletion': True,
                        'title': 'Episode 0',
                    }

def test_episode_cleanup(mocker):
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                mocker.patch.object(RSSManager, 'broadcast_update', return_value=mock_episode_data)
                runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'sync'])
                runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'cleanup'])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'episode', 'list'])
                assert loads(result.output) == []

def test_podcast_sync():
    with NamedTemporaryFile(suffix='.sql') as db_file:
        with TemporaryDirectory() as tmp_dir:
            with NamedTemporaryFile(suffix='.yml') as config:
                config_data = {
                    'hathor': {
                        'database_connection_string': f'sqlite:///{db_file.name}',
                        'podcast_directory': tmp_dir,
                    }
                }
                with open(config.name, 'w+', encoding='utf-8') as writer:
                    dump(config_data, writer)
                runner = CliRunner()
                runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'create',
                                    'rss', 'https://foo.com/example', 'temp-pod',
                                    '--file-location', tmp_dir])
                result = runner.invoke(cli, ['-c', f'{config.name}', 'podcast', 'sync',
                                             '--no-sync-web-episodes', '--no-download-episodes'])
                assert loads(result.output) is True

from tempfile import NamedTemporaryFile

from click.testing import CliRunner
from yaml import dump

from hathor.cli import cli

valid_config_data = {
    'hathor': {
    },
    'logging': {
    }
}

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
            dump(valid_config_data, writer)
        runner = CliRunner()
        result = runner.invoke(cli, ['-c', f'{config.name}', 'dump-config'])
        assert result.exit_code == 0
        assert result.output == '{\n    "hathor": {},\n    "logging": {}\n}\n'

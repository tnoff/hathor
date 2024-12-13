from json import loads
from pathlib import Path
from tempfile import NamedTemporaryFile

from click.testing import CliRunner

from hathor.audio.cli import cli

from tests.utils import temp_audio_file, temp_image_file

def test_tags_show():
    with temp_audio_file() as temp_audio:
        runner = CliRunner()
        result = runner.invoke(cli, ['tags-show', temp_audio])
        assert loads(result.output) == {}

def test_tags_update():
    with temp_audio_file() as temp_audio:
        runner = CliRunner()
        result = runner.invoke(cli, ['tags-update', temp_audio, 'artist=foo'])
        assert result.output == 'true\n'

        result = runner.invoke(cli, ['tags-show', temp_audio])
        assert loads(result.output) == {'artist': 'foo'}

def test_picture_update_and_extract():
    with temp_audio_file() as temp_audio:
        with temp_image_file(suffix='.jpg') as temp_image:
            runner = CliRunner()
            result = runner.invoke(cli, ['picture-update', temp_audio, temp_image])
            assert result.output == 'true\n'

            with NamedTemporaryFile(suffix='.jpg') as new_file:
                result = runner.invoke(cli, ['picture-extract', temp_audio, new_file.name])
                new_file_path = Path(new_file.name)
                assert new_file_path.stat().st_size > 0
                assert loads(result.output) == {
                    'encoding': 3,
                    'mime': 'image/jpeg',
                    'type': 3,
                    'output_path': new_file.name,
                    'desc': 'cover'
                }

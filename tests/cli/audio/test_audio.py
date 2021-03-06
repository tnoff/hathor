from io import StringIO

import mock

from hathor.cli import audio as cli
from tests import utils as test_utils

class TestAudioClient(test_utils.TestHelper):
    def test_tags_delete(self):
        kwargs = {
            'module' : 'tags',
            'command' : 'delete',
            'input_file' : 'foo',
            'tag_list' : ['bar', 'derp'],
        }
        with mock.patch('sys.stdout', new_callable=StringIO) as mock_out:
            with mock.patch('hathor.audio.metadata.tags_delete') as mock_class:
                mock_class.return_value = ['bar', 'derp']
                x = cli.AudioCLI(**kwargs)
                x.run_command()
        self.assertEqual(mock_out.getvalue(), 'bar, derp\n')

    def test_tags_update(self):
        kwargs = {
            'module' : 'tags',
            'command' : 'update',
            'input_file' : 'foo',
            'key_values' : {
                'foo' : 'derp',
                'bar' : 'herp',
            },
        }
        output = "+-----+-------+\n" \
                 "| Key | Value |\n" \
                 "+-----+-------+\n" \
                 "| bar |  herp |\n" \
                 "| foo |  derp |\n" \
                 "+-----+-------+\n"
        with mock.patch('sys.stdout', new_callable=StringIO) as mock_out:
            with mock.patch('hathor.audio.metadata.tags_update') as mock_class:
                mock_class.return_value = {
                    'foo' : 'derp',
                    'bar' : 'herp',
                }
                x = cli.AudioCLI(**kwargs)
                x.run_command()
            self.assertEqual(mock_out.getvalue(), output)

    def test_tags_show(self):
        kwargs = {
            'module' : 'tags',
            'command' : 'show',
            'input_file' : 'foo',
            'key_values' : {
                'foo' : 'foo2',
                'bar' : 'bar2',
            },
        }
        output = "+-----+-------+\n" \
                 "| Key | Value |\n" \
                 "+-----+-------+\n" \
                 "| bar |  bar2 |\n" \
                 "| foo |  foo2 |\n" \
                 "+-----+-------+\n"
        with mock.patch('sys.stdout', new_callable=StringIO) as mock_out:
            with mock.patch('hathor.audio.metadata.tags_show') as mock_class:
                mock_class.return_value = {
                    'foo' : 'foo2',
                    'bar' : 'bar2',
                }
                x = cli.AudioCLI(**kwargs)
                x.run_command()
            self.assertEqual(mock_out.getvalue(), output)

    def test_picture_extract(self):
        kwargs = {
            'module' : 'picture',
            'command' : 'extract',
            'input_file' : 'foo',
            'output_file' : 'bar',
        }
        output = "+-------------+-----------+\n" \
                "|     Key     |   Value   |\n" \
                "+-------------+-----------+\n" \
                "|     desc    | some text |\n" \
                "|   encoding  |     3     |\n" \
                "|     mime    |    foo    |\n" \
                "| output_path |    bar    |\n" \
                "|     type    |   cover   |\n" \
                "+-------------+-----------+\n"
        with mock.patch('sys.stdout', new_callable=StringIO) as mock_out:
            with mock.patch('hathor.audio.metadata.picture_extract') as mock_class:
                mock_class.return_value = {
                    'encoding' : 3,
                    'mime' : 'foo',
                    'type' : 'cover',
                    'desc' : 'some text',
                    'output_path' : 'bar',
                }
                x = cli.AudioCLI(**kwargs)
                x.run_command()
            self.assertEqual(mock_out.getvalue(), output)

    def test_picture_update(self):
        kwargs = {
            'module' : 'picture',
            'command' : 'extract',
            'audio_file' : 'foo',
            'picture_file' : 'bar',
        }
        with mock.patch('sys.stdout', new_callable=StringIO) as mock_out:
            with mock.patch('hathor.audio.metadata.picture_extract') as mock_class:
                mock_class.return_value = True
                x = cli.AudioCLI(**kwargs)
                x.run_command()
        self.assertEqual(mock_out.getvalue(), "Success\n")

    def test_picture_update_fail(self):
        kwargs = {
            'module' : 'picture',
            'command' : 'extract',
            'audio_file' : 'foo',
            'picture_file' : 'bar',
        }
        with mock.patch('sys.stdout', new_callable=StringIO) as mock_out:
            with mock.patch('hathor.audio.metadata.picture_extract') as mock_class:
                mock_class.return_value = False
                x = cli.AudioCLI(**kwargs)
                x.run_command()
        self.assertEqual(mock_out.getvalue(), "Fail\n")

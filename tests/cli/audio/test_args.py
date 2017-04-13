from hathor import settings
from hathor.cli import audio as cli
from hathor.exc import CLIException
from tests import utils as test_utils

class TestGlobalArgs(test_utils.TestHelper):
    def setUp(self):
        # common function to test globals
        self.func = ['tags', 'show', 'foo']

    def test_defaults(self):
        args = cli.parse_args(self.func)
        self.assertEqual(args.pop('module'), 'tags')
        self.assertEqual(args.pop('command'), 'show')
        self.assertEqual(args.pop('column_limit'), settings.COLUMN_LIMIT_DEFAULT)
        self.assertEqual(args.pop('reverse_sort'), False)
        args.pop('input_file', None)
        for key in ['keys', 'sort_key']:
            self.assertEqual(args.pop(key), None)
        self.assert_length(args.keys(), 0)

    def test_column_limit(self):
        with self.assertRaises(CLIException) as error:
            cli.parse_args(['-c', 'foo'] + self.func)
        self.check_error_message("argument -c/--column-limit:"
                                 " invalid int value: 'foo'", error)

        args = cli.parse_args(['-c', '20'] + self.func)
        self.assertEqual(args['column_limit'], 20)
        args = cli.parse_args(['--column-limit', '20'] + self.func)
        self.assertEqual(args['column_limit'], 20)

    def test_keys(self):
        args = cli.parse_args(['-k', 'foo'] + self.func)
        self.assertEqual(args['keys'], 'foo')
        args = cli.parse_args(['--keys', 'foo'] + self.func)
        self.assertEqual(args['keys'], 'foo')

    def test_sort_key(self):
        args = cli.parse_args(['-sk', 'foo'] + self.func)
        self.assertEqual(args['sort_key'], 'foo')
        args = cli.parse_args(['--sort-key', 'foo'] + self.func)
        self.assertEqual(args['sort_key'], 'foo')

class TestTagArgs(test_utils.TestHelper):
    def test_tags_show(self):
        expected = {
            'module' : 'tags',
            'command' : 'show',
            'input_file' : 'foo',
        }
        args = cli.parse_args(['tags', 'show', 'foo'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

    def test_tags_delete(self):
        expected = {
            'module' : 'tags',
            'command' : 'delete',
            'input_file' : 'foo',
            'tags_list' : ['bar', 'derp'],
        }
        args = cli.parse_args(['tags', 'delete', 'foo', 'bar', 'derp'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

    def test_tags_update(self):
        expected = {
            'module' : 'tags',
            'command' : 'update',
            'input_file' : 'foo',
            'key_values' : {
                'bar' : 'derp',
                'herp' : 'sherp',
            }
        }
        args = cli.parse_args(['tags', 'update', 'foo', '{"bar":"derp","herp":"sherp"}'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['tags', 'update', 'foo', 'bar'])
        self.check_error_message("argument key_values:"
                                 " invalid loads value: 'bar'", error)

class TestPictureArgs(test_utils.TestHelper):
    def test_picture_extract(self):
        expected = {
            'module' : 'picture',
            'command' : 'extract',
            'input_file' : 'foo',
            'output_file' : 'bar',
        }
        args = cli.parse_args(['picture', 'extract', 'foo', 'bar'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

    def test_picture_update(self):
        expected = {
            'module' : 'picture',
            'command' : 'update',
            'audio_file' : 'foo',
            'picture_file' : 'bar',
        }
        args = cli.parse_args(['picture', 'update', 'foo', 'bar'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        common_args = ['picture', 'update', 'foo', 'bar']

        with self.assertRaises(CLIException) as error:
            cli.parse_args(common_args + ['--encoding', 'foo'])
        self.check_error_message("argument --encoding:"
                                 " invalid int value: 'foo'",
                                 error)
        with self.assertRaises(CLIException) as error:
            cli.parse_args(common_args + ['--picture-type', 'foo'])
        self.check_error_message("argument --picture-type:"
                                 " invalid int value: 'foo'",
                                 error)

        args = cli.parse_args(common_args + ['--encoding', '3'])
        self.assertEqual(args['encoding'], 3)

        args = cli.parse_args(common_args + ['--picture-type', '4'])
        self.assertEqual(args['picture_type'], 4)

        args = cli.parse_args(common_args + ['--description', 'derp'])
        self.assertEqual(args['description'], 'derp')

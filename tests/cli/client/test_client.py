from io import StringIO

import mock

from hathor import utils
from hathor.cli.client import generate_args, load_settings, ClientCLI
from hathor.exc import CLIException
from tests import utils as test_utils

class TestClientCLI(test_utils.TestHelper):
    def test_cli_class_no_results(self):
        kwargs = {
            'column_limit' : -1,
            'module' : 'podcast',
            'command' : 'list',
            'logging_file_level' : 10,
            'console_logging_level' : 10,
        }
        with mock.patch('hathor.client.HathorClient') as mock_class:
            with mock.patch('sys.stdout', new_callable=StringIO) as mock_out:
                instance = mock_class.return_value
                instance.podcast_list.return_value = []
                x = ClientCLI(**kwargs)
                x.run_command()
            self.assertEqual("No items\n", mock_out.getvalue())

    def test_keys(self):
        kwargs = {
            'column_limit' : -1,
            'module' : 'podcast',
            'command' : 'list',
            'logging_file_level' : 10,
            'console_logging_level' : 10,
        }
        x = ClientCLI(**kwargs)
        self.assertEqual(x.keys, None)

        kwargs['keys'] = 'foo'
        x = ClientCLI(**kwargs)
        self.assertEqual(x.keys, ['foo'])

        kwargs['keys'] = 'foo,bar'
        x = ClientCLI(**kwargs)
        self.assertEqual(x.keys, ['foo', 'bar'])

    def test_return_none(self):
        kwargs = {
            'column_limit' : 100,
            'module' : 'podcast',
            'command' : 'list',
            'logging_file_level' : 10,
            'console_logging_level' : 10,
        }
        with mock.patch('hathor.client.HathorClient') as mock_class:
            with mock.patch('sys.stdout', new_callable=StringIO) as mock_out:
                instance = mock_class.return_value
                instance.podcast_list.return_value = None
                x = ClientCLI(**kwargs)
                x.run_command()
            self.assertEqual(mock_out.getvalue(), '')

    def test_return_list(self):
        kwargs = {
            'column_limit' : 100,
            'module' : 'podcast',
            'command' : 'delete',
            'logging_file_level' : 10,
            'console_logging_level' : 10,
        }
        with mock.patch('hathor.client.HathorClient') as mock_class:
            with mock.patch('sys.stdout', new_callable=StringIO) as mock_out:
                instance = mock_class.return_value
                instance.podcast_delete.return_value = [2, 5]
                x = ClientCLI(**kwargs)
                x.run_command()
            self.assertEqual(mock_out.getvalue(), '2, 5\n')

    def test_return_bool_true(self):
        kwargs = {
            'column_limit' : 100,
            'module' : 'podcast',
            'command' : 'update',
            'logging_file_level' : 10,
            'console_logging_level' : 10,
        }
        with mock.patch('hathor.client.HathorClient') as mock_class:
            with mock.patch('sys.stdout', new_callable=StringIO) as mock_out:
                instance = mock_class.return_value
                instance.podcast_update.return_value = True
                x = ClientCLI(**kwargs)
                x.run_command()
            self.assertEqual("Success\n", mock_out.getvalue())

    def test_return_bool_false(self):
        kwargs = {
            'column_limit' : 100,
            'module' : 'podcast',
            'command' : 'update',
            'logging_file_level' : 10,
            'console_logging_level' : 10,
        }
        with mock.patch('hathor.client.HathorClient') as mock_class:
            with mock.patch('sys.stdout', new_callable=StringIO) as mock_out:
                instance = mock_class.return_value
                instance.podcast_update.return_value = False
                x = ClientCLI(**kwargs)
                x.run_command()
            self.assertEqual("Fail\n", mock_out.getvalue())

    def test_return_dict_invalid_keys(self):
        kwargs = {
            'column_limit' : 100,
            'module' : 'podcast',
            'command' : 'list',
            'logging_file_level' : 10,
            'console_logging_level' : 10,
            'keys' : 'foo',
        }
        with mock.patch('hathor.client.HathorClient') as mock_class:
            instance = mock_class.return_value
            instance.podcast_list.return_value = [
                {
                    'id' : 1,
                    'name' : 'foo',
                },
                {
                    'id' : 2,
                    'name' : 'derp',
                },
            ]
            x = ClientCLI(**kwargs)
            with self.assertRaises(CLIException) as error:
                x.run_command()
            self.check_error_message("Invalid key:foo", error)

    def test_return_dict_list(self):
        kwargs = {
            'column_limit' : 100,
            'module' : 'podcast',
            'command' : 'list',
            'logging_file_level' : 10,
            'console_logging_level' : 10,
        }
        output = "+----+------+\n" \
                 "| Id | Name |\n" \
                 "+----+------+\n" \
                 "| 1  | foo  |\n" \
                 "| 2  | derp |\n" \
                 "+----+------+\n"
        with mock.patch('hathor.client.HathorClient') as mock_class:
            with mock.patch('sys.stdout', new_callable=StringIO) as mock_out:
                instance = mock_class.return_value
                instance.podcast_list.return_value = [
                    {
                        'id' : 1,
                        'name' : 'foo',
                    },
                    {
                        'id' : 2,
                        'name' : 'derp',
                    },
                ]
                x = ClientCLI(**kwargs)
                x.run_command()
            self.assertEqual(mock_out.getvalue(), output)

    def test_return_dict_list_with_pod_cache(self):
        kwargs = {
            'column_limit' : 100,
            'module' : 'episode',
            'command' : 'list',
            'logging_file_level' : 10,
            'console_logging_level' : 10,
        }
        output = "+----+------+---------+\n" \
                 "| Id | Name | Podcast |\n" \
                 "+----+------+---------+\n" \
                 "| 1  | foo  |  name1  |\n" \
                 "| 2  | derp |  name1  |\n" \
                 "+----+------+---------+\n"
        with mock.patch('hathor.client.HathorClient') as mock_class:
            with mock.patch('sys.stdout', new_callable=StringIO) as mock_out:
                instance = mock_class.return_value
                instance.podcast_list.return_value = [
                    {
                        'id' : 3,
                        'name' : 'name1',
                    },
                ]
                instance.episode_list.return_value = [
                    {
                        'id' : 1,
                        'name' : 'foo',
                        'podcast_id' : 3,
                    },
                    {
                        'id' : 2,
                        'name' : 'derp',
                        'podcast_id' : 3,
                    },
                ]
                x = ClientCLI(**kwargs)
                x.run_command()
            self.assertEqual(mock_out.getvalue(), output)

    def test_return_dict_list_with_pod_cache_podcast(self):
        kwargs = {
            'column_limit' : 100,
            'module' : 'episode',
            'command' : 'list',
            'logging_file_level' : 10,
            'console_logging_level' : 10,
        }
        output = "+----+------+---------+\n" \
                 "| Id | Name | Podcast |\n" \
                 "+----+------+---------+\n" \
                 "| 1  | foo  |  name1  |\n" \
                 "| 2  | derp |  name1  |\n" \
                 "+----+------+---------+\n"
        with mock.patch('hathor.client.HathorClient') as mock_class:
            with mock.patch('sys.stdout', new_callable=StringIO) as mock_out:
                instance = mock_class.return_value
                instance.podcast_list.return_value = [
                    {
                        'id' : 3,
                        'name' : 'name1',
                    },
                ]
                instance.episode_list.return_value = [
                    {
                        'id' : 1,
                        'name' : 'foo',
                        'podcast' : 3,
                    },
                    {
                        'id' : 2,
                        'name' : 'derp',
                        'podcast' : 3,
                    },
                ]
                x = ClientCLI(**kwargs)
                x.run_command()
            self.assertEqual(mock_out.getvalue(), output)

    def test_cli_settings_file(self):
        with utils.temp_file(suffix='.conf') as tempfile:
            with open(tempfile, 'w+') as writer:
                writer.write('[general]\ndatabase_file = foo\n'
                             'datetime_output_format = foo\n'
                             'logging_file = foo\n'
                             'logging_file_level = foo\n'
                             'console_logging = foo\n'
                             'console_logging_level = foo\n'
                             '[podcasts]\n'
                             'soundcloud_client_id = foo\n'
                             'google_api_key = foo\n'
                             'podcast_directory = foo\n')

            args = load_settings(tempfile)
            for _, value in args.items():
                self.assertEqual(value, 'foo')

    def test_load_settings_none(self):
        args = load_settings(None)
        self.assertEqual(args, {})

    def test_load_settings_without_values(self):
        with utils.temp_file(suffix='.conf') as tempfile:
            with open(tempfile, 'w+') as writer:
                writer.write('\n')
            args = load_settings(tempfile)
            for _, value in args.items():
                self.assert_none(value)

    def test_generate_args(self):
        with utils.temp_file(suffix='.conf') as tempfile:
            with open(tempfile, 'w+') as writer:
                writer.write('[general]\ndatabase_file = foo\n'
                             'logging_file = foo\n')
            # make sure settings are used
            # as well as any overrides given on cli work
            args = generate_args(['-s', tempfile, '-l', 'bar', '-ll', 'warn', 'episode', 'list'])
            self.assertEqual(args['database_file'], 'foo')
            self.assertEqual(args['logging_file'], 'bar')
            # make sure default logging levels set, if not given
            self.assertEqual(args['logging_file_level'], 30)
            self.assertEqual(args['console_logging_level'], 20)

from hathor import client, settings, utils
from hathor.cli import client as cli
from hathor.exc import CLIException
from tests import utils as test_utils

LOG_LEVELS = [
    'debug',
    'info',
    'warn',
    'error',
]

class TestGlobalArgs(test_utils.TestHelper):
    def setUp(self):
        # common function to test globals
        self.func = ['podcast', 'list']

    def test_defaults(self):
        args = cli.parse_args(self.func)
        self.assertEqual(args.pop('settings'), settings.DEFAULT_SETTINGS_FILE)
        self.assertEqual(args.pop('module'), 'podcast')
        self.assertEqual(args.pop('command'), 'list')
        self.assertEqual(args.pop('column_limit'), settings.COLUMN_LIMIT_DEFAULT)
        self.assertEqual(args.pop('console_logging'), False)
        self.assertEqual(args.pop('reverse_sort'), False)
        null_args = ['database_file', 'logging_file', 'google_api_key',
                     'podcast_directory', 'keys', 'sort_key',
                     'datetime_output_format', 'console_logging_level',
                     'logging_file_level', 'soundcloud_client_id',]
        for key in null_args:
            self.assertEqual(args.pop(key), None)
        self.assert_length(args.keys(), 0)

    def test_settings(self):
        settings_file = utils.random_string(prefix='/home/foo/')
        args = cli.parse_args(['-s', settings_file] + self.func)
        self.assertEqual(args['settings'], settings_file)
        args = cli.parse_args(['--settings', settings_file] + self.func)
        self.assertEqual(args['settings'], settings_file)

    def test_database(self):
        database_file = utils.random_string(prefix='/home/bar/')
        args = cli.parse_args(['-d', database_file] + self.func)
        self.assertEqual(args['database_file'], database_file)
        args = cli.parse_args(['--database', database_file] + self.func)
        self.assertEqual(args['database_file'], database_file)

    def test_log_file(self):
        log_file = utils.random_string(prefix='/home/derp/')
        args = cli.parse_args(['-l', log_file] + self.func)
        self.assertEqual(args['logging_file'], log_file)
        args = cli.parse_args(['--log-file', log_file] + self.func)
        self.assertEqual(args['logging_file'], log_file)

    def test_log_file_level(self):
        with self.assertRaises(CLIException) as error:
            cli.parse_args(['-ll', 'foo'])
        self.check_error_message("argument -ll/--log-file-level: invalid choice: "
                                 "'foo' (choose from 'debug', 'error', 'info', 'warn')",
                                 error)
        for level in LOG_LEVELS:
            args = cli.parse_args(['-ll', level] + self.func)
            self.assertEqual(args['logging_file_level'], level)
            args = cli.parse_args(['--log-file-level', level] + self.func)
            self.assertEqual(args['logging_file_level'], level)

    def test_datetime_output_format(self):
        df = utils.random_string()
        args = cli.parse_args(['-df', df] + self.func)
        self.assertEqual(args['datetime_output_format'], df)
        args = cli.parse_args(['--datetime-format', df] + self.func)
        self.assertEqual(args['datetime_output_format'], df)

    def test_soundcloud_client_id(self):
        sc = utils.random_string()
        args = cli.parse_args(['-sc', sc] + self.func)
        self.assertEqual(args['soundcloud_client_id'], sc)
        args = cli.parse_args(['--soundcloud', sc] + self.func)
        self.assertEqual(args['soundcloud_client_id'], sc)

    def test_google_api_key(self):
        ga = utils.random_string()
        args = cli.parse_args(['-g', ga] + self.func)
        self.assertEqual(args['google_api_key'], ga)
        args = cli.parse_args(['--google', ga] + self.func)
        self.assertEqual(args['google_api_key'], ga)

    def test_podcast_directory(self):
        pd = utils.random_string(prefix='/home/derp/')
        args = cli.parse_args(['-p', pd] + self.func)
        self.assertEqual(args['podcast_directory'], pd)
        args = cli.parse_args(['--podcast-dir', pd] + self.func)
        self.assertEqual(args['podcast_directory'], pd)

    def test_column_limit(self):
        with self.assertRaises(CLIException) as error:
            cli.parse_args(['-c', 'foo'] + self.func)
        self.check_error_message("argument -c/--column-limit: invalid int value: 'foo'",
                                 error)

    def test_console_log(self):
        args = cli.parse_args(['-cl'] + self.func)
        self.assertTrue(args['console_logging'])
        args = cli.parse_args(['-cl'] + self.func)
        self.assertTrue(args['console_logging'])

    def test_console_log_level(self):
        with self.assertRaises(CLIException) as error:
            cli.parse_args(['-cll', 'foo'])
        self.check_error_message("argument -cll/--console-log-level: invalid choice: "
                                 "'foo' (choose from 'debug', 'error', 'info', 'warn')",
                                 error)
        for level in LOG_LEVELS:
            args = cli.parse_args(['-cll', level] + self.func)
            self.assertEqual(args['console_logging_level'], level)
            args = cli.parse_args(['--console-log-level', level] + self.func)
            self.assertEqual(args['console_logging_level'], level)

    def test_keys(self):
        key = utils.random_string()
        args = cli.parse_args(['-k', key] + self.func)
        self.assertEqual(args['keys'], key)
        args = cli.parse_args(['--keys', key] + self.func)
        self.assertEqual(args['keys'], key)
        # make sure comma seperated works
        args = cli.parse_args(['--keys', 'foo,foo2'] + self.func)
        self.assertEqual(args['keys'], 'foo,foo2')

    def test_sort_key(self):
        key = utils.random_string()
        args = cli.parse_args(['-sk', key] + self.func)
        self.assertEqual(args['sort_key'], key)
        args = cli.parse_args(['--sort-key', key] + self.func)
        self.assertEqual(args['sort_key'], key)


class TestFilterArgs(test_utils.TestHelper):
    def test_filter_list(self):
        args = cli.parse_args(['filter', 'list'])
        self.assertEqual(args['module'], 'filter')
        self.assertEqual(args['command'], 'list')

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['filter', 'list', '-i', 'foo'])
        self.check_error_message("argument -i/--include-podcasts: invalid"
                                 " int value: 'foo'", error)
        with self.assertRaises(CLIException) as error:
            cli.parse_args(['filter', 'list', '-e', 'foo'])
        self.check_error_message("argument -e/--exclude-podcasts: invalid"
                                 " int value: 'foo'", error)

        args = cli.parse_args(['filter', 'list', '-i', '5'])
        self.assertEqual(args['include_podcasts'], [5])
        args = cli.parse_args(['filter', 'list', '-i', '5', '7'])
        self.assertEqual(args['include_podcasts'], [5, 7])

        args = cli.parse_args(['filter', 'list', '-e', '5'])
        self.assertEqual(args['exclude_podcasts'], [5])
        args = cli.parse_args(['filter', 'list', '-e', '5', '7'])
        self.assertEqual(args['exclude_podcasts'], [5, 7])

    def test_filter_create(self):
        regex = utils.random_string()
        expected = {
            'module' : 'filter',
            'command' : 'create',
            'podcast_id' : 1,
            'regex_string' : regex,
        }
        args = cli.parse_args(['filter', 'create', '1', regex])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['filter', 'create', 'foo', 'foo'])
        self.check_error_message("argument podcast_id: invalid"
                                 " int value: 'foo'", error)

    def test_filter_delete(self):
        expected = {
            'module' : 'filter',
            'command' : 'delete',
            'filter_input' : [1],
        }
        args = cli.parse_args(['filter', 'delete', '1',])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['filter', 'delete', 'foo'])
        self.check_error_message("argument filter_input: invalid"
                                 " int value: 'foo'", error)
        # make sure multiple works
        args = cli.parse_args(['filter', 'delete', '2', '6'])
        self.assertEqual(args['filter_input'], [2, 6])

class TestPodcastArgs(test_utils.TestHelper):
    def test_podcast_create(self):
        expected = {
            'module' : 'podcast',
            'command' : 'create',
            'file_location' : None,
            'artist_name' : None,
            'automatic_download' : True,
            'max_allowed' : None,
            'podcast_name' : utils.random_string(),
            'archive_type' : 'rss',
            'broadcast_id' : utils.random_string(),
        }
        common_args = [
            'podcast',
            'create',
            expected['podcast_name'],
            expected['archive_type'],
            expected['broadcast_id'],
        ]
        args = cli.parse_args(common_args)
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['podcast', 'create', 'foo',
                            'bar', 'foo'])
        self.check_error_message("argument archive_type: invalid choice:"
                                 " 'bar' (choose from 'rss', 'soundcloud', 'youtube')", error)

        for choice in client.ARCHIVE_TYPES:
            args = cli.parse_args(['podcast', 'create', 'foo',
                                   choice, 'bar'])
            self.assertEqual(args['archive_type'], choice)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(common_args + ['--max-allowed', 'foo'])
        self.check_error_message("argument --max-allowed: invalid"
                                 " int value: 'foo'", error)

        args = cli.parse_args(common_args + ['--max-allowed', '8'])
        self.assertEqual(args['max_allowed'], 8)

        file_location = utils.random_string()
        args = cli.parse_args(common_args + ['--file-location', file_location])
        self.assertEqual(args['file_location'], file_location)

        artist = utils.random_string()
        args = cli.parse_args(common_args + ['--artist-name', artist])
        self.assertEqual(args['artist_name'], artist)

        args = cli.parse_args(common_args + ['--no-auto-download'])
        self.assertFalse(args['automatic_download'])

    def test_podcast_list(self):
        expected = {
            'module' : 'podcast',
            'command' : 'list',
        }
        args = cli.parse_args(['podcast', 'list'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

    def test_podcast_show(self):
        expected = {
            'module' : 'podcast',
            'command' : 'show',
            'podcast_input' : [5],
        }
        args = cli.parse_args(['podcast', 'show', '5'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['podcast', 'show', 'foo'])
        self.check_error_message("argument podcast_input:"
                                 " invalid int value: 'foo'", error)

        args = cli.parse_args(['podcast', 'show', '5', '10'])
        self.assertEqual(args['podcast_input'], [5, 10])

    def test_podcast_delete(self):
        expected = {
            'module' : 'podcast',
            'command' : 'delete',
            'podcast_input' : [5],
            'delete_files' : True,
        }
        args = cli.parse_args(['podcast', 'delete', '5'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['podcast', 'delete', 'foo'])
        self.check_error_message("argument podcast_input:"
                                 " invalid int value: 'foo'", error)

        args = cli.parse_args(['podcast', 'delete', '5', '10'])
        self.assertEqual(args['podcast_input'], [5, 10])

        args = cli.parse_args(['podcast', 'delete', '--keep-files', '5'])
        self.assertFalse(args['delete_files'])

    def test_podcast_update(self):
        expected = {
            'module' : 'podcast',
            'command' : 'update',
            'podcast_id' : 5,
        }
        args = cli.parse_args(['podcast', 'update', '5'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['podcast', 'update', 'foo'])
        self.check_error_message("argument podcast_id:"
                                 " invalid int value: 'foo'", error)

        common_args = ['podcast', 'update', '5']

        pod_name = utils.random_string()
        args = cli.parse_args(common_args + ['--podcast-name', pod_name])
        self.assertEqual(args['podcast_name'], pod_name)

        broadcast_id = utils.random_string()
        args = cli.parse_args(common_args + ['--broadcast-id', broadcast_id])
        self.assertEqual(args['broadcast_id'], broadcast_id)

        artist_name = utils.random_string()
        args = cli.parse_args(common_args + ['--artist-name', artist_name])
        self.assertEqual(args['artist_name'], artist_name)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(common_args + ['--max-allowed', 'foo'])
        self.check_error_message("argument --max-allowed:"
                                 " invalid int value: 'foo'", error)

        args = cli.parse_args(common_args + ['--max-allowed', '11'])
        self.assertEqual(args['max_allowed'], 11)

        args = cli.parse_args(common_args + ['--auto-download'])
        self.assertTrue(args['automatic_download'])
        args = cli.parse_args(common_args + ['--no-auto-download'])
        self.assertFalse(args['automatic_download'])

        args = cli.parse_args(common_args)
        self.assert_none(args['automatic_download'])

        with self.assertRaises(CLIException) as error:
            cli.parse_args(common_args + ['--auto-download', '--no-auto-download'])
        self.check_error_message("argument --no-auto-download: not allowed"
                                 " with argument --auto-download", error)

    def test_podcast_update_file_location(self):
        expected = {
            'module' : 'podcast',
            'command' : 'update-file-location',
            'podcast_id' : 5,
            'file_location' : 'foo',
            'move_files' : True,
        }
        args = cli.parse_args(['podcast', 'update-file-location', '5', 'foo'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['podcast', 'update-file-location', 'foo', 'foo'])
        self.check_error_message("argument podcast_id:"
                                 " invalid int value: 'foo'", error)

        args = cli.parse_args(['podcast', 'update-file-location',
                               '2', 'foo', '--no-move'])
        self.assertFalse(args['move_files'])

    def test_podcast_sync(self):
        expected = {
            'module' : 'podcast',
            'command' : 'sync',
            'sync_web_episodes' : True,
            'download_episodes' : True,
        }
        args = cli.parse_args(['podcast', 'sync'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        common_args = ['podcast', 'sync']
        args = cli.parse_args(common_args + ['--no-web-sync'])
        self.assertFalse(args['sync_web_episodes'])

        args = cli.parse_args(common_args + ['--no-download'])
        self.assertFalse(args['download_episodes'])

        with self.assertRaises(CLIException) as error:
            cli.parse_args(common_args + ['-i', 'foo'])
        self.check_error_message("argument -i/--include-podcasts:"
                                 " invalid int value: 'foo'", error)
        with self.assertRaises(CLIException) as error:
            cli.parse_args(common_args + ['-e', 'foo'])
        self.check_error_message("argument -e/--exclude-podcasts:"
                                 " invalid int value: 'foo'", error)

        args = cli.parse_args(common_args + ['-i', '5', '10'])
        self.assertEqual(args['include_podcasts'], [5, 10])
        args = cli.parse_args(common_args + ['--include-podcasts', '5', '10'])
        self.assertEqual(args['include_podcasts'], [5, 10])

        args = cli.parse_args(common_args + ['-e', '5', '10'])
        self.assertEqual(args['exclude_podcasts'], [5, 10])
        args = cli.parse_args(common_args + ['--exclude-podcasts', '5', '10'])
        self.assertEqual(args['exclude_podcasts'], [5, 10])


class TestEpisodeArgs(test_utils.TestHelper):
    def test_episode_list(self):
        expected = {
            'module' : 'episode',
            'command' : 'list',
            'only_files' : True,
        }
        args = cli.parse_args(['episode', 'list'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        common_args = ['episode', 'list']
        with self.assertRaises(CLIException) as error:
            cli.parse_args(common_args + ['-i', 'foo'])
        self.check_error_message("argument -i/--include-podcasts:"
                                 " invalid int value: 'foo'", error)
        with self.assertRaises(CLIException) as error:
            cli.parse_args(common_args + ['-e', 'foo'])
        self.check_error_message("argument -e/--exclude-podcasts:"
                                 " invalid int value: 'foo'", error)

        args = cli.parse_args(common_args + ['-i', '5', '10'])
        self.assertEqual(args['include_podcasts'], [5, 10])
        args = cli.parse_args(common_args + ['--include-podcasts', '5', '10'])
        self.assertEqual(args['include_podcasts'], [5, 10])

        args = cli.parse_args(common_args + ['-e', '5', '10'])
        self.assertEqual(args['exclude_podcasts'], [5, 10])
        args = cli.parse_args(common_args + ['--exclude-podcasts', '5', '10'])
        self.assertEqual(args['exclude_podcasts'], [5, 10])

        args = cli.parse_args(common_args + ['--all'])
        self.assertFalse(args['only_files'])

    def test_episode_show(self):
        expected = {
            'module' : 'episode',
            'command' : 'show',
            'episode_input' : [5],
        }
        args = cli.parse_args(['episode', 'show', '5'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['episode', 'show', 'bar'])
        self.check_error_message("argument episode_input:"
                                 " invalid int value: 'bar'", error)

        args = cli.parse_args(['episode', 'show', '6', '12'])
        self.assertEqual(args['episode_input'], [6, 12])

    def test_episosde_delete(self):
        expected = {
            'module' : 'episode',
            'command' : 'delete',
            'episode_input' : [5],
            'delete_files' : True,
        }
        args = cli.parse_args(['episode', 'delete', '5'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['episode', 'delete', 'bar'])
        self.check_error_message("argument episode_input:"
                                 " invalid int value: 'bar'", error)

        args = cli.parse_args(['episode', 'delete', '6', '12'])
        self.assertEqual(args['episode_input'], [6, 12])

        args = cli.parse_args(['episode', 'delete', '--keep-files', '6'])
        self.assertFalse(args['delete_files'])

    def test_episode_delete_file(self):
        expected = {
            'module' : 'episode',
            'command' : 'delete-file',
            'episode_input' : [5],
        }
        args = cli.parse_args(['episode', 'delete-file', '5'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['episode', 'delete-file', 'bar'])
        self.check_error_message("argument episode_input:"
                                 " invalid int value: 'bar'", error)

        args = cli.parse_args(['episode', 'delete-file', '6', '12'])
        self.assertEqual(args['episode_input'], [6, 12])

    def test_episode_download(self):
        expected = {
            'module' : 'episode',
            'command' : 'download',
            'episode_input' : [5],
        }
        args = cli.parse_args(['episode', 'download', '5'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['episode', 'download', 'bar'])
        self.check_error_message("argument episode_input:"
                                 " invalid int value: 'bar'", error)

        args = cli.parse_args(['episode', 'download', '6', '12'])
        self.assertEqual(args['episode_input'], [6, 12])

    def test_episode_update(self):
        expected = {
            'module' : 'episode',
            'command' : 'update',
            'episode_id' : 5,
        }
        args = cli.parse_args(['episode', 'update', '5'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['episode', 'update', '5', '--prevent-delete',
                            '--allow-delete'])
        self.check_error_message("argument --allow-delete: not allowed"
                                 " with argument --prevent-delete", error)

        args = cli.parse_args(['episode', 'update', '5', '--prevent-delete'])
        self.assertTrue(args['prevent_delete'])
        args = cli.parse_args(['episode', 'update', '5', '--allow-delete'])
        self.assertFalse(args['prevent_delete'])

        args = cli.parse_args(['episode', 'update', '5'])
        self.assert_none(args['prevent_delete'])

    def test_episode_update_file__path(self):
        expected = {
            'module' : 'episode',
            'command' : 'update-file-path',
            'episode_id' : 5,
            'file_path' : 'foo'
        }
        args = cli.parse_args(['episode', 'update-file-path', '5', 'foo'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

    def test_episode_sync(self):
        expected = {
            'module' : 'episode',
            'command' : 'sync',
        }
        args = cli.parse_args(['episode', 'sync'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['episode', 'sync', '--sync-num', 'bar'])
        self.check_error_message("argument --sync-num:"
                                 " invalid int value: 'bar'", error)

        with self.assertRaises(CLIException) as error:
            cli.parse_args(['episode', 'sync', '-i', 'foo'])
        self.check_error_message("argument -i/--include-podcasts:"
                                 " invalid int value: 'foo'", error)
        with self.assertRaises(CLIException) as error:
            cli.parse_args(['episode', 'sync', '-e', 'foo'])
        self.check_error_message("argument -e/--exclude-podcasts:"
                                 " invalid int value: 'foo'", error)

        common_args = ['episode', 'sync']
        args = cli.parse_args(common_args + ['--sync-num', '5'])
        self.assertEqual(args['max_episode_sync'], 5)

        args = cli.parse_args(common_args + ['-i', '5', '10'])
        self.assertEqual(args['include_podcasts'], [5, 10])
        args = cli.parse_args(common_args + ['-e', '5', '10'])
        self.assertEqual(args['exclude_podcasts'], [5, 10])
        args = cli.parse_args(common_args + ['--include-podcasts', '5', '10'])
        self.assertEqual(args['include_podcasts'], [5, 10])
        args = cli.parse_args(common_args + ['--exclude-podcasts', '5', '10'])
        self.assertEqual(args['exclude_podcasts'], [5, 10])

    def test_episode_cleanup(self):
        expected = {
            'module' : 'episode',
            'command' : 'cleanup',
        }
        args = cli.parse_args(['episode', 'cleanup'])
        for key, value in expected.items():
            self.assertEqual(args[key], value)

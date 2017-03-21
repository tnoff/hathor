from ConfigParser import NoSectionError, NoOptionError, SafeConfigParser
import argparse
import copy
import logging
import sys

from prettytable import PrettyTable

from hathor import client, settings
from hathor.exc import CLIException

CLIENT_ARGS = [
    "podcast_directory",
    "datetime_output_format",
    "logging_file",
    "logging_file_level",
    "database_file",
    "soundcloud_client_id",
    "google_api_key",
    "console_logging",
    "console_logging_level",
]

ORDERD_KEYS = [
    'id',
    'name',
    'podcast',
    'podcast_id',
    'date',
    'title',
]

LOG_SETTINGS_DICT = {
    'debug' : logging.DEBUG,
    'info' : logging.INFO,
    'warn' : logging.WARN,
    'error' : logging.ERROR,
}

class HandsomeTable(PrettyTable):
    def __init__(self, field_names, column_limit, **kwargs):
        if column_limit == -1:
            self.column_limit = None
        self.column_limit = column_limit
        super(HandsomeTable, self).__init__(field_names, **kwargs)

    def add_row(self, row_data):
        new_data = []
        for column in row_data:
            data = column
            if isinstance(column, basestring) and self.column_limit is not None:
                if len(column) > self.column_limit:
                    data = column[0:self.column_limit]
            new_data.append(data)
        super(HandsomeTable, self).add_row(new_data)


class CLI(object):
    def __init__(self, **kwargs):
        client_args = {}
        for key in CLIENT_ARGS:
            client_args[key] = kwargs.pop(key, None)

        self.column_limit = kwargs.pop('column_limit')
        self.keys = kwargs.pop('keys', None)
        if self.keys:
            self.keys = self.keys.split(',')
        self.sort_key = kwargs.pop('sort_key', None)

        module = kwargs.pop('module')
        command = kwargs.pop('command')

        function_name = '%s_%s' % (module, command)
        self.function_name = function_name.replace('-', '_')

        self.client = client.HathorClient(**client_args)
        self.kwargs = kwargs

    def run_command(self):
        method = getattr(self.client, self.function_name)
        return_value = method(**self.kwargs)
        self.print_result(return_value)

    def print_result(self, value): #pylint:disable=too-many-branches,too-many-statements
        # Output depends on function used
        # Could be one of:
        # - none
        # - tuple of two integer lists
        # - integer list
        # - list of dictionaries
        if value is None:
            return

        if isinstance(value, bool):
            if value is True:
                print 'Success'
            else:
                print 'Fail'
            return

        if isinstance(value, int):
            print value
            return

        if isinstance(value, tuple):
            for integer_list in value:
                if integer_list is None:
                    continue
                print ', '.join('%s' % item for item in integer_list)
            return

        # Now assume list
        if len(value) == 0:
            print 'No items'
            return

        if isinstance(value[0], int):
            print ', '.join('%s' % item for item in value)
            return
        # Safe to assume its a dictionary here
        # Keys is either defined by CLI, or all by default
        keys = self.keys
        if not keys:
            # If keys not given, make sure some
            # items, such as ID and Name, are
            # placed first
            keys = value[0].keys()
            index = 0
            for k in ORDERD_KEYS:
                try:
                    key_index = keys.index(k)
                    swap = keys[index]
                    keys[index] = keys[key_index]
                    keys[key_index] = swap
                    index += 1
                except ValueError:
                    pass
        # Show podcast name instead of podcast id
        # when possible. Create cache table now
        # to use later
        podcast_cache = dict()
        table_keys = copy.deepcopy(keys)
        if 'podcast_id' in keys or 'podcast' in keys:
            try:
                index = table_keys.index('podcast_id')
            except ValueError:
                index = table_keys.index('podcast')
            table_keys[index] = 'podcast'
            for item in self.client.podcast_list():
                podcast_cache[item['id']] = item['name']
        # Use handsome table so you can use column limit
        table = HandsomeTable(table_keys, self.column_limit)
        for item in value:
            item_list = []
            for k in keys:
                if k == 'podcast' or k == 'podcast_id':
                    try:
                        value = item['podcast_id']
                    except KeyError:
                        value = item['podcast']
                    value = podcast_cache[value]
                else:
                    try:
                        value = item[k]
                    except KeyError:
                        raise CLIException("Invalid key:%s" % k)
                item_list.append(value)
            table.add_row(item_list)
        print table.get_string(sortby=self.sort_key, reversesort=True)


class HathorArgparse(argparse.ArgumentParser):
    def error(self, message):
        raise CLIException(message)

def _podcast_args(sub_parser):
    podcast = sub_parser.add_parser('podcast', help='Podcast Module')

    podcast_sub = podcast.add_subparsers(description='Commands', dest='command')

    pod_add = podcast_sub.add_parser('create', help='Create new podcast')
    pod_add.add_argument('podcast_name', help='Podcast name')
    pod_add.add_argument('archive_type', choices=client.ARCHIVE_TYPES, help='Archive Type')
    pod_add.add_argument('broadcast_id', help='Broadcast ID')
    pod_add.add_argument('--max-allowed', type=int,
                         help='Maximum number of podcast episodes that will be downloaded to local machine')
    pod_add.add_argument('--remove-commercials', action='store_true', help='Remove commercials upon downloading episodes')
    pod_add.add_argument('--file-location', help='Path where podcast episode files will be stored')
    pod_add.add_argument('--artist-name', help='Name of artist for media metadata tags')
    pod_add.add_argument('--no-auto-download', action='store_false',
                         dest='automatic_download',
                         help='Do not automatically download new episodes with file-sync')

    podcast_sub.add_parser('list', help='List podcasts')

    pod_show = podcast_sub.add_parser('show', help='Show podcast info')
    pod_show.add_argument('podcast_input', nargs='+', type=int, help='Podcast ID(s)')

    pod_delete = podcast_sub.add_parser('delete', help='Delete podcast')
    pod_delete.add_argument('podcast_input', nargs='+', type=int, help='Podcast ID(s)')
    pod_delete.add_argument('--keep-files', action='store_false',
                            dest='delete_files', help='Do not delete media files for podcast')

    pod_up = podcast_sub.add_parser('update', help='Update podcast info')
    pod_up.add_argument('podcast_id', type=int, help='Podcast ID')
    pod_up.add_argument('--podcast-name', help='Podcast name')
    pod_up.add_argument('--broadcast-id', help='Broadcast ID')
    pod_up.add_argument('--max-allowed', type=int,
                        help='Maximum number of podcast episodes that will be downloaded'\
                             'to local machine, use 0 to set to None/Unlimited')
    remove_group = pod_up.add_mutually_exclusive_group()
    remove_group.add_argument('--remove-commercials', action='store_true',
                              help='Remove commercials upon downloading files')
    remove_group.add_argument('--keep-commercials', action='store_false',
                              dest='remove_commercials',
                              help='Keep commercials upon downloading files')
    pod_up.add_argument('--artist-name', help='Name ofartist for media metadata tags')
    auto_group = pod_up.add_mutually_exclusive_group()
    auto_group.add_argument('--auto-download', action='store_true',
                            dest='automatic_download',
                            help='Automatically download new episodes with file sync')
    auto_group.add_argument('--no-auto-download', action='store_false',
                            dest='automatic_download',
                            help='Do not automatically download new episodes with file sync')

    pod_update_file = podcast_sub.add_parser('update-file-location', help='Update file location')
    pod_update_file.add_argument('podcast_id', type=int, help='Podcast ID')
    pod_update_file.add_argument('file_location', help='New file location')
    pod_update_file.add_argument('--no-move', action='store_false',
                                 dest='move_files', help='Do not move episode files')

    pod_file = podcast_sub.add_parser('file-sync', help='Sync podcast episode files')
    pod_file.add_argument('-i', '--include-podcasts', nargs='+', type=int, help='Include these podcasts')
    pod_file.add_argument('-e', '--exclude-podcasts', nargs='+', type=int, help='Exclude these podcasts')
    pod_file.add_argument('--no-web-sync', action='store_false',
                          dest='sync_web_episodes', help='Do not sync podcast episodes with web')
    pod_file.add_argument('--no-download', action='store_false',
                          dest='download_episodes', help='Do not download new podcast episodes from web')

def _pod_filter_args(sub_parser):
    filters = sub_parser.add_parser('filter', help='Filter Module')
    filters_sub = filters.add_subparsers(description='Commands', dest='command')

    filter_list = filters_sub.add_parser('list', help='List podcast filters')
    filter_list.add_argument('-i', '--include-podcasts', nargs='+', type=int, help='Include these podcasts')
    filter_list.add_argument('-e', '--exclude-podcasts', nargs='+', type=int, help='Exclude these podcasts')

    filter_create = filters_sub.add_parser('create', help='Create new podcast title filter')
    filter_create.add_argument('podcast_id', type=int, help='Podcast Id to add filter to')
    filter_create.add_argument('regex_string', help='Regex string to add as filter')

    filter_delete = filters_sub.add_parser('delete', help='Delete podcast title filter')
    filter_delete.add_argument('filter_input', type=int, nargs='+', help='ID(s) of filter(s) to delete')

def _episode_args(sub_parser):
    episodes = sub_parser.add_parser('episode', help='Episode Module')
    episodes_sub = episodes.add_subparsers(description='Commands', dest='command')

    ep_list = episodes_sub.add_parser('list', help='List podcast episode')
    ep_list.add_argument('--all', action='store_false', dest='only_files',
                         help='Show all files, just not those with files')
    ep_list.add_argument('-i', '--include-podcasts', nargs='+', type=int, help='Include these podcasts')
    ep_list.add_argument('-e', '--exclude-podcasts', nargs='+', type=int, help='Exclude these podcasts')

    ep_show = episodes_sub.add_parser('show', help='Show episode data')
    ep_show.add_argument('episode_input', nargs="+", type=int, help='Episode ID(s)')

    ep_delete = episodes_sub.add_parser('delete', help='Delete episode')
    ep_delete.add_argument('episode_input', nargs="+", type=int, help='Episode ID(s)')
    ep_delete.add_argument('--keep-files', action='store_false', dest="delete_files",
                           help='Do not delete media files')

    ep_delete_file = episodes_sub.add_parser('delete-file', help='Delete file for episode(s)')
    ep_delete_file.add_argument('episode_input', nargs="+", type=int, help="Episode ID(s)")

    ep_download = episodes_sub.add_parser('download', help='Download Episode')
    ep_download.add_argument('episode_input', nargs="+", type=int, help='Episode ID(s)')

    ep_update = episodes_sub.add_parser('update', help='Update episode')
    ep_update.add_argument('episode_id', type=int, help='Episode ID')
    delete_group = ep_update.add_mutually_exclusive_group()
    delete_group.add_argument('--prevent-delete', action='store_true',
                              help='Prevent deletion of file from'
                                   ' file-sync (will not be counted toward max allowed)')
    delete_group.add_argument('--allow-delete', action='store_false',
                              dest='prevent_delete',
                              help='Allow deletion of file from file-sync')

    ep_update_file = episodes_sub.add_parser('update-file-path', help='Update episode file path')
    ep_update_file.add_argument('episode_id', type=int, help='Episode ID')
    ep_update_file.add_argument('file_path', help='New file path for episode')

    ep_sync = episodes_sub.add_parser('sync', help='Sync episode data')
    ep_sync.add_argument('-i', '--include-podcasts', nargs='+', type=int, help='Include these podcasts')
    ep_sync.add_argument('-e', '--exclude-podcasts', nargs='+', type=int, help='Exclude these podcasts')
    ep_sync.add_argument('--sync-num', type=int, dest="max_episode_sync",
                         help='Sync back N number of episodes. Use 0 for unlimited')

    episodes_sub.add_parser('cleanup', help='Cleanup podcast episodes')

def parse_args(args):
    parser = HathorArgparse(description='Hathor Client')
    parser.add_argument('-s', '--settings',
                        default=settings.DEFAULT_SETTINGS_FILE, help='Settings file')
    parser.add_argument('-d', '--database',
                        dest='database_file', help='Podcast database file')
    parser.add_argument('-l', '--log-file',
                        dest='logging_file', help='Log file to use')
    parser.add_argument('-ll', '--log-file-level',
                        choices=LOG_SETTINGS_DICT.keys(),
                        dest='logging_file_level',
                        help='Log file level to use')
    parser.add_argument('-df', '--datetime-format',
                        dest='datetime_output_format',
                        help='Datetime output format (python standard)')
    parser.add_argument('-sc', '--soundcloud',
                        dest='soundcloud_client_id', help='Soundcloud client id')
    parser.add_argument('-g', '--google',
                        dest='google_api_key', help='Google api key')
    parser.add_argument('-p', '--podcast-dir',
                        dest='podcast_directory', help='Podcast directory')
    parser.add_argument('-c', '--column-limit', type=int,
                        default=settings.COLUMN_LIMIT_DEFAULT,
                        help='Maximum length of column, if set to -1 acts as unlimited')
    parser.add_argument('-cl', '--console-log', action='store_true',
                        dest='console_logging', help='Enable logging to console')
    parser.add_argument('-cll', '--console-log-level',
                        choices=LOG_SETTINGS_DICT.keys(),
                        dest='console_logging_level',
                        help='Console logging level')
    parser.add_argument('-k', '--keys',
                        help='Show only specified keys in lists of dictionaries'
                             ', should be comma seperated list')
    parser.add_argument('-sk', '--sort-key',
                        help='Sort on key if output is list table')

    sub = parser.add_subparsers(description='Modules', dest='module')

    _podcast_args(sub)
    _pod_filter_args(sub)
    _episode_args(sub)

    return vars(parser.parse_args(args))

def __get_logging_level(value, default):
    if value is None:
        return default
    return LOG_SETTINGS_DICT[value]

def load_settings(settings_file):
    if settings_file is None:
        return {}
    parser = SafeConfigParser()
    parser.read(settings_file)
    mapping = {
        'database_file' : ['general', 'database_file'],
        'datetime_output_format' : ['general', 'datetime_output_format'],
        'logging_file' : ['general', 'logging_file'],
        'logging_file_level' : ['general', 'logging_file_level'],
        'console_logging' : ['general', 'console_logging'],
        'console_logging_level' : ['general', 'console_logging_level'],
        'soundcloud_client_id' : ['podcasts', 'soundcloud_client_id'],
        'google_api_key' : ['podcasts', 'google_api_key'],
        'podcast_directory' : ['podcasts', 'podcast_directory'],
    }
    return_data = dict()
    for key_name, args in mapping.items():
        try:
            value = parser.get(*args)
        except (NoSectionError, NoOptionError):
            value = None
        return_data[key_name] = value
    return return_data

def generate_args(command_line_args):
    # Use settings options first, then override
    # from CLI if given
    cli_args = parse_args(command_line_args)
    args = load_settings(cli_args.pop('settings', None))
    for k, v in cli_args.items():
        if v is None:
            cli_args.pop(k)
    args.update(cli_args)

    # Set logging levels to python class
    args['logging_file_level'] = __get_logging_level(args['logging_file_level'],
                                                     logging.DEBUG)
    args['console_logging_level'] = __get_logging_level(args['console_logging_level'],
                                                        logging.INFO)
    return args

def main():
    args = generate_args(sys.argv[1:])
    command_line = CLI(**args)
    command_line.run_command()

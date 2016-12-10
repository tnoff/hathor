from ConfigParser import NoSectionError, NoOptionError, SafeConfigParser
import argparse
import json
import logging

from hathor import client as hathor_client
from hathor import settings
from scripts import utils

def _podcast_args(sub_parser):
    podcast = sub_parser.add_parser('podcast', help='Podcast Module')

    podcast_sub = podcast.add_subparsers(description='Commands', dest='command')

    pod_add = podcast_sub.add_parser('create', help='Create new podcast')
    pod_add.add_argument('name', help='Podcast name')
    pod_add.add_argument('archive_type', choices=hathor_client.ARCHIVE_TYPES, help='Archive Type')
    pod_add.add_argument('broadcast_id', help='Broadcast ID')
    pod_add.add_argument('--max-allowed', type=int,
                         help='Maximum number of podcast episodes that will be downloaded to local machine')
    pod_add.add_argument('--remove-commercials', action='store_true', help='Remove commercials upon downloading episodes')
    pod_add.add_argument('--file-location', help='Path where podcast episode files will be stored')
    pod_add.add_argument('--artist-name', help='Name of artist for media metadata tags')
    pod_add.add_argument('--no-auto-download', action='store_false',
                         help='Do not automatically download new episodes with file-sync')

    podcast_sub.add_parser('list', help='List podcasts')

    pod_show = podcast_sub.add_parser('show', help='Show podcast info')
    pod_show.add_argument('podcast_id', nargs='+', type=int, help='Podcast ID(s)')

    pod_delete = podcast_sub.add_parser('delete', help='Delete podcast')
    pod_delete.add_argument('podcast_id', nargs='+', type=int, help='Podcast ID(s)')
    pod_delete.add_argument('--keep-files', action='store_false', help='Do not delete media files for podcast')

    pod_up = podcast_sub.add_parser('update', help='Update podcast info')
    pod_up.add_argument('podcast_id', type=int, help='Podcast ID')
    pod_up.add_argument('--podcast-name', help='Podcast name')
    pod_up.add_argument('--broadcast_id', help='Broadcast ID')
    pod_up.add_argument('--max-allowed', type=int,
                        help='Maximum number of podcast episodes that will be downloaded'\
                             'to local machine, use 0 to set to None/Unlimited')
    pod_up.add_argument('--remove-commercials', action='store_true',
                        help='Remove commercials upon downloading files')
    pod_up.add_argument('--keep-commercials', action='store_true',
                        help='Keep commercials upon downloading files')
    pod_up.add_argument('--artist-name', help='Name ofartist for media metadata tags')
    pod_up.add_argument('--auto-download', action='store_true',
                        help='Automatically download new episodes with file sync')
    pod_up.add_argument('--no-auto-download', action='store_true',
                        help='Do not automatically download new episodes with file sync')


    pod_update_file = podcast_sub.add_parser('update-file', help='Update file location')
    pod_update_file.add_argument('podcast_id', type=int, help='Podcast ID')
    pod_update_file.add_argument('file_location', help='New file location')
    pod_update_file.add_argument('--no-move', action='store_false', help='Do not move episode files')

    pod_file = podcast_sub.add_parser('file-sync', help='Sync podcast episode files')
    pod_file.add_argument('-i', '--include-podcasts', nargs='+', type=int, help='Include these podcasts')
    pod_file.add_argument('-e', '--exclude-podcasts', nargs='+', type=int, help='Exclude these podcasts')
    pod_file.add_argument('--no-web-sync', action='store_false', help='Do not sync podcast episodes with web')
    pod_file.add_argument('--no-download', action='store_false', help='Do not download new podcast episodes from web')

    episodes = podcast_sub.add_parser('episode', help='Podcast Episode actions')
    episode_sub = episodes.add_subparsers(description='Episode commands', dest='subcommand')
    _episode_args(episode_sub)

    pod_filters = podcast_sub.add_parser('filters', help='Podcast Title Filters')
    pod_filters_sub = pod_filters.add_subparsers(description='Podcast title filter commands',
                                                 dest='subcommand')
    _pod_filter_args(pod_filters_sub)

def _pod_filter_args(sub_parser):
    filter_list = sub_parser.add_parser('list', help='List podcast filters')
    filter_list.add_argument('-i', '--include-podcasts', nargs='+', type=int, help='Include these podcasts')
    filter_list.add_argument('-e', '--exclude-podcasts', nargs='+', type=int, help='Exclude these podcasts')

    filter_create = sub_parser.add_parser('create', help='Create new podcast title filter')
    filter_create.add_argument('podcast_id', type=int, help='Podcast Id to add filter to')
    filter_create.add_argument('regex_string', help='Regex string to add as filter')

    filter_delete = sub_parser.add_parser('delete', help='Delete podcast title filter')
    filter_delete.add_argument('filter_id', type=int, nargs='+', help='ID of filter to delete')

def _episode_args(sub_parser):
    ep_list = sub_parser.add_parser('list', help='List podcast episode')
    ep_list.add_argument('--all', action='store_true', help='Show all files, just not those with files')
    ep_list.add_argument('-i', '--include-podcasts', nargs='+', type=int, help='Include these podcasts')
    ep_list.add_argument('-e', '--exclude-podcasts', nargs='+', type=int, help='Exclude these podcasts')

    ep_show = sub_parser.add_parser('show', help='Show episode data')
    ep_show.add_argument('episode_id', nargs="+", type=int, help='Episode ID(s)')

    ep_delete = sub_parser.add_parser('delete', help='Delete episode')
    ep_delete.add_argument('episode_id', nargs="+", type=int, help='Episode ID(s)')
    ep_delete.add_argument('--keep-files', action='store_false', help='Do not delete media files')

    ep_delete_file = sub_parser.add_parser('delete-file', help='Delete file for episode(s)')
    ep_delete_file.add_argument('episode_id', nargs="+", type=int, help="Episode ID(s)")

    ep_download = sub_parser.add_parser('download', help='Download Episode')
    ep_download.add_argument('episode_id', nargs="+", type=int, help='Episode ID(s)')

    ep_update = sub_parser.add_parser('update', help='Update episode')
    ep_update.add_argument('episode_id', type=int, help='Episode ID')
    ep_update.add_argument('--prevent-delete', action='store_true',
                           help='Prevent deletion of file from file-sync (will not be counted toward max allowed)')
    ep_update.add_argument('--allow-delete', action='store_false',
                           help='Allow deletion of file from file-sync')

    ep_sync = sub_parser.add_parser('sync', help='Sync episode data')
    ep_sync.add_argument('-i', '--include-podcasts', nargs='+', type=int, help='Include these podcasts')
    ep_sync.add_argument('-e', '--exclude-podcasts', nargs='+', type=int, help='Exclude these podcasts')
    ep_sync.add_argument('--sync-num', type=int, help='Sync back N number of episodes. Use 0 for unlimited')

    sub_parser.add_parser('cleanup', help='Cleanup podcast episodes')

def parse_args():
    parser = argparse.ArgumentParser(description='Hathor Client')
    parser.add_argument('-db', '--database-file', help='Podcast database file')
    parser.add_argument('-lf', '--logging-file', help='Log file to use')
    parser.add_argument('-lfl', '--logging-file-level', choices=['debug', 'info', 'warn', 'error'],
                        help='Log file level to use')
    parser.add_argument('-d', '--datetime-output-format',
                        help='Datetime output format (python standard)')
    parser.add_argument('-sc', '--soundcloud-client-id', help='Soundcloud client id')
    parser.add_argument('-gc', '--google-api-key', help='Google api key')
    parser.add_argument('-p', '--podcast-directory', help='Podcast directory')
    parser.add_argument('-c', '--column-limit', type=int,
                        default=settings.COLUMN_LIMIT_DEFAULT,
                        help='Maximum length of column, if set to -1 acts as unlimited')
    parser.add_argument('-dcl', '--disable-console-logging', action='store_false',
                        dest='console_logging', help='Disable logging to console')
    parser.add_argument('-cll', '--console-logging-level',
                        help='Console logging level')
    sub = parser.add_subparsers(description='Modules', dest='module')

    _podcast_args(sub)

    args = parser.parse_args()

    # check for podcast episode input
    if hasattr(args, 'subcommand'):
        args.module = args.command
        args.command = args.subcommand
    return vars(args)

def load_settings(settings_file):
    parser = SafeConfigParser()
    parser.read(settings_file)
    mapping = {
        'database_file' : ['general', 'database_file'],
        'datetime_output_format' : ['general', 'datetime_output_format'],
        'logging_file' : ['general', 'logging_file'],
        'logging_file_level' : ['general', 'logging_file_level'],
        'podcast_directory' : ['podcasts', 'podcast_directory'],
        'soundcloud_client_id' : ['podcasts', 'soundcloud_client_id'],
        'google_api_key' : ['podcasts', 'google_api_key'],
        'console_logging' : ['general', 'console_logging'],
        'console_logging_level' : ['general', 'console_logging_level'],
    }
    return_data = dict()
    for key_name, args in mapping.items():
        try:
            value = parser.get(*args)
        except (NoSectionError, NoOptionError):
            value = None
        return_data[key_name] = value
    return return_data

def get_logging_file_level(args):
    level = logging.DEBUG
    if args['logging_file_level'] is not None:
        if args['logging_file_level'] == 'debug':
            level = logging.DEBUG
        elif args['logging_file_level'] == 'info':
            level = logging.INFO
        elif args['logging_file_level'] == 'warn':
            level = logging.WARNING
        elif args['logging_file_level'] == 'error':
            level = logging.ERROR
    return level

def get_console_logging_level(args):
    level = logging.INFO
    if args['console_logging_level'] is not None:
        if args['console_logging_level'] == 'debug':
            level = logging.DEBUG
        elif args['console_logging_level'] == 'info':
            level = logging.INFO
        elif args['console_logging_level'] == 'warn':
            level = logging.WARNING
        elif args['console_logging_level'] == 'error':
            level = logging.ERROR
    return level

def podcast_create(client, args):
    client.podcast_create(args['archive_type'], args['broadcast_id'], args['name'],
                          max_allowed=args['max_allowed'], remove_commercials=args['remove_commercials'],
                          file_location=args['file_location'], artist_name=args['artist_name'],
                          automatic_download=args['no_auto_download'])

def podcast_list(client, args):
    table = utils.HandsomeTable(["ID", "Name", "Archive Type", "Broadcast ID"], args['column_limit'])
    for pod in client.podcast_list():
        table.add_row([pod['id'], pod['name'], pod['archive_type'], pod['broadcast_id']])
    print table

def podcast_show(client, args):
    result = client.podcast_show(args['podcast_id'])
    print json.dumps(result, indent=4)

def podcast_delete(client, args):
    client.podcast_delete(args['podcast_id'], delete_files=args['keep_files'])

def podcast_update(client, args):
    remove_comm = None
    if args['remove_commercials'] and args['keep_commercials']:
        print 'Unable to use remove commercials and skip commercials at the same damn time'
        return
    if args['remove_commercials'] is True:
        remove_comm = True
    elif args['keep_commercials'] is True:
        remove_comm = False

    auto_download = None
    if args['no_auto_download'] and args['auto_download']:
        print "Unable to use no auto download and auto download at the same damn time"
        return
    if args['no_auto_download']:
        auto_download = False
    elif args['auto_download']:
        auto_download = True

    client.podcast_update(args['podcast_id'], podcast_name=args['podcast_name'],
                          broadcast_id=args['broadcast_id'], max_allowed=args['max_allowed'],
                          remove_commercials=remove_comm, artist_name=args['artist_name'],
                          automatic_download=auto_download)

def podcast_update_file(client, args):
    client.podcast_update_file_location(args['podcast_id'], args['file_location'],
                                        move_files=args['no_move'])

def podcast_file_sync(client, args):
    client.podcast_file_sync(include_podcasts=args['include_podcasts'],
                             exclude_podcasts=args['exclude_podcasts'],
                             sync_web_episodes=args['no_web_sync'],
                             download_episodes=args['no_download'])

def podcast_filter_list(client, args):
    table = utils.HandsomeTable(["Filter ID", "Podcast", "Regex String"], args['column_limit'])

    podcast_cache = dict()
    for filters in client.podcast_title_filter_list(include_podcasts=args['include_podcasts'],
                                                    exclude_podcasts=args['exclude_podcasts']):
        try:
            pod_name = podcast_cache[filters['podcast_id']]
        except KeyError:
            pod_name = client.podcast_show(filters['podcast_id'])[0]['name']
            podcast_cache[filters['podcast_id']] = pod_name
        table.add_row([filters['id'], pod_name, filters['regex_string']])
    print table

def podcast_filter_create(client, args):
    client.podcast_title_filter_create(args['podcast_id'],
                                       args['regex_string'])

def podcast_filter_delete(client, args):
    client.podcast_title_filter_delete(args['filter_id'])

def episode_list(client, args):
    episodes = client.episode_list(only_files=not args['all'], sort_date=True,
                                   include_podcasts=args['include_podcasts'],
                                   exclude_podcasts=args['exclude_podcasts'])
    table = utils.HandsomeTable(["ID", "Podcast Name", "Date", "Title"], args['column_limit'])

    podcast_cache = dict()

    for ep in episodes:
        try:
            pod_name = podcast_cache[ep['podcast_id']]
        except KeyError:
            pod_name = client.podcast_show(ep['podcast_id'])[0]['name']
            podcast_cache[ep['podcast_id']] = pod_name
        table.add_row([ep['id'], pod_name, ep['date'], ep['title']])
    print table

def episode_sync(client, args):
    client.episode_sync(include_podcasts=args['include_podcasts'],
                        exclude_podcasts=args['exclude_podcasts'],
                        max_episode_sync=args['sync_num'])

def episode_show(client, args):
    result = client.episode_show(args['episode_id'])
    print json.dumps(result, indent=4)

def episode_delete(client, args):
    client.episode_delete(args['episode_id'], delete_files=args['keep_files'])

def episode_delete_file(client, args):
    client.episode_delete_file(args['episode_id'])

def episode_update(client, args):
    prevent_delete = None
    # keep this order to ensure prevent overrides allow
    if args['prevent_delete']:
        prevent_delete = True
    elif not args['allow_delete']:
        prevent_delete = False
    client.episode_update(args['episode_id'], prevent_delete=prevent_delete)

def episode_cleanup(client, _):
    client.database_cleanup()

def episode_download(client, args):
    client.episode_download(args['episode_id'])

FUNCTION_MAPPING = {
    'podcast' : {
        'create' : podcast_create,
        'list' : podcast_list,
        'show' : podcast_show,
        'delete' : podcast_delete,
        'update' : podcast_update,
        'update-file' : podcast_update_file,
        'file-sync' : podcast_file_sync,
    },
    'filters' : {
        'list' : podcast_filter_list,
        'create' : podcast_filter_create,
        'delete' : podcast_filter_delete,
    },
    'episode' : {
        'list' : episode_list,
        'show' : episode_show,
        'download' : episode_download,
        'delete' : episode_delete,
        'delete-file' : episode_delete_file,
        'update' : episode_update,
        'cleanup' : episode_cleanup,
        'sync' : episode_sync,
    }
}

def main():
    client_keys = ['podcast_directory', 'datetime_output_format', 'logging_file',
                   'logging_file_level', 'database_file', 'soundcloud_client_id',
                   'google_api_key', 'console_logging', 'console_logging_level']
    args = load_settings(settings.SETTINGS_FILE)
    cli_args = parse_args()
    for k, v in cli_args.items():
        if k in client_keys and v is None:
            continue
        args[k] = v
    args['logging_file_level'] = get_logging_file_level(args)
    args['console_logging_level'] = get_console_logging_level(args)

    client_args = dict()
    for key in client_keys:
        client_args[key] = args.pop(key)
    client = hathor_client.HathorClient(**client_args)
    method = FUNCTION_MAPPING[cli_args['module']][cli_args['command']]
    method(client, args)

from copy import deepcopy
from pathlib import Path

import click
from pyaml_env import parse_config

from hathor.client import HathorClient
from hathor.exc import CliException
from hathor.output import render_output
from hathor.podcast.archive import VALID_ARCHIVE_KEYS
from hathor.utils import mask_config_secrets, mask_url_secrets, setup_logger

HOME_DIR = Path.home()
SETTINGS_DEFAULT = HOME_DIR / '.hathor_config.yml'

def _generate_cluders(include_podcasts, exclude_podcasts):
    '''
    Generate cluders from input
    '''
    if include_podcasts:
        try:
            include_podcasts = [int(i) for i in include_podcasts.split(',')]
        except ValueError as e:
            raise CliException('Invalid include podcasts arg, must be comma separated list of ints') from e
    if exclude_podcasts:
        try:
            exclude_podcasts = [int(i) for i in exclude_podcasts.split(',')]
        except ValueError as e:
            raise CliException('Invalid exclude podcasts arg, must be comma separated list of ints') from e
    return include_podcasts, exclude_podcasts

def hide_feed_secrets(data):
    '''
    Mask the url secrets in the broadcast_id of podcast dicts, however deeply they are nested
    The client returns real values; only what is printed is masked

    data: A podcast dict, or any list or dict containing them
    '''
    if isinstance(data, list):
        return [hide_feed_secrets(item) for item in data]
    if isinstance(data, dict):
        return {key: mask_url_secrets(value) if key == 'broadcast_id' else hide_feed_secrets(value)
                for key, value in data.items()}
    return data

show_secrets_option = click.option('--show-secrets', is_flag=True, default=False,
                                   help='Print feed urls in full, including query string keys')

@click.group()
@click.option('-c', '--config',
              type=click.Path(dir_okay=False),
              default=str(SETTINGS_DEFAULT),
              show_default=True,
              help='Config options')
@click.option('--json', 'as_json', is_flag=True, default=False,
              help='Print raw json instead of a formatted table')
@click.pass_context
def cli(ctx, config, as_json):
    '''
    Cli Base options

    config: Config file
    '''
    try:
        options = parse_config(config)
    except FileNotFoundError as e:
        raise CliException(f'Invalid path for config file {config}') from e
    if not options:
        raise CliException(f'Invalid config with no data {config}')
    ctx.obj = {
        'config': {
            'hathor': options.get('hathor', {}),
            'logging': options.get('logging', {}),
        },
        'json': as_json,
    }
    config_copy = deepcopy(ctx.obj['config']['hathor'])
    if ctx.obj['config']['logging']:
        logger = setup_logger('hathor', **ctx.obj['config']['logging'])
        config_copy['logger'] = logger
    ctx.obj['client'] = HathorClient(**config_copy)

@cli.command(name='dump-config')
@click.option('--show-secrets', is_flag=True, default=False,
              help='Print credentials in full: api keys, secrets, tokens, passwords and urls with keys')
@click.pass_context
def dump_config(ctx, show_secrets):
    '''
    Dump config data to screen. Credentials are hidden unless --show-secrets is given
    '''
    config = ctx.obj['config']
    render_output(config if show_secrets else mask_config_secrets(config), ctx.obj['json'])

@cli.group()
@click.pass_context
def podcast(_ctx):
    '''
    Podcast functions
    '''

@podcast.command(name='create')
@click.argument('archive_type', type=click.Choice(VALID_ARCHIVE_KEYS))
@click.argument('broadcast_id')
@click.argument('podcast_name')
@click.option('--max-allowed', type=int, help='Max allowed episodes')
@click.option('--file-location', type=click.Path(dir_okay=True), help='Directory for podcast')
@click.option('--artist-name', help='Artist name to set in tags')
@click.option('--no-automatic-download', is_flag=True, default=False)
@click.pass_context
def podcast_create(ctx, archive_type, broadcast_id, podcast_name,
                   max_allowed, file_location, artist_name, no_automatic_download):
    '''
    Create a podcast
    '''
    result = ctx.obj['client'].podcast_create(
        archive_type, broadcast_id, podcast_name,
        max_allowed=max_allowed,
        file_location=file_location,
        artist_name=artist_name,
        automatic_download=not no_automatic_download)
    render_output(hide_feed_secrets(result), ctx.obj['json'])

@podcast.command(name='list')
@show_secrets_option
@click.pass_context
def podcast_list(ctx, show_secrets):
    '''
    List all podcasts. Feed url query strings, which can hold a private feed's key, are hidden
    unless --show-secrets is given
    '''
    result = ctx.obj['client'].podcast_list()
    render_output(result if show_secrets else hide_feed_secrets(result), ctx.obj['json'])

@podcast.command(name='show')
@click.argument('podcast_id', type=int, nargs=-1)
@show_secrets_option
@click.pass_context
def podcast_show(ctx, podcast_id, show_secrets):
    '''
    Show podcast info. Feed url query strings, which can hold a private feed's key, are hidden
    unless --show-secrets is given
    '''
    result = ctx.obj['client'].podcast_show(list(podcast_id))
    render_output(result if show_secrets else hide_feed_secrets(result), ctx.obj['json'])

@podcast.command(name='update')
@click.argument('podcast_id', type=int)
@click.option('--podcast-name', help='New podcast name')
@click.option('--broadcast-id', help='New broadcast id')
@click.option('--archive-type', type=click.Choice(VALID_ARCHIVE_KEYS), help='New archive type')
@click.option('--max-allowed', type=int, help='New max allowed')
@click.option('--artist-name', help='New artist name')
@click.option('--automatic-download', type=bool, help='New automatic download setting')
@click.option('--image', help='Artwork for the podcast feed: an http(s) url or a file. Downloaded once and stored, so the url can expire')
@click.option('--remove-image', is_flag=True, help='Remove the podcast artwork')
@click.pass_context
def podcast_update(ctx, podcast_id, podcast_name, broadcast_id,
                   archive_type, max_allowed, artist_name, automatic_download, image, remove_image):
    '''
    Update podcast info
    '''
    result = ctx.obj['client'].podcast_update(
        podcast_id,
        podcast_name=podcast_name,
        broadcast_id=broadcast_id,
        archive_type=archive_type,
        max_allowed=max_allowed,
        artist_name=artist_name,
        automatic_download=automatic_download,
        image=image,
        remove_image=remove_image,
    )
    render_output(hide_feed_secrets(result), ctx.obj['json'])

@podcast.command(name='update-file-location')
@click.argument('podcast_id', type=int)
@click.argument('file_location', type=click.Path(dir_okay=True))
@click.option('--no-move-files', is_flag=True, default=False)
@click.pass_context
def podcast_update_file_location(ctx, podcast_id, file_location, no_move_files):
    '''
    Update file location
    '''
    result = ctx.obj['client'].podcast_update_file_location(
        podcast_id,
        file_location,
        move_files=not no_move_files,
    )
    render_output(hide_feed_secrets(result), ctx.obj['json'])

@podcast.command(name='delete')
@click.argument('podcast_id', type=int, nargs=-1)
@click.option('--no-delete-files', is_flag=True, default=False)
@click.pass_context
def podcast_delete(ctx, podcast_id, no_delete_files):
    '''
    Podcast delete
    '''
    result = ctx.obj['client'].podcast_delete(
        list(podcast_id),
        delete_files=not no_delete_files,
    )
    render_output(hide_feed_secrets(result), ctx.obj['json'])

@cli.group(name='filter')
@click.pass_context
def filter_group(_ctx):
    '''
    Filter functions
    '''

@filter_group.command(name='create')
@click.argument('podcast_id', type=int)
@click.argument('regex_string')
@click.pass_context
def filter_create(ctx, podcast_id, regex_string):
    '''
    Filter create
    '''
    result = ctx.obj['client'].filter_create(
        podcast_id, regex_string
    )
    render_output(result, ctx.obj['json'])

@filter_group.command(name='list')
@click.option('--include-podcasts', help='Comma separated list of podcasts')
@click.option('--exclude-podcasts', help='Comma separated list of podcasts')
@click.pass_context
def filter_list(ctx, include_podcasts, exclude_podcasts):
    '''
    Filter list
    '''
    include_podcasts, exclude_podcasts = _generate_cluders(include_podcasts, exclude_podcasts)
    result = ctx.obj['client'].filter_list(include_podcasts=include_podcasts, exclude_podcasts=exclude_podcasts)
    render_output(result, ctx.obj['json'])

@filter_group.command(name='delete')
@click.argument('filter_id', type=int, nargs=-1)
@click.pass_context
def filter_delete(ctx, filter_id):
    '''
    Filter delete
    '''
    result = ctx.obj['client'].filter_delete(list(filter_id))
    render_output(result, ctx.obj['json'])

@cli.group(name='episode')
@click.pass_context
def episode(_ctx):
    '''
    Episode functions
    '''

@episode.command(name='sync')
@click.option('--include-podcasts', help='Comma separated list of podcasts')
@click.option('--exclude-podcasts', help='Comma separated list of podcasts')
@click.option('--max-episode-sync', type=int, help='Max episodes to sync')
@click.pass_context
def episode_sync(ctx, include_podcasts, exclude_podcasts, max_episode_sync):
    '''
    Episode sync
    '''
    include_podcasts, exclude_podcasts = _generate_cluders(include_podcasts, exclude_podcasts)
    result = ctx.obj['client'].episode_sync(
        include_podcasts=include_podcasts,
        exclude_podcasts=exclude_podcasts,
        max_episode_sync=max_episode_sync,
    )
    render_output(result, ctx.obj['json'])

@episode.command(name='list')
@click.option('--only-files', is_flag=True, default=False, help='Only show episodes with files')
@click.option('--include-podcasts', help='Comma separated list of podcasts')
@click.option('--exclude-podcasts', help='Comma separated list of podcasts')
@click.pass_context
def episode_list(ctx, only_files, include_podcasts, exclude_podcasts):
    '''
    Episode list
    '''
    include_podcasts, exclude_podcasts = _generate_cluders(include_podcasts, exclude_podcasts)
    result = ctx.obj['client'].episode_list(
        only_files=only_files,
        include_podcasts=include_podcasts,
        exclude_podcasts=exclude_podcasts,
    )
    render_output(result, ctx.obj['json'])

@episode.command(name='show')
@click.argument('episode_id', type=int, nargs=-1)
@click.pass_context
def episode_show(ctx, episode_id):
    '''
    Episode Show
    '''
    episode_ids = list(episode_id)
    result = ctx.obj['client'].episode_show(
        episode_ids,
    )
    render_output(result, ctx.obj['json'])

@episode.command(name='update')
@click.argument('episode_id', type=int)
@click.argument('prevent_delete', type=bool)
@click.pass_context
def episode_update(ctx, episode_id, prevent_delete):
    '''
    Episode update
    '''
    result = ctx.obj['client'].episode_update(
        episode_id, prevent_delete
    )
    render_output(result, ctx.obj['json'])

@episode.command(name='download')
@click.argument('episode_id', type=int, nargs=-1)
@click.pass_context
def episode_download(ctx, episode_id):
    '''
    Episode download
    '''
    episode_ids = list(episode_id)
    result = ctx.obj['client'].episode_download(episode_ids)
    render_output(result, ctx.obj['json'])

@episode.command(name='delete')
@click.argument('episode_id', type=int, nargs=-1)
@click.option('--no-delete-files', is_flag=True, default=False, help='Do not delete files')
@click.pass_context
def episode_delete(ctx, episode_id, no_delete_files):
    '''
    Episode delete
    '''
    episode_ids = list(episode_id)
    result = ctx.obj['client'].episode_delete(
        episode_ids,
        delete_files=not no_delete_files,
    )
    render_output(result, ctx.obj['json'])

@episode.command(name='update-file-path')
@click.argument('episode_id', type=int)
@click.argument('file_path', type=click.Path(dir_okay=False))
@click.pass_context
def episode_update_file_location(ctx, episode_id, file_path):
    '''
    Episode update file path
    '''
    result = ctx.obj['client'].episode_update_file_path(
        episode_id, file_path
    )
    render_output(result, ctx.obj['json'])

@episode.command(name='delete-file')
@click.argument('episode_id', type=int, nargs=-1)
@click.pass_context
def episode_delete_file(ctx, episode_id):
    '''
    Episode delete file
    '''
    episode_ids = list(episode_id)
    result = ctx.obj['client'].episode_delete_file(
        episode_ids,
    )
    render_output(result, ctx.obj['json'])

@episode.command(name='cleanup')
@click.pass_context
def episode_cleanup(ctx):
    '''
    Episode cleanup
    '''
    result = ctx.obj['client'].episode_cleanup()
    render_output(result, ctx.obj['json'])

@podcast.command(name='sync')
@click.option('--include-podcasts', help='Comma separated list of podcasts')
@click.option('--exclude-podcasts', help='Comma separated list of podcasts')
@click.option('--no-sync-web-episodes', is_flag=True, default=False, help='Dont sync web episodes')
@click.option('--no-download-episodes', is_flag=True, default=False, help='Dont download new episodes')
@click.pass_context
def podcast_sync(ctx, include_podcasts, exclude_podcasts, no_sync_web_episodes, no_download_episodes):
    '''
    Podcast Sync
    '''
    include_podcasts, exclude_podcasts = _generate_cluders(include_podcasts, exclude_podcasts)
    result = ctx.obj['client'].podcast_sync(
        include_podcasts=include_podcasts,
        exclude_podcasts=exclude_podcasts,
        sync_web_episodes=not no_sync_web_episodes,
        download_episodes=not no_download_episodes,
    )
    render_output(result, ctx.obj['json'])

@cli.command(name='index')
@click.option('--dry-run', is_flag=True, default=False, help='Print the index instead of writing it to the index file')
@click.pass_context
def index(ctx, dry_run):
    '''
    Write a json index of episode files
    '''
    result = ctx.obj['client'].episode_index(dry_run=dry_run)
    render_output(result, ctx.obj['json'])

def main():
    '''
    Hathor CLI runner
    '''
    cli(obj={}) #pylint:disable=no-value-for-parameter

if __name__ == '__main__':
    main()

from copy import deepcopy
from json import dumps
from pathlib import Path

import click
from pyaml_env import parse_config

from hathor.client import HathorClient
from hathor.exc import CliException
from hathor.podcast.archive import VALID_ARCHIVE_KEYS
from hathor.utils import setup_logger

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

@click.group()
@click.option('-c', '--config',
              type=click.Path(dir_okay=False),
              default=str(SETTINGS_DEFAULT),
              show_default=True,
              help='Config options')
@click.pass_context
def cli(ctx, config):
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
        }
    }
    config_copy = deepcopy(ctx.obj['config']['hathor'])
    if ctx.obj['config']['logging']:
        logger = setup_logger('hathor', **ctx.obj['config']['logging'])
        config_copy['logger'] = logger
    ctx.obj['client'] = HathorClient(**config_copy)

@cli.command(name='dump-config')
@click.pass_context
def dump_config(ctx):
    '''
    Dump config data to screen
    '''
    click.echo(dumps(ctx.obj['config'], indent=4))

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
    click.echo(dumps(result, indent=4))

@podcast.command(name='list')
@click.pass_context
def podcast_list(ctx):
    '''
    List all podcasts
    '''
    click.echo(dumps(ctx.obj['client'].podcast_list(), indent=4))

@podcast.command(name='show')
@click.argument('podcast_id', type=int, nargs=-1)
@click.pass_context
def podcast_show(ctx, podcast_id):
    '''
    Show podcast info
    '''
    click.echo(dumps(ctx.obj['client'].podcast_show(list(podcast_id)), indent=4))

@podcast.command(name='update')
@click.argument('podcast_id', type=int)
@click.option('--podcast-name', help='New podcast name')
@click.option('--broadcast-id', help='New broadcast id')
@click.option('--archive-type', type=click.Choice(VALID_ARCHIVE_KEYS), help='New archive type')
@click.option('--max-allowed', type=int, help='New max allowed')
@click.option('--artist-name', help='New artist name')
@click.option('--automatic-download', type=bool, help='New automatic download setting')
@click.pass_context
def podcast_update(ctx, podcast_id, podcast_name, broadcast_id,
                   archive_type, max_allowed, artist_name, automatic_download):
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
    )
    click.echo(dumps(result, indent=4))

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
    click.echo(dumps(result, indent=4))

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
    click.echo(dumps(result, indent=4))

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
    click.echo(dumps(result, indent=4))

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
    click.echo(dumps(result, indent=4))

@filter_group.command(name='delete')
@click.argument('filter_id', type=int, nargs=-1)
@click.pass_context
def filter_delete(ctx, filter_id):
    '''
    Filter delete
    '''
    result = ctx.obj['client'].filter_delete(list(filter_id))
    click.echo(dumps(result, indent=4))

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
    click.echo(dumps(result, indent=4))

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
    click.echo(dumps(result, indent=4))

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
    click.echo(dumps(result, indent=4))

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
    click.echo(dumps(result, indent=4))

@episode.command(name='download')
@click.argument('episode_id', type=int, nargs=-1)
@click.pass_context
def episode_download(ctx, episode_id):
    '''
    Episode download
    '''
    episode_ids = list(episode_id)
    result = ctx.obj['client'].episode_download(episode_ids)
    click.echo(dumps(result, indent=4))

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
    click.echo(dumps(result, indent=4))

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
    click.echo(dumps(result, indent=4))

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
    click.echo(dumps(result, indent=4))

@episode.command(name='cleanup')
@click.pass_context
def episode_cleanup(ctx):
    '''
    Episode cleanup
    '''
    result = ctx.obj['client'].episode_cleanup()
    click.echo(dumps(result, indent=4))

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
    click.echo(dumps(result, indent=4))

def main():
    '''
    Hathor CLI runner
    '''
    cli(obj={}) #pylint:disable=no-value-for-parameter

if __name__ == '__main__':
    main()

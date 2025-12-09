from copy import deepcopy
from json import dumps
import os
from pathlib import Path

import click
from pyaml_env import parse_config
from yaml import dump as yaml_dump

from hathor.client import HathorClient
from hathor.exc import CliException
from hathor.podcast.archive import VALID_ARCHIVE_KEYS
from hathor.utils import setup_logger

HOME_DIR = Path.home()


def get_config_path():
    """Get config path following XDG Base Directory spec with fallback"""
    # First check for old location for backwards compatibility
    legacy_config = HOME_DIR / '.hathor_config.yml'
    if legacy_config.exists():
        return legacy_config

    # Use XDG_CONFIG_HOME if set, otherwise default to ~/.config
    xdg_config = os.environ.get('XDG_CONFIG_HOME')
    if xdg_config:
        config_dir = Path(xdg_config) / 'hathor'
    else:
        config_dir = HOME_DIR / '.config' / 'hathor'

    return config_dir / 'config.yml'


SETTINGS_DEFAULT = get_config_path()

def _parse_podcast_filters(include_podcasts, exclude_podcasts):
    '''
    Parse include/exclude podcast filters from comma-separated input
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


def validate_config(config_dict, logger=None):
    """
    Validate and warn about configuration issues

    config_dict: Parsed configuration dictionary
    logger: Optional logger for warnings
    """
    hathor_config = config_dict.get('hathor', {})

    warnings = []

    # Check for recommended fields
    if not hathor_config.get('podcast_directory'):
        warnings.append('No podcast_directory configured - you must specify file_location when creating podcasts')

    if not hathor_config.get('database_connection_string'):
        warnings.append('No database_connection_string configured - using default location')

    # Check if podcast directory exists
    if hathor_config.get('podcast_directory'):
        podcast_dir = Path(hathor_config['podcast_directory'])
        if not podcast_dir.exists():
            warnings.append(f'Podcast directory does not exist: {podcast_dir}')

    # Warn about missing Google API key if not present
    if not hathor_config.get('google_api_key'):
        warnings.append('No google_api_key configured - YouTube downloads will not work')

    # Print warnings
    if warnings and logger:
        for warning in warnings:
            logger.warning(warning)

    return config_dict

@click.group()
@click.option('-c', '--config',
              type=click.Path(dir_okay=False),
              default=str(SETTINGS_DEFAULT),
              show_default=True,
              help='Path to configuration file')
@click.pass_context
def cli(ctx, config):
    '''
    Hathor - Podcast download and management tool
    '''
    try:
        options = parse_config(config)
    except FileNotFoundError as e:
        raise CliException(
            f'Config file not found: {config}\n'
            f'Run "hathor init" to create a default configuration file.'
        ) from e
    if not options:
        raise CliException(f'Invalid config with no data {config}')

    ctx.obj = {
        'config': {
            'hathor': options.get('hathor', {}),
            'logging': options.get('logging', {}),
        }
    }
    config_copy = deepcopy(ctx.obj['config']['hathor'])

    # Setup logger
    logger = None
    if ctx.obj['config']['logging']:
        logger = setup_logger('hathor', **ctx.obj['config']['logging'])
        config_copy['logger'] = logger

    # Validate config
    validate_config(ctx.obj['config'], logger)

    ctx.obj['client'] = HathorClient(**config_copy)

@cli.command(name='init')
@click.option('--podcast-dir', type=click.Path(),
              default=str(HOME_DIR / 'Podcasts'),
              help='Default directory for podcast downloads')
@click.option('--database', type=click.Path(),
              help='Database file location (default: ~/.local/share/hathor/hathor.db)')
@click.option('--config-path', type=click.Path(),
              help='Config file location (default: XDG config dir or ~/.hathor_config.yml)')
@click.option('--force', '-f', is_flag=True,
              help='Overwrite existing configuration file')
def init_config(podcast_dir, database, config_path, force):
    '''
    Create a default configuration file
    '''
    # Determine config location
    if config_path:
        config_file = Path(config_path)
    else:
        config_file = SETTINGS_DEFAULT

    # Check if config exists
    if config_file.exists() and not force:
        click.secho(f'✗ Config file already exists: {config_file}', fg='red')
        click.echo('Use --force to overwrite, or specify a different location with --config-path')
        raise click.Abort()

    # Determine database location
    if not database:
        # Use XDG_DATA_HOME or default to ~/.local/share
        xdg_data = os.environ.get('XDG_DATA_HOME')
        if xdg_data:
            data_dir = Path(xdg_data) / 'hathor'
        else:
            data_dir = HOME_DIR / '.local' / 'share' / 'hathor'
        data_dir.mkdir(parents=True, exist_ok=True)
        database = str(data_dir / 'hathor.db')

    # Create podcast directory if it doesn't exist
    podcast_path = Path(podcast_dir)
    podcast_path.mkdir(parents=True, exist_ok=True)

    # Build config
    config = {
        'hathor': {
            'podcast_directory': str(podcast_path),
            'database_connection_string': f'sqlite:///{database}',
            'datetime_output_format': '%Y-%m-%d',
            # 'google_api_key': 'YOUR_API_KEY_HERE',  # Commented out
        },
        'logging': {
            'console_logging': True,
            'log_level': 20,  # INFO level
        }
    }

    # Ensure config directory exists
    config_file.parent.mkdir(parents=True, exist_ok=True)

    # Write config
    with open(config_file, 'w') as f:
        # Add header comment
        f.write('# Hathor configuration file\n')
        f.write('# See https://github.com/tnoff/hathor for documentation\n\n')
        yaml_dump(config, f, default_flow_style=False, sort_keys=False)

    click.secho(f'✓ Created configuration file: {config_file}', fg='green')
    click.echo(f'  Podcast directory: {podcast_dir}')
    click.echo(f'  Database: {database}')
    click.echo('')
    click.echo('To enable YouTube downloads, add your Google API key to the config:')
    click.echo(f'  google_api_key: YOUR_KEY_HERE')


@cli.command(name='dump-config')
@click.pass_context
def dump_config(ctx):
    '''
    Display current configuration
    '''
    click.echo(dumps(ctx.obj['config'], indent=4))

@cli.group()
@click.pass_context
def podcast(_ctx):
    '''
    Manage podcasts - create, list, update, and delete podcast subscriptions
    '''

@podcast.command(name='create')
@click.argument('archive_type', type=click.Choice(VALID_ARCHIVE_KEYS))
@click.argument('broadcast_id')
@click.argument('podcast_name')
@click.option('--max-allowed', '-m', type=int,
              help='Maximum number of episodes to keep (0 for unlimited)')
@click.option('--file-location', '-d', type=click.Path(dir_okay=True),
              help='Directory for podcast files')
@click.option('--artist-name', '-a', help='Artist name to set in metadata tags')
@click.option('--auto-download/--no-auto-download', default=True,
              help='Automatically download new episodes during sync (default: auto-download)')
@click.pass_context
def podcast_create(ctx, archive_type, broadcast_id, podcast_name,
                   max_allowed, file_location, artist_name, auto_download):
    '''
    Create a new podcast subscription

    ARCHIVE_TYPE: Source type (rss or youtube)
    BROADCAST_ID: RSS feed URL or YouTube channel ID
    PODCAST_NAME: Name for the podcast
    '''
    try:
        result = ctx.obj['client'].podcast_create(
            archive_type, broadcast_id, podcast_name,
            max_allowed=max_allowed,
            file_location=file_location,
            artist_name=artist_name,
            automatic_download=auto_download)
        click.secho('✓ Podcast created successfully', fg='green')
        click.echo(dumps(result, indent=4))
    except Exception as e:
        click.secho(f'✗ Error creating podcast: {str(e)}', fg='red', err=True)
        raise click.Abort()

@podcast.command(name='list')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed information')
@click.pass_context
def podcast_list(ctx, verbose):
    '''
    List all podcast subscriptions
    '''
    podcasts = ctx.obj['client'].podcast_list()
    if not verbose:
        # Simple list view
        for p in podcasts:
            click.echo(f"[{p['id']}] {p['name']} ({p['archive_type']})")
    else:
        click.echo(dumps(podcasts, indent=4))

@podcast.command(name='show')
@click.argument('podcast_id', type=int, nargs=-1)
@click.pass_context
def podcast_show(ctx, podcast_id):
    '''
    Show detailed information for one or more podcasts

    PODCAST_ID: One or more podcast IDs to display
    '''
    click.echo(dumps(ctx.obj['client'].podcast_show(list(podcast_id)), indent=4))

@podcast.command(name='update')
@click.argument('podcast_id', type=int)
@click.option('--name', '-n', 'podcast_name', help='New podcast name')
@click.option('--broadcast-id', '-b', help='New broadcast ID (RSS URL or YouTube channel)')
@click.option('--archive-type', '-t', type=click.Choice(VALID_ARCHIVE_KEYS),
              help='New archive type')
@click.option('--max-allowed', '-m', type=int,
              help='Maximum episodes to keep (0 for unlimited)')
@click.option('--artist-name', '-a', help='Artist name for metadata tags')
@click.option('--auto-download/--no-auto-download', 'automatic_download', default=None,
              help='Enable/disable automatic episode downloads')
@click.pass_context
def podcast_update(ctx, podcast_id, podcast_name, broadcast_id,
                   archive_type, max_allowed, artist_name, automatic_download):
    '''
    Update podcast settings

    PODCAST_ID: ID of the podcast to update
    '''
    try:
        result = ctx.obj['client'].podcast_update(
            podcast_id,
            podcast_name=podcast_name,
            broadcast_id=broadcast_id,
            archive_type=archive_type,
            max_allowed=max_allowed,
            artist_name=artist_name,
            automatic_download=automatic_download,
        )
        click.secho('✓ Podcast updated successfully', fg='green')
        click.echo(dumps(result, indent=4))
    except Exception as e:
        click.secho(f'✗ Error updating podcast: {str(e)}', fg='red', err=True)
        raise click.Abort()

@podcast.command(name='move')
@click.argument('podcast_id', type=int)
@click.argument('new_location', type=click.Path(dir_okay=True))
@click.option('--copy-files', is_flag=True, help='Copy files instead of moving them')
@click.pass_context
def podcast_move(ctx, podcast_id, new_location, copy_files):
    '''
    Move podcast files to a new location

    PODCAST_ID: ID of the podcast
    NEW_LOCATION: New directory path for podcast files
    '''
    try:
        result = ctx.obj['client'].podcast_update_file_location(
            podcast_id,
            new_location,
            move_files=not copy_files,
        )
        action = 'copied' if copy_files else 'moved'
        click.secho(f'✓ Podcast files {action} successfully', fg='green')
        click.echo(dumps(result, indent=4))
    except Exception as e:
        click.secho(f'✗ Error moving podcast: {str(e)}', fg='red', err=True)
        raise click.Abort()

@podcast.command(name='delete')
@click.argument('podcast_id', type=int, nargs=-1)
@click.option('--keep-files', is_flag=True, help='Keep downloaded files (only remove from database)')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.pass_context
def podcast_delete(ctx, podcast_id, keep_files, yes):
    '''
    Delete one or more podcasts

    PODCAST_ID: One or more podcast IDs to delete
    '''
    # Get podcast names for confirmation
    if not yes:
        try:
            podcasts = ctx.obj['client'].podcast_show(list(podcast_id))
            names = [p['name'] for p in podcasts]
            files_msg = 'and keep files' if keep_files else 'and DELETE ALL FILES'
            if not click.confirm(
                f'Delete {len(names)} podcast(s) {files_msg}?\n' +
                '\n'.join(f'  - {name}' for name in names)
            ):
                click.echo('Cancelled.')
                return
        except Exception:
            # If we can't get names, still ask for confirmation
            if not click.confirm(f'Delete {len(podcast_id)} podcast(s)?'):
                click.echo('Cancelled.')
                return

    try:
        result = ctx.obj['client'].podcast_delete(
            list(podcast_id),
            delete_files=not keep_files,
        )
        click.secho(f'✓ Deleted {len(podcast_id)} podcast(s)', fg='green')
        click.echo(dumps(result, indent=4))
    except Exception as e:
        click.secho(f'✗ Error deleting podcasts: {str(e)}', fg='red', err=True)
        raise click.Abort()

@podcast.command(name='sync')
@click.option('--include', '-i', 'include_podcasts', multiple=True, type=int,
              help='Include specific podcast IDs (can be used multiple times)')
@click.option('--exclude', '-e', 'exclude_podcasts', multiple=True, type=int,
              help='Exclude specific podcast IDs (can be used multiple times)')
@click.option('--fetch/--no-fetch', 'sync_web_episodes', default=True,
              help='Fetch new episodes from web (default: fetch)')
@click.option('--download/--no-download', 'download_episodes', default=True,
              help='Download episode files (default: download)')
@click.pass_context
def podcast_sync(ctx, include_podcasts, exclude_podcasts, sync_web_episodes, download_episodes):
    '''
    Sync podcasts - fetch new episodes and download files

    This will check for new episodes and download them according to each podcast's settings.
    '''
    try:
        # Convert tuples to lists
        inc_list = list(include_podcasts) if include_podcasts else None
        exc_list = list(exclude_podcasts) if exclude_podcasts else None

        result = ctx.obj['client'].podcast_sync(
            include_podcasts=inc_list,
            exclude_podcasts=exc_list,
            sync_web_episodes=sync_web_episodes,
            download_episodes=download_episodes,
        )
        click.secho('✓ Podcast sync completed', fg='green')
        if result:
            click.echo(dumps(result, indent=4))
    except Exception as e:
        click.secho(f'✗ Error syncing podcasts: {str(e)}', fg='red', err=True)
        raise click.Abort()

@cli.group(name='filter')
@click.pass_context
def filter_group(_ctx):
    '''
    Manage episode filters - regex patterns to include/exclude episodes by title
    '''

@filter_group.command(name='create')
@click.argument('podcast_id', type=int)
@click.argument('regex_pattern')
@click.pass_context
def filter_create(ctx, podcast_id, regex_pattern):
    '''
    Create a new episode filter for a podcast

    PODCAST_ID: Podcast to add filter to
    REGEX_PATTERN: Regular expression to match episode titles
    '''
    try:
        result = ctx.obj['client'].filter_create(podcast_id, regex_pattern)
        click.secho('✓ Filter created successfully', fg='green')
        click.echo(dumps(result, indent=4))
    except Exception as e:
        click.secho(f'✗ Error creating filter: {str(e)}', fg='red', err=True)
        raise click.Abort()

@filter_group.command(name='list')
@click.option('--include', '-i', 'include_podcasts', multiple=True, type=int,
              help='Include podcasts by ID')
@click.option('--exclude', '-e', 'exclude_podcasts', multiple=True, type=int,
              help='Exclude podcasts by ID')
@click.pass_context
def filter_list(ctx, include_podcasts, exclude_podcasts):
    '''
    List all episode filters
    '''
    inc_list = list(include_podcasts) if include_podcasts else None
    exc_list = list(exclude_podcasts) if exclude_podcasts else None
    result = ctx.obj['client'].filter_list(include_podcasts=inc_list, exclude_podcasts=exc_list)
    click.echo(dumps(result, indent=4))

@filter_group.command(name='delete')
@click.argument('filter_id', type=int, nargs=-1)
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.pass_context
def filter_delete(ctx, filter_id, yes):
    '''
    Delete one or more episode filters

    FILTER_ID: One or more filter IDs to delete
    '''
    if not yes and not click.confirm(f'Delete {len(filter_id)} filter(s)?'):
        click.echo('Cancelled.')
        return

    try:
        result = ctx.obj['client'].filter_delete(list(filter_id))
        click.secho(f'✓ Deleted {len(filter_id)} filter(s)', fg='green')
        click.echo(dumps(result, indent=4))
    except Exception as e:
        click.secho(f'✗ Error deleting filters: {str(e)}', fg='red', err=True)
        raise click.Abort()

@cli.group(name='episode')
@click.pass_context
def episode(_ctx):
    '''
    Manage individual podcast episodes
    '''

@episode.command(name='sync')
@click.option('--include', '-i', 'include_podcasts', multiple=True, type=int,
              help='Include podcasts by ID')
@click.option('--exclude', '-e', 'exclude_podcasts', multiple=True, type=int,
              help='Exclude podcasts by ID')
@click.option('--max', '-m', 'max_episode_sync', type=int,
              help='Maximum episodes to sync per podcast (0 for unlimited)')
@click.pass_context
def episode_sync(ctx, include_podcasts, exclude_podcasts, max_episode_sync):
    '''
    Sync episode metadata from web without downloading files

    This updates the database with new episodes but doesn't download files.
    Use 'podcast sync' to both fetch metadata and download files.
    '''
    try:
        inc_list = list(include_podcasts) if include_podcasts else None
        exc_list = list(exclude_podcasts) if exclude_podcasts else None
        result = ctx.obj['client'].episode_sync(
            include_podcasts=inc_list,
            exclude_podcasts=exc_list,
            max_episode_sync=max_episode_sync,
        )
        click.secho(f'✓ Synced {len(result)} new episode(s)', fg='green')
        click.echo(dumps(result, indent=4))
    except Exception as e:
        click.secho(f'✗ Error syncing episodes: {str(e)}', fg='red', err=True)
        raise click.Abort()

@episode.command(name='list')
@click.option('--files-only', '-f', is_flag=True, help='Only show episodes with downloaded files')
@click.option('--include', '-i', 'include_podcasts', multiple=True, type=int,
              help='Include podcasts by ID')
@click.option('--exclude', '-e', 'exclude_podcasts', multiple=True, type=int,
              help='Exclude podcasts by ID')
@click.pass_context
def episode_list(ctx, files_only, include_podcasts, exclude_podcasts):
    '''
    List podcast episodes
    '''
    inc_list = list(include_podcasts) if include_podcasts else None
    exc_list = list(exclude_podcasts) if exclude_podcasts else None
    result = ctx.obj['client'].episode_list(
        only_files=files_only,
        include_podcasts=inc_list,
        exclude_podcasts=exc_list,
    )
    click.echo(dumps(result, indent=4))

@episode.command(name='show')
@click.argument('episode_id', type=int, nargs=-1)
@click.pass_context
def episode_show(ctx, episode_id):
    '''
    Show detailed information for one or more episodes

    EPISODE_ID: One or more episode IDs to display
    '''
    result = ctx.obj['client'].episode_show(list(episode_id))
    click.echo(dumps(result, indent=4))

@episode.command(name='protect')
@click.argument('episode_id', type=int, nargs=-1)
@click.option('--unprotect', is_flag=True, help='Remove protection (allow deletion)')
@click.pass_context
def episode_protect(ctx, episode_id, unprotect):
    '''
    Protect episodes from deletion during cleanup

    EPISODE_ID: One or more episode IDs to protect/unprotect
    '''
    try:
        for eid in episode_id:
            result = ctx.obj['client'].episode_update(eid, prevent_delete=not unprotect)
        action = 'unprotected' if unprotect else 'protected'
        click.secho(f'✓ {len(episode_id)} episode(s) {action}', fg='green')
    except Exception as e:
        click.secho(f'✗ Error updating episodes: {str(e)}', fg='red', err=True)
        raise click.Abort()

@episode.command(name='download')
@click.argument('episode_id', type=int, nargs=-1)
@click.pass_context
def episode_download(ctx, episode_id):
    '''
    Download one or more episode files

    EPISODE_ID: One or more episode IDs to download
    '''
    try:
        result = ctx.obj['client'].episode_download(list(episode_id))
        click.secho(f'✓ Downloaded {len(result)} episode(s)', fg='green')
        click.echo(dumps(result, indent=4))
    except Exception as e:
        click.secho(f'✗ Error downloading episodes: {str(e)}', fg='red', err=True)
        raise click.Abort()

@episode.command(name='delete')
@click.argument('episode_id', type=int, nargs=-1)
@click.option('--keep-files', is_flag=True, help='Keep files (only remove from database)')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.pass_context
def episode_delete(ctx, episode_id, keep_files, yes):
    '''
    Delete one or more episodes

    EPISODE_ID: One or more episode IDs to delete
    '''
    if not yes:
        files_msg = 'and keep files' if keep_files else 'and DELETE FILES'
        if not click.confirm(f'Delete {len(episode_id)} episode(s) {files_msg}?'):
            click.echo('Cancelled.')
            return

    try:
        result = ctx.obj['client'].episode_delete(
            list(episode_id),
            delete_files=not keep_files,
        )
        click.secho(f'✓ Deleted {len(episode_id)} episode(s)', fg='green')
        click.echo(dumps(result, indent=4))
    except Exception as e:
        click.secho(f'✗ Error deleting episodes: {str(e)}', fg='red', err=True)
        raise click.Abort()

@episode.command(name='move')
@click.argument('episode_id', type=int)
@click.argument('new_path', type=click.Path(dir_okay=False))
@click.pass_context
def episode_move(ctx, episode_id, new_path):
    '''
    Update the file path for an episode

    EPISODE_ID: Episode ID
    NEW_PATH: New file path
    '''
    try:
        result = ctx.obj['client'].episode_update_file_path(episode_id, new_path)
        click.secho('✓ Episode path updated', fg='green')
        click.echo(dumps(result, indent=4))
    except Exception as e:
        click.secho(f'✗ Error updating episode path: {str(e)}', fg='red', err=True)
        raise click.Abort()

@episode.command(name='remove-file')
@click.argument('episode_id', type=int, nargs=-1)
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.pass_context
def episode_remove_file(ctx, episode_id, yes):
    '''
    Delete episode files but keep metadata in database

    EPISODE_ID: One or more episode IDs
    '''
    if not yes and not click.confirm(f'Delete files for {len(episode_id)} episode(s)?'):
        click.echo('Cancelled.')
        return

    try:
        result = ctx.obj['client'].episode_delete_file(list(episode_id))
        click.secho(f'✓ Removed files for {len(episode_id)} episode(s)', fg='green')
        click.echo(dumps(result, indent=4))
    except Exception as e:
        click.secho(f'✗ Error removing episode files: {str(e)}', fg='red', err=True)
        raise click.Abort()

@episode.command(name='cleanup')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.pass_context
def episode_cleanup(ctx, yes):
    '''
    Clean up orphaned episode files (files without database entries)
    '''
    if not yes and not click.confirm('Clean up orphaned episode files?'):
        click.echo('Cancelled.')
        return

    try:
        result = ctx.obj['client'].episode_cleanup()
        click.secho('✓ Cleanup completed', fg='green')
        click.echo(dumps(result, indent=4))
    except Exception as e:
        click.secho(f'✗ Error during cleanup: {str(e)}', fg='red', err=True)
        raise click.Abort()


def main():
    '''
    Hathor CLI runner
    '''
    cli(obj={}) #pylint:disable=no-value-for-parameter

if __name__ == '__main__':
    main()

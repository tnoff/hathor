from copy import deepcopy
from json import dumps
from pathlib import Path

import click
from pyaml_env import parse_config

from hathor.client import HathorClient
from hathor.exc import CliException
from hathor.utils import setup_logger

HOME_DIR = Path.home()
SETTINGS_DEFAULT = HOME_DIR / '.hathor_config.yml'

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
    ctx.obj['client'] = HathorClient(**ctx.obj['config']['hathor'])

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
@click.pass_context
def podcast_create(ctx):
    '''
    Create a podcast
    '''
    print(ctx.obj)

@podcast.command(name='list')
@click.pass_context
def podcast_list(ctx):
    '''
    List all podcasts
    '''
    click.echo(dumps(ctx.obj['client'].podcast_list(), indent=4))

def main():
    '''
    Hathor CLI runner
    '''
    cli(obj={}) #pylint:disable=no-value-for-parameter

if __name__ == '__main__':
    main()

from json import dumps

import click

from hathor.audio import metadata

@click.group()
@click.pass_context
def cli(_ctx):
    '''
    Audio tool cli
    '''

@cli.command(name='tags-show')
@click.argument('input_file', type=click.Path(dir_okay=False))
@click.pass_context
def tags_show(_ctx, input_file):
    '''
    Tags show
    '''
    result = metadata.tags_show(input_file)
    click.echo(dumps(result, indent=4))

@cli.command(name='tags-update')
@click.argument('input_file', type=click.Path(dir_okay=False))
@click.argument('key_values')
@click.pass_context
def tags_update(_ctx, input_file, key_values):
    '''
    Tags update
    '''
    data = {}
    for item in key_values.split(','):
        parts = item.split('=')
        data[parts[0]] = parts[1]
    result = metadata.tags_update(input_file, data)
    click.echo(dumps(result, indent=4))


@cli.command('picture-update')
@click.argument('audio_file', type=click.Path(dir_okay=False))
@click.argument('picture_file', type=click.Path(dir_okay=False))
@click.option('--encoding', type=int, default=3, help='Encoding of image')
@click.option('--picture_type', type=int, default=3, help='Type of picture')
@click.option('--description', default='cover', help='Description of image')
@click.pass_context
def picture_update(_ctx, audio_file, picture_file, encoding, picture_type, description):
    '''
    Picture Update
    '''
    result = metadata.picture_update(
        audio_file,
        picture_file,
        encoding=encoding,
        picture_type=picture_type,
        description=description,
    )
    click.echo(dumps(result, indent=4))

@cli.command('picture-extract')
@click.argument('audio_file', type=click.Path(dir_okay=False))
@click.argument('output_file', type=click.Path(dir_okay=False))
@click.pass_context
def picture_extract(_ctx, audio_file, output_file):
    '''
    Picture extract
    '''
    result = metadata.picture_extract(
        audio_file,
        output_file
    )
    click.echo(dumps(result, indent=4))

def main():
    '''
    Main cli runner
    '''
    cli(obj={}) #pylint:disable=no-value-for-parameter

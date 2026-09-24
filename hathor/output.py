from json import dumps

import click
from dappertable import Column, Columns, DapperTable

MAX_COLUMN_WIDTH = 60

def _stringify(value):
    if value is None:
        return ''
    return str(value)

def _column_width(key, rows):
    width = len(_stringify(key))
    for row in rows:
        width = max(width, len(_stringify(row.get(key))))
    return min(width, MAX_COLUMN_WIDTH)

def _render_table(rows, keys):
    columns = Columns([Column(key, _column_width(key, rows)) for key in keys])
    table = DapperTable(columns=columns)
    for row in rows:
        table.add_row([_stringify(row.get(key)) for key in keys])
    click.echo(table.render())

def render_output(data, as_json):
    '''
    Echo cli command output, either as raw json or a formatted table

    data      :   Result from a hathor client/metadata call
    as_json   :   Print raw json instead of a table, for scripting
    '''
    if as_json:
        click.echo(dumps(data, indent=4))
        return

    if isinstance(data, list) and data and isinstance(data[0], dict):
        _render_table(data, list(data[0].keys()))
        return

    if isinstance(data, dict):
        _render_table([{'key': key, 'value': value} for key, value in data.items()], ['key', 'value'])
        return

    if isinstance(data, list):
        if not data:
            click.echo('No results')
            return
        for item in data:
            click.echo(_stringify(item))
        return

    click.echo(_stringify(data))

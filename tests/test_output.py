from json import loads

from hathor.output import render_output

def test_render_output_json_list_of_dicts(capsys):
    data = [{'id': 1, 'name': 'foo'}, {'id': 2, 'name': 'bar'}]
    render_output(data, True)
    assert loads(capsys.readouterr().out) == data

def test_render_output_table_list_of_dicts(capsys):
    data = [{'id': 1, 'name': 'foo'}, {'id': 2, 'name': 'bar'}]
    render_output(data, False)
    output = capsys.readouterr().out
    assert 'id' in output
    assert 'name' in output
    assert 'foo' in output
    assert 'bar' in output

def test_render_output_table_list_of_dicts_none_value(capsys):
    data = [{'id': 1, 'name': None}]
    render_output(data, False)
    output = capsys.readouterr().out
    assert 'id' in output

def test_render_output_table_dict(capsys):
    data = {'id': 1, 'name': 'foo'}
    render_output(data, False)
    output = capsys.readouterr().out
    assert 'key' in output
    assert 'value' in output
    assert 'foo' in output

def test_render_output_table_empty_list(capsys):
    render_output([], False)
    assert capsys.readouterr().out == 'No results\n'

def test_render_output_json_empty_list(capsys):
    render_output([], True)
    assert loads(capsys.readouterr().out) == []

def test_render_output_table_list_of_scalars(capsys):
    render_output([1, 2, 3], False)
    assert capsys.readouterr().out == '1\n2\n3\n'

def test_render_output_table_bool(capsys):
    render_output(True, False)
    assert capsys.readouterr().out == 'True\n'

def test_render_output_json_bool(capsys):
    render_output(True, True)
    assert capsys.readouterr().out == 'true\n'

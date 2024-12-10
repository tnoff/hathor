from tempfile import TemporaryDirectory

from pathlib import Path

from hathor import utils

def test_process_url():
    result = utils.process_url('https://foo.example')
    assert result == 'https://foo.example'
    result = utils.process_url('https://foo.example?id=bar')
    assert result == 'https://foo.example'
    assert utils.process_url('https://foo.example/bar?id=3') == 'https://foo.example/bar'

def test_clean_stringy():
    assert utils.clean_string(None) is None
    assert utils.clean_string('') == ''
    assert utils.clean_string('foo') == 'foo'
    assert utils.clean_string('          foo     ') == 'foo'

def test_normalize_name():
    assert utils.normalize_name('a_______________b') == 'a_b'
    assert utils.normalize_name('a&-b') == 'a_b'
    assert utils.normalize_name('a         b') == 'a_b'

def test_rm_tree():
    with TemporaryDirectory() as tmp_dir:
        dir_path = Path(tmp_dir)
        new_dir = dir_path / 'foo'
        new_dir.mkdir(exist_ok=True)
        file_path = new_dir / 'test.txt'
        file_path.write_text('example')
        sub_dir = new_dir / 'bar'
        sub_dir.mkdir(exist_ok=True)
        utils.rm_tree(new_dir)
        assert new_dir.exists() is False

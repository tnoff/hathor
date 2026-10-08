import stat
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

def test_sanitize_filename():
    assert utils.sanitize_filename('a/b\\c: d?*') == 'abc d'
    assert utils.sanitize_filename('  ...Why? Because   it is... ') == 'Why Because it is'
    assert utils.sanitize_filename('Café ünïcode') == 'Café ünïcode'
    assert utils.sanitize_filename('///') == 'episode'
    assert len(utils.sanitize_filename('a' * 500)) == utils.FILENAME_MAX_LENGTH

def test_display_filename():
    assert utils.display_filename('Pod', '2024-12-07', 'Big/Title', '.MP4') == 'Pod - 2024-12-07 - BigTitle.mp4'
    assert utils.display_filename('Pod', None, None, '.mp3') == 'Pod.mp3'

def test_guess_content_type():
    assert utils.guess_content_type('a.mp3') == 'audio/mpeg'
    assert utils.guess_content_type('a.mp4') == 'video/mp4'
    assert utils.guess_content_type('a.zzz') == 'application/octet-stream'

def test_write_file_atomic(tmp_path):
    target = tmp_path / 'index.json'
    utils.write_file_atomic(target, 'one')
    utils.write_file_atomic(target, 'two')
    assert target.read_text(encoding='utf-8') == 'two'
    assert [p.name for p in tmp_path.iterdir()] == ['index.json']

def test_write_file_atomic_is_world_readable(tmp_path):
    # A temp file is created 0600 and os.replace keeps it, which locks out another
    # user reading the file, such as a web server sharing the volume.
    target = tmp_path / 'index.json'
    utils.write_file_atomic(target, 'one')
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    # Replacing an existing file gets the same mode, whatever the old file had
    target.chmod(0o600)
    utils.write_file_atomic(target, 'two')
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert target.read_text(encoding='utf-8') == 'two'

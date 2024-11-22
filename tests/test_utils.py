from hathor import utils

def test_clean_stringy():
    assert utils.clean_string(None) == None
    assert utils.clean_string('') == ''
    assert utils.clean_string('foo') == 'foo'
    assert utils.clean_string('          foo     ') == 'foo'

def test_normalize_name():
    assert utils.normalize_name('a_______________b') == 'a_b'
    assert utils.normalize_name('a&-b') == 'a_b'

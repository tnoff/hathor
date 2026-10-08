import logging
import os

import pytest

from hathor import client as client_module
from hathor.client import HathorClient, load_plugins
from hathor.exc import HathorException

PLUGIN = '''
def episode_list(self, result, *args, **kwargs):
    return ['patched by plugin']
'''

def write(path, text=PLUGIN):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path

def names(functions):
    return [name for name, _ in functions]

def test_default_loading_is_unchanged():
    # No plugins_directory: the package's own hathor/plugins/ is used, which does not exist in
    # a clean checkout, so nothing loads and nothing is logged about a directory.
    assert not load_plugins()
    assert not load_plugins(None)
    assert not load_plugins('')
    assert not HathorClient().plugins

def test_external_directory_loads_plugin_and_hook_runs(tmp_path):
    write(tmp_path / 'my_plugin.py')
    client = HathorClient(plugins_directory=tmp_path)
    assert names(client.plugins) == ['episode_list']
    # The hook really fires after the client method of the same name
    assert client.episode_list(only_files=False) == ['patched by plugin']

def test_plugins_directory_accepts_a_string(tmp_path):
    write(tmp_path / 'my_plugin.py')
    assert names(HathorClient(plugins_directory=str(tmp_path)).plugins) == ['episode_list']

def test_empty_string_means_unset():
    assert not HathorClient(plugins_directory='').plugins

def test_explicit_directory_replaces_the_default(tmp_path, mocker):
    # An explicit directory must not ADD to the package's own, or a plugin that sits in both
    # (a local setup that also sets the option) would run its hook twice.
    default_dir = tmp_path / 'package'
    write(default_dir / 'plugins' / 'default_plugin.py')
    external = tmp_path / 'external'
    write(external / 'external_plugin.py', 'def episode_show(self, result, *a, **k):\n    return result\n')
    mocker.patch.object(client_module, 'FILE_PATH', str(default_dir / 'client.py'))
    mocker.patch.object(client_module, 'import_module')  # the default path would import by name
    assert names(load_plugins(external)) == ['episode_show']

def test_missing_directory_warns_and_loads_nothing(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger='Hathor'):
        client = HathorClient(plugins_directory=tmp_path / 'nope')
    assert not client.plugins
    assert 'is not a directory' in caplog.text

def test_directory_with_no_plugins_warns(tmp_path, caplog):
    (tmp_path / 'notes.txt').write_text('not python', encoding='utf-8')
    write(tmp_path / '__init__.py', '')
    with caplog.at_level(logging.WARNING, logger='Hathor'):
        client = HathorClient(plugins_directory=tmp_path)
    assert not client.plugins
    assert 'has no plugin functions' in caplog.text

def test_loaded_plugins_are_logged(tmp_path, caplog):
    write(tmp_path / 'my_plugin.py')
    with caplog.at_level(logging.INFO, logger='Hathor'):
        HathorClient(plugins_directory=tmp_path)
    assert 'Loaded plugin my_plugin.py: episode_list' in caplog.text

def test_nested_directories_and_deterministic_order(tmp_path):
    write(tmp_path / 'b_plugin.py', 'def episode_show(self, result, *a, **k):\n    return result\n')
    write(tmp_path / 'a_plugin.py', 'def episode_list(self, result, *a, **k):\n    return result\n')
    write(tmp_path / 'sub' / 'c_plugin.py', 'def podcast_list(self, result, *a, **k):\n    return result\n')
    assert names(load_plugins(tmp_path)) == ['episode_list', 'episode_show', 'podcast_list']

def test_init_py_is_ignored(tmp_path):
    write(tmp_path / '__init__.py', 'def episode_list(self, result, *a, **k):\n    return result\n')
    assert not load_plugins(tmp_path)

def test_same_module_names_in_different_directories_do_not_clash(tmp_path):
    write(tmp_path / 'one' / 'plugin.py', 'def episode_list(self, result, *a, **k):\n    return result\n')
    write(tmp_path / 'two' / 'plugin.py', 'def episode_show(self, result, *a, **k):\n    return result\n')
    assert sorted(names(load_plugins(tmp_path))) == ['episode_list', 'episode_show']

def test_kubernetes_configmap_layout_loads_each_plugin_once(tmp_path):
    # A mounted ConfigMap holds every file three ways: the timestamped directory with the real
    # file, a ..data symlink to that directory, and the visible name symlinked through ..data.
    # A plain **/*.py glob matches all three and the hook would run three times.
    real = tmp_path / '..2026_10_08_21_00_00.123456'
    write(real / 'youtube_extractor.py')
    os.symlink(real.name, tmp_path / '..data')
    os.symlink('..data/youtube_extractor.py', tmp_path / 'youtube_extractor.py')
    assert names(load_plugins(tmp_path)) == ['episode_list']

def test_broken_plugin_fails_loudly_naming_the_file(tmp_path):
    write(tmp_path / 'good.py')
    write(tmp_path / 'broken.py', 'import a_module_that_does_not_exist\n')
    with pytest.raises(HathorException, match=r'Unable to load plugin .*broken\.py: .*a_module_that_does_not_exist'):
        HathorClient(plugins_directory=tmp_path)

def test_plugin_with_a_syntax_error_fails_loudly(tmp_path):
    write(tmp_path / 'bad.py', 'def oops(:\n')
    with pytest.raises(HathorException, match=r'Unable to load plugin .*bad\.py'):
        load_plugins(tmp_path)

def test_plugin_can_use_the_client(tmp_path):
    write(tmp_path / 'uses_client.py', '''
def episode_list(self, result, *args, **kwargs):
    self.logger.info('plugin saw %d results', len(result))
    return result
''')
    client = HathorClient(plugins_directory=tmp_path)
    assert not client.episode_list(only_files=False)

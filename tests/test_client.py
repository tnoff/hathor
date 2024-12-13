from hathor.client import HathorClient

def mock_plugin(self, result, *_, **__): #pylint:disable=unused-argument
    return 2


def test_plugins():
    client = HathorClient()
    client.plugins = [('episode_list', mock_plugin)]
    result = client.episode_list(only_files=False)
    assert result == 2

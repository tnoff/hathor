from hathor.client import HathorClient

def mock_plugin(self, result, *_, **__): #pylint:disable=unused-argument
    return 2


def test_plugins():
    client = HathorClient()
    client.plugins = [('episode_list', mock_plugin)]
    result = client.episode_list(only_files=False)
    assert result == 2


def test_ytdlp_options_default_empty():
    client = HathorClient()
    assert client.ytdlp_options == {}


def test_ytdlp_options_stored():
    client = HathorClient(ytdlp_options={'sleep_requests': 4})
    assert client.ytdlp_options == {'sleep_requests': 4}


def test_twitch_credentials_default_none():
    client = HathorClient()
    assert client.twitch_client_id is None
    assert client.twitch_client_secret is None


def test_twitch_credentials_stored():
    client = HathorClient(twitch_client_id='id123', twitch_client_secret='secret123')
    assert client.twitch_client_id == 'id123'
    assert client.twitch_client_secret == 'secret123'

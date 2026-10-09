from json import dumps as json_dumps, loads

from click.testing import CliRunner
import pytest
from yaml import dump

from hathor.cli import cli
from hathor.utils import mask_config_secrets

# Shaped like the cluster's real config: the same setting names, fake values
GOOGLE = 'AIzaGOOGLEKEY123'
TWITCH_SECRET = 'TWITCHSECRET456'
TOKEN = 'URLTOKEN789abcdefghij'
DB_PASSWORD = 'DBPASSWORD321'
PROXY_PASSWORD = 'PROXYPASS654'
QUERY_KEY = 'QUERYKEY987'
ALL_SECRETS = (GOOGLE, TWITCH_SECRET, TOKEN, DB_PASSWORD, PROXY_PASSWORD, QUERY_KEY)
CONFIG_SECRETS = (GOOGLE, TWITCH_SECRET, TOKEN, DB_PASSWORD, PROXY_PASSWORD)     # the ones in CONFIG

CONFIG = {
    'hathor': {
        'podcast_directory': '/data/podcasts',
        'database_connection_string': f'postgresql://hathor:{DB_PASSWORD}@db.example.com:5432/hathor',
        'index_file': '/data/index.json',
        'feeds_directory': '/data/feeds',
        'feed_base_url': f'https://tyler-north.com/hathor/{TOKEN}',
        'plugins_directory': '/plugins',
        'google_api_key': GOOGLE,
        'twitch_client_id': 'public-client-id',
        'twitch_client_secret': TWITCH_SECRET,
        'youtube_skip_shorts': True,
        'ytdlp_options': {
            'cookiefile': '/tmp/youtube-cookies.txt',
            'proxy': f'http://user:{PROXY_PASSWORD}@proxy.example.com:8080',
            'remote_components': ['ejs:github'],
            'extractor_args': {'youtube': {'player_client': ['tv_downgraded', 'web_embedded']}},
        },
    },
    'logging': {'log_level': 10, 'console_logging': True},
}

# ------------------------------------------------------------------ the helper

def test_credentials_are_hidden_and_the_rest_is_kept():
    masked = mask_config_secrets(CONFIG)
    hathor = masked['hathor']
    assert hathor['google_api_key'] == '<hidden>'
    assert hathor['twitch_client_secret'] == '<hidden>'
    assert hathor['feed_base_url'] == 'https://tyler-north.com/<hidden>'
    assert hathor['database_connection_string'] == 'postgresql://hathor:<hidden>@db.example.com:5432/hathor'
    assert hathor['ytdlp_options']['proxy'] == 'http://<hidden>@proxy.example.com:8080'
    # everything that is not a credential comes through unchanged
    assert hathor['podcast_directory'] == '/data/podcasts'
    assert hathor['twitch_client_id'] == 'public-client-id'
    assert hathor['youtube_skip_shorts'] is True
    assert hathor['ytdlp_options']['cookiefile'] == '/tmp/youtube-cookies.txt'
    assert hathor['ytdlp_options']['remote_components'] == ['ejs:github']
    assert hathor['ytdlp_options']['extractor_args'] == {'youtube': {'player_client': ['tv_downgraded', 'web_embedded']}}
    assert masked['logging'] == {'log_level': 10, 'console_logging': True}

def test_no_secret_survives_anywhere_in_the_output():
    assert not any(secret in str(mask_config_secrets(CONFIG)) for secret in ALL_SECRETS)

def test_the_input_is_not_changed():
    before = repr(CONFIG)
    mask_config_secrets(CONFIG)
    assert repr(CONFIG) == before                   # the client is built from the real values

@pytest.mark.parametrize('name', ['google_api_key', 'API_KEY', 'twitch_client_secret', 'url_token', 'db_password',
                                  'passwd', 'Secret', 'access_key_id'])
def test_credential_names(name):
    assert mask_config_secrets({name: 'value'}) == {name: '<hidden>'}

@pytest.mark.parametrize('name', ['podcast_directory', 'twitch_client_id', 'log_level', 'cookiefile', 'index_file'])
def test_ordinary_names_are_left_alone(name):
    assert mask_config_secrets({name: 'value'}) == {name: 'value'}

def test_unset_credentials_still_read_as_unset():
    # a hidden placeholder would make an unset key look configured
    assert mask_config_secrets({'google_api_key': None, 'twitch_client_secret': '', 'token': False}) == \
        {'google_api_key': None, 'twitch_client_secret': '', 'token': False}

def test_a_credential_name_hides_a_list_and_a_nested_value():
    masked = mask_config_secrets({'api_keys': ['a', 'b'], 'secrets': {'one': 'x', 'two': 'y'}})
    assert masked == {'api_keys': ['<hidden>', '<hidden>'], 'secrets': {'one': '<hidden>', 'two': '<hidden>'}}

def test_urls_lose_query_string_and_userinfo_wherever_they_are():
    masked = mask_config_secrets({'feed': f'https://example.com/rss?auth={QUERY_KEY}', 'other': ['http://u:p@h.example/x']})
    assert masked == {'feed': 'https://example.com/rss?<hidden>', 'other': ['http://<hidden>@h.example/x']}

@pytest.mark.parametrize('url, expected', [
    (f'https://tyler-north.com/hathor/{TOKEN}', 'https://tyler-north.com/<hidden>'),
    (f'https://tyler-north.com/hathor/{TOKEN}/', 'https://tyler-north.com/<hidden>'),
    (f'http://127.0.0.1:18080/hathor/{TOKEN}', 'http://127.0.0.1:18080/<hidden>'),
    ('not a url at all', '<hidden>'),
])
def test_feed_base_url_keeps_only_the_host(url, expected):
    assert mask_config_secrets({'feed_base_url': url}) == {'feed_base_url': expected}

@pytest.mark.parametrize('value, expected', [
    (f'postgresql://hathor:{DB_PASSWORD}@db.example.com:5432/hathor', 'postgresql://hathor:<hidden>@db.example.com:5432/hathor'),
    (f'mysql+pymysql://root:{DB_PASSWORD}@h/db', 'mysql+pymysql://root:<hidden>@h/db'),
    ('sqlite:////data/hathor.db', 'sqlite:////data/hathor.db'),                    # nothing to hide
    ('postgresql://hathor@db.example.com/hathor', 'postgresql://hathor@db.example.com/hathor'),   # no password
])
def test_connection_string_passwords(value, expected):
    assert mask_config_secrets({'database_connection_string': value}) == {'database_connection_string': expected}

# ------------------------------------------------------------------ the command

@pytest.fixture(name='no_real_client', autouse=True)
def no_real_client_fixture(mocker):
    # The config is fake, and its postgres connection string needs a driver that is not installed
    return mocker.patch('hathor.cli.HathorClient')

def run(tmp_path, *args):
    path = tmp_path / 'config.yml'
    path.write_text(dump(CONFIG), encoding='utf-8')
    result = CliRunner().invoke(cli, ['-c', str(path), *args])
    assert result.exit_code == 0, result.output
    return result.output

def test_dump_config_hides_credentials_by_default(tmp_path):
    table = run(tmp_path, 'dump-config')
    as_json = run(tmp_path, '--json', 'dump-config')
    for output in (table, as_json):
        assert not any(secret in output for secret in ALL_SECRETS)
        assert '<hidde' in output                        # the table view truncates long cells
    assert '/data/podcasts' in as_json                   # the rest is still shown

def test_dump_config_json_is_valid_and_masked(tmp_path):
    data = loads(run(tmp_path, '--json', 'dump-config'))
    assert data['hathor']['google_api_key'] == '<hidden>'
    assert data['hathor']['feed_base_url'] == 'https://tyler-north.com/<hidden>'

def test_show_secrets_prints_everything(tmp_path):
    output = run(tmp_path, '--json', 'dump-config', '--show-secrets')
    assert all(secret in output for secret in CONFIG_SECRETS)
    assert loads(output) == loads(json_dumps(CONFIG))

def test_masking_the_dump_does_not_change_what_the_client_gets(tmp_path, no_real_client):
    run(tmp_path, 'dump-config')
    assert no_real_client.call_args.kwargs['google_api_key'] == GOOGLE
    assert no_real_client.call_args.kwargs['feed_base_url'].endswith(TOKEN)

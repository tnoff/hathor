import os

# for hathor client
DEFAULT_DATETIME_FORMAT = '%Y-%m-%d'

# for podcast urls
BROADCAST_UPDATE_URL_LIMIT = 8

# cli options
HOME_PATH = os.path.expanduser('~')
SETTINGS_FILE = os.path.join(HOME_PATH, '.hathor_settings.conf')
COLUMN_LIMIT_DEFAULT = 80

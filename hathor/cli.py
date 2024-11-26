import os

import click
from pathlib import Path

HOME_PATH = os.path.expanduser('~')
DEFAULT_SETTINGS_FILE = Path(HOME_PATH) / '.hathor_settings.conf'
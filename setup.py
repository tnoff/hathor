import setuptools
import os


THIS_DIR = os.path.dirname(__file__)
REQUIREMENTS_FILE = os.path.join(THIS_DIR, 'requirements.txt')
VERSION_FILE = os.path.join(THIS_DIR, 'VERSION')

required = []
if os.path.exists(REQUIREMENTS_FILE):
    with open(REQUIREMENTS_FILE) as f:
        required += f.read().splitlines()

try:
    with open(VERSION_FILE) as r:
        version = r.read().strip()
except FileNotFoundError:
    version = '0.0.1'

setuptools.setup(
    name='hathor',
    description='Hathor Audio File Manager',
    author='Tyler D. North',
    author_email='me@tyler-north.com',
    install_requires=required,
    entry_points={
        'console_scripts' : [
            'hathor = hathor.cli:main',
            'audio-tool = hathor.audio.cli:main'
        ]
    },
    packages=setuptools.find_packages(exclude=['tests']),
    version=version,
)

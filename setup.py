import setuptools
import os


THIS_DIR = os.path.dirname(__file__)
REQUIREMENTS_FILE = os.path.join(THIS_DIR, 'requirements.txt')

required = []
if os.path.exists(REQUIREMENTS_FILE):
    with open(REQUIREMENTS_FILE) as f:
        required += f.read().splitlines()

print(required)

setuptools.setup(
    name='hathor',
    description='Hathor Audio File Manager',
    author='Tyler D. North',
    author_email='ty_north@yahoo.com',
    install_requires=required,
    entry_points={
        'console_scripts' : [
            'hathor = hathor.cli.client:main',
            'audio-tool = hathor.cli.audio:main',
        ]
    },
    packages=setuptools.find_packages(exclude=['tests']),
    version='1.0.13',
)

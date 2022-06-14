import setuptools

setuptools.setup(
    name='hathor',
    description='Hathor Audio File Manager',
    author='Tyler D. North',
    author_email='ty_north@yahoo.com',
    install_requires=[
        'beautifulsoup4 >= 4.7.1',
        'mutagen >= 1.42.0',
        'python-dateutil >= 2.8.0',
        'requests >= 2.21.0',
        'SQLAlchemy >= 1.2.18',
        'prettytable >= 0.7.2',
        'yt-dlp >= 2021.10.10',
    ],
    entry_points={
        'console_scripts' : [
            'hathor = hathor.cli.client:main',
            'audio-tool = hathor.cli.audio:main',
        ]
    },
    packages=setuptools.find_packages(exclude=['tests']),
    version='1.0.13',
)

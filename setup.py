import setuptools

setuptools.setup(
    name='hathor',
    description='Hathor Audio File Manager',
    author='Tyler D. North',
    author_email='tylernorth18@gmail.com',
    install_requires=[
        'beautifulsoup4 >= 4.4.0',
        'httpretty >= 0.8.4',
        'matplotlib >= 1.5.1',
        'moviepy >= 0.2.2.11',
        'mutagen >= 1.34',
        'numpy >= 1.10.4',
        'Pillow >= 3.2.0',
        'requests >= 2.5.1',
        'SQLAlchemy >= 1.0.8',
        'prettytable >= 0.7.2',
        'youtube-dl >= 2015.12.23'
    ],
    entry_points={
        'console_scripts' : [
            'hathor = scripts.hathor_cli:main',
            'audio-tool = scripts.audio_cli:main',
        ]
    },
    packages=setuptools.find_packages(exclude=['tests']),
    version='0.1.1',
)
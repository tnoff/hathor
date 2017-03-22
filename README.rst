######
Hathor
######
Hathor is a python package that is designed to help users download and maintain podcast files.


============
Installation
============

-------------
Install Steps
-------------
Clone the repo from github and use pip to install::

    git clone https://github.com/tnoff/hathor.git
    pip install hathor/

-----------------
What Is Installed
-----------------
The ``hathor`` python module will be installed, as well as 2 cli scripts:

``hathor``
    Used for downloading and managing podcast media files
``audio-tool``
    A general use tool for editing audio tags and cover pictures for mp3 files.

=================
The Hathor Client
=================
The hathor client is the main component of hathor. Using the hathor cli or hathor python
package, it is possible to create new podcast records, update them, and download the latest episodes.

You can use hathor with the command line::

    hathor podcast --help

---------------------------
Initialization and Settings
---------------------------
When the hathor client is initialized, certain variables must be specified. These
are better documented in the codebase.

These variables can also be loaded from a settings file. The default location of this settings file
is the home directory, under ``~/.hathor_settings.conf``. It can also be specified in the command line
with the ``-s`` flag.

Setting options include:

``database_file``
    Where the sqlite database file will be placed
``logging_file``
    Where log output will be sent ( rotating logs )
``podcast_directory``
    Default directory where podcast files will be stored

Here is an example of what a settings file looks like::

    [general]
    database_file = /home/user/.hathor-db.sql
    datetime_output_format = %%Y.%%m.%%d
    logging_file = /var/log/hathor/hathor.log
    logging_level = debug

    [podcasts]
    podcast_directory = /home/user/podcasts/
    soundcloud_client_id = foo-bar
    google_api_key = bar-foo

----------------
Podcast Archives
----------------
When creating a new podcast record, users will need to specify where the podcast will be downloaded
from, we call that the "archive". The following archives are supported:

- Soundcloud
- Youtube
- RSS Feeds

******************************
Soundcloud and Google API Keys
******************************
To download podcasts from soundcloud and youtube, users will need to create credentials
that can be used for their APIs.

For soundcloud users will need a `client id <https://developers.soundcloud.com/>`_.

For youtube users will need a `google api secret key <https://console.developers.google.com>`_.

These can be either placed in the settings file, or specified when initializing hathor.

------------
Broadcast ID
------------
The broadcast ID for a podcast is the unique identifier for that podcast when downloading
it from its archive.

For Soundcloud, if given the following url ``https://soundcloud.com/themonday-morning-podcast/``,
the broadcast id will be the last portion of the url, in this case ``themonday-morning-podcast``.

For Youtube, if given the following url ``https://www.youtube.com/channel/UCzQUP1qoWDoEbmsQxvdjxgQ``,
the broadcast id will be the last portion of the url, in this case ``UCzQUP1qoWDoEbmsQxvdjxgQ``.

--------------------
Downloading Podcasts
--------------------
With a archive type and broadcast id, users can then create a new podcast record using the cli::

    hathor podcast create 'podcast-name' "rss" "http://feeds.podtrac.com/xUnmFXZLuavF"

After the podcast has been created, users can then run a "file-sync", which will check the web
for new episodes, and then download the latest to the local machine::

    hathor podcast file-sync

You can then list the podcast episodes to check for new episodes::

    # Will only list episodes with files
    hathor podcast episode list
    # Will list all episodes
    hathor podcast episode list --all

Alternatively, you can sync podcast episodes without downloading them::

    hathor podcast episode sync

To download podcast episodes individually::

    hathor podcast episode download <episode-id>

-----------
Max Allowed
-----------
The option "max allowed" controls how many podcast episode files are kept
at one time. For example, if max allowed is set to 5, hathor will download the five latest
episodes, and delete any that remain. Alternatively, this can be set to "None" to download all
possible episodes.

To set max allowed on a podcast::

    hathor podcast update --max-allowed <max-allowed-int> <podcast-id>

It is possible to prevent the deletion of a file from max allowed restrictions.
If the user sets "prevent delete" to True, it will not be deleted by
a file-sync command. To update the podcast episode use::

    hathor podcast episode update --prevent-delete <episode-id>

-----------------------
Episode filters Filters
-----------------------
Episode filters can be used to control which podcast episodes will be
added to the database and downloaded via regexes.

To add podcast filters::

    hathor podcast filters create <podcast-id> <regex-filter>

=====
Tests
=====
To run the tests install the additional packages in
``tests/requirements.txt``.

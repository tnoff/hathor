######
Hathor
######
Hathor is a python package that is designed to help you download and maintain podcast files.


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
is in your home directory, under ``~/.hathor_settings.conf``. It can also be specified in the command line
with the ``s`` flag.

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
When creating a new podcast record, you'll need to specify where the podcast will be downloaded
from, we call that the "archive". The following archives are supported:

- Soundcloud
- Youtube
- RSS Feeds

******************************
Soundcloud and Google API Keys
******************************
To download podcasts from soundcloud and youtube, you will need to create credentials
that can be used for their APIs.

For soundcloud you'll need a `client id <https://developers.soundcloud.com/>`_.

For youtube you'll need a `google api secret key <https://console.developers.google.com>`_.

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
Once you have an archive type and broadcast id, you can create a new podcast record using the cli::

    hathor podcast create 'podcast-name' "rss" "http://feeds.podtrac.com/xUnmFXZLuavF"

After the podcast has been created, you can then run a "file-sync", which will check the web
for new episodes, and then download the latest to your local machine::

    hathor podcast file-sync

You can then list the podcast episodes to check for new episodes::

    hathor podcast episode list


----------------------------------------------------
Download Extras : Max Allowed and Remove Commercials
----------------------------------------------------
There are additional flags used with podcasts to help better handle the media files.

The first of which is "max allowed", which controls how many podcast episodes are downloaded
at any one time. For example, if max allowed is set to 5, hathor will download the five latest
episodes, and delete any that remain. Alternatively, this can be set to "None" to download all
possible episodes.

It is possible to prevent the deletion of a file from max allowed constrictions. To do this
update the episode you wish to save and set ``prevent_delete`` to True. This is possible using the
``hathor podcast episode update`` command.


The second is "remove commercials", which will attempt to identify and remove commercial
intervals from the downloaded media files. Note that this functionality will not work with
youtube and is not supported.


=====
Tests
=====
To run the tests you'll have to install the additional packages in
``tests/requirements.txt``.

================
Database Scripts
================
Sub-major version bumps (for example: v0.2.3 --> v0.3.0) might contain database
changes. Inside the ``database-scripts`` directory you can find scripts that can
be run against an sqlite database in order to update the local database
to the newest changes. These are not well tested.

============
Known Issues
============
--------------
Moviepy Issues
--------------
I've found a couple of issues with moviepy that haven't been `fixed upstream
<https://github.com/Zulko/moviepy/pull/225>`_.

You specifically might see an error like the following::

    result['video_fps'] = float(line[match.start():match.end()].split(' ')[1])
    AttributeError: 'NoneType' object has no attribute 'start'

If you see these problems I'd recommend installing `my fork <https://github.com/tnoff/moviepy.git>`_.

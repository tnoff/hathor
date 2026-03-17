# Development

## Setup

Clone the repo and install in editable mode with dev dependencies:

```bash
git clone https://github.com/tnoff/hathor.git
cd hathor
pip install -e .
pip install -r requirements.txt -r tests/requirements.txt
```

## Running Tests

Run the full test suite with linting and coverage via tox:

```bash
tox
```

Run tests only (no lint):

```bash
pytest --cov=hathor/ --cov-report=html --cov-fail-under=95 tests/
```

Run a single test file:

```bash
pytest tests/podcasts/test_archive.py
```

Run a single test:

```bash
pytest tests/podcasts/test_archive.py::TestClassName::test_method_name
```

## Linting

```bash
pylint hathor/
pylint --rcfile .pylintrc.test tests/
```

## Plugins

Plugins can be added for most functions in the hathor client.

Any plugins will have to be written in python and be placed in the
``hathor/plugins/`` directory.

Plugins should be named after the function you want them to run after,
for example if the plugin function is named "episode_download", it will be
run after the episode_download client function is complete.

Plugin functions should take 4 arguments: the first being the hathor client
(self), the second being the result of the original client function, and the next being the `*args` and `**kwargs` the original function was called with.

Plugins should also return a result, that will be treated as the result of the
client function.

Take the following plugin function for example:

```python
# the following is in hathor/plugins/fix_title.py
from hathor.database.tables import PodcastEpisode

def episode_download(self, results, *args, **kwargs):
    for episode in results:
        if episode['podcast_id'] in [2, 3, 5]:
            episode['title'] = 'some fancy title'
            episode_obj = self.db_session.get(PodcastEpisode, episode['id'])
            episode_obj.title = 'some fancy title'
            self.db_session.commit()
    return results
```

This will change the title of new episodes for certain podcasts. Note that for the change
to be permanent, you'll have to change the episodes in the database.

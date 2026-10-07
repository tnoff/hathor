# Development

## Setup

Clone the repo and install in editable mode with the `test` extra (there is
no `requirements.txt`; dev dependencies are declared in `pyproject.toml`'s
`[project.optional-dependencies] test`, the same source `tox.ini` installs
from):

```bash
git clone https://github.com/tnoff/hathor.git
cd hathor
pip install -e ".[test]"
```

## Running Tests

Run the full test suite with linting and coverage via tox:

```bash
tox
```

Run tests only (no lint):

```bash
pytest --cov=hathor --cov-report=html --cov-fail-under=98 tests/
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

Matches what `tox` runs under its `py314` factor (`tox.ini`) -- pylint,
tests-pylint, and a bandit security scan, all excluding `hathor/plugins/`:

```bash
pylint --ignore=plugins hathor/
pylint --rcfile .pylintrc.test tests/
bandit -r hathor/ --exclude hathor/plugins
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

## Docker build

```bash
docker build -t hathor .
```

Built and scanned on every PR that touches an image input (`Dockerfile`,
`pyproject.toml`, `VERSION`, `hathor/`) via the shared `tnoff/github-workflows`
`docker-build-check.yml`. It is not pushed from CI on PRs; see Releasing.

## Releasing

`VERSION` at the repo root is the source of truth. Merging a bump to
`main` runs `.github/workflows/release.yml`, which assembles the
changelog, tags, and creates the GitHub release (shared workflows from
`tnoff/github-workflows`). No package is published to PyPI.

On the same push, if an image input changed, it also builds the image for
`linux/arm64` (the cluster is OKE Ampere) and pushes it to OCIR as
`iad.ocir.io/tnoff/hathor:<short sha>` (plus `latest`) with the shared
`docker-push.yml`, then dispatches `bump-image-pin` with source `hathor` so
docker-apps opens a PR that rewrites its pin. The changelog fold commit
(`docs: assemble changelog ...`) is skipped so an image is never pushed twice.

The Release workflow can also be run by hand (Actions > Release > Run workflow,
on `main`) to build and push the image without any change to an image input,
for example the very first image or a rebuild. A manual run builds the image and
dispatches the bump and nothing else: it skips the changelog fold, the tag and
the GitHub release. It is ignored on any branch other than `main`. The
`workflow_dispatch` trigger must be on `main` before it can be started.

The push needs repository variables `OCI_REGISTRY`, `OCI_NAMESPACE` and
`OCI_REPO_NAME`, and secrets `OCI_USERNAME` and `OCI_TOKEN`, alongside the
`CI_APP_CLIENT_ID` / `CI_APP_PRIVATE_KEY` pair the release already uses.

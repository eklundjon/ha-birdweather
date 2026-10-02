# Contributing

This page covers setting up a development environment, running the tests and linter, what CI checks on a pull request, the smoke tests used for refactors, and how releases are cut.

If you haven't read [architecture.md](architecture.md) yet, start there. It explains how the code fits together.

## Setup

The integration has no runtime dependencies of its own; it uses the `aiohttp` that comes with Home Assistant. The tests also need Home Assistant, which comes from [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) (PHACC). Each PHACC release is tied to one Home Assistant version.

With [`uv`](https://github.com/astral-sh/uv):

```bash
uv venv --python 3.13 .venv-test
uv pip install --python .venv-test/bin/python -r requirements_test.txt
.venv-test/bin/python -m pytest
```

`requirements_test.txt` doesn't pin PHACC, so a local install gets the newest Home Assistant. CI also tests against the oldest supported version (see below), so something that passes locally can still fail there.

> `uv venv` doesn't put `pip` in the venv. You don't need it for the commands above, but if you want it, run `.venv-test/bin/python -m ensurepip`.

## Tests

```bash
.venv-test/bin/python -m pytest                          # everything
.venv-test/bin/python -m pytest tests/test_client.py     # one file
.venv-test/bin/python -m pytest -k rarity                # by keyword
```

The tests in `tests/` are roughly one file per module:

- `test_client.py` and `test_client_fetch.py`: the GraphQL client
- `test_coordinator_pure.py`: the `normalize` helpers
- `test_coordinator_update.py` and `test_coordinator_events.py`: the poll and the automation events
- `test_coordinator_bats.py`: bat support
- `test_statistics.py`, `test_config_flow.py`, `test_advanced_options.py`, `test_device_trigger.py`, `test_diagnostics.py` and `test_store_migration.py`
- `test_entry_setup.py`: setting up a whole entry
- `test_card_loader.py`: the startup card loader

The card loader and the cards' guards against loading twice also have JavaScript tests in `tests/js/`. They use Node's built-in test runner (Node 22 or newer) and have no dependencies, so there's nothing to install:

```bash
node --test "tests/js/*.test.mjs"
```

### How the tests build a coordinator

The coordinator's `__init__` sets up an aiohttp session, the GraphQL client, seven `Store` objects and the `DataUpdateCoordinator` base. Most tests don't need all of that, so two helpers keep them light:

- **`tests/coordinator_helpers.py`**: `make_coordinator(hass=None, ...)` builds a `BirdWeatherCoordinator` with `__new__` (skipping `__init__`) and sets only what the code under test uses, with fakes that always behave the same (`FakeStore`) and a stubbed client. `make_client(...)` returns an `AsyncMock` client with canned answers for each poll query (baseline, detections, overview, time of day, sensors), so a whole `_async_update_data` runs without the network.
- **`tests/conftest.py`**: turns on `enable_custom_integrations` for every test so HA will load the integration, and has a `bypass_frontend_setup` fixture that stubs out `frontend`. The integration depends on `frontend` to register its cards, but the real frontend needs the large `home-assistant-frontend` package, which PHACC doesn't include, and the tests don't touch the UI anyway.

The HTTP side is tested directly against `BirdWeatherClient`, in `test_client.py` and `test_client_fetch.py`, with a small fake session that returns canned GraphQL answers, rather than by mocking aiohttp deep inside the coordinator.

## Linting

The linter is `ruff`, pinned in `requirements_test.txt`. CI reads the pin from that file instead of repeating it, so local and CI always use the same version. Change it in one place and both follow.

```bash
.venv-test/bin/python -m ruff check .
```

The rules are set in `pyproject.toml`: pyflakes, pycodestyle, isort, bugbear, comprehensions and pyupgrade. I don't follow Home Assistant core's ruff config, since nothing requires it for a custom integration and keeping up with it would be churn. Line length (`E501`) isn't checked, and there's no formatter.

## What CI checks

`.github/workflows/test.yml` runs on every push to `main` and every pull request. It has three jobs:

- **ruff**: `ruff check .` on Python 3.13 with the pinned ruff.
- **card JS**: the tests in `tests/js/` on Node 24.
- **pytest**: runs the tests against two Home Assistant versions, the minimum and the latest, by pinning PHACC:

  | Job | PHACC | Home Assistant |
  |---|---|---|
  | minimum | `0.13.236` | 2025.4.4 |
  | latest | `0.13.316` | 2026.2.3 |

  The minimum matches `hacs.json` (2025.4, because of the recorder statistics API the long-term statistics need; see "Minimum HA version" in [architecture.md](architecture.md)). If you raise the minimum, update this job too.

A pull request needs the ruff and pytest jobs, plus `hassfest` and HACS validation, to pass before it can merge. Documentation-only changes run everything too.

*Note:* the minimum-version pytest job sometimes fails with a "Lingering timer after test" error during teardown. It's an intermittent problem with PHACC at that pin, not with the code under test, and re-running the job clears it.

### Coverage

The pytest job fails if coverage drops below a minimum:

```bash
.venv-test/bin/python -m pytest \
  --cov=custom_components.birdweather --cov-report=term-missing --cov-fail-under=88
```

The minimum is a few points under the current coverage (about 94%), so a small change doesn't trip it. Raise it over time instead of letting coverage slide down to meet it.

## The smoke tests

`scripts/coordinator_smoke.py` runs the real `BirdWeatherCoordinator._async_update_data` against the live BirdWeather API, with the `Store`s and `hass` faked, and prints a summary of the result:

```bash
.venv-test/bin/python scripts/coordinator_smoke.py [station_id]
```

Use it to check that a refactor doesn't change behavior: save the output, make your change, run it again, and diff the two. The split into `normalize.py` and `statistics.py`, and the merging of the saved files, were each checked this way.

Two smaller scripts run against the live API too, from any directory, with the HA venv:

- `scripts/pipeline_smoke.py [station_id]` runs the normalize pipeline (rarity baseline, the 24-hour and recent windows, rarity and notability scores, recent events) with the coordinator's defaults, and prints a readable summary. It's a quick way to see what a pipeline change does to real data.
- `scripts/smoke.py [lat] [lon]` exercises the client on its own: nearby stations, a few detections and the top species.

None of these replace the tests. The tests check specific behavior. The smoke tests catch any unexpected change to the output during a restructuring.

## Cards

The two cards in `custom_components/birdweather/www/` are generated from the Haikubox integration's cards by `scripts/sync-cards.sh`, which swaps the brand names and flips a few feature switches. Don't edit them by hand except for the bits the script tells you to re-apply. See the comment at the top of each card and [cards.md](cards.md).

`www/birdweather-card-loader.js` and `card_loader.py` are copied from Haikubox by hand, with only the names changed, rather than generated. Keep them in step with the Haikubox originals.

## Pull requests

- Branch off `main` and keep each PR to one change.
- Run `ruff check .` and the tests before pushing. CI runs the same things, so it's faster to catch problems locally.
- Don't change the `version` in `manifest.json` in a feature PR. Changing it starts a release (see [Cutting a release](#cutting-a-release)).
- Keep commit messages and PR descriptions to plain text, with no emoji.

## Cutting a release

The version lives in one place: `custom_components/birdweather/manifest.json`. The release tag is made from it, never the other way around.

1. **Change the version** in `manifest.json` in its own PR, and merge it.
2. **CI creates a draft release** (`.github/workflows/release.yaml`) called `v<version>`, pointing at the merge commit. There's no tag yet.
3. **Write the release notes and publish.** Publishing creates the tag. It's the only step that can't be undone, so a person does it.

If you change your mind before step 3, delete the draft and change the version again. Nothing has been tagged, so there's nothing to clean up.

It's done this way because HACS gets an integration's version from the tag of the latest release, and installs the code at that tag. The code at the tag has to have the matching version in `manifest.json`, and making the tag from the manifest guarantees it. The old workflow went the other way: publish a release, then update `manifest.json` and move the tag to the new commit. For a while the published tag pointed at the old version, and releases could change after they were published.

Two details in the workflow matter, so please don't "simplify" them:

- The draft is created with `--target "$GITHUB_SHA"`, not `main`. A draft's target is only resolved when it's published, so targeting a branch would let anything merged in the meantime end up in the release.
- The check for an existing release uses `gh release list`, not `gh release view "$TAG"`. A draft has no tag until it's published, and GitHub only documents the get-release-by-tag API for published releases, but the list includes drafts. That's what makes the job safe to run more than once. It also runs on manifest edits that don't change the version, and GitHub allows several drafts with the same tag name.

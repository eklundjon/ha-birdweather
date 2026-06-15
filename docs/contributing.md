# Contributing

This page covers the development loop: setting up an environment, running the
test suite and linter locally, what CI enforces on a pull request, and the smoke
harness used to keep coordinator refactors behaviour-preserving.

For how the code is organised, read [docs/architecture.md](architecture.md)
first — it's the map. This page is about working *on* the code.

## Local setup

The integration has no third-party runtime dependencies (it uses Home
Assistant's bundled `aiohttp`). The test environment adds Home Assistant itself,
via [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
(PHACC), which pins the exact Home Assistant version it was built against.

The quickest loop uses [`uv`](https://github.com/astral-sh/uv):

```bash
uv venv --python 3.13 .venv-test
uv pip install --python .venv-test/bin/python -r requirements_test.txt
.venv-test/bin/python -m pytest
```

`requirements_test.txt` leaves PHACC unpinned, so a local install pulls the
latest (newest Home Assistant) for a fast dev loop. CI pins specific versions —
see the matrix below — so a change that passes locally against the latest HA can
still be exercised against the declared minimum in CI.

> Note: `uv venv` does not bootstrap `pip` into the venv. The commands above
> don't need it (they install via `uv pip` from outside), but if you want a
> `pip` inside the venv, run `.venv-test/bin/python -m ensurepip` first.

## Running the tests

```bash
.venv-test/bin/python -m pytest                          # everything
.venv-test/bin/python -m pytest tests/test_client.py     # one file
.venv-test/bin/python -m pytest -k rarity                # by keyword
```

The suite is ~100 tests across the modules in `tests/`, organised roughly one
file per source module — `test_client.py` / `test_client_fetch.py` (the GraphQL
client), `test_coordinator_pure.py` (the pure `normalize` helpers),
`test_coordinator_update.py` / `test_coordinator_events.py` (the poll loop and
automation events), `test_statistics.py`, `test_config_flow.py`,
`test_advanced_options.py`, `test_device_trigger.py`, `test_diagnostics.py`,
`test_entry_setup.py` (end-to-end setup), and `test_store_migration.py`.

### How the tests stand up a coordinator

The coordinator's `__init__` wires an aiohttp session, the GraphQL client, six
`Store` objects, and the `DataUpdateCoordinator` base. Most unit tests don't want
all that. Two patterns keep them light:

- **`tests/coordinator_helpers.py`** — `make_coordinator(hass=None, ...)` builds
  a `BirdWeatherCoordinator` via `__new__` (bypassing `__init__`) and sets only
  the attributes the method under test touches, with deterministic fakes
  (`FakeStore`) and a stubbed client. `make_client(...)` returns an `AsyncMock`
  client with canned poll responses (baseline, detections, overview, time-of-day,
  sensors), so a full `_async_update_data` runs with no network.
- **`tests/conftest.py`** — an autouse `enable_custom_integrations` fixture (so
  HA loads the custom component) and a `bypass_frontend_setup` fixture that stubs
  `frontend` setup (the integration declares `frontend` to register its card JS;
  real frontend setup needs the heavyweight `home-assistant-frontend` wheel PHACC
  doesn't ship, and these tests don't exercise the UI).

The HTTP layer is tested directly against `BirdWeatherClient` in
`test_client.py` / `test_client_fetch.py` with a tiny fake session that returns
canned GraphQL payloads — rather than mocking aiohttp deep in the coordinator.

## Linting

Linting is `ruff`, pinned to the same version in `requirements_test.txt` and in
CI so local and CI never disagree:

```bash
.venv-test/bin/python -m ruff check .
```

The rule set is deliberately lean and self-owned (`pyproject.toml`): pyflakes,
pycodestyle, isort, bugbear, comprehensions, and pyupgrade. We do **not** track
Home Assistant core's ruff config — nothing enforces it on a custom component and
chasing it is pure churn. Line length (`E501`) is ignored; there's no formatter
in play, so line breaks are a judgement call.

## What CI enforces

`.github/workflows/test.yml` runs on every push to `main` and every pull
request, in two jobs:

- **ruff** — `ruff check .` on Python 3.13 with the pinned ruff.
- **pytest** — a matrix that pins PHACC (and therefore Home Assistant) to two
  points: the declared minimum and the latest. Each PHACC release pins one exact
  HA version, so pinning PHACC pins HA:

  | Job | PHACC | Home Assistant |
  |---|---|---|
  | minimum | `0.13.236` | 2025.4.4 |
  | latest | `0.13.316` | 2026.2.3 |

  The minimum tracks `hacs.json`'s floor (2025.4 — the recorder statistics API
  the long-term Statistics backfill needs; see the "Minimum HA version" note in
  [docs/architecture.md](architecture.md)). When you raise that floor, update the
  matrix to match.

Both jobs must pass for a PR to merge (the required checks also include the
`hassfest` and `hacs` validation workflows). Docs-only changes still run the full
suite.

> Heads-up: the minimum-HA pytest job occasionally fails with a "Lingering timer
> after test" teardown error — a known intermittent PHACC flake on that pin,
> unrelated to the code under test. A re-run clears it.

### Coverage gate

The pytest job runs under coverage and fails under a floor:

```bash
.venv-test/bin/python -m pytest \
  --cov=custom_components.birdweather --cov-report=term-missing --cov-fail-under=88
```

The floor sits a few points below the current coverage (~94%) so a trivial change
doesn't trip it. Ratchet it up over time rather than letting coverage drift down
to meet it.

## The refactor smoke harness

`scripts/coordinator_smoke.py` drives the real
`BirdWeatherCoordinator._async_update_data` against the live BirdWeather API,
with the `Store`s and `hass` faked out, and prints a structural summary of the
result dict:

```bash
.venv-test/bin/python scripts/coordinator_smoke.py [station_id]
```

It exists to prove a refactor is behaviour-preserving: capture the output before
your change, apply the change, run it again, and diff. The coordinator split into
`normalize.py` / `statistics.py` and the store consolidation were each verified
this way. (`scripts/pipeline_smoke.py` is a niche cross-check that runs the
sibling Haikubox pipeline helpers over live BirdWeather data; it needs a sibling
`ha-haikubox` checkout.)

This complements the unit tests: the tests assert specific behaviours; the smoke
harness catches *any* unintended change to the overall output shape.

## Cards

The two Lovelace cards in `custom_components/birdweather/www/` are generated from
the canonical Haikubox cards by `scripts/sync-cards.sh` (brand substitution plus
a small feature flip). Don't hand-edit them ad hoc — see the header comment in
each card and [docs/cards.md](cards.md).

## Pull request conventions

- Branch off `main`; one focused change per PR.
- Run `ruff check .` and the test suite locally before pushing — CI runs the same
  thing, so catching it locally is faster.
- Don't hand-edit `manifest.json`'s `version`. The release workflow stamps it;
  see `.github/workflows/release.yaml`.
- Keep commit messages and PR descriptions plain text (no emoji), matching the
  existing history.

"""Shared fixtures for the BirdWeather test suite."""

from __future__ import annotations

from unittest.mock import patch

import pytest

# PHACC is auto-discovered as a pytest plugin, but declaring it is the
# documented pattern and keeps fixture resolution explicit.
pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load the birdweather custom integration in tests."""
    yield


@pytest.fixture(autouse=True)
def bypass_frontend_setup():
    """Stub the `frontend` dependency's setup.

    The integration declares `frontend` (it registers Lovelace card JS), and
    Home Assistant sets that dependency up when the integration loads. Real
    frontend setup needs the heavyweight `home-assistant-frontend` wheel, which
    PHACC doesn't install; the tests here don't exercise the UI, so stub it so
    the dependency resolves.
    """
    with patch(
        "homeassistant.components.frontend.async_setup", return_value=True
    ):
        yield

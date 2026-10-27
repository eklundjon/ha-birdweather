"""Tests for removing the old /local card loader (legacy_card_loader.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

import custom_components.birdweather as integration
from custom_components.birdweather.legacy_card_loader import (
    LOADER_FILE,
    LOADER_URL,
    async_remove_legacy_card_loader,
)

OTHER = {"res_type": "module", "url": "/hacsfiles/other-card/other-card.js"}


@pytest.fixture
async def resources(hass: HomeAssistant):
    """A real storage-mode Lovelace resource collection."""
    assert await async_setup_component(hass, "lovelace", {})
    return hass.data[LOVELACE_DATA].resources


def _loader_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("www", LOADER_FILE))


def _leave_old_loader(hass: HomeAssistant) -> None:
    """What 0.6.0 and 0.7.0 left in config/www."""
    path = _loader_path(hass)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("// old loader\n")


async def test_removes_resources_and_file(hass: HomeAssistant, resources) -> None:
    await resources.async_create_item(OTHER)
    # Duplicates from older releases, each with its own ?v=.
    for v in ("0.6.0", "0.7.0"):
        await resources.async_create_item(
            {"res_type": "module", "url": f"{LOADER_URL}?v={v}"}
        )
    await hass.async_add_executor_job(_leave_old_loader, hass)

    await async_remove_legacy_card_loader(hass)

    # Someone else's resource is left alone.
    assert [i["url"] for i in resources.async_items()] == [OTHER["url"]]
    assert not _loader_path(hass).exists()


async def test_leaves_other_files_in_www(hass: HomeAssistant, resources) -> None:
    other = Path(hass.config.path("www", "mine.js"))
    await hass.async_add_executor_job(_leave_old_loader, hass)
    await hass.async_add_executor_job(other.write_text, "// the user's\n")

    await async_remove_legacy_card_loader(hass)

    assert other.is_file()


async def test_yaml_mode_leaves_resources_and_removes_file(hass: HomeAssistant) -> None:
    # A YAML dashboard's resources are read-only to us: the cleanup skips them
    # (troubleshooting.md asks the user to remove the entry) without raising.
    old = f"{LOADER_URL}?v=0.7.0"
    assert await async_setup_component(
        hass,
        "lovelace",
        {"lovelace": {"mode": "yaml", "resources": [{"url": old, "type": "module"}]}},
    )
    await hass.async_add_executor_job(_leave_old_loader, hass)

    await async_remove_legacy_card_loader(hass)

    resources = hass.data[LOVELACE_DATA].resources
    assert [i["url"] for i in resources.async_items()] == [old]
    assert not _loader_path(hass).exists()


async def test_integration_setup_runs_the_cleanup(
    hass: HomeAssistant, resources, monkeypatch
) -> None:
    """What an upgrade from 0.6.0 or 0.7.0 hits on the next start."""
    await resources.async_create_item(OTHER)
    await resources.async_create_item(
        {"res_type": "module", "url": f"{LOADER_URL}?v=0.7.0"}
    )
    await hass.async_add_executor_job(_leave_old_loader, hass)
    # async_setup also registers the static paths and the card JS; stub those.
    monkeypatch.setattr(
        hass, "http", MagicMock(async_register_static_paths=AsyncMock())
    )

    with patch("custom_components.birdweather.add_extra_js_url"):
        assert await integration.async_setup(hass, {})

    assert [i["url"] for i in resources.async_items()] == [OTHER["url"]]
    assert not _loader_path(hass).exists()


async def test_without_storage_mode_still_removes_file(hass: HomeAssistant) -> None:
    # No lovelace set up at all (stands in for YAML mode's read-only
    # collection): no resources to edit, but the copied file still goes.
    await hass.async_add_executor_job(_leave_old_loader, hass)

    await async_remove_legacy_card_loader(hass)

    assert not _loader_path(hass).exists()


async def test_nothing_to_remove_is_a_noop(hass: HomeAssistant, resources) -> None:
    await async_remove_legacy_card_loader(hass)

    assert resources.async_items() == []

"""Tests for the startup card loader (card_loader.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.birdweather.card_loader import (
    LOADER_FILE,
    LOADER_URL,
    async_install_card_loader,
    async_remove_card_loader,
)

OTHER = {"res_type": "module", "url": "/hacsfiles/other-card/other-card.js"}


@pytest.fixture
async def resources(hass: HomeAssistant):
    """A real storage-mode Lovelace resource collection."""
    assert await async_setup_component(hass, "lovelace", {})
    return hass.data[LOVELACE_DATA].resources


def _loader_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("www", LOADER_FILE))


def _ours(resources) -> list[dict]:
    return [i for i in resources.async_items() if i["url"].startswith(LOADER_URL)]


async def test_install_copies_file_and_registers_resource(
    hass: HomeAssistant, resources
) -> None:
    await async_install_card_loader(hass, "1.2.3")

    packaged = Path(__file__).parent.parent / "custom_components/birdweather/www" / LOADER_FILE
    assert _loader_path(hass).read_bytes() == packaged.read_bytes()
    ours = _ours(resources)
    assert len(ours) == 1
    assert ours[0]["url"] == f"{LOADER_URL}?v=1.2.3"
    assert ours[0]["type"] == "module"


async def test_upgrade_updates_url_in_place(hass: HomeAssistant, resources) -> None:
    await resources.async_create_item(OTHER)
    await async_install_card_loader(hass, "1.0.0")
    first_id = _ours(resources)[0]["id"]

    await async_install_card_loader(hass, "1.1.0")

    ours = _ours(resources)
    assert [(i["id"], i["url"]) for i in ours] == [(first_id, f"{LOADER_URL}?v=1.1.0")]
    # Someone else's resource is left alone.
    assert any(i["url"] == OTHER["url"] for i in resources.async_items())


async def test_duplicates_collapse_to_one(hass: HomeAssistant, resources) -> None:
    for v in ("0.1", "0.2"):
        await resources.async_create_item(
            {"res_type": "module", "url": f"{LOADER_URL}?v={v}"}
        )

    await async_install_card_loader(hass, "1.0.0")

    assert [i["url"] for i in _ours(resources)] == [f"{LOADER_URL}?v=1.0.0"]


async def test_install_without_storage_mode_still_copies_file(
    hass: HomeAssistant,
) -> None:
    # No lovelace set up at all (stands in for YAML mode's read-only
    # collection): nothing to register, but the file is still provided so a
    # YAML user can list it, and setup doesn't raise.
    await async_install_card_loader(hass, "1.0.0")
    assert _loader_path(hass).is_file()


async def test_remove_deletes_resource_and_file(hass: HomeAssistant, resources) -> None:
    await resources.async_create_item(OTHER)
    await async_install_card_loader(hass, "1.0.0")

    await async_remove_card_loader(hass)

    assert _ours(resources) == []
    assert not _loader_path(hass).exists()
    assert [i["url"] for i in resources.async_items()] == [OTHER["url"]]


async def test_remove_when_never_installed_is_a_noop(hass: HomeAssistant) -> None:
    await async_remove_card_loader(hass)

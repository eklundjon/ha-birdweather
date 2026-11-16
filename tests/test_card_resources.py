"""Tests for the cards' Lovelace resources (card_resources.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.birdweather as integration
from custom_components.birdweather.card_resources import (
    async_register_card_resources,
    async_remove_card_resources,
)
from custom_components.birdweather.const import CONF_STATION_ID, DOMAIN
from custom_components.birdweather.coordinator import BirdWeatherCoordinator

BIRD = "/birdweather/birdweather-bird-card.js"
LIST = "/birdweather/birdweather-bird-list-card.js"
OTHER = {"res_type": "module", "url": "/hacsfiles/other-card/other-card.js"}


def _urls(version: str) -> list[str]:
    return [f"{BIRD}?v={version}", f"{LIST}?v={version}"]


@pytest.fixture
async def resources(hass: HomeAssistant):
    """A real storage-mode Lovelace resource collection."""
    assert await async_setup_component(hass, "lovelace", {})
    return hass.data[LOVELACE_DATA].resources


def _ours(resources) -> list[tuple[str, str]]:
    return sorted(
        (i["type"], i["url"])
        for i in resources.async_items()
        if i["url"].startswith("/birdweather/")
    )


async def test_new_install_adds_one_module_per_card(
    hass: HomeAssistant, resources
) -> None:
    await resources.async_create_item(OTHER)

    await async_register_card_resources(hass, _urls("0.7.2"))

    assert _ours(resources) == [("module", u) for u in sorted(_urls("0.7.2"))]
    # Someone else's resource is left alone.
    assert OTHER["url"] in [i["url"] for i in resources.async_items()]


async def test_upgrade_moves_the_existing_entry_to_the_new_version(
    hass: HomeAssistant, resources
) -> None:
    await async_register_card_resources(hass, _urls("0.7.1"))
    ids = sorted(i["id"] for i in resources.async_items())

    await async_register_card_resources(hass, _urls("0.7.2"))

    assert _ours(resources) == [("module", u) for u in sorted(_urls("0.7.2"))]
    # Updated in place, not deleted and re-created.
    assert sorted(i["id"] for i in resources.async_items()) == ids


async def test_same_version_writes_nothing(hass: HomeAssistant, resources) -> None:
    await async_register_card_resources(hass, _urls("0.7.2"))

    with (
        patch.object(resources, "async_create_item") as create,
        patch.object(resources, "async_update_item") as update,
        patch.object(resources, "async_delete_item") as delete,
    ):
        await async_register_card_resources(hass, _urls("0.7.2"))

    create.assert_not_called()
    update.assert_not_called()
    delete.assert_not_called()


async def test_duplicates_and_wrong_type_are_fixed(
    hass: HomeAssistant, resources
) -> None:
    # A user who added the card by hand as "js", plus a stale duplicate.
    await resources.async_create_item({"res_type": "js", "url": f"{BIRD}?v=0.7.0"})
    await resources.async_create_item({"res_type": "module", "url": BIRD})

    await async_register_card_resources(hass, _urls("0.7.2"))

    assert _ours(resources) == [("module", u) for u in sorted(_urls("0.7.2"))]


async def test_yaml_mode_is_left_alone(hass: HomeAssistant) -> None:
    # A YAML dashboard's resources are read-only to us, so it's skipped
    # without raising (troubleshooting.md covers that case).
    assert await async_setup_component(
        hass, "lovelace", {"lovelace": {"mode": "yaml", "resources": []}}
    )

    await async_register_card_resources(hass, _urls("0.7.2"))

    assert hass.data[LOVELACE_DATA].resources.async_items() == []


async def test_without_lovelace_is_a_noop(hass: HomeAssistant) -> None:
    await async_register_card_resources(hass, _urls("0.7.2"))
    await async_remove_card_resources(hass, _urls("0.7.2"))


async def test_a_failure_is_logged_not_raised(
    hass: HomeAssistant, resources, caplog
) -> None:
    with patch.object(
        resources, "async_create_item", side_effect=RuntimeError("disk full")
    ):
        await async_register_card_resources(hass, _urls("0.7.2"))

    assert "Couldn't add the BirdWeather cards" in caplog.text


async def test_remove_deletes_only_ours(hass: HomeAssistant, resources) -> None:
    await resources.async_create_item(OTHER)
    await async_register_card_resources(hass, _urls("0.7.2"))

    await async_remove_card_resources(hass, [BIRD, LIST])

    assert [i["url"] for i in resources.async_items()] == [OTHER["url"]]


async def test_integration_setup_registers_the_same_urls_as_extra_js(
    hass: HomeAssistant, resources, monkeypatch
) -> None:
    """The resource and the extra-JS entry must match, or a page runs two copies."""
    monkeypatch.setattr(
        hass, "http", MagicMock(async_register_static_paths=AsyncMock())
    )
    with patch("custom_components.birdweather.add_extra_js_url") as add_js:
        assert await integration.async_setup(hass, {})

    extra_js = sorted(call.args[1] for call in add_js.call_args_list)
    assert extra_js == sorted(i["url"] for i in resources.async_items())
    assert {u.split("?")[0] for u in extra_js} == {BIRD, LIST}


@pytest.mark.parametrize("another_box", [False, True])
async def test_removing_the_last_box_removes_the_resources(
    hass: HomeAssistant, resources, another_box: bool
) -> None:
    await async_register_card_resources(hass, _urls("0.7.2"))
    if another_box:
        MockConfigEntry(domain=DOMAIN, data={CONF_STATION_ID: "1"}).add_to_hass(hass)
    removed = MockConfigEntry(domain=DOMAIN, data={CONF_STATION_ID: "20184"})

    with patch.object(BirdWeatherCoordinator, "async_remove_stores", AsyncMock()):
        await integration.async_remove_entry(hass, removed)

    assert bool(_ours(resources)) is another_box

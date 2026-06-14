"""Tests for the BirdWeather device triggers."""

from __future__ import annotations

import pytest
from homeassistant.components import automation
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.birdweather import device_trigger
from custom_components.birdweather.const import (
    CONF_STATION_ID,
    DOMAIN,
    EVENT_BIRDWEATHER,
    TRIGGER_NEW_SPECIES,
    TRIGGER_TYPES,
    TRIGGER_UNUSUAL_VISITOR,
)

STATION_ID = "12345"
_ACTION_EVENT = "birdweather_test_action"


@pytest.fixture
def device_id(hass: HomeAssistant) -> str:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=STATION_ID, data={CONF_STATION_ID: STATION_ID})
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, STATION_ID)}
    )
    return device.id


@pytest.fixture
def action_events(hass: HomeAssistant) -> list:
    events: list = []
    hass.bus.async_listen(_ACTION_EVENT, lambda e: events.append(e))
    return events


async def _install_automation(hass: HomeAssistant, device_id: str, trigger_type: str):
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "trigger": {
                    CONF_PLATFORM: "device",
                    CONF_DOMAIN: DOMAIN,
                    CONF_DEVICE_ID: device_id,
                    CONF_TYPE: trigger_type,
                },
                "action": {"event": _ACTION_EVENT},
            }
        },
    )
    await hass.async_block_till_done()


async def test_lists_all_trigger_types(hass: HomeAssistant, device_id: str) -> None:
    triggers = await device_trigger.async_get_triggers(hass, device_id)
    assert {t[CONF_TYPE] for t in triggers} == set(TRIGGER_TYPES)
    for t in triggers:
        assert t[CONF_PLATFORM] == "device"
        assert t[CONF_DOMAIN] == DOMAIN
        assert t[CONF_DEVICE_ID] == device_id


async def test_fires_on_matching_event(
    hass: HomeAssistant, device_id: str, action_events: list
) -> None:
    await _install_automation(hass, device_id, TRIGGER_NEW_SPECIES)
    hass.bus.async_fire(
        EVENT_BIRDWEATHER,
        {"device_id": device_id, "type": TRIGGER_NEW_SPECIES, "species": "Barred Owl"},
    )
    await hass.async_block_till_done()
    assert len(action_events) == 1


async def test_ignores_other_trigger_type(
    hass: HomeAssistant, device_id: str, action_events: list
) -> None:
    await _install_automation(hass, device_id, TRIGGER_NEW_SPECIES)
    hass.bus.async_fire(
        EVENT_BIRDWEATHER, {"device_id": device_id, "type": TRIGGER_UNUSUAL_VISITOR}
    )
    await hass.async_block_till_done()
    assert action_events == []


async def test_ignores_other_device(
    hass: HomeAssistant, device_id: str, action_events: list
) -> None:
    await _install_automation(hass, device_id, TRIGGER_NEW_SPECIES)
    hass.bus.async_fire(
        EVENT_BIRDWEATHER, {"device_id": "not-this-device", "type": TRIGGER_NEW_SPECIES}
    )
    await hass.async_block_till_done()
    assert action_events == []

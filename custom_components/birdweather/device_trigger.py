"""Device triggers for BirdWeather — expose the detection events in the
automation editor's "When → device" picker.

The species triggers are available on every BirdWeather device, and
bat_activity on devices with bat support turned on. They wrap the
`birdweather_event` bus event, filtered by its `type` field, via the core event
trigger platform (the deconz / bthome pattern).
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_PLATFORM,
    CONF_TYPE,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import (
    BAT_TRIGGER_TYPES,
    CONF_BAT_SUPPORT,
    DEFAULT_BAT_SUPPORT,
    DOMAIN,
    EVENT_BIRDWEATHER,
    TRIGGER_TYPES,
)

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES + BAT_TRIGGER_TYPES)}
)


def _has_bat_support(hass: HomeAssistant, device_id: str) -> bool:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return False
    # Devices belong to a single config entry from 2026.8, and reading the old
    # `config_entries` set is deprecated from 2026.10. Fall back to it on older
    # versions, which lack `config_entry_id`.
    entry_ids = (
        [device.config_entry_id]
        if hasattr(device, "config_entry_id")
        else device.config_entries
    )
    return any(
        (entry := hass.config_entries.async_get_entry(entry_id)) is not None
        and entry.domain == DOMAIN
        and entry.data.get(CONF_BAT_SUPPORT, DEFAULT_BAT_SUPPORT)
        for entry_id in entry_ids
        if entry_id is not None
    )


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, Any]]:
    """List the triggers a BirdWeather device offers."""
    types = TRIGGER_TYPES
    if _has_bat_support(hass, device_id):
        types += BAT_TRIGGER_TYPES
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DEVICE_ID: device_id,
            CONF_DOMAIN: DOMAIN,
            CONF_TYPE: trigger_type,
        }
        for trigger_type in types
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a device trigger by delegating to the event trigger platform,
    filtered to this device's `birdweather_event` of the requested type."""
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: EVENT_BIRDWEATHER,
            event_trigger.CONF_EVENT_DATA: {
                CONF_DEVICE_ID: config[CONF_DEVICE_ID],
                CONF_TYPE: config[CONF_TYPE],
            },
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )

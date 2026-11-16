"""Lovelace resources for the cards, so a page loaded during startup gets them.

add_extra_js_url only reaches pages rendered after async_setup has run, but HA
serves the frontend from bootstrap stage 0, long before custom integrations
load. The frontend reloads itself when it sees a new backend version, so after
every HA update a kiosk or wall tablet reloads in that gap, gets an index.html
without the cards, and shows "Custom element doesn't exist" until someone
refreshes it.

Lovelace's resource list is stored by HA itself and is there from the first
request, so a resource for each card gets it requested on that page too. Our
static path isn't registered yet at that point, but the card files are served
with a month-long max-age, so a browser that has shown the cards before loads
them from its cache. Lovelace's error card waits for the element to be defined
and rebuilds itself, so nothing else is needed.

Each resource carries the same ?v= URL as the extra-JS entry, so a page that
has both still runs one copy of each module.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from urllib.parse import urlsplit

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

RESOURCE_TYPE = "module"


async def async_storage_resources(
    hass: HomeAssistant,
) -> ResourceStorageCollection | None:
    """The loaded resource collection, or None when it isn't ours to edit.

    In YAML mode the collection is a read-only ResourceYAMLCollection.
    """
    lovelace = hass.data.get(LOVELACE_DATA)
    resources = lovelace.resources if lovelace is not None else None
    if not isinstance(resources, ResourceStorageCollection):
        return None
    # The collection loads lazily (on first websocket list); mirror what HA's
    # own handlers do so async_items() reflects what's on disk.
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True
    return resources


async def async_register_card_resources(
    hass: HomeAssistant, urls: Iterable[str]
) -> None:
    """Keep exactly one module resource per card, at the current ?v= URL.

    Runs on every setup. It writes only when something changed: a new install,
    an upgrade (new ?v=), or a duplicate. Best-effort: without the resource the
    cards still load on pages rendered after setup, so log and carry on rather
    than fail setup.
    """
    try:
        resources = await async_storage_resources(hass)
        if resources is None:
            return
        for url in urls:
            mine = _items_for(resources, urlsplit(url).path)
            if not mine:
                await resources.async_create_item(
                    {"res_type": RESOURCE_TYPE, "url": url}
                )
                continue
            first, *extra = mine
            if first.get("url") != url or first.get("type") != RESOURCE_TYPE:
                await resources.async_update_item(
                    first["id"], {"res_type": RESOURCE_TYPE, "url": url}
                )
            for item in extra:
                await resources.async_delete_item(item["id"])
    except Exception:
        _LOGGER.warning(
            "Couldn't add the BirdWeather cards to the dashboard resources",
            exc_info=True,
        )


async def async_remove_card_resources(
    hass: HomeAssistant, urls: Iterable[str]
) -> None:
    """Delete the cards' resources, for when the last BirdWeather station is removed."""
    try:
        resources = await async_storage_resources(hass)
        if resources is None:
            return
        for url in urls:
            for item in _items_for(resources, urlsplit(url).path):
                await resources.async_delete_item(item["id"])
    except Exception:
        _LOGGER.warning(
            "Couldn't remove the BirdWeather cards from the dashboard resources",
            exc_info=True,
        )


def _items_for(resources: ResourceStorageCollection, path: str) -> list[dict]:
    """Our resources for one card path, matched on path since ?v= changes."""
    return [
        item
        for item in resources.async_items()
        if urlsplit(item.get("url", "")).path == path
    ]
